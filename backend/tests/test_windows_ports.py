"""Golden-command and contract tests for the Python ports of the Windows packaging scripts (service manager, server bundle, installer, deployment packaging).

Linux checks of command lines, paths, order, failures and file effects. They do not run the Windows tools; see docs/BUILD.md for the Windows validation checklist."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_system.windows import installer, local, packaging, server, service_manager, stages  # noqa: E402


class Recorder:
    def __init__(self, hooks=None, fail_on=None, capture='1.2.3'):
        self.commands, self.hooks, self.fail_on, self.value = [], hooks or {}, fail_on, capture

    def run(self, command, cwd, env):
        text = command if isinstance(command, str) else ' '.join(str(part) for part in command)
        self.commands.append(text)
        for marker, hook in self.hooks.items():
            if marker in text:
                hook(command)
        if callable(self.fail_on):
            return 1 if self.fail_on(text) else 0
        return 1 if self.fail_on and self.fail_on in text else 0

    def capture(self, command, cwd, env):
        self.commands.append(' '.join(command))
        return 0, self.value


class Case(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write(self, relative, data='x'):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode())
        return path

    def norm(self, commands):
        python = str(stages.venv_python(self.root))
        return [c.replace(python, '<buildpy>').replace(str(self.root), '<root>').replace('\\', '/') for c in commands]

    def identity(self):
        self.write('backend/build/build-version.json', json.dumps({'version': '1.2.3-beta.4', 'file_version': [1, 2, 3, 4], 'source_sha': 'abc'}))


class ServiceManager(Case):
    def test_compile_and_self_test_sequence(self):
        self.identity()
        windir = self.root / 'win'
        csc = self.write('win/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
        out = self.root / 'out'
        out.mkdir()
        recorder = Recorder()
        service_manager.build(out, self.root, recorder, str(windir), {}, guid='g')
        text = self.norm(recorder.commands)
        refs = ' '.join(service_manager.REFERENCES)
        manager = f'<root>/win/Microsoft.NET/Framework64/v4.0.30319/csc.exe /nologo /target:winexe /platform:x64 /optimize+ /out:<root>/out/SAP-Lens-Service-Manager.exe /win32icon:<root>/assets/sap-lens.ico /win32manifest:<root>/deploy/windows/service-manager.manifest {refs} <root>/deploy/windows/ServiceManager.cs <root>/backend/build/service-manager-version.cs'
        self.assertEqual(text[0], manager)
        self.assertEqual(text[1], f'<root>/win/Microsoft.NET/Framework64/v4.0.30319/csc.exe /nologo /target:exe /platform:x64 /main:SapLensSelfTest /out:<root>/backend/build/service-manager-check-g/SelfTest.exe /win32manifest:<root>/backend/build/service-manager-check-g/self-test.manifest {refs} <root>/deploy/windows/ServiceManager.cs <root>/backend/build/service-manager-check-g/SelfTest.cs')
        self.assertEqual(text[2], '<root>/backend/build/service-manager-check-g/SelfTest.exe')
        generated = (self.root / 'backend/build/service-manager-version.cs').read_text(encoding='utf-8-sig')
        self.assertIn('[assembly: AssemblyVersion("1.2.3.4")]', generated)
        self.assertIn('[assembly: AssemblyInformationalVersion("1.2.3-beta.4")]', generated)
        self.assertFalse((self.root / 'backend/build/service-manager-check-g').exists(), 'the disposable harness is removed')
        self.assertTrue(csc.exists())

    def test_failures_and_cleanup(self):
        self.identity()
        self.write('win/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
        with self.assertRaisesRegex(stages.StageError, 'self-test failed'):
            service_manager.build(self.root, self.root, Recorder(fail_on=lambda text: text.endswith('SelfTest.exe') and '/target' not in text), str(self.root / 'win'), {}, guid='h')
        self.assertFalse((self.root / 'backend/build/service-manager-check-h').exists())
        with self.assertRaisesRegex(stages.StageError, 'compilation failed'):
            service_manager.build(self.root, self.root, Recorder(fail_on='/target:winexe'), str(self.root / 'win'), {})
        with self.assertRaisesRegex(stages.StageError, 'Install .NET Framework 4.8'):
            service_manager.build(self.root, self.root, Recorder(), str(self.root / 'nowhere'), {})


class ServerBundle(Case):
    def prepare(self):
        self.identity()
        stages.venv_python(self.root).parent.mkdir(parents=True, exist_ok=True)
        stages.venv_python(self.root).write_bytes(b'')
        for relative in ('frontend/dist/index.html', 'assets/sap-lens.ico', 'assets/sap-lens.png', 'backend/build/version-info.txt', 'scripts/manage-server-service.ps1',
                         'deploy/windows/LICENSE-WinSW.txt', 'LICENSE.md', 'docs/deployment/WINDOWS_SERVICE.md'):
            self.write(relative)
        wrapper = self.write('backend/build/WinSW-x64.exe', b'wrapper')
        self.pin = hashlib.sha256(b'wrapper').hexdigest()
        return wrapper

    def hooks(self, output):
        def pyinstaller(_):
            self.write(f'{output}/app/SAP-Lens/SAP-Lens.exe')
            self.write(f'{output}/app/SAP-Lens/_internal/data.bin')
        return {'PyInstaller': pyinstaller}

    def test_validated_deployment_sequence_and_layout(self):
        wrapper = self.prepare()
        output = self.root / 'bundle'
        built = []
        original = server.WINSW_SHA256
        server.WINSW_SHA256 = self.pin
        self.addCleanup(setattr, server, 'WINSW_SHA256', original)
        recorder = Recorder(self.hooks(output))
        server.build(str(wrapper), '', True, str(output), self.root, recorder, {}, True, lambda o: built.append(o))
        text = self.norm(recorder.commands)
        self.assertEqual(text[:3], ['<buildpy> scripts/packaging/local-build.py version', '<buildpy> scripts/packaging/local-build.py tools', '<buildpy> scripts/deployment-package.py require-inputs'])
        self.assertEqual(text[3], '<buildpy> scripts/packaging/write-windows-metadata.py')
        pyinstaller = text[4]
        self.assertTrue(pyinstaller.startswith('<buildpy> -m PyInstaller --noconfirm --clean --onedir --console --noupx --name SAP-Lens --distpath <root>/bundle/app --workpath backend/build/server --specpath backend/build/server --paths <root>/backend --icon <root>/assets/sap-lens.ico'))
        self.assertTrue(pyinstaller.endswith('--exclude-module webview --exclude-module pythonnet --exclude-module clr backend/server.py'))
        self.assertEqual(text[5:], ['<buildpy> scripts/deployment-package.py readme --document docs/deployment/WINDOWS_SERVICE.md --directory <root>/bundle', '<buildpy> scripts/packaging/verify-server-bundle.py <root>/bundle'])
        for name in ('app/SAP-Lens.exe', 'app/_internal/data.bin', 'SAPLensService.exe', 'manage-server-service.ps1', 'LICENSE-WinSW.txt', 'LICENSE.md', 'README.md'):
            self.assertTrue((output / name).exists(), name)
        self.assertFalse((output / 'app/SAP-Lens').exists())
        self.assertEqual(built, [output], 'the service manager is built into the bundle')

    def test_local_mode_checks_the_version_and_provisions_winsw(self):
        self.prepare()
        (self.root / 'backend/build/WinSW-x64.exe').unlink()
        output = self.root / 'bundle'
        original = server.WINSW_SHA256
        server.WINSW_SHA256 = hashlib.sha256(b'wrapper').hexdigest()
        self.addCleanup(setattr, server, 'WINSW_SHA256', original)
        hooks = {**self.hooks(output), 'winsw --output': lambda c: self.write('backend/build/WinSW-x64.exe', b'wrapper')}
        recorder = Recorder(hooks)
        server.build('', '', False, str(output), self.root, recorder, {}, True, lambda o: None)
        text = self.norm(recorder.commands)
        self.assertEqual(text[:4], ['<buildpy> scripts/packaging/local-build.py version', '<buildpy> scripts/packaging/local-build.py tools', '<buildpy> scripts/packaging/local-build.py check --version 1.2.3',
                                    '<buildpy> scripts/packaging/local-build.py winsw --output <root>/backend/build/WinSW-x64.exe'])

    def test_guards(self):
        wrapper = self.prepare()
        with self.assertRaisesRegex(stages.StageError, 'x64 Windows'):
            server.build(str(wrapper), '', True, str(self.root / 'b'), self.root, Recorder(), {}, False)
        with self.assertRaisesRegex(stages.StageError, 'does not match the official pinned'):
            server.build(str(wrapper), '', True, str(self.root / 'b'), self.root, Recorder(), {}, True)
        server.WINSW_SHA256, original = self.pin, server.WINSW_SHA256
        self.addCleanup(setattr, server, 'WINSW_SHA256', original)
        (self.root / 'exists').mkdir()
        with self.assertRaisesRegex(stages.StageError, 'Output already exists'):
            server.build(str(wrapper), '', True, str(self.root / 'exists'), self.root, Recorder(), {}, True)
        with self.assertRaisesRegex(stages.StageError, 'Server build failed'):
            server.build(str(wrapper), '', True, str(self.root / 'new'), self.root, Recorder(self.hooks(self.root / 'new'), fail_on='verify-server-bundle'), {}, True, lambda o: None)


class Installer(Case):
    def prepare(self, provisioned=True):
        self.identity()
        self.write('deploy/windows/desktop-installer.iss',(ROOT/'deploy/windows/desktop-installer.iss').read_text())
        stages.venv_python(self.root).parent.mkdir(parents=True, exist_ok=True)
        tool = self.root / f'backend/build/inno-setup-{installer.INNO_VERSION}'
        if provisioned:
            self.write(f'backend/build/inno-setup-{installer.INNO_VERSION}/ISCC.exe', b'compiler')
            self.write(f'backend/build/inno-setup-{installer.INNO_VERSION}/compiler-sha256.txt', hashlib.sha256(b'compiler').hexdigest())
            self.write(f'backend/build/inno-setup-{installer.INNO_VERSION}/license.txt', 'license')
        return tool

    def test_compile_and_name_the_installer(self):
        self.prepare()
        exe = self.write('backend/dist/SAP-Lens.exe', b'portable')
        self.write('backend/build/package-verification.json', json.dumps({'status':'passed','exe_sha256': hashlib.sha256(b'portable').hexdigest()}))
        out = self.root / 'out'
        recorder = Recorder({'ISCC.exe': lambda c: self.write('out/SAP-Lens-Setup.exe', b'setup')})
        named = installer.build(str(out), False, self.root, recorder, {}, True)
        text = self.norm(recorder.commands)
        self.assertEqual(text[0], '<buildpy> <root>/scripts/deployment-package.py require-inputs')
        self.assertEqual(text[1], '<root>/backend/build/inno-setup-7.1.0/ISCC.exe /Qp /O<root>/out /DSourceExe=<root>/backend/dist/SAP-Lens.exe /DProductLicense=<root>/LICENSE.md /DProductIcon=<root>/assets/sap-lens.ico /DFullVersion=1.2.3-beta.4 /DNumericVersion=1.2.3.4 <root>/deploy/windows/desktop-installer.iss')
        self.assertEqual(text[2], '<buildpy> <root>/scripts/packaging/verify-desktop-installer.py --installer <root>/out/SAP-Lens-Windows-Desktop-x64-1.2.3-beta.4-Setup.exe')
        self.assertEqual(named.name, 'SAP-Lens-Windows-Desktop-x64-1.2.3-beta.4-Setup.exe')
        self.assertEqual(named.with_name(named.name + '.sha256').read_text(), f'{hashlib.sha256(b"setup").hexdigest()}  {named.name}\n')
        self.assertTrue((out / 'LICENSE-Inno-Setup.txt').exists())
        self.assertTrue(exe.exists())

    def test_the_executable_must_be_the_verified_one(self):
        self.prepare()
        self.write('backend/dist/SAP-Lens.exe', b'changed')
        self.write('backend/build/package-verification.json', json.dumps({'status':'passed','exe_sha256': 'f' * 64}))
        with self.assertRaisesRegex(stages.StageError, 'changed after canonical verification'):
            installer.build(str(self.root / 'out'), False, self.root, Recorder({'ISCC': lambda c: None}), {}, True)

    def test_compile_check_builds_every_channel_and_cleans_up(self):
        self.prepare()
        self.write('backend/requirements-build.txt', '-r requirements-desktop.txt\npyinstaller==1\npefile==2024.8.26\n')
        out = self.root / 'out'
        out.mkdir()
        recorder = Recorder({'ISCC.exe': lambda c: [(Path(part[2:]) / 'SAP-Lens-Setup.exe').write_bytes(b's') for part in c if part.startswith('/O')]})
        installer.build(str(out), True, self.root, recorder, {}, True)
        text = self.norm(recorder.commands)
        self.assertNotIn('require-inputs', ' '.join(text))
        self.assertEqual(text[0], 'python -m venv <root>/backend/build/installer-check-env')
        self.assertTrue(text[1].endswith('-m pip install --disable-pip-version-check pefile==2024.8.26'))
        verified = [t for t in text if 'verify-desktop-installer.py' in t]
        self.assertEqual([t.split('--compiler-fixture-channel ',1)[1].split()[0] for t in verified], ['alpha', 'beta', 'rc', 'stable', 'beta'])
        versions = [t.split('/DFullVersion=')[1].split(' ')[0] for t in text if '/DFullVersion=' in t]
        self.assertEqual(versions, ['0.1.0-alpha.1', '0.1.0-beta.1', '0.1.0-rc.1', '0.1.0', '0.1.0-beta.1'])
        self.assertEqual(list(out.iterdir()), [], 'the disposable recipe directory is removed')

    def test_provisioning_downloads_verifies_and_installs_per_user(self):
        tool = self.prepare(provisioned=False)
        original = installer.INNO_SHA256
        installer.INNO_SHA256 = hashlib.sha256(b'inno-installer').hexdigest()
        self.addCleanup(setattr, installer, 'INNO_SHA256', original)
        downloads = []
        recorder = Recorder({'/VERYSILENT': lambda c: self.write(f'backend/build/inno-setup-{installer.INNO_VERSION}/ISCC.exe', b'compiler'),
                             '/Qp': lambda c: [(Path(part[2:]) / 'SAP-Lens-Setup.exe').write_bytes(b's') for part in c if part.startswith('/O')]})
        self.write('backend/requirements-build.txt', 'pefile==1.0\n')
        installer.build(str(self.root / 'out'), True, self.root, recorder, {}, True, fetch=lambda url, target: (downloads.append(url), Path(target).write_bytes(b'inno-installer')))
        self.assertEqual(downloads, [installer.INNO_URL])
        command = self.norm(recorder.commands)[0]
        self.assertTrue(command.endswith('/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER /DIR="<root>/backend/build/inno-setup-7.1.0"'), command)
        self.assertEqual((tool / 'compiler-sha256.txt').read_text(), hashlib.sha256(b'compiler').hexdigest())

    def test_a_wrong_download_or_a_changed_compiler_is_rejected(self):
        self.prepare(provisioned=False)
        with self.assertRaisesRegex(stages.StageError, 'download SHA-256 mismatch'):
            installer.build(str(self.root / 'out'), True, self.root, Recorder(), {}, True, fetch=lambda url, target: Path(target).write_bytes(b'tampered'))
        self.prepare()
        (self.root / f'backend/build/inno-setup-{installer.INNO_VERSION}/ISCC.exe').write_bytes(b'replaced')
        with self.assertRaisesRegex(stages.StageError, 'compiler changed after verified provisioning'):
            installer.build(str(self.root / 'out'), True, self.root, Recorder(), {}, True)

    def test_not_windows(self):
        with self.assertRaisesRegex(stages.StageError, 'on Windows'):
            installer.build(str(self.root), False, self.root, Recorder(), {}, False)


class DeploymentPackaging(Case):
    def run_target(self, target, **extra):
        calls = []
        recorder = Recorder()
        stages_seen = []
        bundle = packaging.build(target, '', self.root, recorder, {'GITHUB_ACTIONS': extra.get('actions', '')}, lambda options: stages_seen.append((options.Stage, options.ValidatedDeployment)),
                                 lambda out: (calls.append(('installer', out)), (out / 'SAP-Lens-Windows-Desktop-x64-1.2.3-beta.4-Setup.exe').write_bytes(b's'), (out / 'SAP-Lens-Windows-Desktop-x64-1.2.3-beta.4-Setup.exe.sha256').write_bytes(b'h')),
                                 lambda **kw: calls.append(('server', kw)), guid=lambda: 'g', NativeAcceptance=extra.get('accept', False))
        return recorder, stages_seen, calls, bundle

    def test_desktop_sequence(self):
        self.identity()
        self.write('LICENSE.md', 'license')
        recorder, seen, calls, bundle = self.run_target('Desktop')
        text = self.norm(recorder.commands)
        tests = ['test_desktop.py', 'test_windows_package.py', 'test_server.py']
        self.assertEqual(text[0], 'python scripts/deployment-package.py require-inputs')
        self.assertEqual(text[1:4], [f'<buildpy> -W error::DeprecationWarning -m unittest discover -s backend/tests -p {p} -v' for p in tests])
        self.assertEqual(seen, [('Package', True), ('Verify', False), ('Smoke', False)])
        self.assertTrue(text[4].endswith('scripts/test-desktop-installer.ps1 -Installer <root>/backend/build/deployment-desktop-g/SAP-Lens-Windows-Desktop-x64-1.2.3-beta.4-Setup.exe -Report <root>/backend/build/deployment-desktop-g/metadata/installer-verification.json'))
        self.assertEqual(text[5:], ['<buildpy> scripts/deployment-package.py finish --directory <root>/backend/build/deployment-desktop-g --platform Windows-Desktop-x64 --output <root>/dist/deployment',
                                    '<buildpy> scripts/packaging/verify-desktop-distribution.py --directory <root>/backend/build/deployment-desktop-g --payload-directory backend/dist'])
        readme = (bundle / 'README.md').read_text()
        self.assertIn('Run SAP-Lens-Windows-Desktop-x64-1.2.3-beta.4-Setup.exe', readme)
        self.assertFalse(readme.endswith('\n'))
        self.assertTrue((bundle / 'LICENSE.md').exists())
        self.assertFalse((bundle / 'SAP-Lens-Windows-Desktop-x64-1.2.3-beta.4-Setup.exe.sha256').exists(), 'compiler checksums stay internal')
        self.assertEqual(calls[0], ('installer', bundle))

    def test_service_sequence_packages_without_the_privileged_scm_acceptance(self):
        recorder, seen, calls, bundle = self.run_target('Service')
        text = self.norm(recorder.commands)
        self.assertEqual(seen, [])
        self.assertEqual(text[4], '<buildpy> scripts/packaging/local-build.py winsw --output <root>/backend/build/WinSW-x64.exe')
        self.assertFalse(any('test-server-service.ps1' in line for line in text), 'ordinary packaging must not install or change a Windows service')
        self.assertEqual(text[5], '<buildpy> scripts/deployment-package.py finish --directory <root>/backend/build/deployment-service-g --platform Windows-Service-x64 --output <root>/dist/deployment')
        self.assertEqual(calls, [('server', {'WinSW': str(self.root / 'backend/build/WinSW-x64.exe'), 'ValidatedDeployment': True, 'OutputDirectory': str(bundle)})])

    def test_service_sequence_with_native_acceptance_runs_the_scm_test_before_finishing(self):
        recorder, seen, calls, bundle = self.run_target('Service', accept=True)
        text = self.norm(recorder.commands)
        self.assertTrue(text[5].endswith('scripts/test-server-service.ps1 -Bundle <root>/backend/build/deployment-service-g'))
        self.assertTrue(text[6].startswith('<buildpy> scripts/deployment-package.py finish'))

    def test_actions_prepares_the_environment_first(self):
        self.identity()
        self.write('LICENSE.md', 'license')
        _, seen, _, _ = self.run_target('Desktop', actions='true')
        self.assertEqual([stage for stage, _ in seen][:3], ['Environment', 'Python', 'Audit'])

    def test_a_failing_step_stops_the_sequence(self):
        recorder = Recorder(fail_on='test_server.py')
        with self.assertRaisesRegex(stages.StageError, 'packaging failed'):
            packaging.build('Service', '', self.root, recorder, {}, lambda o: None, lambda out: None, lambda **kw: self.fail('must not build after failing tests'))


class LocalBuild(Case):
    VALUES = {'process.versions.node': '24.1.0', 'npm --version': '10.9.0', 'py -3.12': 'PYHOST', 'local-build.py version': '1.2.3', 'local-build.py quick': '{"version": "1.2.3-dev", "source_sha": "abc"}'}

    def recorder(self, **kwargs):
        recorder = Recorder(**kwargs)
        def capture(command, cwd, env):
            text = ' '.join(str(c) for c in command)
            recorder.commands.append(text)
            for marker, value in self.VALUES.items():
                if marker in text:
                    return 0, value
            return 0, ''
        recorder.capture = capture
        return recorder

    def run_mode(self, mode, recorder=None, **kwargs):
        self.identity()
        (self.root / 'scripts').mkdir(exist_ok=True)
        recorder = recorder or self.recorder()
        stage_calls, printed, locks = [], [], []
        ok = local.build(mode, kwargs.pop('Version', ''), kwargs.pop('IncludeService', False), kwargs.pop('OutputDirectory', ''), self.root, recorder,
                         kwargs.pop('environ', {'PATH': 'P', 'WINDIR': str(self.root / 'win')}), True, lambda o: stage_calls.append((o.Stage, o.TargetedValidation, o.PythonExecutable, o.AuditPython)),
                         kwargs.pop('server_build', None), kwargs.pop('lock', lambda path: (locks.append(path), lambda: locks.append('released'))[1]), token=__import__('uuid').uuid4().hex, printer=printed.append, **kwargs)
        return ok, recorder, stage_calls, printed, locks

    def test_build_runs_the_powershell_stage_sequence(self):
        ok, recorder, stage_calls, printed, locks = self.run_mode('Build', Version='1.2.3')
        self.assertTrue(ok)
        names = [line.strip('= \n') for line in printed if line.startswith('\n=== ')]
        self.assertEqual(names, ['Version resolution', 'Clean source check', 'Local identity', 'Managed tool preflight', 'Invalidate previous validation', 'Environment', 'Python', 'Packaging tool versions', 'Frontend', 'Audit',
                                 'PackagingBackend', 'PackagingBrowser', 'Repository', 'Validation receipt', 'Validated input freshness', 'Package', 'Verify', 'Smoke', 'Distribution roundtrip'])
        self.assertEqual([(s, t) for s, t, _, _ in stage_calls], [('Environment', False), ('Python', False), ('Frontend', False), ('Audit', False), ('Backend', True), ('Browser', True),
                                                                 ('Package', False), ('Verify', False), ('Smoke', False)])
        self.assertTrue(all(host == 'PYHOST' for _, _, host, _ in stage_calls))
        text = self.norm(recorder.commands)
        helper = '<root>/scripts/packaging/local-build.py'
        self.assertIn(f'PYHOST {helper} clean', text)
        self.assertIn(f'PYHOST {helper} identity --version 1.2.3', text)
        self.assertIn('npm --prefix frontend run check:types', text)
        self.assertIn('node scripts/sync-lucide-catalog.mjs --check', text)
        self.assertIn(f'<buildpy> {helper} record --version 1.2.3 --stages Frontend Python Audit PackagingBackend PackagingBrowser Repository', text)
        export = next(t for t in text if ' export ' in t)
        self.assertIn('--output <root>/dist/1.2.3-beta.4-abc', export)
        summary = json.loads(next((self.root / 'dist/local/runs').iterdir()).joinpath('summary.json').read_text())
        self.assertEqual((summary['status'], summary['mode'], summary['requested_version'], summary['node'], summary['npm']), ('passed', 'Build', '1.2.3', '24.1.0', '10.9.0'))
        self.assertEqual([row['stage'] for row in summary['stages']], names)
        self.assertEqual(locks[0].name, 'local-build.lock')
        self.assertEqual(locks[-1], 'released')

    def test_quick_validate_and_package_modes(self):
        ok, recorder, stage_calls, printed, _ = self.run_mode('Quick')
        self.assertTrue(ok)
        text = self.norm(recorder.commands)
        self.assertTrue(any(t.endswith('scripts/check-powershell.ps1') for t in text))
        self.assertIn('git diff --check', text)
        self.assertEqual(stage_calls, [])
        self.assertTrue(any('Version: 1.2.3-dev | Source: abc' in line for line in printed))
        ok, _, stage_calls, printed, _ = self.run_mode('Validate', Version='1.2.3')
        self.assertTrue(ok)
        self.assertNotIn('Package', [s for s, *_ in stage_calls])
        self.assertFalse(any('Clean source check' in line for line in printed))
        ok, recorder, stage_calls, printed, _ = self.run_mode('Package', Version='1.2.3')
        self.assertTrue(ok)
        self.assertEqual([s for s, *_ in stage_calls], ['Audit', 'Package', 'Verify', 'Smoke'])
        self.assertIn('npm --prefix frontend audit --omit=dev', recorder.commands)

    def test_service_bundle_after_the_desktop_build(self):
        self.write('win/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
        calls = []
        ok, recorder, _, _, _ = self.run_mode('Build', Version='1.2.3', IncludeService=True, OutputDirectory=str(self.root / 'out'), server_build=lambda **kw: calls.append(kw))
        self.assertTrue(ok)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['Version'], '1.2.3')
        service = Path(calls[0]['OutputDirectory'])
        self.assertEqual(service.parent, self.root / 'backend/build')
        self.assertTrue(service.name.startswith('local-service-'))
        command = self.norm(recorder.commands)[-1]
        self.assertIn('scripts/deployment-package.py finish --directory <root>/backend/build/local-service-', command)
        self.assertTrue(command.endswith('--platform Windows-Service-x64 --output <root>/out'))


    def test_guards_fail_before_any_build_work(self):
        self.identity()
        base = {'PATH': 'P', 'WINDIR': str(self.root / 'win')}
        for message, kwargs in (('.NET Framework 4.8', {'IncludeService': True}), ('Build or Package mode', {'IncludeService': True, 'Mode': 'Quick'}),
                                ('local-only', {'environ': {**base, 'GITHUB_ACTIONS': 'true'}}), ('Windows builds require x64', {'windows': False})):
            printed = []
            self.write('win/Microsoft.NET/Framework64/v4.0.30319/csc.exe') if 'Quick' in str(kwargs.get('Mode')) else None
            call = {'Mode': 'Build', 'Version': '1', 'IncludeService': False, 'OutputDirectory': '', 'root': self.root, 'process': self.recorder(), 'environ': base, 'windows': True,
                    'stage_runner': lambda o: self.fail('no stage may run'), 'lock': lambda p: (lambda: None), 'printer': printed.append}
            call.update(kwargs)
            self.assertFalse(local.build(**call), message)
            self.assertTrue(any(message in line for line in printed), (message, printed))

    def test_node_and_npm_versions_are_enforced(self):
        self.identity()
        for marker, value, message in (('process.versions.node', '22.0.0', 'Node.js 24 LTS'), ('npm --version', '9.0.0', 'npm 10 or 11')):
            printed = []
            recorder = self.recorder()
            original = recorder.capture
            recorder.capture = lambda c, cwd, env, original=original, marker=marker, value=value: (0, value) if marker in ' '.join(c) else original(c, cwd, env)
            local.build('Quick', '1', False, '', self.root, recorder, {'PATH': 'P', 'WINDIR': ''}, True, printer=printed.append, lock=lambda p: (lambda: None))
            self.assertTrue(any(message in line for line in printed), printed)

    def test_a_held_lock_and_a_cleanup_guard_stop_the_build(self):
        self.identity()
        printed = []
        def busy(path):
            raise OSError('held')
        self.assertFalse(local.build('Quick', '1', False, '', self.root, self.recorder(), {'PATH': 'P', 'WINDIR': ''}, True, lock=busy, printer=printed.append))
        self.assertTrue(any('Another local build is running' in line for line in printed))
        self.write('dist/.sap-lens-clean.lock')
        printed.clear()
        self.assertFalse(local.build('Quick', '1', False, '', self.root, self.recorder(), {'PATH': 'P', 'WINDIR': ''}, True, lock=lambda p: (lambda: None), printer=printed.append))
        self.assertTrue(any('Cleanup owns build paths' in line for line in printed))

    def test_a_failing_stage_is_recorded_reported_and_releases_the_lock(self):
        ok, _, _, printed, locks = self.run_mode('Build', self.recorder(fail_on='local-build.py identity'), Version='1.2.3')
        self.assertFalse(ok)
        self.assertTrue(any("failed in stage 'Local identity'" in line for line in printed))
        summary = json.loads(next((self.root / 'dist/local/runs').iterdir()).joinpath('summary.json').read_text())
        self.assertEqual((summary['status'], summary['last_stage'], summary['stages'][-1]['status']), ('failed', 'Local identity', 'failed'))
        self.assertEqual(locks[-1], 'released')

    def test_real_lock_is_exclusive_on_this_platform(self):
        if sys.platform == 'win32':
            self.skipTest('POSIX flock path only; the Windows CreateFileW path is part of the Windows checklist')
        path = self.root / 'lock'
        release = local.acquire_lock(path)
        with self.assertRaises(OSError):
            local.acquire_lock(path)
        release()
        local.acquire_lock(path)()


class Wiring(unittest.TestCase):
    def plan(self, tool, environment):
        from types import SimpleNamespace
        from unittest.mock import patch
        import os
        from build_system import targets
        args = SimpleNamespace(ci_tool=tool, mode='package' if tool == 'windows-package' else 'build', benchmark_packaging='false', tool_args=['-Target', 'Desktop'], setup_only=False)
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}):
            os.environ.pop('SAP_LENS_WINDOWS_PACKAGING', None)
            os.environ.update(environment)
            return targets.plan(args, 'PY')[0][1]

    def test_local_desktop_build_is_opt_in(self):
        from unittest.mock import patch
        import os
        from build_system import cli, targets
        value = cli.parser().parse_args(['build', '--platform', 'windows', '--target', 'desktop', '--version', '1.2.3', '--non-interactive'])
        value.tool_args = []
        value = cli.configure(value, False)
        with patch.object(targets.platform, 'system', return_value='Windows'), patch.dict(os.environ, {}, clear=False):
            os.environ.pop('SAP_LENS_WINDOWS_PACKAGING', None)
            default = targets.plan(value, 'PY')[0][1]
            self.assertTrue(default[3].replace('\\', '/').endswith('scripts/build-local.ps1'))
            os.environ['SAP_LENS_WINDOWS_PACKAGING'] = 'python'
            ported = targets.plan(value, 'PY')[0][1]
        self.assertEqual(ported[0], 'PY')
        self.assertTrue(ported[1].replace('\\', '/').endswith('scripts/build_system/windows/local.py'))
        self.assertEqual(ported[2:], ['-Mode', 'Build', '-Version', '1.2.3'])

    def test_ports_are_opt_in_for_the_packaging_adapters(self):
        for tool, script in (('windows-package', 'package-windows-deployment.ps1'), ('installer-check', 'build-desktop-installer.ps1')):
            default = self.plan(tool, {})
            self.assertTrue(default[3].replace('\\', '/').endswith('scripts/' + script), tool)
            ported = self.plan(tool, {'SAP_LENS_WINDOWS_PACKAGING': 'python'})
            self.assertEqual(ported[0], 'PY')
            self.assertTrue(ported[1].replace('\\', '/').endswith('scripts/build_system/windows/' + ('packaging.py' if tool == 'windows-package' else 'installer.py')))
            self.assertEqual(ported[2:], ['-Target', 'Desktop'])


    def test_every_port_is_documented_and_the_originals_remain(self):
        guide = (ROOT / 'docs/BUILD.md').read_text(encoding='utf-8')
        for name in ('build-windows.ps1', 'build-service-manager.ps1', 'build-server-windows.ps1', 'build-desktop-installer.ps1', 'package-windows-deployment.ps1'):
            self.assertTrue((ROOT / 'scripts' / name).is_file(), name)
            self.assertIn(name, guide)


if __name__ == '__main__':
    unittest.main()
