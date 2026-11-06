"""Symlink creation for tests. A missing OS capability (unprivileged Windows: WinError 1314) is an explicit skip with a stated reason, never a pass:
the link-handling assertions only run where a link can actually be created, so run them on Linux or a Windows account with Developer Mode."""
import os
import unittest

#: ERROR_PRIVILEGE_NOT_HELD; EPERM/EACCES/ENOSYS are the POSIX-side equivalents (restricted containers, some network filesystems).
UNAVAILABLE = {1314}


def symlink(target, link, directory=False):
    try:
        os.symlink(target, link, target_is_directory=directory)
    except OSError as error:
        if getattr(error, 'winerror', None) in UNAVAILABLE or (os.name != 'nt' and error.errno in (1, 13, 38)):
            raise unittest.SkipTest(f'Symbolic links cannot be created here ({error}); link-handling coverage is skipped on this host.') from None
        raise
