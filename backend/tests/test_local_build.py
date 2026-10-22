"""Offline receipt/identity regressions; no native EXE or private CSV inputs."""
import copy
import hashlib
import io
import os
import shutil
import zipfile
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('local_builder', ROOT / 'scripts/local-build.py')
local = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local)


class LocalVersionTests(unittest.TestCase):
    def test_deterministic_offline_stable_and_beta_identity(self):
        for requested, fourth in [('0.1.0', 0), ('0.1.0-beta-4', 4)]:
            info = local.version.make_local_package_info(requested, 'a' * 40)
            self.assertEqual(info['version'], requested + '+local.' + 'a' * 12)
            self.assertEqual(info['file_version'], [0, 1, 0, fourth])
            self.assertEqual((info['run_id'], info['run_number'], info['attempt'], info['tag']), ('', '', 0, ''))
            self.assertEqual(local.version.parse_build_info(info), info)
            self.assertEqual(local.version.make_local_package_info(requested, 'a' * 40), info)
            for field, value in [('run_id', '123'), ('tag', 'v' + requested), ('file_version', [0,1,0,8]), ('source_sha', 'b'*40), ('attempt', False)]:
                bad = {**info, field: value}
                with self.subTest(field=field), self.assertRaises(ValueError):
                    local.version.parse_build_info(bad)

    def test_invalid_versions_and_source_are_rejected(self):
        for value in ['v0.1.0', '01.1.0', '0.1.0-beta-0', '0.1.0-beta-65536', '65536.0.0', '0.1.0+local.fake', '', '0.1.0-dev.1']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                local.version.make_local_package_info(value, 'a' * 40)
        with self.assertRaises(ValueError):
            local.version.make_local_package_info('0.1.0', 'not-a-sha')

    def test_local_identity_generates_matching_windows_resources(self):
        spec = importlib.util.spec_from_file_location('local_metadata', ROOT / 'scripts/write-windows-metadata.py')
        metadata = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(metadata)
        info = local.version.make_local_package_info('0.1.0-beta-4', 'a' * 40)
        with patch.object(metadata, 'BUILD_INFO', info), patch.object(metadata, 'VERSION', info['version']), patch.object(metadata, 'FILE_VERSION', tuple(info['file_version'])):
            # Same resource writer used by CI; no alternate PE implementation.
            with tempfile.TemporaryDirectory() as directory, patch.object(metadata, 'ROOT', Path(directory)):
                metadata.main()
                text = (Path(directory) / 'backend/build/version-info.txt').read_text(encoding='utf-8')
        self.assertIn(info['version'], text)
        self.assertIn('(0, 1, 0, 4)', text)


class LocalReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sap-lens-local-æ ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        self.run_git('config', 'user.email', 'synthetic@example.invalid')
        self.run_git('config', 'user.name', 'Synthetic Test')
        (self.root / '.gitignore').write_text('backend/build/\nfrontend/dist/\n')
        (self.root / 'source.py').write_text('VALUE = 1\n')
        self.run_git('add', '.')
        self.run_git('-c', 'commit.gpgsign=false', 'commit', '-qm', 'Synthetic baseline')
        for directory in ['frontend/dist', 'backend/build/python-env']:
            (self.root / directory).mkdir(parents=True)
            (self.root / directory / 'input.txt').write_text('validated')

    def run_git(self, *args):
        return subprocess.run(['git', *args], cwd=self.root, check=True, capture_output=True)

    def record(self):
        return local.record('0.1.0', local.REQUIRED, self.root)

    def test_clean_matching_receipt_accepts_spaces_and_unicode_paths(self):
        value = self.record()
        self.assertEqual(local.check('0.1.0', self.root), value)
        self.assertNotIn(str(self.root), json.dumps(value))

    def test_receipt_requires_complete_validation(self):
        with self.assertRaises(ValueError):
            local.record('0.1.0', local.REQUIRED[:-1], self.root)
        self.assertFalse(local.receipt_path(self.root).exists())
        with self.assertRaises(ValueError):
            local.check('0.1.0', self.root)

    def test_changed_source_commit_version_dependencies_or_frontend_fail_closed(self):
        for relative in ['source.py', 'frontend/dist/input.txt', 'backend/build/python-env/input.txt']:
            self.record()
            path = self.root / relative
            original = path.read_bytes()
            path.write_bytes(b'changed')
            with self.subTest(path=relative), self.assertRaises(ValueError):
                local.check('0.1.0', self.root)
            path.write_bytes(original)
        self.record()
        with self.assertRaises(ValueError):
            local.check('0.1.0-beta-4', self.root)
        (self.root / 'source.py').write_text('VALUE = 2\n')
        self.run_git('add', '.')
        self.run_git('-c', 'commit.gpgsign=false', 'commit', '-qm', 'Changed source')
        with self.assertRaises(ValueError):
            local.check('0.1.0', self.root)

    def test_old_future_corrupt_incomplete_receipts_are_rejected(self):
        value = self.record()
        for now in [value['validated_at'] - 1, value['validated_at'] + local.MAX_AGE + 1]:
            with self.assertRaises(ValueError):
                local.check('0.1.0', self.root, now=now)
        bad = copy.deepcopy(value)
        bad['stages'].pop()
        local.write_json(local.receipt_path(self.root), bad)
        with self.assertRaises(ValueError):
            local.check('0.1.0', self.root)
        local.receipt_path(self.root).write_text('not JSON')
        with self.assertRaises(ValueError):
            local.check('0.1.0', self.root)

    def test_bytecode_does_not_invalidate_but_real_environment_changes_do(self):
        self.record()
        cache = self.root / 'backend/build/python-env/__pycache__'
        cache.mkdir()
        (cache / 'runtime.pyc').write_bytes(b'temporary bytecode')
        local.check('0.1.0', self.root)
        (self.root / 'backend/build/python-env/extra.dll').write_bytes(b'unverified')
        with self.assertRaises(ValueError):
            local.check('0.1.0', self.root)

    def test_untracked_source_is_not_silently_packaged(self):
        self.record()
        (self.root / 'unexpected.py').write_text('private = True')
        with self.assertRaises(ValueError):
            local.check('0.1.0', self.root)


class LocalToolingTests(unittest.TestCase):
    def test_actionlint_windows_download_checksum_cache_and_extraction(self):
        spec = importlib.util.spec_from_file_location('local_ci', ROOT / 'scripts/ci.py')
        ci = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ci)
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            archive.writestr('actionlint.exe', b'synthetic executable, never executed')
        payload = data.getvalue()
        with tempfile.TemporaryDirectory() as directory, patch.object(ci.platform, 'system', return_value='Windows'), patch.object(ci.platform, 'machine', return_value='AMD64'), patch.object(ci, 'ACTIONLINT_WINDOWS_SHA256', hashlib.sha256(payload).hexdigest()), patch.dict(os.environ, {'RUNNER_TEMP':directory}), patch.object(ci.subprocess, 'call', return_value=0) as execute:
            with patch.object(ci.urllib.request, 'urlopen', return_value=io.BytesIO(payload)) as download:
                self.assertEqual(ci.lint(), 0)
                self.assertIn('windows_amd64.zip', download.call_args.args[0])
            tool = Path(directory) / ('actionlint-' + ci.ACTIONLINT_VERSION + '.exe')
            self.assertEqual(tool.read_bytes(), b'synthetic executable, never executed')
            tool.write_bytes(b'tampered extracted tool')
            with patch.object(ci.urllib.request, 'urlopen') as download:
                self.assertEqual(ci.lint(), 0)
                download.assert_not_called()
            self.assertEqual(tool.read_bytes(), b'synthetic executable, never executed')
            cached = next(Path(directory).glob('*.zip'))
            cached.write_bytes(b'corrupt cache')
            with patch.object(ci.urllib.request, 'urlopen', return_value=io.BytesIO(b'corrupt download')):
                with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                    ci.lint()
            self.assertEqual(execute.call_count, 2)

    @unittest.skipUnless(shutil.which('pwsh') and os.name != 'nt', 'Requires PowerShell on Linux')
    def test_powershell_rejects_non_windows_and_invalid_arguments(self):
        env = {**os.environ, 'OS':'Linux'}
        for mode in ['Quick', 'Validate', 'Build', 'Package']:
            result = subprocess.run(['pwsh', '-NoProfile', '-File', str(ROOT / 'scripts/build-local.ps1'), '-Mode', mode], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('require Windows x64', result.stdout)
            self.assertIn('failed', result.stdout)
        result = subprocess.run(['pwsh', '-NoProfile', '-File', str(ROOT / 'scripts/build-local.ps1'), '-Mode', 'Unknown'], env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ValidateSet', result.stderr)

    def test_local_ensure_uses_git_identity_without_github_run_numbers(self):
        release = local.load_script('release-windows')
        with tempfile.TemporaryDirectory() as directory, patch.object(release, 'ROOT', Path(directory)), patch.dict(os.environ, {'SAP_LENS_LOCAL_VERSION':'0.1.0-beta-4'}, clear=True), patch.object(release.subprocess, 'check_output', return_value='b'*40 + '\n') as git, patch.object(sys, 'argv', ['release-windows.py', 'ensure-local-build']):
            release.main()
            info = json.loads((Path(directory) / 'backend/build/build-version.json').read_text())
            self.assertEqual(info, local.version.make_local_package_info('0.1.0-beta-4', 'b'*40))
            self.assertEqual(git.call_args.args[0], ['git', 'rev-parse', 'HEAD'])

    def test_packaging_tools_follow_requirements_not_duplicate_version_constants(self):
        with patch.object(local.importlib.metadata, 'version', side_effect=lambda name: {'pyinstaller':'6.22.3', 'pywebview':'6.2.1'}[name]):
            local.check_packaging_tools()
        with patch.object(local.importlib.metadata, 'version', return_value='0.0.0'):
            with self.assertRaises(ValueError):
                local.check_packaging_tools()


class LocalExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'backend/dist').mkdir(parents=True)
        (self.root / 'backend/build').mkdir()
        self.exe = self.root / 'backend/dist/SAP-Lens.exe'
        self.exe.write_bytes(b'Synthetic EXE, never executed')
        self.sha = local.digest(self.exe)
        (self.exe.parent / 'SAP-Lens.exe.sha256').write_text(self.sha + '  SAP-Lens.exe\n')
        local.write_json(self.root / 'backend/build/package-verification.json', {'exe_sha256':self.sha})
        (self.root / 'backend/build/timings.jsonl').write_text('\n'.join(json.dumps({'stage':name,'status':'passed'}) for name in ['PyInstaller packaging (clean)', 'Package verification and checksum', 'EXE smoke testing']))
        self.info = local.version.make_local_package_info('0.1.0', 'a'*40)
        self.output = self.root / 'dist/local/packages/synthetic'

    def test_exact_archive_is_roundtripped_and_extracted_exe_reverified(self):
        # Stub only the native PE subprocess; real ZIP parser/digest/content checks run.
        with patch.object(local, 'identity', return_value=self.info), patch.object(local, 'check', return_value={'stages':local.REQUIRED}), patch.object(local.subprocess, 'run') as pe:
            local.export('0.1.0', self.output, self.root)
        with zipfile.ZipFile(next((self.output / 'archive').glob('*.zip'))) as archive:
            self.assertEqual(set(archive.namelist()), {'SAP-Lens.exe','SAP-Lens.exe.sha256'})
        args = pe.call_args.args[0]
        self.assertIn(str(self.output / 'application'), args)
        self.assertIn(self.sha, args)
        self.assertTrue(pe.call_args.kwargs['check'])
        manifest = json.loads((self.output / 'build-manifest.json').read_text())
        self.assertFalse(manifest['official_release'])
        self.assertEqual(manifest['signing'], 'disabled')
        self.assertEqual(manifest['exe_sha256'], self.sha)
        self.assertEqual(local.digest(next((self.output / 'archive').glob('*.zip'))), manifest['zip_sha256'])

    def test_changed_exe_or_failed_native_smoke_cannot_be_exported(self):
        with patch.object(local, 'identity', return_value=self.info):
            self.exe.write_bytes(b'changed after verification')
            with self.assertRaises(ValueError):
                local.export('0.1.0', self.output, self.root)
            (self.root / 'backend/build/timings.jsonl').write_text(json.dumps({'stage':'EXE smoke testing', 'status':'failed'}))
            with self.assertRaises(ValueError):
                local.export('0.1.0', self.output, self.root)
        self.assertFalse(self.output.exists())

    def test_failed_distribution_verification_never_writes_success_manifest(self):
        with patch.object(local, 'identity', return_value=self.info), patch.object(local.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'synthetic verifier')):
            with self.assertRaises(subprocess.CalledProcessError):
                local.export('0.1.0', self.output, self.root)
        self.assertFalse((self.output / 'build-manifest.json').exists())
