# Architecture assessment: SAP Lens v1 (Python) as the baseline for a C# backend

Source of truth: code and tests at `origin/work` `d7a39fb`. Documentation was used only to find code. Tags as in [README](README.md).

## 1. What v1 is

| Concern | v1 implementation | Tag |
| --- | --- | --- |
| Process model | One FastAPI app (`backend/main.py:create_app`), single Uvicorn worker. Desktop runs Uvicorn in a thread under pywebview (PyInstaller one-file); Server runs PyInstaller one-dir under WinSW / the Service Manager on Windows, systemd or Docker on Linux. | [C] |
| Hot data | An immutable in-memory snapshot (`cache._CacheState`: catalogue, users, SoD, directory), replaced atomically after a load. All lookups, comparisons and SoD analysis run against it. | [C] |
| SQLite | `store_db.py`: **a rebuildable cache**, not the system of record. WAL, `BEGIN IMMEDIATE`, busy timeout 15 s, short-lived connections, a storage lease that admits one process per data directory, `user_version` ladder, newer schema left untouched. | [C] |
| System of record | Validated JSON stores in the configuration directory: SoD decisions, SoD reviews, periods and frozen report evidence, account review decisions, review identity, saved filters, position changes, retention, branding, settings. | [C] |
| Imports | `csv_import.CsvImport` (128 MiB, 1 M rows, field and identifier limits, BOM/UTF-16/UTF-8/cp1252 detection, `csv.Sniffer` delimiter detection, duplicate and blank row handling, changed-while-reading guard), `csv_lifecycle` revisions and diffs, `import_checks` suspicious-change rules with confirmation. | [C] |
| Business rules | Role normalization and scope, release-role parsing, `RoleMatcher` (exact, ambiguous, wildcard, unmapped), SAP date intervals, anchored `*` search, User Access selection, Compare Users, SoD (`sod-two-sided-v1`) with SHA-256 finding identities over canonical JSON. | [C] |
| Security | Desktop: loopback, per-session header token, host and origin checks. Server: accounts with Argon2id (pbkdf2 fallback), sessions, login throttling, roles. Backups: streaming AES-256-GCM. | [C] |
| Reports | SoD reports from one frozen model: python-docx (DOCX) and ReportLab (PDF). | [C] |
| Size | About 23 k lines in `backend/*.py` and `backend/routers/*.py`, 125 test modules. | [M] |

## 2. Findings that shape a migration

1. **The audit trail is in JSON files, not in SQLite.** A C# backend that moves decisions into SQLite changes the system of record. That is
   the biggest migration item and the reason [MIGRATION_STRATEGY.md](MIGRATION_STRATEGY.md) treats data migration as its own project. [C]
2. **v1 is single-process by design** (storage lease). The prototype allows several processes on one database and therefore needs
   database-level guarantees (BEGIN IMMEDIATE, fenced job leases, unique active revision). Both are valid; they are different contracts. [C]
3. **Determinism is part of the contract.** SoD finding IDs and evidence versions are SHA-256 over Python `json.dumps(sort_keys=True,
   ensure_ascii=False, separators=(',', ':'))`. Any port must reproduce Python serialization byte for byte or every stored decision is
   orphaned. The prototype does ([FUNCTIONAL_EQUIVALENCE.md](FUNCTIONAL_EQUIVALENCE.md)). [T]
4. **CSV delimiter detection is CPython's `csv.Sniffer`,** including its failures on tiny files. A "better" sniffer changes which files
   import. The prototype ports the Sniffer verbatim. [T]
5. **Python-specific text semantics** appear in normalization (`str.upper`, code-point ordering). For ASCII SAP identifiers .NET
   `ToUpperInvariant` and ordinal ordering are identical; for characters such as `ß` or astral code points they are not. Recorded as a
   known difference, not observed in SAP role or user names. [C]
6. **No Python-only algorithm.** Nothing in the analysis core depends on a library without a .NET counterpart. Python-only value sits in
   report generation (python-docx, ReportLab) and in existing operational tooling. [C]

## 3. What the prototype covers and what it does not

| Area | Prototype | Not in prototype |
| --- | --- | --- |
| CSV import, normalization, catalogue, users | Ported, equivalence-tested | Directory (employee) source, functional groups, position changes |
| Role Lookup, User Access | Ported core filters, server-side sort and paging | Username lists, missing-role, manager, band filters, exports |
| Compare Users | Ported incl. listing filters | Evidence drill-down endpoint |
| SoD | Analysis and identities ported | Governance, periods, frozen reports, DOCX/PDF |
| Reviews | Append-only decisions, invalidation on reappearance, hash chain | Account review workflow, approval roles, periods |
| Persistence, jobs, backups | Implemented and tested | Encrypted portable backups, restore UI |
| Security | Loopback-only, token, host/origin checks | Accounts, sessions, roles, TLS, remote access |
| Desktop / Server | Built; Server run on Linux | Windows execution, installer, service registration, signing |

The prototype is about 3.5 k lines of C# plus 0.8 k lines of tests against 23 k lines of v1 Python. It is representative of the risky
parts (rules, storage, jobs, concurrency, hosting), not of the breadth.
