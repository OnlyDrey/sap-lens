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
spec = importlib.util.spec_from_file_location('local_builder', ROOT / 'scripts/packaging/local-build.py')
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
        spec = importlib.util.spec_from_file_location('local_metadata', ROOT / 'scripts/packaging/write-windows-metadata.py')
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

    def test_previous_receipt_schema_does_not_claim_current_packaging_validation(self):
        saved = self.record()
        saved['schema'] = 1
        local.write_json(local.receipt_path(self.root), saved)
        with self.assertRaisesRegex(ValueError, 'stale'):
            local.check('0.1.0', self.root)



class ActionlintAcquisitionTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('local_ci_acq', ROOT / 'scripts/testing/ci.py')
        self.ci = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.ci)
        self.payload = b'synthetic archive'
        self.digest = hashlib.sha256(self.payload).hexdigest()
        self.name = 'actionlint-' + self.ci.ACTIONLINT_VERSION + '-pkg.zip'

    def acquire(self, directory, **env):
        with patch.dict(os.environ, env, clear=False):
            return self.ci.acquire_actionlint('pkg.zip', self.digest, 'https://example.invalid/a.zip', Path(directory))

    def test_cache_hit_needs_no_network(self):
        with tempfile.TemporaryDirectory() as d, patch.object(self.ci.managed_tools, 'open_url') as net:
            (Path(d) / self.name).write_bytes(self.payload)
            self.assertEqual(self.acquire(d), self.payload); net.assert_not_called()

    def test_persistent_cache_is_preferred_and_receives_downloads(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as cache:
            with patch.object(self.ci.managed_tools, 'open_url', return_value=io.BytesIO(self.payload)):
                self.acquire(d, SAP_LENS_TOOL_CACHE=cache)
            self.assertEqual((Path(cache) / self.name).read_bytes(), self.payload)
            self.assertFalse((Path(d) / self.name).exists())

    def test_corrupted_cache_is_ignored_and_redownloaded(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / self.name).write_bytes(b'corrupt')
            with patch.object(self.ci.managed_tools, 'open_url', return_value=io.BytesIO(self.payload)) as net:
                self.assertEqual(self.acquire(d), self.payload); net.assert_called_once()

    def test_failed_download_reports_url_status_cache_and_recovery_and_blocks(self):
        import urllib.error
        error = urllib.error.HTTPError('https://example.invalid/a.zip', 403, 'Forbidden', {}, None)
        with tempfile.TemporaryDirectory() as d, patch.object(self.ci.managed_tools, 'open_url', side_effect=error):
            with self.assertRaises(self.ci.ActionlintUnavailable) as raised: self.acquire(d)
            message = str(raised.exception)
            for token in ('403', 'https://example.invalid/a.zip', d, 'SAP_LENS_ACTIONLINT_ARCHIVE', 'never disabled'): self.assertIn(token, message)
            with patch.object(self.ci, 'lint', side_effect=self.ci.ActionlintUnavailable('x')), patch.object(sys, 'argv', ['ci.py', 'lint']):
                self.assertEqual(self.ci.main(), 2)

    def test_checksum_mismatch_is_discarded(self):
        with tempfile.TemporaryDirectory() as d, patch.object(self.ci.managed_tools, 'open_url', return_value=io.BytesIO(b'other')):
            with self.assertRaisesRegex(self.ci.ActionlintUnavailable, 'checksum mismatch'): self.acquire(d)
            self.assertFalse((Path(d) / self.name).exists())

    def test_offline_local_archive_never_touches_the_network(self):
        with tempfile.TemporaryDirectory() as d, patch.object(self.ci.managed_tools, 'open_url') as net:
            archive = Path(d) / 'mine.zip'; archive.write_bytes(self.payload)
            self.assertEqual(self.acquire(d, SAP_LENS_ACTIONLINT_ARCHIVE=str(archive)), self.payload); net.assert_not_called()
            archive.write_bytes(b'tampered')
            with self.assertRaisesRegex(self.ci.ActionlintUnavailable, 'SHA-256 does not match'): self.acquire(d, SAP_LENS_ACTIONLINT_ARCHIVE=str(archive))


class LocalToolingTests(unittest.TestCase):
    def test_actionlint_windows_download_checksum_cache_and_extraction(self):
        spec = importlib.util.spec_from_file_location('local_ci', ROOT / 'scripts/testing/ci.py')
        ci = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ci)
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            archive.writestr('actionlint.exe', b'synthetic executable, never executed')
        payload = data.getvalue()
        with tempfile.TemporaryDirectory() as directory, patch.object(ci.platform, 'system', return_value='Windows'), patch.object(ci.platform, 'machine', return_value='AMD64'), patch.object(ci, 'ACTIONLINT_WINDOWS_SHA256', hashlib.sha256(payload).hexdigest()), patch.dict(os.environ, {'RUNNER_TEMP':directory}), patch.object(ci.subprocess, 'call', return_value=0) as execute, patch.object(ci.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, ci.ACTIONLINT_VERSION)):
            with patch.object(ci.managed_tools, 'open_url', return_value=io.BytesIO(payload)) as download:
                self.assertEqual(ci.lint(), 0)
                self.assertIn('windows_amd64.zip', download.call_args.args[0].full_url)
            tool = Path(directory) / ('actionlint-' + ci.ACTIONLINT_VERSION + '.exe')
            self.assertEqual(tool.read_bytes(), b'synthetic executable, never executed')
            tool.write_bytes(b'tampered extracted tool')
            with patch.object(ci.managed_tools, 'open_url') as download:
                self.assertEqual(ci.lint(), 0)
                download.assert_not_called()
            self.assertEqual(tool.read_bytes(), b'synthetic executable, never executed')
            cached = next(Path(directory).glob('*.zip'))
            cached.write_bytes(b'corrupt cache')
            with patch.object(ci.managed_tools, 'open_url', return_value=io.BytesIO(b'corrupt download')):
                with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                    ci.lint()
            commands=[call.args[0] for call in execute.call_args_list]
            self.assertEqual(commands.count([str(tool)]),2)
            self.assertEqual(sum(str(command[-1]).endswith('check-docs.py') for command in commands),2)
            self.assertEqual(len(commands),4)

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


    @unittest.skipUnless(shutil.which('powershell' if os.name == 'nt' else 'pwsh') or shutil.which('pwsh'), 'Requires Windows PowerShell 5.1 or PowerShell 7')
    def test_node_gate_accepts_24_and_25_and_rejects_unvalidated_majors(self):
        # Execute the actual preflight expression without invoking Windows setup.
        script = r'''$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $env:SAP_LENS_TEST_ROOT 'scripts/build-local.ps1'), [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'PowerShell parse failure' }
$guard = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.IfStatementAst] -and
    $node.Clauses[0].Item1.Extent.Text -match 'nodeVersion'
}, $true)
if (-not $guard) { throw 'Missing Node preflight check' }
$condition = [scriptblock]::Create($guard.Clauses[0].Item1.Extent.Text)
foreach ($version in @('22.12.0', '23.0.0', '24.0.0', '24.19.0', '25.0.0', '25.9.0', '26.0.0')) {
    $nodeVersion = $version; $LASTEXITCODE = 0
    Write-Output "$version=$(& $condition)"
}
$nodeVersion = '24.0.0'; $LASTEXITCODE = 1
Write-Output "command-failed=$(& $condition)"
'''
        result = subprocess.run([(shutil.which('powershell') if os.name == 'nt' else None) or shutil.which('pwsh'), '-NoProfile', '-Command', script],
                                env={**os.environ, 'SAP_LENS_TEST_ROOT':str(ROOT)},
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.splitlines(), [
            '22.12.0=True', '23.0.0=True', '24.0.0=False', '24.19.0=False',
            '25.0.0=False', '25.9.0=False', '26.0.0=True', 'command-failed=True'])
        manifest = json.loads((ROOT / 'frontend/package.json').read_text())
        lock = json.loads((ROOT / 'frontend/package-lock.json').read_text())
        self.assertEqual(manifest['engines']['node'], '>=24 <26')
        self.assertEqual(lock['packages']['']['engines'], manifest['engines'])


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
        distribution_index = args.index("--distribution")
        actual_distribution = Path(args[distribution_index + 1])
        expected_distribution = self.output / "application"

        self.assertTrue(
            os.path.samefile(actual_distribution, expected_distribution),
            f"Distribution path mismatch: {actual_distribution} != {expected_distribution}",
        )
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


class BuildEntryRepairTests(unittest.TestCase):
    def test_authoritative_default_and_prerelease_identity_are_preserved(self):
        product = local.version.product_version()
        result = subprocess.run([sys.executable, str(ROOT/'scripts/packaging/local-build.py'), 'version'], cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), product)
        for requested in ('1.0.0', '1.0.0-alpha.2', '1.0.0-beta.2', '1.0.0-rc.3', '1.0.0-beta-4'):
            info = local.identity(requested)
            self.assertEqual(info['version'].split('+')[0], requested)
            self.assertEqual(local.version.parse_build_info(info), info)
        wrapper = (ROOT/'scripts'/'build.ps1').read_text()
        self.assertNotIn('[Parameter(Mandatory=$true)][string]$Version', wrapper)
        self.assertIn("@('--version',$Version)", wrapper)

    def test_canonical_packager_uses_the_same_default_version_as_the_local_entry(self):
        release=local.load_script('release-windows')
        product=local.version.product_version()
        with tempfile.TemporaryDirectory() as directory, patch.object(release,'ROOT',Path(directory)), patch.dict(os.environ,{},clear=True), patch.object(release.subprocess,'check_output',return_value='b'*40+'\n'), patch.object(sys,'argv',['release-windows.py','ensure-local-build']):
            release.main()
            info=json.loads((Path(directory)/'backend/build/build-version.json').read_text())
        self.assertEqual(info,local.version.make_local_package_info(product,'b'*40))
        entry=(ROOT/'scripts/build-local.ps1').read_text()
        self.assertLess(entry.index("Run-Stage 'Version resolution'"),entry.index('$env:SAP_LENS_LOCAL_VERSION = $Version'))

    def test_quick_is_offline_read_only_and_does_not_touch_receipts_or_versions(self):
        names = ['backend/resources/product-version.json', 'frontend/package.json', 'frontend/package-lock.json', 'backend/build/build-version.json', 'backend/build/local-validation.json']
        before = {name:(ROOT/name).read_bytes() if (ROOT/name).exists() else None for name in names}
        with patch.object(local, 'git', return_value='a'*40), patch.object(local, 'write_json') as write, patch.object(local.urllib.request, 'urlopen') as download, patch.object(local.subprocess, 'run') as execute:
            result = local.quick(local.version.product_version())
        self.assertTrue(result['version'].startswith(local.version.product_version()+'+local.'))
        write.assert_not_called(); download.assert_not_called(); execute.assert_not_called()
        self.assertEqual(before, {name:(ROOT/name).read_bytes() if (ROOT/name).exists() else None for name in names})

    def test_quick_checks_required_inputs_and_manifest_consistency(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            names=set(local.QUICK_INPUTS)|{'backend/version.py','scripts/packaging/local-build.py'}
            for name in names:
                destination=root/name; destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,destination)
            with patch.object(local, 'identity', return_value=local.version.local_build_info()):
                local.quick(local.version.product_version(),root)
                manifest=root/'frontend/package.json';original=manifest.read_text();value=json.loads(original);value['version']='0.0.0';manifest.write_text(json.dumps(value))
                with self.assertRaisesRegex(ValueError,'versions differ'):local.quick(local.version.product_version(),root)
                manifest.write_text(original)
                (root/'assets/sap-lens.ico').unlink()
                with self.assertRaisesRegex(ValueError,'Missing or unsafe'):local.quick(local.version.product_version(),root)

    def test_entry_point_keeps_quick_light_and_packaging_validation_targeted(self):
        entry=(ROOT/'scripts/build-local.ps1').read_text()
        quick=entry.split("if ($Mode -eq 'Quick') {",1)[1].split('    } else {',1)[0]
        for forbidden in ('FrontendInstall','npm ci','pip install','unittest discover','invalidate','record'):
            self.assertNotIn(forbidden,quick)
        for command in ('local-build.py','scripts/product-version.mjs','scripts/check-docs.py','check-powershell.ps1'):
            self.assertIn(command, entry)
        self.assertIn('-TargetedValidation',entry)
        self.assertIn('-IncludeService',entry)
        self.assertNotIn(".Replace('-beta.'",entry)
        canonical=(ROOT/'scripts/build-windows.ps1').read_text()
        self.assertIn("'--grep', '@smoke'",canonical)
        for pattern in ('test_desktop.py','test_windows_package.py','test_server.py','test_build_version.py','test_local_build.py'):
            self.assertIn(pattern,canonical)
        self.assertIn('--windowed',canonical)
        self.assertIn('verify-windows-package.py',canonical)
        self.assertIn('test-windows-exe.ps1',canonical)

    def test_service_self_test_uses_same_source_without_launching_the_elevated_manager(self):
        script=(ROOT/'scripts/build-service-manager.ps1').read_text()
        self.assertIn('SapLens.ServiceSetup.SelfTest()',script)
        self.assertIn('level="asInvoker"',script)
        self.assertIn('/main:SapLensSelfTest',script)
        self.assertIn('Start-Process -FilePath $check',script)
        self.assertNotIn('Start-Process -FilePath $output',script)
        self.assertIn('finally',script)
        self.assertIn('Remove-Item -LiteralPath $temporary',script)
        self.assertIn('requireAdministrator',(ROOT/'deploy/windows/service-manager.manifest').read_text())
        self.assertIn('scripts/build-service-manager.ps1',(ROOT/'scripts/check-powershell.ps1').read_text())

    def test_server_and_ci_share_verified_wrapper_download(self):
        service=(ROOT/'scripts/build-server-windows.ps1').read_text()
        dispatch=(ROOT/'scripts/package-windows-deployment.ps1').read_text()
        self.assertNotIn('[Parameter(Mandatory=$true)][string]$WinSW',service)
        self.assertIn('local-build.py winsw --output',service)
        self.assertIn('local-build.py winsw --output',dispatch)
        self.assertNotIn('Invoke-WebRequest',dispatch)
        self.assertNotIn(".Replace('-beta.'",service)
        self.assertIn('Get-FileHash $WinSW',service)


class WinSWAcquisitionTests(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.output=Path(self.temp.name)/'WinSW-x64.exe'
        self.payload=b'synthetic wrapper bytes; never executed'
        pin=hashlib.sha256(self.payload).hexdigest()
        patcher=patch.object(local,'load_script',return_value=SimpleNamespace(WINSW_SHA=pin))
        patcher.start();self.addCleanup(patcher.stop)

    def test_verified_download_is_atomic_and_valid_cache_is_reused(self):
        with patch.object(local.urllib.request,'urlopen',return_value=io.BytesIO(self.payload)) as download:
            self.assertEqual(local.fetch_winsw(self.output),self.output)
            self.assertEqual(self.output.read_bytes(),self.payload)
            self.assertIn('/v2.12.0/WinSW-x64.exe',download.call_args.args[0])
        with patch.object(local.urllib.request,'urlopen') as download:
            local.fetch_winsw(self.output)
            download.assert_not_called()
        self.assertFalse(list(self.output.parent.glob('*.download')))

    def test_bad_checksum_does_not_activate_or_leave_temporary_download(self):
        with patch.object(local.urllib.request,'urlopen',return_value=io.BytesIO(b'corrupted')):
            with self.assertRaisesRegex(ValueError,'SHA-256 mismatch'):local.fetch_winsw(self.output)
        self.assertFalse(self.output.exists());self.assertFalse(list(self.output.parent.glob('*.download')))

    def test_network_failure_is_actionable_and_does_not_activate_wrapper(self):
        with patch.object(local.urllib.request,'urlopen',side_effect=OSError('synthetic offline')):
            with self.assertRaisesRegex(ValueError,'verified offline -WinSW'):local.fetch_winsw(self.output)
        self.assertFalse(self.output.exists());self.assertFalse(list(self.output.parent.glob('*.download')))

    def test_tampered_cache_fails_without_redownloading_or_overwriting(self):
        self.output.write_bytes(b'tampered')
        with patch.object(local.urllib.request,'urlopen') as download:
            with self.assertRaisesRegex(ValueError,'Cached WinSW'):local.fetch_winsw(self.output)
            download.assert_not_called()
        self.assertEqual(self.output.read_bytes(),b'tampered')


class ManagedToolResolverTests(unittest.TestCase):
    """Only synthetic archives and mocked networking/version probes; no tool is installed or executed."""
    def setUp(self):
        from build_system import managed_tools
        self.tools = managed_tools
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            archive.writestr('actionlint.exe', b'synthetic executable')
        self.payload = data.getvalue()
        self.digest = hashlib.sha256(self.payload).hexdigest()
        for mock in (patch.dict(os.environ, dict.fromkeys(('SAP_LENS_TOOL_CACHE', 'SAP_LENS_ACTIONLINT_ARCHIVE', 'SAP_LENS_ACTIONLINT_MIRROR', 'SAP_LENS_TOOLS_OFFLINE'), '')),
                     patch.object(self.tools.platform, 'system', return_value='Windows'), patch.object(self.tools.platform, 'machine', return_value='AMD64'),
                     patch.object(self.tools.shutil, 'which', return_value=None)):
            mock.start(); self.addCleanup(mock.stop)

    def resolve(self):
        return self.tools.resolve_actionlint(self.directory, expected=self.digest, report=lambda text: None)

    def archive(self):
        return self.directory / f'actionlint-{self.tools.ACTIONLINT_VERSION}-windows_amd64.zip'

    def version(self, value=None):
        return patch.object(self.tools.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, value or self.tools.ACTIONLINT_VERSION))

    def test_success_cached_offline_and_binary_repair(self):
        with patch.object(self.tools, 'open_url', side_effect=lambda request: io.BytesIO(self.payload)) as net, self.version():
            tool = self.resolve()
            self.assertEqual(tool.read_bytes(), b'synthetic executable')
            self.assertEqual(net.call_count, 1)
        tool.write_bytes(b'corrupt')
        with patch.dict(os.environ, {'SAP_LENS_TOOLS_OFFLINE': '1'}), patch.object(self.tools, 'open_url') as net, self.version():
            self.assertEqual(self.resolve().read_bytes(), b'synthetic executable')
            net.assert_not_called()
        self.assertFalse(list(self.directory.glob('.tool-*')))

    def test_offline_missing_cache_is_a_block_without_network(self):
        with patch.dict(os.environ, {'SAP_LENS_TOOLS_OFFLINE': '1'}), patch.object(self.tools, 'open_url') as net:
            with self.assertRaisesRegex(self.tools.ToolUnavailable, 'offline: no verified cache'): self.resolve()
            net.assert_not_called()

    def test_permanent_http_errors_are_not_retried_and_secrets_are_not_printed(self):
        import urllib.error
        for status in (403, 404):
            with self.subTest(status=status), patch.object(self.tools, 'open_url', side_effect=urllib.error.HTTPError('https://invalid/?token=secret-value', status, 'secret-value', {}, None)) as net:
                with self.assertRaises(self.tools.ToolUnavailable) as raised: self.resolve()
                self.assertIn(f'HTTP {status}', str(raised.exception))
                self.assertNotIn('secret-value', str(raised.exception))
                self.assertEqual(net.call_count, 1)

    def test_transient_network_errors_retry_three_times_with_bounded_backoff(self):
        import urllib.error
        import http.client
        for error in (TimeoutError(), ConnectionResetError(), urllib.error.URLError('proxy secret-value refused'), http.client.IncompleteRead(b'partial'), urllib.error.HTTPError('https://invalid', 503, 'Unavailable', {}, None)):
            with self.subTest(error=type(error).__name__), patch.object(self.tools, 'open_url', side_effect=error) as net, patch.object(self.tools.time, 'sleep') as wait:
                with self.assertRaises(self.tools.ToolUnavailable) as raised: self.resolve()
                self.assertNotIn('secret-value', str(raised.exception))
                self.assertEqual(net.call_count, 3)
                self.assertEqual([call.args[0] for call in wait.call_args_list], [0.25, 0.5])
                self.assertFalse(self.archive().exists())

    def test_transient_download_recovers_and_mirror_403_falls_back(self):
        import urllib.error
        responses = [urllib.error.HTTPError('https://mirror.invalid',403,'Forbidden',{},None), io.BytesIO(self.payload)]
        with patch.dict(os.environ, {'SAP_LENS_ACTIONLINT_MIRROR': 'https://mirror.invalid/tools'}), patch.object(self.tools, 'open_url', side_effect=responses) as net, self.version():
            self.resolve()
            self.assertTrue(net.call_args_list[0].args[0].full_url.startswith('https://mirror.invalid/tools/'))
            self.assertTrue(net.call_args_list[1].args[0].full_url.startswith('https://github.com/rhysd/'))

    def test_mirror_success_uses_pinned_checksum_and_no_upstream(self):
        with patch.dict(os.environ, {'SAP_LENS_ACTIONLINT_MIRROR': 'https://mirror.invalid/tools'}), patch.object(self.tools, 'open_url', return_value=io.BytesIO(self.payload)) as net, self.version():
            self.resolve(); self.assertEqual(net.call_count, 1)
            self.assertIn('/tools/actionlint_1.7.12_windows_amd64.zip', net.call_args.args[0].full_url)

    def test_wrong_version_blocks_execution_even_with_verified_archive(self):
        self.archive().write_bytes(self.payload)
        with self.version('1.7.11'), self.assertRaisesRegex(self.tools.ToolUnavailable, 'version mismatch'): self.resolve()

    def test_corrupt_checksum_never_publishes_or_probes(self):
        with patch.object(self.tools, 'open_url', return_value=io.BytesIO(b'bad')), patch.object(self.tools.subprocess, 'run') as run:
            with self.assertRaisesRegex(self.tools.ToolUnavailable, 'checksum mismatch'): self.resolve()
            self.assertFalse(self.archive().exists()); run.assert_not_called()

    def test_interrupted_publication_leaves_no_partial_archive(self):
        with patch.object(self.tools, 'open_url', return_value=io.BytesIO(self.payload)), patch.object(self.tools.os, 'replace', side_effect=OSError('synthetic interrupt')):
            with self.assertRaisesRegex(self.tools.ToolUnavailable, 'could not be cached'): self.resolve()
        self.assertFalse(self.archive().exists()); self.assertFalse(list(self.directory.glob('.tool-*')))

    def test_concurrent_resolution_downloads_once(self):
        from concurrent.futures import ThreadPoolExecutor
        with patch.object(self.tools, 'open_url', side_effect=lambda request: io.BytesIO(self.payload)) as net, self.version():
            with ThreadPoolExecutor(max_workers=3) as executor:
                results = list(executor.map(lambda _: self.resolve(), range(3)))
            self.assertEqual(len(set(results)), 1); self.assertEqual(net.call_count, 1)

    def test_tls_failure_is_not_retried_and_downgrade_is_refused(self):
        import ssl
        with patch.object(self.tools, 'open_url', side_effect=ssl.SSLCertVerificationError()) as net:
            with self.assertRaisesRegex(self.tools.ToolUnavailable, 'TLS verification failure'): self.resolve()
            self.assertEqual(net.call_count, 1)
        with self.assertRaisesRegex(self.tools.ToolUnavailable, 'insecure scheme'):
            self.tools.SecureRedirect().redirect_request(None, None, 302, '', {}, 'http://invalid/tool')

    def test_unsupported_platform_never_fetches(self):
        with patch.object(self.tools.platform, 'system', return_value='Darwin'), patch.object(self.tools, 'open_url') as net:
            with self.assertRaisesRegex(self.tools.ToolUnavailable, 'Windows or Linux x64'): self.resolve()
            net.assert_not_called()

    def test_preflight_precedes_expensive_validation_and_receipt_reuse_needs_no_tool(self):
        local_source = (ROOT/'scripts/build_system/windows/local.py').read_text()
        self.assertLess(local_source.index("run_stage('Managed tool preflight'"), local_source.index("run_stage('Environment'"))
        deploy = (ROOT/'scripts/deployment/build-deployments.py').read_text()
        self.assertLess(deploy.index("self.run('Managed tool preflight'"), deploy.index("self.run('Create dedicated build Python environment'"))
        self.assertLess(deploy.index('if self.args.reuse_validation:'), deploy.index("self.run('Managed tool preflight'"))
        self.assertIn("if Mode != 'Package':\n                run_stage('Managed tool preflight'", local_source)

    def test_linux_archive_and_approved_path_binary(self):
        import tarfile
        content = b'synthetic executable'
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
            member = tarfile.TarInfo('actionlint'); member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
        self.payload = buffer.getvalue(); self.digest = hashlib.sha256(self.payload).hexdigest()
        candidate = self.directory / 'approved-actionlint'; candidate.write_bytes(content)
        with patch.object(self.tools.platform, 'system', return_value='Linux'), patch.object(self.tools.shutil, 'which', return_value=str(candidate)), patch.object(self.tools, 'open_url', return_value=io.BytesIO(self.payload)), self.version():
            self.assertEqual(self.resolve(), candidate)

    def test_transient_failure_can_recover_without_a_partial_cache(self):
        with patch.object(self.tools, 'open_url', side_effect=[TimeoutError(), io.BytesIO(self.payload)]) as net, patch.object(self.tools.time, 'sleep') as wait, self.version():
            self.resolve(); self.assertEqual(net.call_count, 2); wait.assert_called_once_with(0.25)
            self.assertEqual(self.archive().read_bytes(), self.payload)

    def test_zip_link_member_is_not_executed(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            member = zipfile.ZipInfo('actionlint.exe'); member.external_attr = 0o120777 << 16
            archive.writestr(member, 'untrusted-target')
        self.payload = buffer.getvalue(); self.digest = hashlib.sha256(self.payload).hexdigest()
        with patch.object(self.tools, 'open_url', return_value=io.BytesIO(self.payload)), patch.object(self.tools.subprocess, 'run') as run:
            with self.assertRaisesRegex(self.tools.ToolUnavailable, 'member is invalid'): self.resolve()
            run.assert_not_called()

    def test_source_diagnostics_hide_mirror_path_and_authentication(self):
        self.assertEqual(self.tools.safe_url('https://user:password@mirror.invalid/private-token/file.zip?token=secret'), 'https://mirror.invalid/file.zip')

    def test_inno_uses_shared_verified_acquisition_without_running_installer(self):
        with patch.object(self.tools, 'INNO_SHA256', self.digest), patch.object(self.tools, 'open_url', return_value=io.BytesIO(self.payload)), patch.object(self.tools.subprocess, 'run') as execute:
            self.assertEqual(self.tools.acquire_inno(self.directory, report=lambda text: None), self.payload)
            self.assertEqual((self.directory/'innosetup-7.1.0-x64.exe').read_bytes(), self.payload)
            execute.assert_not_called()
        source = (ROOT/'scripts/build-desktop-installer.ps1').read_text()
        self.assertIn('scripts/testing/ci.py', source)
        self.assertNotIn('Invoke-WebRequest', source)
        self.assertIn('Get-Command python -ErrorAction Stop', source, 'compile check must work before packaging venv creation')

    def test_legacy_verified_archive_is_promoted_without_network(self):
        legacy_root = self.directory/'legacy'
        legacy = legacy_root/'backend/build'; legacy.mkdir(parents=True)
        (legacy/self.archive().name).write_bytes(self.payload)
        with patch.object(self.tools, 'ROOT', legacy_root), patch.object(self.tools, 'open_url') as net, self.version():
            self.resolve(); net.assert_not_called()
        self.assertEqual(self.archive().read_bytes(), self.payload)

    def test_installer_inspection_is_read_only_and_reports_missing_bootstrap(self):
        from argparse import Namespace
        from build_system import doctor
        args = Namespace(mode='prerequisites', platform='windows', target='installer', target_given=True, skip_setup=False)
        with patch.object(doctor.python_env, 'find_python', return_value=(None, [])), patch.object(doctor.python_env, 'inspect_venv', return_value=('missing','',None)), patch.object(doctor, 'tool_item', side_effect=lambda name, required: doctor.item(name, doctor.READY)), patch.object(doctor.deps, 'frontend_current', return_value=True), patch.object(self.tools, 'open_url') as net:
            rows = doctor.collect(args, self.directory)
        row = next(row for row in rows if row['name'] == 'Inno Setup bootstrap')
        self.assertEqual(row['status'], doctor.MISSING); self.assertTrue(row['required'])
        self.assertEqual(list(self.directory.iterdir()), []); net.assert_not_called()
