# Target architecture: modular monolith on ASP.NET Core and SQLite

One process, one SQLite database, one deployable per target. No microservices, broker, cache server or second database. Desktop and
Server run the same core; only the host and the security boundary differ.

## Layers (implemented as projects)

```
SapLens.Desktop (Windows shell)      SapLens.Api (Server entry point, shared host builder, v1-compatible API)   SapLens.Cli (local tools)
            \                          /          \
             SapLens.Application                SapLens.Documents   import pipeline, jobs, snapshot, reviews, accounts, backups and
                  |            \                                     crypto, v1 backup archives, data retention | PDF/DOCX rendering
         SapLens.Domain     SapLens.Persistence    pure rules, Python text semantics  |  EF Core SQLite, migrations, write coordinator
```

The project references are acyclic: Domain has none; Persistence references Domain; Application references both; Api references
Application and Documents; Desktop references Api; Cli references Application.

- **Domain** has no I/O beyond reading a CSV stream and no framework dependency. Everything that must be byte-equivalent to v1 lives here.
- **Persistence** owns the schema and every database invariant (triggers, unique filtered index, PRAGMAs, path policy).
- **Application** composes them: one registration method used by Desktop, Server and tests, so there is exactly one core.
- **Api** hosts transport (validation, paging, problem details, the security boundary) and, as the port grew route by route, the
  v1-compatible modules that are still bound to their routes: the SoD scope, periods, reviews and reports, Functional Groups and the SAP Lens 1
  data migration workflow. Moving those stores and services into Application is recorded technical debt (see below); it is a mechanical move
  with no behaviour change, deferred to keep the migration diffs reviewable.
- **Writes** all go through `WriteCoordinator` (one writer per process, `BEGIN IMMEDIATE`), including backup records, retention purges and
  storage confirmations. The SAP Lens 1 migration writes a separate candidate database and never the active one.

## Modules

The requested bounded modules map to the code as follows. In the prototype they are namespaces and services inside the layers; a product
would make each a folder with its own endpoints, services and tests, still in one assembly per layer.

| Module | Prototype content | Status |
| --- | --- | --- |
| Import & Data Quality | `CsvImport`, `PythonSniffer`, `ImportChecks`, `ImportService`, held-import confirmation | Implemented |
| SAP Role Catalog | `CatalogueBuilder`, `RoleNames`, `RoleMatcher`, `ModuleRegistry`, `RoleLookup` | Implemented |
| Access Analysis | `UserDirectoryBuilder`, `UserLookup`, `UserComparison`, `TransactionFilters` | Implemented (core filters) |
| SoD Analysis | `SodSource`, `SodAnalyzer`, canonical JSON identities | Implemented (analysis only) |
| Review & Governance | `ReviewService`, `SodDecisionStore`, `SodPeriods`, `SodReviewStore`, `AssignmentLifecycle`: append-only hash-chained decisions, periods with approval and frozen evidence | Implemented |
| Reporting & Evidence | Dataset revisions kept as evidence; `SodReports` with the native PDF/DOCX renderers (`SapLens.Documents`) | Implemented |
| Identity & Access | `AccountStore` (v1 schema, Argon2id, sessions, roles), `V1Auth` permission map, token boundary, host/origin/CSRF checks, `ProxyTrust` | Implemented |
| Backups, Retention & Migration | `ApplicationBackups`, `BackupCrypto` (SLBAK3), `V1BackupArchive`, `DataRetention`, `V1DataMigration` | Implemented |
| Platform & Operations | Health, readiness, JSON logs, correlation ids, migrations, integrity, job worker, schedulers, ICU check | Implemented |

## Technical debt (recorded, not hidden)

| Item | Why it matters | Proposal |
| --- | --- | --- |
| Domain stores in the Api project (`FunctionalGroupStore`, `SodPeriodStore`, `SodReviewStore`, `PrivateSnapshots`, `V1DataMigration`) | Application-level services cannot be reused without the web host; Api is 14k lines | Move to `SapLens.Application` module folders; pure move, covered by the existing tests |
| Large route modules (`SodPeriods.cs` about 1,100 lines, `V1DataMigration.cs` about 830) | Hard to review | Split by sub-feature together with the move above |
| Per-file small helpers (`Json(...)`, `Detail(...)`) repeated in route files | Noise, not risk | Fold into one result helper when the files are next changed |
| SAP Lens 1 archives authenticated in memory (one AES-GCM stream, tag at the end) | 1 GiB limit for `.slbak` migration | Migrate larger installations from a stopped copy of the data directory (documented) |

## Request flow

`RequestBoundary` (correlation id, loopback Host header, same-origin writes, constant-time token) -> endpoint (input validation, limit
1..100) -> `SnapshotService.GetAsync` (one indexed query for the active dataset ids; rebuild only when they changed) -> domain function ->
paged, snake_case JSON. Errors become RFC 9457 problem details with the correlation id; unexpected errors are logged, never echoed.

## Import and job flow

1. `POST /api/v1/imports/{source}` streams the body to `data/uploads`, enqueues a persistent job (optional `Idempotency-Key`), returns 202
   with the job URL.
2. The worker claims the job with a lease (`BEGIN IMMEDIATE`, conditional update). Heartbeats extend the lease and carry cancel requests.
3. The handler streams records into a **Staged** dataset in batches of 5,000 rows, each its own short write transaction, so other writers
   interleave.
4. Validation builds the domain model from the staged records (the same code that serves queries). Bad input fails permanently with v1's
   message; contention (SQLITE_BUSY/LOCKED, I/O) retries with backoff, at most 3 attempts.
5. `ImportChecks` evaluates the change against the active revision. Suspicious: the dataset becomes **Held** and needs an explicit,
   attributed `POST /datasets/{id}/confirm`. Otherwise activation runs **in the same transaction as the job completion**, fenced on the lease
   owner: retire previous, activate new, record review invalidations for disappeared assignments.
6. Restart recovery: expired leases are re-queued and their staging discarded. A completed job cannot run again, a stale worker cannot
   commit, and a live lease is never stolen.

## Hosting

| | Desktop | Server |
| --- | --- | --- |
| Entry | `SapLens.Desktop` (WinForms + WebView2) | `SapLens.Api` executable |
| Bind | `127.0.0.1:0` (OS-assigned), never anything else | `127.0.0.1:18790` by default; trusted LAN only with `--network`, one private address, HTTPS and explicit host names ([SERVER_NETWORK_ACCESS.md](../deployment/SERVER_NETWORK_ACCESS.md)) |
| Token | New 256-bit token per run, injected into `/api` requests by WebView2 `WebResourceRequested`; never visible to page script | `SAP_LENS_V2_TOKEN` or a generated `api-token` file (0600 on Linux) |
| Data | `%LOCALAPPDATA%\SAP Lens Desktop\data` | `--data-dir` (absolute, local; UNC and network drives refused) |
| UI | Embedded prototype UI for `/api/v1` (in `SapLens.Api.dll`), token injected by the shell | Same embedded UI; browser sign-in exchanges the token for an HttpOnly session cookie |
| Shutdown | Window closed -> host stop; running job handed back | SIGTERM / service stop -> same |

## Deliberate non-decisions

- **Network access** is limited to a trusted LAN behind HTTPS with a shared access token and browser sessions. Per-user identity, roles and
  approvals (OIDC or Windows authentication) are required before production use; public exposure is refused by design.
- **API compatibility with the v1 frontend** is not provided: the prototype API is `/api/v1` with its own contract. See
  [MIGRATION_STRATEGY.md](../migration/MIGRATION_STRATEGY.md) for the compatibility facade approach.
- **Native AOT** is not used: EF Core and reflection-based JSON are not AOT-clean, and WinForms is not supported by AOT. See
  [DESKTOP_SERVER_DEPLOYMENT.md](../deployment/DESKTOP_SERVER_DEPLOYMENT.md).
