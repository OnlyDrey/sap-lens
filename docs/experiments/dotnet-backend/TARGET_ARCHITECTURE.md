# Target architecture: modular monolith on ASP.NET Core and SQLite

One process, one SQLite database, one deployable per target. No microservices, broker, cache server or second database. Desktop and
Server run the same core; only the host and the security boundary differ.

## Layers (implemented as projects)

```
SapLens.Desktop (Windows shell)      SapLens.Api (Server entry point + shared host builder)
            \                          /
             SapLens.Application         import pipeline, jobs, snapshot, reviews, DI registration (AddSapLensCore)
                  |            \
         SapLens.Domain     SapLens.Persistence    pure rules  |  EF Core SQLite, migrations, write coordinator, backup
```

- **Domain** has no I/O beyond reading a CSV stream and no framework dependency. Everything that must be byte-equivalent to v1 lives here.
- **Persistence** owns the schema and every database invariant (triggers, unique filtered index, PRAGMAs, path policy).
- **Application** composes them: one registration method used by Desktop, Server and tests, so there is exactly one core.
- **Api** is transport only: validation of query input, paging, problem details, security boundary.

## Modules

The requested bounded modules map to the code as follows. In the prototype they are namespaces and services inside the layers; a product
would make each a folder with its own endpoints, services and tests, still in one assembly per layer.

| Module | Prototype content | Status |
| --- | --- | --- |
| Import & Data Quality | `CsvImport`, `PythonSniffer`, `ImportChecks`, `ImportService`, held-import confirmation | Implemented |
| SAP Role Catalog | `CatalogueBuilder`, `RoleNames`, `RoleMatcher`, `ModuleRegistry`, `RoleLookup` | Implemented |
| Access Analysis | `UserDirectoryBuilder`, `UserLookup`, `UserComparison`, `TransactionFilters` | Implemented (core filters) |
| SoD Analysis | `SodSource`, `SodAnalyzer`, canonical JSON identities | Implemented (analysis only) |
| Review & Governance | `ReviewService`, append-only decisions, invalidation, hash chain | Partial (no periods, approvals) |
| Reporting & Evidence | Dataset revisions kept as evidence; frozen SoD reports | Data only; no DOCX/PDF |
| Identity & Access | Loopback-only token boundary, host and origin checks | Minimal; accounts not implemented |
| Platform & Operations | Health, readiness, JSON logs, correlation ids, migrations, integrity, backup, retention, job worker | Implemented |

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
| Bind | `127.0.0.1:0` (OS-assigned) | `127.0.0.1:<port>` (default 18790); any non-loopback bind is refused |
| Token | New 256-bit token per run, injected into `/api` requests by WebView2 `WebResourceRequested`; never visible to page script | `SAP_LENS_V2_TOKEN` or a generated `api-token` file (0600 on Linux) |
| Data | `%LOCALAPPDATA%\SAP Lens 2 Prototype\data` | `--data-dir` (absolute, local; UNC and network drives refused) |
| UI | Embedded prototype UI for `/api/v1` (in `SapLens.Api.dll`), token injected by the shell | Same embedded UI; browser sign-in exchanges the token for an HttpOnly session cookie |
| Shutdown | Window closed -> host stop; running job handed back | SIGTERM / service stop -> same |

## Deliberate non-decisions

- **Remote server access** is out of scope until TLS and a real identity model (Windows authentication or OIDC, roles, approvals) exist.
  The prototype refuses to listen beyond loopback instead of offering a weak option.
- **API compatibility with the v1 frontend** is not provided: the prototype API is `/api/v1` with its own contract. See
  [MIGRATION_STRATEGY.md](MIGRATION_STRATEGY.md) for the compatibility facade approach.
- **Native AOT** is not used: EF Core and reflection-based JSON are not AOT-clean, and WinForms is not supported by AOT. See
  [DESKTOP_SERVER_DEPLOYMENT.md](DESKTOP_SERVER_DEPLOYMENT.md).
