"""Test-only Windows mutex isolation shared by unittest and browser subprocesses."""
from uuid import uuid4
from unittest.mock import patch


def desktop_mutex_patch(factory):
    """Use a fresh real kernel namespace; callers retain normal acquire/close semantics."""
    name = 'Local\\SAPLensTest-' + uuid4().hex
    return patch('instance.WindowsInstance', side_effect=lambda: factory(name=name))
