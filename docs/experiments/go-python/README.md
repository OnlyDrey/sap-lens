# Go + Python experiment (Phase 0)

Branch `experiment/go-python` only. Nothing here is part of the product, the build system or CI, and it must not be merged into `work` or `main`.
Question tested: can a small Go host supervise a bundled Python/FastAPI backend (no PyInstaller, no system Python) and serve the existing React build in browser mode?

Files: [measurements](MEASUREMENTS.md), [security](SECURITY.md), [Windows limits and decision](DECISION.md), raw data in [measurements.json](measurements.json).
Code: `experiments/go-python/` (`host/`, `backend/`, `runtime/`, `tests/`, `measure/`, `run_all.py`). No existing backend, frontend, deployment or build file was modified.

## Architecture

```
saplens-host (Go, stdlib only, no cgo)
  |  stdin: {"capability","instance_id"}  (never argv, environment or logs)
  |  stdout line 1: {"event":"listening","port":N}
  v
python -I -m poc_backend   (bundled CPython 3.12.11, hash-locked wheels, no pip, no system Python)
  -> existing main.create_app(browser_access=True), unchanged, serves frontend/dist and /api
```

- Host: validates the isolated data directory (marker file), starts the child with an explicit minimal environment, waits for the listening report, then polls `/health` with strict validation (app name, per-launch instance id, bounded body, no redirects, no proxy). Stop: `stop` line or stdin EOF, then forced kill of the process group after a timeout. Linux: `Pdeathsig`. Windows: Job Object with kill-on-close (cross-compiled, not executed).
- Backend entry (`poc_backend.py`): refuses anything but an absolute directory carrying the marker, reserves the loopback listener itself (OS-assigned port, exclusive bind on Windows), exits when stdin closes so it never outlives the host. No business logic added.
- Runtime (`runtime/assemble.py`): python-build-standalone 20250902 archive plus 28 binary wheels, all pinned by SHA-256 in `runtime/lock.json`. Wheels are unpacked, not installed. Output has a sorted per-file manifest with a root hash, hash-based `.pyc` files and a deterministic tar.gz. `--prune` drops tkinter, test suites and pip.
- No reverse proxy: the browser talks to the Python listener directly. The host only supervises.

## Setup and commands

Requirements: Go 1.22+, Python 3.12, network access to GitHub releases and PyPI for the first assembly (cached in `experiments/go-python/.cache`).

```
cd experiments/go-python/host && CGO_ENABLED=0 go build -trimpath -o bin/saplens-host .
python experiments/go-python/runtime/assemble.py --platform linux --out /tmp/poc-linux [--archive A.tar.gz] [--prune]
experiments/go-python/host/bin/saplens-host --runtime /tmp/poc-linux --data /tmp/poc-data --hold 30s
python experiments/go-python/run_all.py --runtime /tmp/poc-linux        # every check, bounded timeouts
python experiments/go-python/measure/measure.py --runtime /tmp/poc-linux --pruned /tmp/poc-linux-pruned --pyinstaller DIR --venv PY --json OUT
```

Windows tree (experimental, assembled on Linux, never executed): `assemble.py --platform windows`; host: `GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build`.

## Runtime dependencies

- Go host: standard library only (`go.mod` has no requirements). Toolchain used: Go 1.24.7.
- Python: interpreter archive (1) plus 28 wheels (14 direct pins of `backend/requirements.txt`, 14 transitive), identical set for Linux and Windows, binary wheels only, every file hash-verified before use. Closure is tested against wheel metadata.
- Native code in the tree: 46 `.so` files (Linux, pruned 43); Windows tree 52 `.pyd`, 13 `.dll`, 10 `.exe` (21 `.pyd`/`.dll` under site-packages). Each is a separate Windows App Control decision (see [DECISION](DECISION.md)).

## Tests

| Stage | Result (Linux, this environment) |
| --- | --- |
| gofmt, `go vet` (linux and windows/amd64) | passed |
| `go test -race` (9 tests: health validation, redaction, supervisor lifecycle, forced stop, start timeout, data dir) | passed |
| Python static (15): lock vs `backend/requirements.txt`, wheel-metadata closure, platform tags, safe extraction, manifest tamper detection, two assemblies identical (tree root and archive hash) | passed |
| Python e2e (26): health identity, SIGTERM, SIGINT, SIGKILL of host leaves no orphan, port closed after stop, distinct instances, startup failures and exit codes, start-timeout cleanup, backend refusals, 403 without or with wrong capability, foreign Host and Origin, loopback-only listener, no secret in argv, environment, files, minimal child environment, data confined to isolated directory | passed |
| `govulncheck` | NOT EXECUTED: vulnerability database unreachable (HTTP 403). The module has no third-party dependencies, so exposure is the Go toolchain only |
| Windows native smoke, installer acceptance, App Control verification, Windows lifecycle tests | NOT EXECUTED: no Windows host |

Defects found by the tests and fixed in the experiment: non-reproducible `.pyc` files (hash-seed ordering, timestamp pyc of modules imported by `compileall`) and the output path leaking into the gzip header.

## Differences from the existing implementation

| Topic | Existing | Experiment |
| --- | --- | --- |
| Python | PyInstaller-frozen | Bundled CPython tree, source and `.pyc` |
| Lifecycle owner | `backend/desktop.py` / `backend/server.py` | Go host; backend has no window or thread host |
| Version identity | `build-version.json` required when frozen | Not frozen: reports `local` identity. Shipping build metadata is a Phase 1 item |
| Integrity | Installer and package verifiers | Per-file manifest, root hash, tamper test |
| Scope | Desktop, service, container, Linux server | Browser mode, loopback, isolated data only |
