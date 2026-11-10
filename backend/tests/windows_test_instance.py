"""Keep real Windows lock semantics, isolated from user applications and parallel tests."""
from pathlib import Path
import sys
from instance import WindowsInstance

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/testing'))
from desktop_test_mutex import desktop_mutex_patch


def isolate_desktop_instance(case):
    replacement = desktop_mutex_patch(lambda **kwargs: WindowsInstance(**kwargs))
    replacement.start()
    case.addCleanup(replacement.stop)
