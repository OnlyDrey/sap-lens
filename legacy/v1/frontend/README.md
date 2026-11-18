# Archived v1 browser contracts

These four specs launch or inspect Python-only runtime internals: authentication
subprocesses, server deployment, backup fixture generation and the Python startup
HTML. They are preserved here, not silently skipped by the .NET browser harness.
They are not evidence of .NET runtime acceptance. Run the original v1 suite from
its pre-promotion checkout (6fa0c7f's parent migration history documents the layout).
The original Python runtime is under `legacy/v1/`; no v1 production data is used.

Active .NET account/backup contracts are covered by backend integration tests.
Equivalent browser activation/recovery/backup-restart workflows still need .NET
fixture adapters. The active `refinement-round2` and `sod-metadata` specs still
use Python **reference generators**, not a Python application server. Those
fixture generators require the optional archived v1 Python environment and are
not included in the dependency-free .NET CI smoke selection. All other active
specs remain available; route parity alone does not establish browser parity.
