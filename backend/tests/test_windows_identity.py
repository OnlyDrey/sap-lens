"""Windows SID lookup and private ACLs run in-process (ctypes). Regression for repeated `powershell ... GetCurrent().User.Value` processes (visible
console windows) started by SAP-Lens.exe during backup, upload and restore. The Windows APIs are replaced by a fake here; the real API behaviour is
native-Windows evidence only."""
import ctypes
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import maintenance
import windows_identity as wi
from windows_identity import WindowsIdentityError

BACKEND = Path(__file__).resolve().parents[1]
USER_SID = 'S-1-5-21-1004336348-1177238915-682003330-1001'
SERVICE_SID = 'S-1-5-19'


class FakeWindows:
    """Just enough of advapi32/kernel32 for current_user_sid and make_private. `thread_sid` set = the calling thread impersonates; `fail` names an API that fails."""

    def __init__(self, process_sid=USER_SID, thread_sid=None, fail=None, set_result=0, bad_sid=None):
        self.process_sid, self.thread_sid, self.fail, self.set_result, self.bad_sid = process_sid, thread_sid, fail, set_result, bad_sid
        self.error, self.calls, self.sddl, self.freed, self.closed, self.applied = 0, [], None, 0, 0, None
        self.tokens = {}
        self.kernel32 = SimpleNamespace(GetCurrentThread=lambda: 1, GetCurrentProcess=lambda: 2, CloseHandle=self.close, LocalFree=self.free)
        self.advapi32 = SimpleNamespace(OpenThreadToken=self.open_thread, OpenProcessToken=self.open_process, GetTokenInformation=self.token_information,
                                        ConvertSidToStringSidW=self.to_string, ConvertStringSecurityDescriptorToSecurityDescriptorW=self.to_descriptor,
                                        GetSecurityDescriptorDacl=self.dacl, SetNamedSecurityInfoW=self.set_security)

    def last_error(self):
        return self.error

    def close(self, handle):
        self.closed += 1
        return True

    def free(self, pointer):
        self.freed += 1

    def open_thread(self, thread, access, as_self, out):
        self.calls.append('OpenThreadToken')
        if self.fail == 'OpenThreadToken':
            self.error = 5
            return False
        if self.thread_sid is None:
            self.error = wi.ERROR_NO_TOKEN
            return False
        out._obj.value = 100
        self.tokens[100] = self.thread_sid
        return True

    def open_process(self, process, access, out):
        self.calls.append('OpenProcessToken')
        if self.fail == 'OpenProcessToken':
            self.error = 5
            return False
        out._obj.value = 200
        self.tokens[200] = self.process_sid
        return True

    def token_information(self, token, kind, buffer, length, size):
        self.calls.append('GetTokenInformation')
        if self.fail == 'GetTokenInformation' and buffer is not None:
            self.error = 87
            return False
        if buffer is None:
            size._obj.value = 40
            self.error = wi.ERROR_INSUFFICIENT_BUFFER
            return False
        ctypes.memmove(buffer, ctypes.byref(ctypes.c_void_p(0xABC)), ctypes.sizeof(ctypes.c_void_p))  # TOKEN_USER.User.Sid
        self.current = self.tokens[token.value if hasattr(token, 'value') else token]
        return True

    def to_string(self, sid_pointer, out):
        self.calls.append('ConvertSidToStringSidW')
        out._obj.value = self.bad_sid if self.bad_sid is not None else self.current
        return True

    def to_descriptor(self, sddl, revision, out, size):
        self.calls.append('ConvertStringSecurityDescriptorToSecurityDescriptorW')
        self.sddl = sddl
        out._obj.value = 0x1000
        return True

    def dacl(self, descriptor, present, pointer, defaulted):
        present._obj.value = True
        pointer._obj.value = 0x2000
        return True

    def set_security(self, path, kind, info, owner, group, dacl, sacl):
        self.calls.append('SetNamedSecurityInfoW')
        self.applied = (path, kind, info)
        return self.set_result


class NoSubprocess:
    """Fails the test when anything starts a process."""

    def __enter__(self):
        def refuse(*args, **kwargs):
            raise AssertionError('A subprocess was started: ' + repr(args[:1]))
        self.patches = [patch.object(subprocess, name, refuse) for name in ('run', 'Popen', 'check_output', 'call', 'check_call')]
        for item in self.patches:
            item.start()
        return self

    def __exit__(self, *exc):
        for item in self.patches:
            item.stop()


class SidLookup(unittest.TestCase):
    def test_returns_the_sid_of_the_process_token_with_the_standard_format(self):
        api = FakeWindows()
        self.assertEqual(wi.current_user_sid(api), USER_SID)
        self.assertRegex(wi.current_user_sid(api), r'^S-1-5-21(-\d+){4}$')
        self.assertEqual(api.calls[:2], ['OpenThreadToken', 'OpenProcessToken'])          # no thread token: the process token is the effective identity

    def test_an_impersonating_thread_wins_over_the_process_and_nothing_is_cached(self):
        self.assertEqual(wi.current_user_sid(FakeWindows(thread_sid=SERVICE_SID)), SERVICE_SID)
        api = FakeWindows()
        first = wi.current_user_sid(api)
        api.thread_sid = 'S-1-5-21-1-2-3-500'
        self.assertEqual((first, wi.current_user_sid(api)), (USER_SID, 'S-1-5-21-1-2-3-500'))   # the second lookup sees the new identity

    def test_service_and_desktop_identities_are_each_reported_as_their_own_sid(self):
        for sid in ('S-1-5-18', SERVICE_SID, 'S-1-5-20', USER_SID):                          # SYSTEM, LocalService, NetworkService, an interactive user
            self.assertEqual(wi.current_user_sid(FakeWindows(process_sid=sid)), sid)

    def test_handles_and_allocations_are_released(self):
        api = FakeWindows()
        wi.current_user_sid(api)
        self.assertEqual((api.closed, api.freed), (1, 1))

    def test_failures_are_explicit_and_never_substitute_another_identity(self):
        for name, code in (('OpenThreadToken', 5), ('OpenProcessToken', 5), ('GetTokenInformation', 87)):
            api = FakeWindows(fail=name)
            with self.assertRaises(WindowsIdentityError) as caught:
                wi.current_user_sid(api)
            self.assertIn(name, str(caught.exception))
            self.assertIn(f'Windows error {code}', str(caught.exception))
        with self.assertRaisesRegex(WindowsIdentityError, 'unexpected SID format'):
            wi.current_user_sid(FakeWindows(bad_sid='not-a-sid'))
        with self.assertRaisesRegex(WindowsIdentityError, 'unexpected SID format'):
            wi.current_user_sid(FakeWindows(bad_sid=''))


class PrivateAcl(unittest.TestCase):
    def test_the_dacl_is_protected_and_grants_only_the_user_and_system(self):
        api = FakeWindows()
        wi.make_private('C:/data/backup.tar.gz', api=api)
        self.assertEqual(api.sddl, f'D:P(A;;FA;;;{USER_SID})(A;;FA;;;SY)')                   # inheritance removed, user + SYSTEM full control, nothing else
        path, kind, info = api.applied
        self.assertEqual((path, kind), ('C:/data/backup.tar.gz', wi.SE_FILE_OBJECT))
        self.assertTrue(info & wi.PROTECTED_DACL_SECURITY_INFORMATION and info & wi.DACL_SECURITY_INFORMATION)

    def test_directories_pass_the_grant_to_new_children(self):
        api = FakeWindows(process_sid=SERVICE_SID)
        wi.make_private('C:/ProgramData/SAP Lens/backups', inherit_children=True, api=api)
        self.assertEqual(api.sddl, 'D:P(A;OICI;FA;;;S-1-5-19)(A;OICI;FA;;;SY)')

    def test_an_acl_failure_names_the_api_and_the_windows_error(self):
        with self.assertRaisesRegex(WindowsIdentityError, r'SetNamedSecurityInfoW failed \(Windows error 5\)'):
            wi.make_private('C:/x', api=FakeWindows(set_result=5))

    def test_maintenance_reports_a_failure_instead_of_leaving_the_file_open(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'file'
            target.write_text('x')
            with patch.object(maintenance.os, 'name', 'nt'), patch.object(wi, '_load', return_value=FakeWindows(set_result=5)):
                with self.assertRaisesRegex(maintenance.MaintenanceError, 'Cannot make the backup file private'):
                    maintenance.private_file(target)


class NoProcessesAreStarted(unittest.TestCase):
    def test_sid_lookup_and_acls_start_no_subprocess_however_often_they_run(self):
        api = FakeWindows()
        with NoSubprocess():
            for _ in range(200):                                                            # a restore of hundreds of files, or each backup progress write
                wi.current_user_sid(api)
                wi.make_private('C:/x', api=api)

    def test_the_private_file_path_used_by_backup_upload_and_restore_never_spawns_a_process(self):
        with tempfile.TemporaryDirectory() as temporary, NoSubprocess():
            target = Path(temporary) / 'upload.tar.gz'
            target.write_text('x')
            with patch.object(maintenance.os, 'name', 'nt'), patch.object(wi, '_load', return_value=FakeWindows()):
                for _ in range(50):
                    maintenance.private_file(target)

    def test_no_backend_module_launches_powershell_or_icacls(self):
        offenders = []
        for path in sorted(BACKEND.glob('*.py')) + sorted((BACKEND / 'routers').glob('*.py')):
            text = path.read_text(encoding='utf-8')
            if re.search(r"powershell|icacls|WindowsIdentity\]|GetCurrent\(\)\.User", text, re.I) and path.name != 'windows_identity.py':
                offenders.append(path.name)
        self.assertEqual(offenders, [], 'Windows identity and ACLs must use windows_identity, not external commands')

    def test_backup_and_restore_workflows_never_start_a_process(self):
        import json
        import tarfile
        with tempfile.TemporaryDirectory() as temporary, NoSubprocess():
            root = Path(temporary)
            data = root / 'data'
            data.mkdir()
            (data / 'deployment.json').write_text(json.dumps({'version': 1, 'mode': 'server'}))
            (data / 'settings.json').write_text(json.dumps({'schema_version': 3, 'data_csv_path': 'synthetic'}))
            archive = root / 'backups' / 'b.sap-lens-backup.tar.gz'
            maintenance.backup(data, archive, 'server', '1.0.0')
            self.assertTrue(tarfile.is_tarfile(archive))


if __name__ == '__main__':
    unittest.main()
