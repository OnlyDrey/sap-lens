# Migration strategy: SAP Lens v1 (Python) to a .NET backend

Not executed. No production data was migrated or read. This is the plan the prototype's evidence supports.

## Principles (from the requirements, all binding)

- Existing user data and audit history are preserved; historical decisions are immutable.
- Previously reviewed assignments that disappear and later reappear require a new review (implemented and tested in the prototype).
- Migration backups remain protected until an administrator explicitly confirms the upgrade. Retention: automatic 90 days, manual until
  deleted, migration until confirmation (implemented as a pure, tested policy).
- Every step is reversible until that confirmation.

## 1. API and frontend

The prototype API (`/api/v1`, snake_case, problem details) is not the v1 API. Two options:

| Option | Effort | Risk |
| --- | --- | --- |
| A. Compatibility facade: .NET implements the v1 routes and response shapes the React app calls today, generated from v1's OpenAPI and pinned by contract tests that replay recorded v1 responses | High (about 25 routers) | Low for users; the frontend does not change |
| B. Move the frontend to `/api/v1` screen by screen behind a feature flag | High, spread over UI work | Medium; two APIs during transition |

Decision (Phase 1): **A**, implemented as `V1Compatibility.cs`; boot and Role Lookup are served, everything else answers 501 until migrated.
Recommendation: **A** first. The frontend stays the single UI, v1 stays the behavioural reference, and contract tests give a mechanical
definition of "done" per router. Security headers move from `X-SAP-Lens` (v1) to the token header injected by the shell.

## 2. Schema and data

v1's authoritative state is in JSON stores; the prototype's is in SQLite. Migration is an **import of the v1 stores into the v2
database**, never an in-place conversion:

1. **Freeze and back up**: run v1's own backup (encrypted portable backup) and copy the configuration directory read-only. Record SHA-256
   of every source file.
2. **Sources**: import the current CSV of each source through the normal v2 import (validation, change checks) to create revision 1 of each
   source. Historical v1 source revisions (SQLite cache, JSON snapshots) are imported as Retired datasets with their original timestamps and
   content hashes, marked as migrated evidence.
3. **Decisions**: each v1 decision becomes one `ReviewDecisions` row in original order, with its original reviewer, timestamp and comment,
   and the v1 record's own hash stored alongside, so the chain starts from verifiable v1 evidence. SoD decisions keep their finding id and
   evidence version, which the prototype reproduces byte for byte, so they stay attached to the same findings.
4. **Invalidations**: replay the v1 assignment history (revision diffs) to create invalidations for assignments that disappeared after a
   decision, so "reappeared means re-review" holds for history, not only for future imports.
5. **Periods, frozen report evidence, approvals**: imported as immutable rows plus the original frozen JSON as an evidence blob with its
   hash. Reports are re-rendered from the frozen model; the original rendered files are archived unchanged.
6. **Verification gate**: counts per store, per-record hash comparison, review chain verification, integrity check, and a re-run of the
   equivalence suite on the migrated sources. Any mismatch aborts and leaves v1 untouched.

EF Core migrations then own the v2 schema from that point; each future schema change takes a protected migration backup first (implemented).

### Implemented procedure (`--migrate-v1`)

The server binary migrates a SAP Lens 1 data directory, or a SAP Lens 1 `.slbak` (passphrase or recovery key) or `.tar.gz` backup of it, in explicit steps.
The administrator procedure with exact PowerShell commands is [V1_MIGRATION.md](V1_MIGRATION.md). An archive is checked like SAP Lens 1
`maintenance.verify` after authentication: regular files with safe, case-unique names, member and size limits, and a manifest listing exactly the
members with matching SHA-256.
The source is only read. Use synthetic data or a copy; do not run it against a production installation before the owner's acceptance.

| Step | Command | Effect |
| --- | --- | --- |
| Dry run | `SapLens.Api --migrate-v1 preview --source <v1 dir or backup> --data-dir <v2 dir> [--replace-existing]` | SHA-256 inventory, validation of every store, what is imported or only preserved, blockers, warnings, and an approval digest. Writes only `migration/<id>/preview.json`. Existing SAP Lens 2 data is a blocker unless `--replace-existing` is given. |
| Run | `--migrate-v1 run --id <id> --approve <digest>` | Refuses a changed source. Makes a verified private copy and an encrypted migration backup (host key; unencrypted with a warning when none is configured), builds a separate candidate database and verifies it (integrity, every record of every revision, evidence content addresses, both hash chains, counts). Active data is untouched. |
| Activate | `--migrate-v1 activate --id <id> --approve <digest>` | Refuses when the v1 directory changed since the run. The candidate replaces the active data at the next start, before the database opens; the previous files go to `migration/<id>/previous`. Any failure rolls back. Retention cleanup pauses for 7 days. |
| Rollback | `--migrate-v1 rollback --id <id>` | The previous SAP Lens 2 files return at the next start; the migrated files are kept in `migration/<id>/rolled-back`. |
| Status | `--migrate-v1 status --id <id>` | The migration report. |

Imported: settings, every role, user and SoD matrix revision (active and superseded, with the v1 snapshot id kept as an alias that protects it from
retention), Employee Directory revisions, SoD evidence snapshots (content addresses re-verified), SoD decision events (hash chain in timestamp order),
remediation actions and report log, review periods and legacy reviews, catalogue and reference annotations, functional groups, assignment lifecycle,
position changes, report branding, reviewer profile, saved filters, refresh reports, account review decisions with their history (on the review hash
chain; decisions for users in no migrated revision are kept in a `v1-account-review-unmatched` document), branding images, the account store (sessions
removed) and the refresh schedule state. Not migrated: data retention approvals (bound to the installation), SAP Lens 1 application backups and its derived
SQLite cache. Every source file, migrated or not, is in the migration backup, which Settings, Storage keeps until an administrator confirms the upgrade.

## 3. Import formats

Unchanged. The prototype accepts the same CSV files (encodings, delimiters, mappings, limits) with identical results on the equivalence
suite, including v1's failure cases. Custom import profiles (column mappings) must be migrated from settings; the domain already accepts a
mapping.

## 4. Installer and server transition

- **Desktop**: install side by side under a new product code and data directory; first start offers "import from SAP Lens v1" (read-only).
  v1 stays installed until the administrator confirms.
- **Server**: install the v2 service stopped; migrate from a copy of v1's data; switch the port or reverse proxy; keep the v1 service
  disabled, not removed, until confirmation.
- Signing and App Control approval are prerequisites for both (see [DESKTOP_SERVER_DEPLOYMENT.md](../deployment/DESKTOP_SERVER_DEPLOYMENT.md)).

## 5. Rollback

Until confirmation, rollback is "stop v2, start v1": v1's data was never written. After confirmation, decisions made in v2 would need an
export back to v1's format; that path is not designed and is the reason confirmation must be explicit and late (after a full review cycle).

## 6. Order of work (if the decision is GO)

1. Identity and remote-access design (accounts, roles, approvals, TLS) for Server mode.
2. Compatibility facade with contract tests, router by router, starting with read-only screens.
3. Remaining domain: directory source, functional groups, Access Package suffix rules, SoD governance, periods, reports.
4. Migration importer with the verification gate, rehearsed on synthetic v1 stores, then on a copy of a real installation by the owner.
5. Windows packaging, signing, App Control rule, service, then pilot.
