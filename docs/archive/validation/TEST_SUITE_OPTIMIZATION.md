# Test suite cleanup and optimization

Dated record (29 October 2026); final results are filled in when the regression run completes.
Environment: Linux sandbox, 4 vCPU, Python 3.12, Node 22, headless Chromium. Absolute times
are specific to that machine.

## Baseline (before changes, commit `03088fb`)

| Metric | Value |
| --- | --- |
| Backend tests | 716 (3 skipped) |
| Browser tests | 473 in 49 spec files |
| Backend wall time | about 80 to 100 s serial (sum of test time 93.7 s) |
| Browser wall time | about 16 min serial (3 batches: 6.1 + 5.4 + 4.6 min) |
