# Performance benchmark: Python v1 versus .NET prototype

All numbers **[M]**: Linux x64, 4 vCPU, 15 GiB, shared cloud VM, Python 3.12 venv (production requirements), .NET 10.0.15. Same synthetic
**large** dataset for both (3,642 roles / 96,924 role rows, 20,000 users / 101,046 user rows, 300 risks / 1,801 SoD rows; 11 MB + 11 MB +
0.1 MB CSV). Windows was not measured [U]. Single machine, few repetitions: treat differences below about 20 % as noise.

Harnesses: `tools/bench_algorithms.py` / `AuthLens.Cli bench` (language level) and `tools/bench_http.py` (service level). Raw JSON is not
committed; rerun with the commands in [README.md](README.md).

## 1. Language level: same algorithms, one process, no HTTP, no storage

Median of repeated runs after the first (catalogue, users, SoD: 3 runs; lookups: 7 runs). Python runs the production v1 functions.

| Operation | Python v1 ms | .NET ms | Speed-up |
| --- | ---: | ---: | ---: |
| Catalogue: parse + build (97 k rows) | 4,540 | 996 | 4.6x |
| Users: parse + build (101 k rows) | 4,509 | 1,807 | 2.5x |
| SoD source parse | 50 | 30 | 1.6x |
| Role Lookup, text `ROLE_01*` | 3.0 | 1.9 | 1.6x |
| Role Lookup, 3 T-codes OR | 0.8 | 0.5 | 1.6x |
| Role Lookup, 2 SAP areas | 1.1 | 0.2 | 5x |
| User Access, all 20 k users sorted | 365 | 209 | 1.7x |
| User Access, by T-code | 251 | 92 | 2.7x |
| User Access, search | 203 | 92 | 2.2x |
| Compare Users | 0.8 | 0.5 | 1.6x |
| SoD analysis (64,664 user findings) | 8,906 | 6,413 | 1.4x |
| Peak process memory | 858 MB | 989 MB | .NET 15 % higher |

Reading: a direct port is 1.4x to 4.6x faster per operation. SoD analysis gains least because it is dominated by canonical JSON
serialization and SHA-256 per finding, which must stay byte-identical; it was not optimized. First-run (JIT) costs are visible only on
sub-10 ms operations (for example Compare Users 8.9 ms first, 0.5 ms after).

## 2. Service level: real servers over loopback HTTP

Python v1 = production `create_app` in desktop mode under Uvicorn (`tools/run_python_v1.py`). .NET = self-contained `linux-x64` publish of
`AuthLens.Api`. Default .NET configuration uses Server GC; a second run with workstation GC (`DOTNET_gcServer=0`) is shown where it matters.

### Startup, memory, shutdown

| Metric | Python v1 | .NET (Server GC) | .NET (workstation GC) |
| --- | ---: | ---: | ---: |
| Empty start to `/health/ready`, cold (new data dir) | 1,319 ms | 1,763 ms | 1,255 ms |
| Empty start, warm (median of 4) | 1,166 ms | 1,375 ms | 1,151 ms |
| Idle memory (RSS), empty | 76 MB | 107 MB | 109 MB |
| First load: start to data queryable | 18.7 s | 23.2 s | 28.8 s |
| Restart with existing data: start to first query answered | 9.8 s | **5.0 s** | 5.5 s |
| RSS after restart (data loaded) | 571 MB | 810 MB | 801 MB |
| RSS after load + concurrency runs | 776 MB | 1,381 MB | 1,112 MB |
| Shutdown (SIGTERM to exit), loaded | 265 ms | 164 ms | 164 ms |

What the first-load numbers contain: Python reads the configured CSV paths into memory and its SQLite cache. .NET receives three HTTP
uploads, stages every row into SQLite in 5,000-row transactions, validates by building the model, evaluates the change, activates
atomically with job completion, then builds the snapshot. The extra durability costs about 5 to 12 s on first load and pays back on every
restart (5 s versus 9.8 s), because the active revision is read from SQLite instead of re-parsing CSVs.

### Concurrency: 15 simulated users, with and without a concurrent large import

Python: 15 readers. .NET: 12 readers and 3 users continuously writing review decisions (Python v1 has no comparable write endpoint in
desktop mode, so its run is read-only; this favours Python). Read mix for both: role search, user page (offset paging over 20 k users),
user filter by T-code, Compare Users. "During import": the same load for 25 s while the users source (101 k rows, changed revision) is
re-imported (.NET: upload + job; Python: file replaced + `POST /api/refresh`).

| | Python steady | Python during import | .NET steady | .NET during import |
| --- | ---: | ---: | ---: | ---: |
| Requests completed | 91 | 124 | 684 | 1,234 |
| Throughput (req/s) | 5.2 | 4.0 | 42.8 | 48.1 |
| P50 latency, all | 2,650 ms | 2,638 ms | 31 ms | 17 ms |
| P95 latency, all | 5,524 ms | 6,347 ms | 1,411 ms | 1,340 ms |
| P99 latency, all | 5,963 ms | 7,267 ms | 1,723 ms | 1,582 ms |
| Errors (5xx, timeouts, SQLITE_BUSY) | 0 | 0 | 0 | 0 |
| Import duration under load | | 29.0 s | | 23.6 s (Completed) |

Per operation, steady state, P50 / P95 ms:

| Operation | Python v1 | .NET |
| --- | --- | --- |
| Role search | 1,842 / 3,068 | 49 / 577 |
| User page (20 k users, filtered and sorted per request) | 4,699 / 5,963 | 1,238 / 1,854 |
| Users by T-code | 3,559 / 4,476 | 1,041 / 1,524 |
| Compare Users | 1,708 / 2,744 | 43 / 578 |
| Review write (SQLite, hash chain) | n/a | 16 / 803 (P99 1,222) |

The .NET tail is dominated by the two User Access queries, which recompute filter and sort over 20,000 users on every page request (as v1
does). Four cores are saturated at this load (CPU time 166 s for .NET versus 59 s for Python over the run, for 8x the requests). Caching the
sorted selection per filter and snapshot would remove most of it; not done, to keep v1 semantics visible.

## 3. Separating language effects from architecture effects

| Effect | Evidence | Size |
| --- | --- | --- |
| Language / runtime (same algorithm) | Section 1 | 1.4x to 4.6x faster per operation; 15 % more peak memory |
| Runtime concurrency (no GIL, Kestrel thread pool) | Section 2 versus 1: per-request work is 2 to 3x faster, but throughput is 8x and overall P50 85x (steady) to 155x (during import) lower | The dominant service-level gain. Python v1 cannot use the other cores because its storage lease admits one process and the GIL serializes the threads. |
| Architecture: SQLite as system of record | First load slower (23 s vs 19 s), restart faster (5 s vs 10 s) | Durability and fast restart traded for first-load time |
| Architecture: in-memory snapshot rebuilt from SQLite | RSS 810 MB vs 571 MB after restart | **Regression**: .NET object model is about 1.4x larger (UTF-16 strings, per-row dictionaries, no interning); not optimized |

## 4. Artifact size and build

| Artifact | Size | Files | Build time (warm NuGet cache) |
| --- | ---: | ---: | ---: |
| Server, linux-x64, self-contained | 114 MB | 353 | 11 s |
| Server, win-x64, self-contained | 115 MB | 356 | 5 s |
| Desktop, win-x64, self-contained single-file exe | 154 MB exe (measured before the UI was embedded; the UI adds about 20 KB) | 1 exe | 11 s |

Not trimmed (EF Core and WinForms are not trim-safe) and not compressed. Python v1 artifact sizes were not rebuilt here [U].

## 5. Conclusions for the decision

- Performance is **not a blocker and not a primary reason** to migrate for a single desktop user; per-operation gains are moderate.
- For **multi-user server mode** the runtime difference is large and measured: 8x throughput, sub-50 ms median for most operations, no
  errors and no write starvation while a 101 k row import runs.
- **Memory must be fixed before a desktop GO**: about 1.4x v1 at rest and up to 1.8x after load. Candidates: string interning of codes and
  role names, compact record types instead of dictionaries, releasing staged rows before snapshot rebuild, workstation GC for Desktop.
