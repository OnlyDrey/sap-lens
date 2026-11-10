"""Keep real Windows lock semantics, isolated from user applications and parallel tests."""
from uuid import uuid4
from unittest.mock import patch
from instance import WindowsInstance


def isolate_desktop_instance(case):
    name = 'Local\\SAPLensTest-' + uuid4().hex
    replacement = patch('instance.WindowsInstance', side_effect=lambda: WindowsInstance(name=name))
    replacement.start()
    case.addCleanup(replacement.stop)
