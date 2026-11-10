# Performance measurements

Dated measurements of the data path on a 4-vCPU container, kept so changes can be compared; they are not guarantees for other hardware or data. Reproduce
with `python scripts/benchmarks/data_benchmark.py --roles 400 --users 16000 --assignments 12 --employees 16000 [--api]` (each scenario runs in a fresh process; `SAP_LENS_BENCH_BACKEND`
points at another checkout's `backend/` to compare revisions). Architecture: [storage and revisions](../architecture/STORAGE_AND_REVISIONS.md).

## Data-path measurements (synthetic corpus, one container, Python 3.12)

Reproduce with `python scripts/benchmarks/data_benchmark.py` (see also [Testing](TESTING.md)). 192 000 assignment rows (17 MB of CSV), real production path
(`csv_lifecycle.load`), each scenario in a fresh process. "Original" is the code before the storage work, "Step 1" the SQLite store, "Step 2" source-specific refresh.

| Scenario | Original | Step 1 | Step 2 |
| --- | --- | --- | --- |
| Import (parse, derive, stage, activate) | 20.2 s, peak 1017 MB | 21.3 s, peak 1028 MB | 16.4 s, peak 836 MB |
| Start, Dynamic sources, unchanged files (first after an import / next starts) | 27.8 s, peak 1164 MB | 28.1 s / 21.8 s, peak 1215 MB | 6.7 s / 2.2 s, peak 655 / 525 MB |
| Refresh, one source changed (users) | not measured | 24.6 s, peak 1251 MB | 15.3 s, peak 1125 MB |
| Start, Static sources | 9.8 s, peak 730 MB | 6.2 s first / 2.2 s next | 6.5 s first / 2.1 s next, peak 525 MB |
| Disk after import | snapshots 132 MB | snapshots 132 MB + store 28 MB (rows) | unchanged |

The first start after an import still derives the model once (about 4 s) and stores it; later starts load it. Resident memory of a started instance is about 525 MB, of which about 185 MB are the raw
source records retained for comparisons; removing that retention needs comparisons against the store and is a separate refactor.

## Request and refresh performance (192 000 assignment rows, 16 000 SAP users)

Profiling first (`--api --profile api`): the users list and the Dashboard spent 70 % of their time re-parsing the same few date strings for every assignment on every request, and the users list recomputed export totals across all users each time. Changes, all behaviour-preserving:

| Change | Why it is safe |
| --- | --- |
| `sap_date` memoized (`lru_cache`) | Pure function of its text; errors are raised again every call, never cached |
| Dataset-level assignment status counts (Dashboard) and per-user expired counts (users list), memoized per dataset and day | Held on the SAP dataset object, so a refresh or a new day recomputes; excluded from pickling and copying |
| `diff_records`: exact records cancel first across the whole source, only the remainder is grouped by identifier; records are identified by a tuple of references instead of per-row JSON text | Randomised differential test against the former implementation (counts, ambiguity, missing identifiers, every change) |
| Snapshots are streamed to a temporary file while hashing instead of building the full text and its bytes | Byte-identical output, so every existing snapshot keeps its identity; the test compares against the former encoding |

| Measurement (median of 5 requests unless noted) | Before | After |
| --- | --- | --- |
| `GET /api/access/users?limit=50` | 631 ms | 203 ms |
| same, sorted | 686 ms | 189 ms |
| `GET /api/dashboard` | 734 ms | 151 ms |
| Refresh, users source changed (time / peak memory) | 15.3 s / 1164 MB | 11.2 s / 1071 MB |

What remains: both endpoints still scan every user once per request (selection and summaries, about 0.24 s and 0.17 s of the users page); caching those would need invalidation keyed to the filters and is not done. Peak memory of a changed-source refresh is dominated by the
old dataset (kept until publication) plus the new one (about 350 MB for 192 000 records); the retained raw source records (about 185 MB per running instance) are unchanged.

## Final measurements (192 000 assignment rows, 16 000 users, 16 000 employees; one run)

| Scenario | Original | Final |
| --- | --- | --- |
| Import | 20.2 s, peak 1017 MB | 14.8 s, peak 802 MB |
| Dynamic start, unchanged (cold / warm) | 27.8 s, peak 1164 MB | 5.5 s / 2.6 s, peak 607 / 524 MB |
| Static start (cold / warm) | 9.8 s, peak 730 MB | 2.7 s / 2.5 s, peak 542 / 524 MB |
| Refresh, users changed | 24.6 s, peak 1251 MB | 12.1 s, peak 1017 MB |
| Refresh, only the directory changed | not measured | 0.74 s, peak 607 MB |
| `GET /api/access/users` page / sorted / filtered | 631 ms | 162 / 165 / 39 ms |
| `GET /api/dashboard` | 734 ms | 128 ms |

## Changed-directory refresh repeat (five alternating runs each, identical data)

100 000 employees, 20 000 SAP users, 400 roles, 10 assignments per user; before = backend of commit `2ab0b0d`, after = current.

| Scenario | Before median [range] | After median [range] |
| --- | --- | --- |
| Refresh, only the directory changed | 6.61 s [5.95 to 6.95] | 5.08 s [4.29 to 5.49] |
| Refresh, only users changed | 21.5 s [21.3 to 22.1] | 12.9 s [12.1 to 13.4] |
| Start, unchanged files (warm) | 8.13 s [7.69 to 8.78] | 3.23 s [3.03 to 3.36] |
| Import | 20.7 s [19.6 to 21.3] | 19.4 s [18.6 to 19.6] |

An earlier single run of the directory refresh (7.1 s against 6.6 s) was noise: the ranges above do not overlap. Run-to-run spread is about 5 to 10 percent.
