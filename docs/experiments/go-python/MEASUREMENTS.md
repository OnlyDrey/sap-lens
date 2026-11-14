# Measurements (Linux only)

One machine: 4 vCPU, 16 GiB, kernel 6.18, Python 3.12.3 harness. Six runs per variant. Not Windows-equivalent: Windows process creation, Defender/App Control scanning and file system behave differently. Raw data: [measurements.json](measurements.json).

All variants start the same backend through the same `poc_backend` entry, same handoff and same `/health` check. The "existing architecture" stand-in is a PyInstaller onedir build (PyInstaller 6.22.3) of that entry with the same pinned requirements. It is not the product's own spec, installer or desktop path, so it indicates direction only.

| Variant | Cold ready (s) | Warm ready median (s) | Warm range (s) | Steady RSS (MiB) | Shutdown (s) | Files | Unpacked (MB) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| venv, direct | 1.14 | 1.14 | 1.07 to 1.18 | 78.1 | 0.44 | n/a | n/a |
| bundled, direct | 0.96 | 1.01 | 0.91 to 1.17 | 78.8 | 0.47 | 9343 | 198.1 |
| bundled + Go host | 1.13 | 1.08 | 0.99 to 1.11 | 87.0 | 0.42 | 9343 | 198.1 |
| bundled pruned + Go host | 0.97 | 0.98 | 0.91 to 1.16 | 87.2 | 0.42 | 7700 | 170.7 |
| PyInstaller onedir, direct | 1.28 | 1.29 | 1.17 to 1.43 | 86.0 | 0.49 | 1575 | 82.5 |

- Cold means the first run in the process; the page cache was not dropped. Memory is the sum over the process tree (shared pages counted per process, so it overstates). Peak equals steady in every row, so no startup spike was observed at 100 ms sampling.
- Go host cost: about 8 MiB RSS (one extra process) and about 70 ms over bundled-direct, within run-to-run noise at six runs. Graceful shutdown through the host is not slower.
- Archive sizes (tar.gz): bundled 69.1 MB, pruned 58.4 MB, PyInstaller 36.1 MB, Windows tree 52.7 MB (unpruned; 144 MB unpacked).
- Host binary: Linux 9.0 MB (unstripped), Windows 6.2 MB (`-s -w`).
- Build and assembly time: host build 3.7 s (cached), assembly 24 s unpruned and 20 s pruned with a warm download cache, PyInstaller build 18 s. Cold-cache downloads were not timed separately.
- Reproducibility: two assemblies give identical tree root hash and archive hash (tested). PyInstaller reproducibility was not measured.

## What the numbers support

- Startup and memory are equivalent within noise. There is no performance argument for or against the Go host.
- The bundled tree is 2.1 to 2.4 times larger than the frozen build and has about 5 to 6 times more files. That is a cost: install size, antivirus scan time and number of files an App Control policy must cover.
- The advantage is auditability (hash-locked inputs, manifest, reproducible build), not speed or size.
