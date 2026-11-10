"""SAP Lens public build CLI; initial checks require only the Python standard library."""
import sys

sys.dont_write_bytecode = True
from build_system.cli import main  # noqa: E402 (keep help/dry-run free of bytecode writes)

if __name__ == '__main__':
    raise SystemExit(main())
