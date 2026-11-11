"""Prerequisites setup, check, repair and preflight (scripts/build_system/doctor.py, python_env.py, cli.py). Isolated temporary roots only:
no real environment is created, repaired or changed, nothing is installed and no network is used. Windows-only behaviour is mocked, not verified."""
import json
import contextlib
import io
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))

from build_system import cli, doctor, prerequisites as deps, python_env as env  # noqa: E402
from build_system.runner import BuildError  # noqa: E402


def info(version='3.12.10', bits=64, path='C:/Python312/python.exe', venv=True):
    return dict(path=path, version=version, major_minor=tuple(map(int, version.split('.')[:2])), bits=bits, venv_module=venv)


def fake_venv(directory, cfg=True, interpreter=True):
    python = env.venv_python(directory)
    python.parent.mkdir(parents=True)
    if cfg:
        (Path(directory) / 'pyvenv.cfg').write_text('home = x\n')
    if interpreter:
        python.write_text('')
    return python


def args(**values):
    base = dict(mode='prerequisites', platform='linux', target='server', target_given=False, check_only=False, repair=False, json=False, setup=False)
    return Namespace(**{**base, **values})


class Recorder:
    def __init__(self, fail=None):
        self.commands, self.fail, self.directory, self.last_output = [], fail, None, None

    def run(self, label, command, **kw):
        self.commands.append(label)
        if self.fail and self.fail in label:
            raise BuildError('failed: ' + label, 5)


class Discovery(unittest.TestCase):
    def test_python_315_default_with_312_installed_selects_312(self):
        answers = {'C:/Python315/python.exe': info('3.15.0', path='C:/Python315/python.exe'), 'py': info('3.12.10', path='C:/Python312/python.exe')}
        cands = [('current interpreter', 'C:/Python315/python.exe', ()), ('Python launcher (py -3.12)', 'py', ('-3.12',)), ('PATH (python)', 'C:/Python315/python.exe', ())]
        with patch.object(env, 'candidates', return_value=cands), patch.object(env, 'probe_python', side_effect=lambda c, p=(): answers[c]):
            found, rejected = env.find_python()
        self.assertEqual(found['path'], 'C:/Python312/python.exe'); self.assertEqual(found['source'], 'Python launcher (py -3.12)')
        self.assertEqual(rejected[0]['reason'], 'Python 3.15.0 64-bit')

    def test_32_bit_and_missing_venv_module_are_rejected_and_reported(self):
        cands = [('a', 'a', ()), ('b', 'b', ()), ('c', 'c', ())]
        answers = {'a': info(bits=32), 'b': info(venv=False), 'c': None}
        with patch.object(env, 'candidates', return_value=cands), patch.object(env, 'probe_python', side_effect=lambda c, p=(): answers[c]):
            found, rejected = env.find_python()
        self.assertIsNone(found); self.assertEqual([row['source'] for row in rejected], ['a', 'b', 'c'])
        self.assertIn('without venv', rejected[1]['reason']); self.assertIn('could not be started', rejected[2]['reason'])

    def test_probe_handles_paths_with_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'Program Files' / 'Python 312'; folder.mkdir(parents=True)
            if os.name == 'nt':          # a batch file stands in for the interpreter; the probe must be a single line for cmd.exe
                script = folder / 'python.cmd'; script.write_text('@echo ["/x y/python", [3,12,10], 64, 1]\r\n')
            else:
                script = folder / 'python.sh'
                script.write_text('#!/bin/sh\necho \'["/x y/python", [3,12,10], 64, 1]\'\n'); script.chmod(script.stat().st_mode | stat.S_IEXEC)
            result = env.probe_python(script)
        self.assertEqual((result['path'], result['version'], result['bits']), ('/x y/python', '3.12.10', 64))

    def test_probe_of_a_broken_interpreter_is_none_not_an_exception(self):
        self.assertIsNone(env.probe_python('/definitely/not/python'))

    def test_pinned_interpreter_override_comes_first_and_bare_python_is_last(self):
        with patch.object(env.shutil, 'which', side_effect=lambda n: {'py': None, 'python3.12': '/u/python3.12', 'python3': '/u/python3', 'python': '/u/python'}.get(n)):
            sources = [row[0] for row in env.candidates({'SAP_LENS_PYTHON': '/opt/py312'})]
        self.assertEqual(sources[0], 'SAP_LENS_PYTHON'); self.assertEqual(sources[-1], 'PATH (python)')

    def test_test_interpreter_never_falls_back_silently(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(env.sys, 'version_info', (3, 15, 0)):
            with self.assertRaises(SystemExit) as caught:
                env.test_interpreter(tmp)
        self.assertIn('Python 3.12 x64 is required', str(caught.exception)); self.assertIn('prerequisites', str(caught.exception))

    def test_test_interpreter_uses_a_ready_project_venv_under_another_python(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(env.sys, 'version_info', (3, 15, 0)):
            python = fake_venv(Path(tmp) / '.venv')
            with patch.object(env, 'probe_python', return_value=info()):
                self.assertEqual(env.test_interpreter(tmp), str(python))


class VenvInspection(unittest.TestCase):
    def check(self, build=None, probe=None):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / '.venv'
            if build:
                build(directory)
            with patch.object(env, 'probe_python', return_value=probe):
                return env.inspect_venv(directory)[0]

    def test_states(self):
        self.assertEqual(self.check(), 'missing')
        self.assertEqual(self.check(fake_venv, info()), 'ready')
        self.assertEqual(self.check(fake_venv, info('3.13.1')), 'incompatible')
        self.assertEqual(self.check(fake_venv, info(bits=32)), 'incompatible')
        self.assertEqual(self.check(fake_venv, None), 'broken')                                  # interpreter does not start
        self.assertEqual(self.check(lambda d: fake_venv(d, cfg=False), info()), 'broken')        # incomplete
        self.assertEqual(self.check(lambda d: fake_venv(d, interpreter=False), info()), 'broken')

    def test_inspection_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_venv(Path(tmp) / '.venv'); before = sorted(map(str, Path(tmp).rglob('*')))
            with patch.object(env, 'probe_python', return_value=info('3.14.0')):
                env.inspect_venv(Path(tmp) / '.venv')
            self.assertEqual(before, sorted(map(str, Path(tmp).rglob('*'))))


class Dependencies(unittest.TestCase):
    def test_missing_and_changed_requirements_are_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'r.txt').write_text('alpha==1.0\nbeta==2.0\n')
            with patch.object(env, 'installed_packages', return_value={'alpha': '1.0', 'beta': '2.0'}):
                self.assertTrue(env.dependencies_satisfied('py', tmp, ['r.txt']))
            with patch.object(env, 'installed_packages', return_value={'alpha': '1.0'}):
                self.assertFalse(env.dependencies_satisfied('py', tmp, ['r.txt']))            # missing
            (Path(tmp) / 'r.txt').write_text('alpha==1.1\nbeta==2.0\n')
            with patch.object(env, 'installed_packages', return_value={'alpha': '1.0', 'beta': '2.0'}):
                self.assertFalse(env.dependencies_satisfied('py', tmp, ['r.txt']))            # requirement changed

    def test_missing_node_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'frontend').mkdir(); (Path(tmp) / 'frontend/package.json').write_text('{}'); (Path(tmp) / 'frontend/package-lock.json').write_text('{}')
            self.assertFalse(deps.frontend_current(Path(tmp)))
            (Path(tmp) / 'frontend/node_modules').mkdir(); (Path(tmp) / 'frontend/node_modules/.package-lock.json').write_text('{}')
            os.utime(Path(tmp) / 'frontend/node_modules/.package-lock.json', (9e9, 9e9))
            self.assertTrue(deps.frontend_current(Path(tmp)))


    def test_probe_is_one_line_so_cmd_exe_cannot_truncate_it(self):
        self.assertNotIn('\n', env.PROBE); self.assertNotIn('"', env.PROBE)

    def test_probe_reports_this_interpreter(self):
        result = env.probe_python(sys.executable)
        self.assertEqual(result['version'].split('.')[:2], [str(sys.version_info[0]), str(sys.version_info[1])]); self.assertTrue(result['venv_module'])


class Tools(unittest.TestCase):
    def test_unsupported_node_is_incompatible_and_non_lts_warns(self):
        with patch.object(deps, 'probe_tool', return_value=deps.ToolProbe('node', 'ok', '/n/node', '22.1.0', 0)):
            self.assertEqual(doctor.tool_item('node', True)['status'], doctor.INCOMPATIBLE)
        with patch.object(deps, 'probe_tool', return_value=deps.ToolProbe('node', 'ok', '/n/node', '25.8.0', 0)):
            self.assertEqual(doctor.tool_item('node', True)['status'], doctor.WARNING)
        with patch.object(deps, 'probe_tool', return_value=deps.ToolProbe('node', 'ok', '/n/node', '24.3.0', 0)):
            self.assertEqual(doctor.tool_item('node', True)['status'], doctor.READY)

    def test_missing_optional_tool_is_a_warning_and_never_blocks(self):
        with patch.object(deps, 'probe_tool', return_value=deps.ToolProbe('docker', 'missing')):
            row = doctor.tool_item('docker', False)
        self.assertEqual(row['status'], doctor.WARNING); self.assertEqual(doctor.exit_code([row]), 0)

    def test_missing_required_tool_fails_with_code_3(self):
        with patch.object(deps, 'probe_tool', return_value=deps.ToolProbe('git', 'missing')):
            self.assertEqual(doctor.exit_code([doctor.tool_item('git', True)]), 3)

    def test_npm_runs_from_python(self):
        probe = deps.probe_tool('npm')
        if probe.status == 'missing':
            self.skipTest('npm is not installed on this machine')
        self.assertEqual(probe.status, 'ok', probe.detail)


class Targets(unittest.TestCase):
    def test_requirements_follow_platform_and_target(self):
        linux = doctor.requirements(args(mode='build', platform='linux', target='server'))
        self.assertFalse(linux['csc'] or linux['powershell'] or linux['docker'])
        docker = doctor.requirements(args(mode='build', platform='docker', target='server'))
        self.assertTrue(docker['docker'] and not docker['csc'])
        test = doctor.requirements(args(mode='test', platform='windows', target='desktop'))
        self.assertFalse(test['csc'] or test['powershell'] or test['packaging_env'])        # backend tests need no packaging tools
        with patch.object(doctor.platform, 'system', return_value='Windows'):
            service = doctor.requirements(args(mode='build', platform='windows', target='service'))
            desktop = doctor.requirements(args(mode='build', platform='windows', target='desktop'))
        self.assertTrue(service['csc'] and service['powershell']); self.assertFalse(desktop['csc'])

    def test_preflight_fails_before_building_when_a_target_tool_is_missing(self):
        rows = [doctor.item('.NET Framework csc.exe (service manager)', doctor.MISSING, 'x', 'enable it')]
        with patch.object(doctor, 'collect', return_value=rows):
            with self.assertRaises(BuildError) as caught:
                doctor.preflight(args(mode='build'))
        self.assertEqual(caught.exception.code, 3); self.assertIn('before any build step', str(caught.exception))

    def test_preflight_ignores_environment_rows_that_setup_creates(self):
        rows = [doctor.item('Project .venv', doctor.MISSING), doctor.item('Project .venv dependencies', doctor.REPAIR), doctor.item('Frontend dependencies', doctor.MISSING)]
        with patch.object(doctor, 'collect', return_value=rows):
            doctor.preflight(args(mode='build'))


class SetupCheckRepair(unittest.TestCase):
    def test_check_mode_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fake_venv(root / '.venv'); before = sorted(map(str, root.rglob('*')))
            with patch.object(env, 'probe_python', return_value=info('3.13.0')), patch('builtins.print'):
                code = doctor.run_prerequisites(args(check_only=True), Recorder(), root)
            self.assertEqual(code, 3); self.assertEqual(before, sorted(map(str, root.rglob('*'))))

    def test_json_report_has_stable_shape_and_no_environment_dump(self):
        rows = [doctor.item('x', doctor.READY, 'ok'), doctor.item('y', doctor.MISSING, 'gone', 'fix')]
        data = json.loads(doctor.render(rows, as_json=True))
        self.assertEqual((data['ok'], data['exit_code']), (False, 3)); self.assertEqual(set(data['items'][0]), {'name', 'status', 'detail', 'action', 'required'})

    def test_incompatible_venv_is_never_touched_without_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); python = fake_venv(root / '.venv'); python.write_text('keep me')
            with patch.object(env, 'find_python', return_value=(dict(info(), source='t'), [])), patch.object(env, 'probe_python', return_value=info('3.13.0')):
                with self.assertRaises(BuildError) as caught:
                    doctor.run_prerequisites(args(), Recorder(), root)
            self.assertIn('--repair', str(caught.exception)); self.assertEqual(python.read_text(), 'keep me')

    def test_repair_renames_aside_instead_of_deleting_and_recreates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); python = fake_venv(root / '.venv'); python.write_text('keep me')
            with patch.object(env, 'find_python', return_value=(dict(info(), source='t'), [])), patch.object(env, 'probe_python', return_value=info('3.13.0')), \
                 patch.object(deps, 'prepare_environment') as prepare, patch.object(doctor, 'collect', return_value=[]), patch('builtins.print'):
                doctor.run_prerequisites(args(repair=True), Recorder(), root)
            moved = [p for p in root.iterdir() if p.name.startswith('.venv.broken-')]
            self.assertEqual(len(moved), 1); self.assertEqual(env.venv_python(moved[0]).read_text(), 'keep me')
            self.assertEqual(prepare.call_args.kwargs['creator'], 'C:/Python312/python.exe')

    def test_application_data_locations_are_never_touched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fake_venv(root / '.venv'); (root / 'data').mkdir(); (root / 'data/settings.json').write_text('{}')
            with patch.object(env, 'find_python', return_value=(dict(info(), source='t'), [])), patch.object(env, 'probe_python', return_value=None), \
                 patch.object(deps, 'prepare_environment'), patch.object(doctor, 'collect', return_value=[]), patch('builtins.print'):
                doctor.run_prerequisites(args(repair=True), Recorder(), root)
            self.assertEqual((root / 'data/settings.json').read_text(), '{}')

    def test_second_setup_run_reinstalls_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fake_venv(root / '.venv'); recorder = Recorder()
            with patch.object(deps.subprocess, 'check_output', return_value='[3, 12, 64]'), patch.object(env, 'ensure_pip', return_value='ok'), \
                 patch.object(env, 'dependencies_satisfied', return_value=True), patch.object(deps, 'frontend_current', return_value=True), patch('builtins.print'):
                deps.prepare_environment(root, recorder, creator='py312')
        self.assertEqual(recorder.commands, ['Check local Python dependencies'])

    def test_missing_environment_is_created_with_the_resolved_312_not_the_running_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); created = []
            class Capturing(Recorder):
                def run(self, label, command, **kw):
                    created.append(command); super().run(label, command)
                    if 'Create' in label:
                        fake_venv(Path(command[-1]))
            with patch.object(deps.subprocess, 'check_output', return_value='[3, 12, 64]'), patch.object(env, 'ensure_pip', return_value='ok'), \
                 patch.object(env, 'dependencies_satisfied', return_value=True), patch.object(deps, 'frontend_current', return_value=True), patch('builtins.print'):
                deps.prepare_environment(root, Capturing(), creator='/py312/python')
        self.assertEqual(created[0][:3], ['/py312/python', '-m', 'venv'])

    def test_install_failure_propagates_its_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fake_venv(root / '.venv')
            class Failing(Recorder):
                def run(self, label, command, **kw):
                    if 'Install locked project' in label:
                        raise BuildError('pip failed', 7)
                    super().run(label, command)
            with patch.object(deps.subprocess, 'check_output', return_value='[3, 12, 64]'), patch.object(env, 'ensure_pip', return_value='ok'), \
                 patch.object(env, 'dependencies_satisfied', return_value=False):
                with self.assertRaises(BuildError) as caught:
                    deps.prepare_environment(root, Failing(), creator='py')
        self.assertEqual(caught.exception.code, 7)

    def test_setup_without_python_312_fails_with_code_3(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(env, 'find_python', return_value=(None, [])), patch('builtins.print'), patch.object(doctor, 'collect', return_value=[]):
            self.assertEqual(doctor.run_prerequisites(args(), Recorder(), Path(tmp)), 3)


class EntryPoint(unittest.TestCase):
    def test_reexec_runs_the_engine_under_312_when_started_by_another_python(self):
        found = dict(info(), source='launcher')
        with patch.object(cli.sys, 'version_info', (3, 15, 0)), patch.dict(os.environ, {'SAP_LENS_REEXEC': ''}), patch.object(env, 'find_python', return_value=(found, [])), \
             patch.object(cli.subprocess, 'call', return_value=0) as call, patch('builtins.print'):
            self.assertEqual(cli.reexec(['prerequisites', '--check-only']), 0)
        self.assertEqual(call.call_args.args[0][0], 'C:/Python312/python.exe'); self.assertEqual(call.call_args.kwargs['env']['SAP_LENS_REEXEC'], '1')

    def test_reexec_without_312_fails_but_check_only_can_still_report(self):
        with patch.object(cli.sys, 'version_info', (3, 15, 0)), patch.dict(os.environ, {'SAP_LENS_REEXEC': ''}), patch.object(env, 'find_python', return_value=(None, [])), patch('builtins.print'):
            self.assertEqual(cli.reexec(['build']), 3); self.assertIsNone(cli.reexec(['prerequisites', '--check-only']))

    def test_reexec_does_not_loop(self):
        with patch.object(cli.sys, 'version_info', (3, 15, 0)), patch.dict(os.environ, {'SAP_LENS_REEXEC': '1'}):
            self.assertIsNone(cli.reexec([]))

    def test_check_flags_belong_to_the_prerequisites_mode(self):
        for bad in (['build', '--check-only'], ['prerequisites', '--check-only', '--repair']):
            with self.assertRaises(BuildError):
                cli.configure(cli.parser().parse_args(bad), False)

    def test_non_interactive_check_runs_end_to_end_without_prompts(self):
        done = subprocess.run([sys.executable, str(ROOT / 'scripts/build.py'), 'prerequisites', '--check-only', '--json', '--non-interactive'],
                              capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120, cwd=ROOT)
        details = f'Exit code: {done.returncode}\nSTDOUT:\n{done.stdout}\nSTDERR:\n{done.stderr}'
        self.assertIn(done.returncode, (0, 3), details)
        try:
            report = json.loads(done.stdout)
        except json.JSONDecodeError as error:
            error.add_note(details)
            raise
        self.assertEqual(report['exit_code'], done.returncode); self.assertIn('Python 3.12 x64', [row['name'] for row in report['items']])

    def test_existing_modes_and_arguments_are_preserved(self):
        for mode in ('quick', 'test', 'build', 'package', 'release', 'clean'):
            self.assertIn(mode, cli.MODES)
        parsed = cli.parser().parse_args(['build', '--platform', 'windows', '--target', 'desktop', '--setup-only', '--dry-run'])
        self.assertTrue(parsed.setup_only and parsed.dry_run)

    def test_powershell_bootstrapper_forwards_the_new_switches(self):
        text = (ROOT / 'scripts/build.ps1').read_text(encoding='utf-8')
        for switch in ('CheckOnly', 'Repair', 'Json'):
            self.assertIn(f'[switch]${switch}', text); self.assertIn(f"'--{'check-only' if switch == 'CheckOnly' else switch.lower()}',${switch}", text)
        self.assertNotIn('Set-ExecutionPolicy', text); self.assertNotIn('Activate.ps1', text)

    def test_windows_scripts_never_use_the_bare_default_python(self):
        text = (ROOT / 'scripts/build-windows.ps1').read_text(encoding='utf-8')
        self.assertNotIn('(Get-Command python).Source', text); self.assertIn('Resolve-HostPython', text)



class JsonOutputContract(unittest.TestCase):
    def test_non_lts_node_and_diagnostics_do_not_contaminate_json(self):
        out, err = io.StringIO(), io.StringIO()
        def collect(_args, _root):
            return [doctor.tool_item('node', True)]
        probe = deps.ToolProbe('node', 'ok', '/synthetic/node', '25.8.0', 0)
        with patch.object(doctor, 'collect', side_effect=collect), patch.object(deps, 'probe_tool', return_value=probe), patch.object(deps, 'NOTED', []), patch.dict(os.environ, {'SAP_LENS_BUILD_DIAGNOSTICS':'1'}), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = doctor.run_prerequisites(args(check_only=True, json=True), Recorder())
        report = json.loads(out.getvalue())
        self.assertEqual(code, 0); self.assertEqual(report['exit_code'], 0)
        self.assertEqual(report['items'][0]['status'], doctor.WARNING)
        self.assertIn('non-LTS', err.getvalue()); self.assertIn('[diagnostics]', err.getvalue())
        self.assertNotIn('Note:', out.getvalue())

    def test_non_lts_node_json_is_consumable_by_a_python_subprocess(self):
        script = """
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path.cwd()/'scripts'))
from build_system import cli,doctor,prerequisites as deps
probe=deps.ToolProbe('node','ok','synthetic-node','25.8.0',0)
with patch.object(deps,'probe_tool',return_value=probe), patch.object(deps,'NOTED',[]), patch.object(doctor,'collect',side_effect=lambda *args:[doctor.tool_item('node',True)]):
    sys.exit(cli.main(['prerequisites','--check-only','--json','--non-interactive']))
"""
        done = subprocess.run([sys.executable, '-c', script], cwd=ROOT, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
        details = f'Exit code: {done.returncode}\nSTDOUT:\n{done.stdout}\nSTDERR:\n{done.stderr}'
        self.assertEqual(done.returncode, 0, details)
        try:
            report = json.loads(done.stdout)
        except json.JSONDecodeError as error:
            error.add_note(details)
            raise
        self.assertEqual(report['exit_code'], 0); self.assertIn('non-LTS', done.stderr)
        self.assertEqual(report['items'][0]['status'], doctor.WARNING)

    def test_json_setup_progress_and_failures_are_separate_from_report(self):
        for failed in (False, True):
            out, err = io.StringIO(), io.StringIO()
            def prepare(*unused, failed=failed):
                print('Synthetic setup progress')
                if failed: raise BuildError('Synthetic setup failed', 3)
                return [doctor.item('synthetic', doctor.READY)]
            with self.subTest(failed=failed), patch.object(doctor, '_prerequisite_items', side_effect=prepare), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = doctor.run_prerequisites(args(json=True), Recorder())
            report = json.loads(out.getvalue())
            self.assertEqual(code, 3 if failed else 0); self.assertEqual(report['exit_code'], code)
            self.assertIn('Synthetic setup progress', err.getvalue())
            if failed:self.assertIn('Synthetic setup failed', err.getvalue())

    def test_missing_python_still_emits_json_on_stdout(self):
        out, err = io.StringIO(), io.StringIO()
        rows = [doctor.item('Python 3.12 x64', doctor.MISSING)]
        with patch.object(env, 'find_python', return_value=(None, [])), patch.object(doctor, 'collect', return_value=rows), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = doctor.run_prerequisites(args(json=True), Recorder())
        self.assertEqual(json.loads(out.getvalue())['exit_code'], 3); self.assertEqual(code, 3)

    def test_interpreter_handoff_diagnostic_stays_on_stderr(self):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(cli.sys, 'version_info', (3, 13)), patch.dict(os.environ, {'SAP_LENS_REEXEC':''}), patch.object(env, 'find_python', return_value=(info(path='synthetic-python'), [])), patch.object(cli.subprocess, 'call', return_value=0), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(cli.reexec(['quick','--dry-run']), 0)
        self.assertEqual(out.getvalue(), ''); self.assertIn('Using Python', err.getvalue())

    def test_json_runner_routes_ci_child_stdout_to_stderr(self):
        from build_system.runner import Runner
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {'GITHUB_ACTIONS':'true'}), patch('build_system.runner.subprocess.run', return_value=subprocess.CompletedProcess([], 0)) as child, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            runner = Runner(Path(temporary)); runner.machine_readable = True
            runner.run('Synthetic operation', ['synthetic'])
            self.assertIs(child.call_args.kwargs['stdout'], err)
            self.assertEqual(child.call_args.kwargs['stdin'], subprocess.DEVNULL)
        self.assertEqual(out.getvalue(), ''); self.assertIn('Synthetic operation', err.getvalue())

    def test_bootstrap_json_diagnostics_and_native_exit_guards(self):
        text = (ROOT/'scripts/build.ps1').read_text()
        self.assertIn('[Console]::Error.WriteLine($Message)', text)
        self.assertIn('Write-BootstrapFailure', text)
        self.assertIn('$LASTEXITCODE = 2', text)
        self.assertIn('$exitCode=$LASTEXITCODE', text)
        self.assertIn('$script:EngineCompleted', text)
        self.assertIn('$ErrorActionPreference = $nativePreference', text)

if __name__ == '__main__':
    unittest.main()
