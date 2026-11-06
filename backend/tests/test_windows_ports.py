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
from build_system.windows import installer, packaging, server, service_manager, stages  # noqa: E402


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
        self.write('backend/build/build-version.json', json.dumps({'version': '1.2.3-beta.4', 'file_version': [1, 2, 3, 4]}))


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
        self.assertEqual(text[:3], ['<buildpy> scripts/local-build.py version', '<buildpy> scripts/local-build.py tools', '<buildpy> scripts/deployment-package.py require-inputs'])
        self.assertEqual(text[3], '<buildpy> scripts/write-windows-metadata.py')
        pyinstaller = text[4]
        self.assertTrue(pyinstaller.startswith('<buildpy> -m PyInstaller --noconfirm --clean --onedir --console --noupx --name SAP-Lens --distpath <root>/bundle/app --workpath backend/build/server --specpath backend/build/server --paths <root>/backend --icon <root>/assets/sap-lens.ico'))
        self.assertTrue(pyinstaller.endswith('--exclude-module webview --exclude-module pythonnet --exclude-module clr backend/server.py'))
        self.assertEqual(text[5:], ['<buildpy> scripts/deployment-package.py readme --document docs/deployment/WINDOWS_SERVICE.md --directory <root>/bundle', '<buildpy> scripts/verify-server-bundle.py <root>/bundle'])
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
        self.assertEqual(text[:4], ['<buildpy> scripts/local-build.py version', '<buildpy> scripts/local-build.py tools', '<buildpy> scripts/local-build.py check --version 1.2.3',
                                    '<buildpy> scripts/local-build.py winsw --output <root>/backend/build/WinSW-x64.exe'])

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
        self.write('backend/build/package-verification.json', json.dumps({'exe_sha256': hashlib.sha256(b'portable').hexdigest()}))
        out = self.root / 'out'
        recorder = Recorder({'ISCC.exe': lambda c: self.write('out/SAP-Lens-Setup.exe', b'setup')})
        named = installer.build(str(out), False, self.root, recorder, {}, True)
        text = self.norm(recorder.commands)
        self.assertEqual(text[0], '<buildpy> <root>/scripts/deployment-package.py require-inputs')
        self.assertEqual(text[1], '<root>/backend/build/inno-setup-7.1.0/ISCC.exe /Qp /O<root>/out /DSourceExe=<root>/backend/dist/SAP-Lens.exe /DProductLicense=<root>/LICENSE.md /DProductIcon=<root>/assets/sap-lens.ico /DFullVersion=1.2.3-beta.4 /DNumericVersion=1.2.3.4 <root>/deploy/windows/desktop-installer.iss')
        self.assertEqual(text[2], '<buildpy> <root>/scripts/verify-desktop-installer.py --installer <root>/out/SAP-Lens-Windows-Desktop-x64-1.2.3-beta.4-Setup.exe')
        self.assertEqual(named.name, 'SAP-Lens-Windows-Desktop-x64-1.2.3-beta.4-Setup.exe')
        self.assertEqual(named.with_name(named.name + '.sha256').read_text(), f'{hashlib.sha256(b"setup").hexdigest()}  {named.name}\n')
        self.assertTrue((out / 'LICENSE-Inno-Setup.txt').exists())
        self.assertTrue(exe.exists())

    def test_the_executable_must_be_the_verified_one(self):
        self.prepare()
        self.write('backend/dist/SAP-Lens.exe', b'changed')
        self.write('backend/build/package-verification.json', json.dumps({'exe_sha256': 'f' * 64}))
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
        self.assertEqual([t.rsplit(' ', 1)[1] for t in verified], ['alpha', 'beta', 'rc', 'stable'])
        versions = [t.split('/DFullVersion=')[1].split(' ')[0] for t in text if '/DFullVersion=' in t]
        self.assertEqual(versions, ['0.1.0-alpha.1', '0.1.0-beta.1', '0.1.0-rc.1', '0.1.0'])
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
                                 lambda **kw: calls.append(('server', kw)), guid=lambda: 'g')
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
                                    '<buildpy> scripts/verify-desktop-distribution.py --directory <root>/backend/build/deployment-desktop-g --payload-directory backend/dist'])
        readme = (bundle / 'README.md').read_text()
        self.assertIn('Run SAP-Lens-Windows-Desktop-x64-1.2.3-beta.4-Setup.exe', readme)
        self.assertFalse(readme.endswith('\n'))
        self.assertTrue((bundle / 'LICENSE.md').exists())
        self.assertFalse((bundle / 'SAP-Lens-Windows-Desktop-x64-1.2.3-beta.4-Setup.exe.sha256').exists(), 'compiler checksums stay internal')
        self.assertEqual(calls[0], ('installer', bundle))

    def test_service_sequence(self):
        recorder, seen, calls, bundle = self.run_target('Service')
        text = self.norm(recorder.commands)
        self.assertEqual(seen, [])
        self.assertEqual(text[4], '<buildpy> scripts/local-build.py winsw --output <root>/backend/build/WinSW-x64.exe')
        self.assertTrue(text[5].endswith('scripts/test-server-service.ps1 -Bundle <root>/backend/build/deployment-service-g'))
        self.assertEqual(text[6], '<buildpy> scripts/deployment-package.py finish --directory <root>/backend/build/deployment-service-g --platform Windows-Service-x64 --output <root>/dist/deployment')
        self.assertEqual(calls, [('server', {'WinSW': str(self.root / 'backend/build/WinSW-x64.exe'), 'ValidatedDeployment': True, 'OutputDirectory': str(bundle)})])

    def test_actions_prepares_the_environment_first(self):
        self.identity()
        self.write('LICENSE.md', 'license')
        _, seen, _, _ = self.run_target('Desktop', actions='true')
        self.assertEqual([stage for stage, _ in seen][:3], ['Environment', 'Python', 'Audit'])

    def test_a_failing_step_stops_the_sequence(self):
        recorder = Recorder(fail_on='test_server.py')
        with self.assertRaisesRegex(stages.StageError, 'packaging failed'):
            packaging.build('Service', '', self.root, recorder, {}, lambda o: None, lambda out: None, lambda **kw: self.fail('must not build after failing tests'))


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
