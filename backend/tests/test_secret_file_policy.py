"""SEC-03: the shared-access secret is owner-only by default; group read is an explicit, checked exception."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deployment import ServerSettings, check_secret_permissions

ROOT = Path(__file__).resolve().parents[2]
SECRET = 'synthetic-access-secret-' + 'a' * 40
ORIGIN = 'http://127.0.0.1:18743'


@unittest.skipIf(os.name == 'nt', 'POSIX modes; Windows ACLs are applied by the service provisioning')
class SecretFilePolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.secret = self.root / 'access.secret'; self.secret.write_text(SECRET)
        self.env = {'SAP_LENS_DEPLOYMENT_MODE': 'server', 'SAP_LENS_DATA_DIR': str(self.root / 'data'), 'SAP_LENS_SOURCE_DIR': str(self.root / 'sources'),
                    'SAP_LENS_HOST': '127.0.0.1', 'SAP_LENS_PUBLIC_ORIGIN': ORIGIN, 'SAP_LENS_ALLOWED_HOSTS': '127.0.0.1', 'SAP_LENS_AUTH': 'basic',
                    'SAP_LENS_AUTH_SECRET_FILE': str(self.secret), 'SAP_LENS_TRUSTED_PROXIES': ''}
        self.patch = patch.dict(os.environ, self.env); self.patch.start(); os.environ.pop('SAP_LENS_CONFIG_DIR', None); os.environ.pop('SAP_LENS_AUTH_SECRET_GROUP_READ', None)

    def tearDown(self):
        self.patch.stop(); self.temp.cleanup()

    def load(self, mode, group_read=False):
        self.secret.chmod(mode)
        with patch.dict(os.environ, {'SAP_LENS_AUTH_SECRET_GROUP_READ': '1'} if group_read else {}):
            return ServerSettings.from_env()

    def test_owner_only_modes_are_accepted(self):
        for mode in (0o600, 0o400): self.assertEqual(self.load(mode).secret, SECRET, oct(mode))

    def test_other_access_and_group_write_or_execute_are_always_refused(self):
        for mode in (0o601, 0o602, 0o604, 0o644, 0o660, 0o620, 0o610, 0o666, 0o777):
            for group_read in (False, True):
                with self.assertRaises(ValueError, msg=f'{mode:04o} group_read={group_read}'): self.load(mode, group_read)

    def test_group_read_needs_the_explicit_opt_in_and_names_the_remedy(self):
        for mode in (0o640, 0o440):
            with self.assertRaises(ValueError) as refused: self.load(mode)
            message = str(refused.exception)
            self.assertIn(str(self.secret), message); self.assertIn('chmod 600', message); self.assertIn('SAP_LENS_AUTH_SECRET_GROUP_READ=1', message)
            self.assertNotIn(SECRET, message)
            self.assertEqual(self.load(mode, group_read=True).secret, SECRET)  # our own group: the file's group is the account's primary group

    def test_group_read_is_refused_for_a_group_the_service_account_does_not_belong_to(self):
        self.secret.chmod(0o640)
        foreign = max({os.getegid(), *os.getgroups()}) + 1000
        status = os.stat_result((self.secret.stat().st_mode, 0, 0, 1, os.geteuid(), foreign, 0, 0, 0, 0))
        with self.assertRaises(ValueError) as refused: check_secret_permissions(self.secret, status, allow_group_read=True)
        self.assertIn('does not belong', str(refused.exception))

    def test_the_file_is_never_changed_and_a_symlink_is_judged_by_its_target(self):
        self.secret.chmod(0o640)
        with self.assertRaises(ValueError): ServerSettings.from_env()
        self.assertEqual(self.secret.stat().st_mode & 0o777, 0o640, 'validation does not chmod administrator-managed files')
        link = self.root / 'link'; link.symlink_to(self.secret)
        with patch.dict(os.environ, {'SAP_LENS_AUTH_SECRET_FILE': str(link)}), self.assertRaises(ValueError): ServerSettings.from_env()
        self.secret.chmod(0o600)
        with patch.dict(os.environ, {'SAP_LENS_AUTH_SECRET_FILE': str(link)}): self.assertEqual(ServerSettings.from_env().secret, SECRET)

    def test_proxy_mode_applies_the_same_policy(self):
        self.secret.chmod(0o644)
        with patch.dict(os.environ, {'SAP_LENS_AUTH': 'proxy', 'SAP_LENS_TRUSTED_PROXIES': '127.0.0.1/32'}), self.assertRaises(ValueError): ServerSettings.from_env()

    def test_local_mode_needs_no_secret(self):
        with patch.dict(os.environ, {'SAP_LENS_AUTH': 'local'}): self.assertEqual(ServerSettings.from_env().secret, '')

    def test_a_new_secret_is_owner_only_even_under_a_permissive_umask_and_never_overwrites(self):
        target = self.root / 'created.secret'
        run = lambda: subprocess.run([sys.executable, str(ROOT / 'backend' / 'server.py'), '--init-secret', str(target)], preexec_fn=lambda: os.umask(0), capture_output=True, text=True)
        self.assertEqual(run().returncode, 0)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        text = target.read_text(); self.assertGreaterEqual(len(text.strip()), 32)
        again = run()
        self.assertNotEqual(again.returncode, 0); self.assertEqual(target.read_text(), text, 'an existing secret is never replaced')
        self.assertNotIn(text.strip(), again.stdout + again.stderr)


if __name__ == '__main__':
    unittest.main()
