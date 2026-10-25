"""Linux management contracts without touching system services or real stores."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('linux_lifecycle', ROOT/'scripts/install-linux-server.py')
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)


class LinuxLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def release(self):
        prefix = self.root/'application'; release = prefix/'releases/0.1.0-synthetic'
        release.mkdir(parents=True)
        identity = dict(version='0.1.0', source_sha='a'*40)
        (release/'package-manifest.json').write_text(json.dumps(dict(platform='Linux-Native-x64', identity=identity, files={})))
        (prefix/'current').symlink_to(release)
        return prefix, release, identity

    def test_installed_identity_requires_owned_release_link(self):
        prefix, release, identity = self.release()
        self.assertEqual(ops.installed(prefix), identity)
        (prefix/'current').unlink(); (prefix/'current').symlink_to(self.root)
        with self.assertRaises(ValueError): ops.installed(prefix)

    def test_uninstall_guard_preserves_administrator_added_files(self):
        prefix, release, _ = self.release()
        ops.managed_prefix(prefix)
        extra = release/'administrator-note.txt'; extra.write_text('retain')
        with self.assertRaises(ValueError): ops.managed_prefix(prefix)
        self.assertEqual(extra.read_text(), 'retain')

    def test_pid_ledger_never_selects_unrelated_process(self):
        prefix = self.root/'application'; (prefix/'run').mkdir(parents=True)
        (prefix/'run/process.json').write_text(json.dumps(dict(pid=12345, ticks='123')))
        with patch.object(ops, 'process_owned', return_value=False):
            self.assertIsNone(ops.user_pid(prefix, self.root/'server.env'))
        with patch.object(ops, 'process_owned', return_value=True) as check:
            self.assertEqual(ops.user_pid(prefix, self.root/'server.env'), 12345)
            check.assert_called_once_with(12345, prefix, self.root/'server.env', '123')

    def test_configuration_must_agree_with_selected_persistent_store(self):
        from types import SimpleNamespace
        with patch.object(ops, 'load_script', return_value=SimpleNamespace(configure=lambda _: SimpleNamespace(data=self.root/'actual'))):
            with self.assertRaises(ValueError): ops.configuration(self.root/'server.env', self.root/'different')

    def test_downgrade_rejected_before_staging(self):
        from types import SimpleNamespace
        args = SimpleNamespace(prefix=self.root/'application', action='upgrade')
        with patch.object(ops, 'validate_bundle', return_value={'identity': {'version':'0.1.0-beta.1'}}), patch.object(ops, 'installed', return_value={'version':'0.1.0'}):
            with self.assertRaises(ValueError): ops.install(args, self.root/'unit', '# marker')
        self.assertFalse(args.prefix.exists())
