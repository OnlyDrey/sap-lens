"""Integrity of the test profiles: no test file may be silently left out of regression."""
import importlib.util
import io
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('run_tests_script', ROOT / 'scripts' / 'run-tests.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
server_spec = importlib.util.spec_from_file_location('serve_browser_tests', ROOT / 'scripts' / 'testing' / 'serve-browser-tests.py')
server = importlib.util.module_from_spec(server_spec)
server_spec.loader.exec_module(server)


class TestProfileTests(unittest.TestCase):
    def test_every_backend_module_and_browser_spec_belongs_to_exactly_one_feature(self):
        self.assertEqual(runner.coverage_problems(), [])

    def test_smoke_backend_selection_resolves_to_real_tests(self):
        loader = unittest.TestLoader()
        for name in runner.load_map()['smoke']['backend']:
            try:
                suite = loader.loadTestsFromName(name)
            except (ImportError, AttributeError) as error:
                self.fail(f'{name} does not resolve: {error}')
            self.assertGreater(suite.countTestCases(), 0, name)
            self.assertNotIn('_FailedTest', repr(suite), name)

    def test_smoke_browser_tests_exist_and_cover_the_critical_features(self):
        tag = runner.load_map()['smoke']['browser_tag']
        owners = {}
        for feature, entry in runner.load_map()['features'].items():
            for spec_name in entry['browser']:
                text = (ROOT / 'frontend' / 'tests' / f'{spec_name}.spec.ts').read_text(encoding='utf-8')
                # `tag: '@smoke'` or a list that includes it (`tag: ['@smoke', '@workflow']`), as Playwright accepts both
                if re.search(rf"tag:\s*(?:'{re.escape(tag)}'|\[[^\]]*'{re.escape(tag)}'[^\]]*\])", text):
                    owners.setdefault(feature, []).append(spec_name)
        for feature in ('dashboard', 'role-lookup', 'user-access', 'access-package', 'account-review', 'data-sources', 'sod', 'shared-ui', 'platform', 'role-comparison'):
            self.assertIn(feature, owners, f'no {tag} browser test for {feature}')

    def test_map_has_known_feature_descriptions_and_no_empty_features(self):
        for name, feature in runner.load_map()['features'].items():
            self.assertTrue(feature['description'], name)
            self.assertTrue(feature['backend'] or feature['browser'], name)


class RiskBasedSelectionTests(unittest.TestCase):
    """QUICK/TARGETED selection for realistic changed-file sets (scripts/run-tests.py plan_targeted). Nothing runs; only the plan is checked."""
    def plan(self, *paths):
        return runner.plan_targeted(list(paths))

    def repository(self):
        return set(runner.load_map()['features']['repository']['backend'])

    def test_backend_source_selects_the_test_modules_that_import_it_and_its_feature_specs(self):
        plan = self.plan('backend/sod_governance.py')
        self.assertIn('test_sod_governance', plan['modules']); self.assertIn('sod-governance', plan['specs'])
        self.assertFalse(plan['broad_backend'] or plan['broad_browser'] or plan['security'])
        self.assertLessEqual(self.repository(), set(plan['modules']))

    def test_security_sensitive_change_cannot_bypass_the_security_modules(self):
        for path in ('backend/deployment.py', 'backend/routers/sod.py', 'backend/server_access.py', 'backend/windows_identity.py'):
            plan = self.plan(path)
            self.assertTrue(plan['security'], path)
            self.assertLessEqual(set(runner.load_map()['profiles']['security_modules']), set(plan['modules']), path)

    def test_feature_frontend_change_runs_that_features_specs_without_widening(self):
        plan = self.plan('frontend/src/components/Sod/SodWorkQueue.tsx')
        self.assertIn('sod-bulk-review', plan['specs']); self.assertFalse(plan['broad_browser']); self.assertTrue(plan['browser'])

    def test_widely_shared_component_change_runs_the_component_tests_and_the_regression_browser_set(self):
        plan = self.plan('frontend/src/components/Shared/Button.tsx')
        self.assertIn('component-library', plan['specs']); self.assertTrue(plan['broad_browser'])

    def test_stylesheets_and_frontend_toolchain_select_broadly(self):
        for path in ('frontend/src/index.css', 'frontend/package.json'):
            self.assertTrue(self.plan(path)['broad_browser'], path)

    def test_unknown_paths_broaden_instead_of_skipping(self):
        plan = self.plan('unmapped-schema.new')
        self.assertTrue(plan['broad_backend'] and plan['broad_browser'])
        self.assertTrue(self.plan('frontend/src/components/UnknownBusiness/New.tsx')['broad_browser'])
        self.assertTrue(self.plan('backend/tests/fixtures/roles.csv')['broad_backend'])

    def test_documentation_only_changes_run_the_repository_integrity_modules_and_no_browser(self):
        plan = self.plan('docs/development/TESTING.md', 'README.md')
        self.assertEqual(set(plan['modules']), self.repository()); self.assertFalse(plan['browser'])

    def test_changes_to_the_selection_system_run_its_own_tests(self):
        for path in ('scripts/test-map.json', 'scripts/run-tests.py', 'scripts/validate.py'):
            self.assertIn('test_test_profiles', self.plan(path)['modules'], path)
        self.assertTrue(self.plan('frontend/playwright.config.ts')['broad_browser'])

    def test_test_files_and_helpers_select_their_users(self):
        self.assertEqual(self.plan('frontend/tests/sod-periods.spec.ts')['specs'], ['sod-periods'])
        self.assertIn('test_backup_retention', self.plan('backend/tests/links.py')['modules'])
        self.assertTrue(self.plan('frontend/tests/support.ts')['broad_browser'])        # used by most specs: regression set, FULL runs all
        narrow = self.plan('frontend/tests/source-activation-fixture.ts')                 # imported by a handful of specs: exactly those run
        self.assertIn('csv-lifecycle', narrow['specs']); self.assertFalse(narrow['broad_browser'])
        self.assertTrue(self.plan('frontend/tests/sod-fixture.ts')['broad_browser'])      # 50 specs: regression set instead

    def test_profile_configuration_is_consistent_and_never_excludes_critical_features_from_regression(self):
        mapping = runner.load_map(); profiles = mapping['profiles']
        for name, feature in mapping['features'].items():
            self.assertIn(feature.get('criticality'), {'critical', 'standard', 'release'}, name)
            self.assertIn(feature.get('owner'), {'backend', 'browser', 'component', 'platform'}, name)
            self.assertTrue(feature.get('platform'), name)
        for name in profiles['release_features']:
            self.assertEqual(mapping['features'][name]['criticality'], 'release', f'{name} is excluded from REGRESSION, so it must be classified release')
        self.assertFalse({n for n, f in mapping['features'].items() if f['criticality'] == 'critical'} & set(profiles['release_features']))
        for spec in profiles['regression_browser_specs']:
            self.assertTrue((ROOT / 'frontend' / 'tests' / f'{spec}.spec.ts').exists(), spec)
        for module in profiles['security_modules']:
            self.assertTrue((ROOT / 'backend' / 'tests' / f'{module}.py').exists(), module)
        full_only = set(filter(None, profiles.get('full_only_tags', '').split('|')))
        self.assertFalse(full_only & set(profiles['regression_browser_tags'].split('|')), 'a full-only tag cannot also select REGRESSION tests')

    def test_sod_page_changes_select_that_pages_specs_and_shared_files_select_all(self):
        mapping = runner.load_map(); everything = set(mapping['features']['sod']['browser'])
        core = set(mapping['profiles']['page_core_specs']['frontend/src/components/Sod/'])
        periods = self.plan('frontend/src/components/Sod/SodLegacyReview.tsx')                 # imported only by the Periods page
        self.assertEqual(set(periods['specs']), core | set(mapping['profiles']['page_specs']['frontend/src/components/Sod/SodPeriods.tsx']))
        bulk = set(self.plan('frontend/src/components/Sod/SodBulkReview.tsx')['specs'])      # renders on Access Explorer and Reviews
        self.assertIn('sod-bulk-review', bulk); self.assertIn('remediation-export', bulk); self.assertLess(len(bulk), len(everything))
        self.assertIn('test_sod_governance', periods['modules'])                              # backend coverage of the feature is unchanged
        for shared in ('frontend/src/components/Sod/SodShared.tsx', 'frontend/src/components/Sod/SodWorkspace.tsx', 'frontend/src/components/Sod/SodRemediation.tsx'):
            self.assertLessEqual(everything, set(self.plan(shared)['specs']), shared)           # container, shared module, investigation panel
        self.assertLessEqual(everything, set(self.plan('frontend/src/components/Sod/SodPeriods.tsx', 'backend/sod_periods.py')['specs']))

    def test_page_map_names_existing_roots_and_specs(self):
        profiles = runner.load_map()['profiles']
        for root, specs in profiles['page_specs'].items():
            self.assertTrue((ROOT / root).exists(), root)
            self.assertTrue(any(root.startswith(area) for area in profiles['page_core_specs']), root)
            for spec in specs:
                self.assertTrue((ROOT / 'frontend' / 'tests' / f'{spec}.spec.ts').exists(), spec)
        for specs in profiles['page_core_specs'].values():
            for spec in specs:
                self.assertTrue((ROOT / 'frontend' / 'tests' / f'{spec}.spec.ts').exists(), spec)

    def test_quick_defers_packaging_only_when_the_change_does_not_touch_packaging(self):
        source = (ROOT / 'scripts' / 'run-tests.py').read_text(encoding='utf-8')
        self.assertIn("direct_release = set(plan['features']) & set(mapping['profiles']['release_features'])", source)
        self.assertIn('deployment', self.plan('scripts/deployment/build-deployments.py')['features'])
        self.assertNotIn('deployment', self.plan('backend/sod_governance.py')['features'])

    def test_renamed_profiles_still_work_and_say_so(self):
        done = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'run-tests.py'), 'fast', '--list-tests', '--base', 'HEAD'], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:]); self.assertIn('`fast` is now `quick`', done.stdout)


class BrowserIsolationGuardTests(unittest.TestCase):
    """Specs never read the shared browser clipboard back; they assert the page's recorded writeText value (tests/support.ts)."""
    def test_no_spec_reads_the_system_clipboard(self):
        offenders = sorted(path.name for path in (ROOT / 'frontend' / 'tests').glob('*.ts') if 'clipboard.readText(' in path.read_text(encoding='utf-8'))
        self.assertEqual(offenders, [])

    def test_specs_that_copy_record_the_clipboard_first(self):
        for path in sorted((ROOT / 'frontend' / 'tests').glob('*.spec.ts')):
            text = path.read_text(encoding='utf-8')
            if 'copiedText(page)' in text:
                self.assertIn('recordClipboard(page)', text, path.name)


class InterpreterConsistencyTests(unittest.TestCase):
    """Every Python subprocess of the browser tests uses the runner's interpreter (frontend/tests/python.ts), never PATH's first python."""
    def test_no_spec_or_fixture_spawns_a_bare_python(self):
        offenders = []
        for path in sorted((ROOT / 'frontend' / 'tests').glob('*.ts')):
            text = path.read_text(encoding='utf-8')
            if re.search(r"""(execFileSync|execFile|spawn|spawnSync|exec)\(\s*['"`]python3?['"`]""", text) or "process.env.PYTHON" in text and path.name != 'python.ts':
                offenders.append(path.name)
        self.assertEqual(offenders, [])

    def test_the_test_server_and_the_runner_pass_the_interpreter_explicitly(self):
        config = (ROOT / 'frontend' / 'playwright.config.ts').read_text(encoding='utf-8')
        self.assertIn("from './tests/python'", config); self.assertNotIn("'python ../scripts", config); self.assertNotIn("exec python ", config)
        self.assertIn("'SAP_LENS_TEST_PYTHON': python_exe()", (ROOT / 'scripts' / 'run-tests.py').read_text(encoding='utf-8'))
        resolver = (ROOT / 'frontend' / 'tests' / 'python.ts').read_text(encoding='utf-8')
        self.assertLess(resolver.index('SAP_LENS_TEST_PYTHON'), resolver.index("'.venv'"))


FAKE_PLAYWRIGHT = r"""#!/usr/bin/env python3
import json, os, sys, time
mode = os.environ.get('FAKE_MODE', 'pass')
print('[1/2] fake a.spec.ts', flush=True); print('[2/2] fake b.spec.ts', flush=True)
sys.stderr.write('fake diagnostics on stderr\n')
if mode == 'hang':
    time.sleep(120)
if mode == 'noreport':
    sys.exit(3)
failed = mode == 'fail'
events = os.environ.get('SAP_LENS_PROGRESS_FILE')
def event(**item):
    if events:
        with open(events, 'a', encoding='utf-8') as stream: stream.write(json.dumps(item) + '\n')
event(type='begin', total=2)
event(type='test-end', file='a.spec.ts', line=1, title='one › déjà vu', status='passed', outcome='expected', duration=5, error='')
event(type='test-end', file='a.spec.ts', line=2, title='two', status='failed' if failed else 'passed', outcome='unexpected' if failed else 'expected',
      duration=5, error='Expected: 1\nReceived: 2' if failed else '')
time.sleep(0.8)                                   # the runner renders the events while the process is still running
test = lambda title, status: {'title': title, 'file': 'a.spec.ts', 'tests': [{'status': status, 'results': [{'duration': 5, 'status': 'failed' if status == 'unexpected' else 'passed',
                               'error': {'message': 'Expected: 1\nReceived: 2'} if status == 'unexpected' else None}]}]}
report = {'stats': {'expected': 1 if failed else 2, 'unexpected': 1 if failed else 0, 'flaky': 0, 'skipped': 1, 'duration': 1000},
          'suites': [{'file': 'a.spec.ts', 'specs': [test('one', 'expected'), test('two', 'unexpected' if failed else 'expected')]}], 'errors': []}
open(os.environ['PLAYWRIGHT_JSON_OUTPUT_NAME'], 'w').write(json.dumps(report))
sys.exit(1 if failed else 0)
"""


@unittest.skipIf(os.name == 'nt', 'the fake Playwright is a POSIX executable script; Windows behaviour of the same code paths is covered by the mocked tests below')
class BrowserLifecycleTests(unittest.TestCase):
    """run_browser against a fake Playwright: logs are closed before cleanup, failures keep their artifacts, infrastructure problems are
    classified and the exit codes are 0 (pass), 1 (tests failed) and 2 (infrastructure only)."""
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        fake = Path(self.folder.name) / 'fake-playwright'
        fake.write_text(FAKE_PLAYWRIGHT, encoding='utf-8'); fake.chmod(0o755)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
        self.patches = [patch.object(runner, 'BASE_PORT', port), patch.object(runner, 'ROOT', Path(self.folder.name)),
                        patch.dict(os.environ, {'SAP_LENS_NPM': str(fake), 'SAP_LENS_TEST_HEARTBEAT': '0'})]
        for item in self.patches:
            item.start(); self.addCleanup(item.stop)
        for name in ('SAP_LENS_TEST_ARTIFACTS', 'SAP_LENS_TEST_ASCII', 'SAP_LENS_TEST_COLOR', 'SAP_LENS_TEST_PROGRESS'):
            os.environ.pop(name, None)       # validate.py sets these for its own run; these tests check the defaults (restored by patch.dict)
        self.specs = [p.name[:-len('.spec.ts')] for p in sorted((ROOT / 'frontend' / 'tests').glob('*.spec.ts'))[:4]]

    def run_browser(self, mode, jobs=2):
        with patch.dict(os.environ, {'FAKE_MODE': mode}), patch('sys.stdout', new=io.StringIO()) as out, patch('sys.stderr', new=io.StringIO()) as err:
            result = runner.run_browser(self.specs, None, jobs, f'fake {mode}', [])
        self.assertEqual(err.getvalue(), '', 'the runner prints to stdout only: stderr made PowerShell 5.1 report NativeCommandError')
        return result, out.getvalue()

    def open_logs(self):
        fd = Path('/proc/self/fd')
        return [str(link.resolve()) for link in fd.iterdir() if 'sap-lens-browser-' in str(link.resolve())] if fd.exists() else []

    def test_a_passing_run_closes_its_logs_and_removes_the_scratch_directory(self):
        result, _ = self.run_browser('pass')
        self.assertTrue(result['ok']); self.assertEqual((result['passed'], result['failures'], len(result['skipped'])), (4, 0, 2))
        self.assertEqual(self.open_logs(), [], 'no log handle may stay open (WinError 32 on Windows)')
        self.assertFalse(result.get('artifacts')); self.assertEqual(result['infrastructure'], [])
        self.assertEqual(runner.report('targeted', 'x', [result], [], None), 0)

    def test_progress_is_live_per_test_and_failures_are_reported_before_the_process_ends(self):
        result, out = self.run_browser('fail', jobs=1)
        self.assertIn('PASS    a.spec.ts:1 > one › déjà vu', out)
        failure = out.index('FAIL    a.spec.ts:2 > two')
        self.assertIn('Received: 2', out[failure:failure + 200])
        self.assertLess(failure, out.index('[done] fake fail shard 1/1'), 'a failure is shown when it happens, not after the process exits')
        self.assertIn('[fake fail] 2 tests in 1 Playwright process(es)', out)
        self.assertEqual(result['failures'], 1)

    def test_failed_tests_keep_artifacts_report_errors_and_exit_1(self):
        result, err = self.run_browser('fail')
        self.assertFalse(result['ok']); self.assertEqual(result['failures'], 2); self.assertEqual(result['infrastructure'], [])
        self.assertIn('Received: 2', err); self.assertIn('fake diagnostics on stderr', err)
        self.assertTrue(Path(result['artifacts']).is_dir()); self.assertTrue(any(Path(result['artifacts']).glob('log-*.err.txt')))
        with patch('sys.stdout', new=io.StringIO()):
            self.assertEqual(runner.report('targeted', 'x', [result], [], None), 1)

    def test_a_process_without_a_report_is_an_infrastructure_failure_with_exit_2(self):
        result, err = self.run_browser('noreport')
        self.assertFalse(result['ok']); self.assertEqual(result['failures'], 0)
        self.assertTrue(result['infrastructure']); self.assertIn('without a test report', result['infrastructure'][0])
        self.assertIn('fake diagnostics on stderr', err)
        with patch('sys.stdout', new=io.StringIO()):
            self.assertEqual(runner.report('targeted', 'x', [result], [], None), 2)

    def test_a_hung_process_is_stopped_diagnosed_and_classified(self):
        started = time.perf_counter()
        with patch.object(runner, 'BROWSER_TIMEOUT', 3):
            result, _ = self.run_browser('hang', jobs=1)
        self.assertLess(time.perf_counter() - started, 60)
        self.assertFalse(result['ok']); self.assertTrue(any('stopped after 3s' in item for item in result['infrastructure']))
        self.assertEqual(runner.OWNED, [])


class TerminalOutputTests(unittest.TestCase):
    """Console output that works on Windows PowerShell 5.1, PowerShell 7 and Linux: nothing fails on an unencodable glyph, the --log copy keeps
    UTF-8, backend failures appear when they happen and the exit code is the runner's own."""
    def setUp(self):
        environment = patch.dict(os.environ, {})
        environment.start(); self.addCleanup(environment.stop)
        for name in ('SAP_LENS_TEST_ASCII', 'SAP_LENS_TEST_COLOR', 'SAP_LENS_TEST_COLOR_MARKERS'):
            os.environ.pop(name, None)       # validate.py sets SAP_LENS_TEST_ASCII=0 for its child run; these tests check the defaults

    def console(self, encoding):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding=encoding, errors='strict', newline='')
        return raw, stream, runner.SafeConsole(stream)

    def test_a_console_that_cannot_encode_a_glyph_gets_ascii_and_never_an_error(self):
        raw, stream, console = self.console('cp1252')                # a redirected Windows stdout: ANSI encoder, OEM decoder in PowerShell 5.1
        console.write('a.spec.ts:1 > one › two – déjà ✘ Ω\n'); console.flush()
        self.assertEqual(raw.getvalue().decode('ascii'), 'a.spec.ts:1 > one > two - deja x ?\n')

    def test_a_redirected_windows_console_gets_ascii_even_when_its_code_page_could_encode_the_text(self):
        raw, stream, console = self.console('utf-8')
        with patch.object(runner.os, 'name', 'nt'):
            console = runner.SafeConsole(stream)                       # not a TTY: PowerShell 5.1 would decode it in another code page
        console.write('one › déjà\n'); console.flush()
        self.assertEqual(raw.getvalue().decode('ascii'), 'one > deja\n')

    def test_a_utf8_console_and_the_log_keep_the_original_text(self):
        raw, stream, console = self.console('utf-8')
        log = io.StringIO()
        tee = runner.Tee(console, log)
        tee.write('one › déjà vu\n'); tee.flush()
        self.assertEqual(raw.getvalue().decode('utf-8'), 'one › déjà vu\n')
        self.assertEqual(log.getvalue(), 'one › déjà vu\n')

    def test_backend_failures_are_reported_when_they_happen(self):
        class Sample(unittest.TestCase):
            def test_a_fails(self):
                self.fail('synthetic')

            def test_b_passes(self):
                pass
        stream = io.StringIO()
        result = runner.QuietResult(unittest.runner._WritelnDecorator(stream), True, 0)
        result.startTestRun()
        unittest.defaultTestLoader.loadTestsFromTestCase(Sample).run(result)
        self.assertIn('FAIL: ', stream.getvalue()); self.assertIn('test_a_fails', stream.getvalue())
        self.assertNotIn('test_b_passes', stream.getvalue())

    def test_a_piped_ascii_console_keeps_the_exit_code_and_a_utf8_log(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / 'out.log'
            env = {**os.environ, 'PYTHONIOENCODING': 'ascii'}        # what a redirected PowerShell 5.1 console may offer
            done = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'run-tests.py'), 'nonsense-profile', '--log', str(log)],
                                  cwd=ROOT, env=env, capture_output=True, text=True, encoding='ascii', errors='strict')
            self.assertEqual(done.returncode, 2)                       # argparse's own exit code passes through unchanged
            ok = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'run-tests.py'), 'list', '--log', str(log)],
                                cwd=ROOT, env=env, capture_output=True, text=True, encoding='ascii', errors='strict')
            self.assertEqual(ok.returncode, 0, ok.stdout[-1000:])
            self.assertEqual(ok.stderr, '')
            self.assertIn('sod', log.read_text(encoding='utf-8'))

    def test_live_summary_counts_come_from_reporter_events(self):
        with tempfile.TemporaryDirectory() as folder:
            files = [Path(folder) / f'progress-{index}.jsonl' for index in range(2)]
            files[0].write_text('{"type":"begin","total":2}\n{"type":"test-end","file":"a.spec.ts","line":1,"title":"x","status":"passed","outcome":"expected","duration":1}\n', encoding='utf-8')
            files[1].write_text('{"type":"begin","total":3}\n{"type":"test-end","file":"b.spec.ts","line":1,"title":"y","status":"skipped","outcome":"skipped","duration":0}\n{"type":"test-e', encoding='utf-8')
            live = runner.LiveProgress('demo', files, [Path(folder) / 'none.txt'] * 2, time.perf_counter())
            with patch('sys.stdout', new=io.StringIO()):
                live.poll()
                summary = live.summary(set())
            self.assertIn('2/5 completed | passed 1 | failed 0 | skipped 1', summary)
            self.assertIn('shard 1: 1/2 | shard 2: 1/3', summary)
            with files[1].open('a', encoding='utf-8') as stream:      # the incomplete line is completed by a later write
                stream.write('nd","file":"b.spec.ts","line":2,"title":"z","status":"failed","outcome":"unexpected","duration":3,"error":"boom"}\n')
            with patch('sys.stdout', new=io.StringIO()) as out:
                live.poll()
            self.assertIn('FAIL    [shard 2] b.spec.ts:2 > z', out.getvalue()); self.assertIn('boom', out.getvalue())
            self.assertEqual(live.counts['failed'], 1)


class ColorOutputTests(unittest.TestCase):
    """Status colours: only on an interactive terminal (ANSI, or Windows console attributes when ANSI is unavailable), never in redirected
    output, logs or reports, NO_COLOR respected; with colours removed the text is exactly what an uncoloured run prints."""
    class Terminal(io.StringIO):
        def __init__(self, tty):
            super().__init__(); self.tty = tty

        def isatty(self):
            return self.tty

    def mode(self, tty=True, env=None, nt=False, ansi_ok=True):
        environment = {key: value for key, value in os.environ.items() if key not in {'NO_COLOR', 'SAP_LENS_TEST_COLOR', 'TERM'}}
        environment.update(env or {})
        with patch.dict(os.environ, environment, clear=True), patch.object(runner.os, 'name', 'nt' if nt else 'posix'):
            return runner.color_mode(self.Terminal(tty), enable_windows_ansi=lambda stream: ansi_ok)

    def test_colours_only_on_an_interactive_terminal(self):
        self.assertEqual(self.mode(tty=True, env={'TERM': 'xterm-256color'}), 'ansi')
        self.assertEqual(self.mode(tty=False), '', 'redirected output and pipes get no escape sequences')
        self.assertEqual(self.mode(tty=True, env={'TERM': 'dumb'}), '', 'a terminal without colour support')

    def test_no_color_and_the_explicit_switch_win(self):
        self.assertEqual(self.mode(env={'NO_COLOR': '1'}), '')
        self.assertEqual(self.mode(env={'NO_COLOR': '1', 'SAP_LENS_TEST_COLOR': 'always'}), '', 'NO_COLOR is never overridden')
        self.assertEqual(self.mode(env={'SAP_LENS_TEST_COLOR': 'never'}), '')
        self.assertEqual(self.mode(tty=False, env={'SAP_LENS_TEST_COLOR': 'always'}), 'ansi')

    def test_windows_uses_ansi_when_the_console_accepts_it_and_console_attributes_otherwise(self):
        self.assertEqual(self.mode(nt=True, ansi_ok=True), 'ansi')      # Windows 10+ conhost (PowerShell 5.1 and 7), Windows Terminal
        self.assertEqual(self.mode(nt=True, ansi_ok=False), 'native')   # older consoles: SetConsoleTextAttribute
        self.assertEqual(self.mode(nt=True, tty=False), '', 'a redirected PowerShell 5.1 console stays plain')

    def painted(self, text_factory):
        with patch.object(runner, 'PAINT', True):
            return text_factory()

    def test_ansi_colours_only_the_status_word_and_keeps_the_columns(self):
        line = self.painted(lambda: f"[00:01] {runner.status('PASS', 'pass', 7)} a.spec.ts:1 > one\n")
        terminal = self.Terminal(True)
        runner.SafeConsole(terminal, 'ansi').write(line)
        self.assertEqual(terminal.getvalue(), '[00:01] \x1b[32mPASS\x1b[0m    a.spec.ts:1 > one\n')
        self.assertEqual(re.sub('\x1b\\[[0-9;]*m', '', terminal.getvalue()), '[00:01] PASS    a.spec.ts:1 > one\n')

    def test_each_status_has_its_colour(self):
        codes = {kind: runner.COLORS[kind][0] for kind in ('pass', 'fail', 'warn', 'skip', 'info')}
        self.assertEqual(codes, {'pass': '32', 'fail': '31', 'warn': '33', 'skip': '90', 'info': '36'})   # green, red, yellow, gray, cyan

    def test_plain_terminals_logs_and_redirected_output_never_see_markers_or_escapes(self):
        line = self.painted(lambda: f"Summary: {runner.count(3, 'pass')} passed | {runner.count(1, 'fail')} failed | {runner.count(0, 'skip')} skipped\n")
        console, log = self.Terminal(False), io.StringIO()
        runner.Tee(runner.SafeConsole(console, ''), log).write(line)
        expected = 'Summary: 3 passed | 1 failed | 0 skipped\n'
        self.assertEqual(console.getvalue(), expected); self.assertEqual(log.getvalue(), expected)
        coloured, log = self.Terminal(True), io.StringIO()
        runner.Tee(runner.SafeConsole(coloured, 'ansi'), log).write(line)
        self.assertIn('\x1b[31m1\x1b[0m', coloured.getvalue()); self.assertNotIn('\x1b[', log.getvalue().replace('', ''))
        self.assertEqual(log.getvalue(), expected, 'the log copy is plain even when the terminal is coloured')
        self.assertNotIn('\x1b[', coloured.getvalue().split('|')[2], 'zero skipped stays neutral')

    def test_windows_console_attributes_wrap_only_the_status_word(self):
        terminal, calls = self.Terminal(True), []
        console = runner.SafeConsole(terminal, 'native')
        console.set_attribute = lambda attribute: calls.append((attribute, terminal.getvalue()))
        console.write(self.painted(lambda: f"[done] build: {runner.paint('FAIL (exit code 2)', 'fail')} (1.0s)\n"))
        self.assertEqual(terminal.getvalue(), '[done] build: FAIL (exit code 2) (1.0s)\n')
        self.assertEqual(calls, [(0x0C, '[done] build: '), (None, '[done] build: FAIL (exit code 2)')])

    def test_markers_pass_through_to_the_process_that_owns_the_terminal(self):
        line = self.painted(lambda: runner.paint('FAIL', 'fail'))
        pipe = self.Terminal(False)
        runner.SafeConsole(pipe, 'markers').write(line)
        self.assertEqual(pipe.getvalue(), line); self.assertEqual(runner.plain(pipe.getvalue()), 'FAIL')

    def test_importing_the_runner_never_paints_even_inside_a_coloured_worker(self):
        with patch.dict(os.environ, {'SAP_LENS_TEST_COLOR_MARKERS': '1'}):
            spec = importlib.util.spec_from_file_location('runner_copy', ROOT / 'scripts' / 'run-tests.py')
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        self.assertFalse(module.PAINT)
        self.assertEqual(module.status('PASS', 'pass', 7), 'PASS   ')

    def test_without_colours_paint_changes_nothing(self):
        with patch.object(runner, 'PAINT', False):
            self.assertEqual(runner.status('FAIL', 'fail', 7), 'FAIL   ')
            self.assertEqual(runner.count(2, 'fail'), '2')

    def test_ascii_consoles_keep_colours_and_readable_text(self):
        terminal = self.Terminal(True)
        console = runner.SafeConsole(terminal, 'ansi'); console.ascii = True
        console.write(self.painted(lambda: f"{runner.status('PASS', 'pass', 7)} one › déjà\n"))
        self.assertEqual(terminal.getvalue(), '\x1b[32mPASS\x1b[0m    one > deja\n')

    def test_live_failures_and_summaries_are_coloured(self):
        with tempfile.TemporaryDirectory() as folder:
            files = [Path(folder) / 'progress-0.jsonl']
            files[0].write_text('{"type":"begin","total":2}\n{"type":"test-end","file":"a.spec.ts","line":3,"title":"x","status":"failed","outcome":"unexpected","duration":10,"error":"boom"}\n'
                                '{"type":"test-end","file":"a.spec.ts","line":4,"title":"y","status":"passed","outcome":"expected","duration":5}\n', encoding='utf-8')
            terminal = self.Terminal(True)
            with patch.object(runner, 'PAINT', True), patch('sys.stdout', new=runner.SafeConsole(terminal, 'ansi')):
                live = runner.LiveProgress('demo', files, [Path(folder) / 'none.txt'], time.perf_counter())
                live.poll()
                summary = live.summary(set())
            self.assertIn('\x1b[31mFAIL\x1b[0m    a.spec.ts:3 > x', terminal.getvalue())
            self.assertIn('\x1b[32mPASS\x1b[0m    a.spec.ts:4 > y', terminal.getvalue())
            self.assertEqual(runner.plain(summary).split('] ', 1)[1], '2/2 completed | passed 1 | failed 1 | skipped 0')
            self.assertIn('\x02fail\x1f1\x03', summary); self.assertIn('\x02pass\x1f1\x03', summary)


class WindowsCleanupTests(unittest.TestCase):
    """Windows-specific lifecycle code driven with mocks (no Windows host here): tree termination and bounded cleanup retries."""
    def test_windows_termination_kills_the_whole_tree_by_process_id(self):
        process = unittest.mock.Mock(pid=4242)
        with patch.object(runner.os, 'name', 'nt'), patch.object(runner.subprocess, 'run') as run:
            runner._terminate_tree(process, force=True)
        self.assertEqual(run.call_args.args[0], ['taskkill', '/PID', '4242', '/T', '/F'])

    def test_cleanup_retries_transient_locks_and_never_raises(self):
        calls = {'n': 0}
        def locked(path):
            calls['n'] += 1
            if calls['n'] < 3:
                raise PermissionError(32, 'The process cannot access the file because it is being used by another process', 'log-2.txt')
        with patch.object(runner.shutil, 'rmtree', side_effect=locked), patch.object(runner.time, 'sleep'):
            self.assertIsNone(runner.remove_tree(Path('x')))
        self.assertEqual(calls['n'], 3)
        with patch.object(runner.shutil, 'rmtree', side_effect=PermissionError(32, 'locked')), patch.object(runner.time, 'sleep'):
            note = runner.remove_tree(Path('x'), attempts=3)
        self.assertIn('after 3 attempts', note)


class BrowserFailureReportingTests(unittest.TestCase):
    def test_failure_details_come_from_the_json_report_not_a_log_tail(self):
        report = {'suites': [{'file': 'a.spec.ts', 'specs': [
            {'file': 'a.spec.ts', 'title': 'fails', 'tests': [{'status': 'unexpected', 'results': [{'status': 'failed', 'error': {'message': '\x1b[31mExpected: 2\x1b[39m\nReceived: 3', 'location': {'file': '/x/a.spec.ts', 'line': 12}}}]}]},
            {'file': 'a.spec.ts', 'title': 'passes', 'tests': [{'status': 'expected', 'results': [{'status': 'passed'}]}]}]}]}
        messages = runner.playwright_failures(report)
        self.assertEqual(len(messages), 1)
        self.assertIn('a.spec.ts :: fails (a.spec.ts:12)', messages[0]); self.assertIn('Received: 3', messages[0]); self.assertNotIn('\x1b', messages[0])


class QuietBackendRunnerTests(unittest.TestCase):
    """The backend worker is quiet on success, keeps every diagnostic of a failing test, reports leaks and fails with a non-zero exit code."""
    PROBE = (
        "import unittest\n"
        "class Probe(unittest.TestCase):\n"
        "    def test_expected_diagnostic(self):\n"
        "        print('EXPECTED-NOISE from a passing negative test')\n"
        "        import logging; logging.getLogger('sap-lens').warning('EXPECTED-WARNING retained previous data')\n"
        "    def test_failure_keeps_its_output(self):\n"
        "        print('FAILURE-CONTEXT printed before the failure')\n"
        "        self.fail('deliberate probe failure')\n"
        "    def test_leak(self):\n"
        "        open(__file__); import gc; gc.collect()\n")

    def run_worker(self, **env):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'probe_quiet_runner.py').write_text(self.PROBE, encoding='utf-8')
            out = Path(folder) / 'result.json'
            done = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'run-tests.py'), '_backend', str(out), 'probe_quiet_runner'],
                                  cwd=ROOT, capture_output=True, text=True, timeout=120, env={**os.environ, 'PYTHONPATH': folder, **env})
            import json
            return done, json.loads(out.read_text(encoding='utf-8'))

    def test_quiet_mode_hides_passing_output_but_keeps_failures_leaks_and_the_exit_code(self):
        done, data = self.run_worker()
        output = done.stdout + done.stderr
        self.assertNotIn('EXPECTED-NOISE', output); self.assertNotIn('EXPECTED-WARNING', output)
        self.assertIn('FAILURE-CONTEXT', output); self.assertIn('deliberate probe failure', output)
        self.assertEqual(done.returncode, 1); self.assertEqual((data['tests'], data['failures'], data['errors']), (3, 1, 0))
        self.assertTrue(any('unclosed file' in leak for leak in data['resource_warnings']), data['resource_warnings'])
        self.assertEqual(len(data['slowest']), 3)

    def test_verbose_mode_shows_everything(self):
        done, _ = self.run_worker(SAP_LENS_TEST_VERBOSE='1')
        output = done.stdout + done.stderr
        self.assertIn('EXPECTED-NOISE', output); self.assertIn('test_expected_diagnostic', output)

    def test_single_test_selection_and_log_file(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / 'run.log'
            done = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'run-tests.py'), 'targeted', '--test', 'test_test_profiles.TestProfileTests', '--log', str(log)],
                                  cwd=ROOT, capture_output=True, text=True, timeout=300)
            self.assertEqual(done.returncode, 0, done.stdout[-2000:] + done.stderr[-2000:])
            self.assertIn('backend selected tests', log.read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as folder:                                  # failure details written to stderr reach the log as well
            log = Path(folder) / 'failed.log'
            done = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'run-tests.py'), 'targeted', '--test', 'no_such_module_for_log_test', '--log', str(log)],
                                  cwd=ROOT, capture_output=True, text=True, timeout=120)
            self.assertNotEqual(done.returncode, 0)
            self.assertIn('no_such_module_for_log_test', log.read_text(encoding='utf-8'))
        refused = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'run-tests.py'), 'regression', '--test', 'x'], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(refused.returncode, 0)


class BrowserProcessHygieneTests(unittest.TestCase):
    """Test processes clean up after themselves and the tooling never signals processes it does not own."""

    def make_dir(self, root, name, pid=None, age=0):
        path = Path(root) / f'{server.PREFIX}{name}'
        path.mkdir()
        if pid is not None:
            (path / server.OWNER_FILE).write_text(str(pid), encoding='ascii')
        if age:
            old = time.time() - age
            os.utime(path, (old, old))
        return path

    @unittest.skipIf(sys.platform == 'win32', 'owner liveness is only probed on POSIX')
    def test_sweep_removes_only_directories_whose_owner_is_gone(self):
        with tempfile.TemporaryDirectory() as root:
            gone = subprocess.Popen([sys.executable, '-c', 'pass']); gone.wait()
            dead = self.make_dir(root, 'dead', gone.pid)
            live = self.make_dir(root, 'live', os.getpid())
            fresh = self.make_dir(root, 'fresh-legacy')
            old = self.make_dir(root, 'old-legacy', age=server.LEGACY_MAX_AGE + 60)
            unrelated = Path(root) / 'other-project-dir'; unrelated.mkdir()
            broken = self.make_dir(root, 'broken'); (broken / server.OWNER_FILE).write_text('not a pid')
            removed = server.sweep_stale(Path(root))
            self.assertEqual(sorted(removed), sorted([dead.name, old.name]))
            self.assertTrue(live.exists() and fresh.exists() and unrelated.exists() and broken.exists())

    def test_runner_reports_busy_ports_without_touching_the_owner(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); listener.listen()
            port = listener.getsockname()[1]
            original = runner.BASE_PORT
            runner.BASE_PORT = port
            try:
                self.assertEqual(runner.busy_ports(1), [port])
                result = runner.run_browser(None, None, 1, 'busy', [])
            finally:
                runner.BASE_PORT = original
            self.assertFalse(result['ok'])
            self.assertEqual(result['tests'], 0)
            self.assertGreaterEqual(listener.fileno(), 0)  # the listener is still ours and untouched

    @unittest.skipIf(sys.platform == 'win32', 'SIGTERM semantics differ on Windows')
    def test_test_server_removes_its_directory_on_sigterm(self):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
        with tempfile.TemporaryDirectory() as root:
            env = {**os.environ, 'TMPDIR': root, 'SAP_LENS_BROWSER_TEST_PORT': str(port)}
            process = subprocess.Popen([sys.executable, str(ROOT / 'scripts' / 'testing' / 'serve-browser-tests.py')], env=env,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.time() + 20
                while time.time() < deadline and not list(Path(root).glob(f'{server.PREFIX}*/{server.OWNER_FILE}')):
                    time.sleep(0.1)
                directories = list(Path(root).glob(f'{server.PREFIX}*'))
                self.assertEqual(len(directories), 1, 'the server created its isolated directory')
                self.assertEqual(int((directories[0] / server.OWNER_FILE).read_text()), process.pid)
                time.sleep(0.5)
                process.send_signal(signal.SIGTERM)
                self.assertIn(process.wait(15), (0, -signal.SIGTERM))
                self.assertEqual(list(Path(root).glob(f'{server.PREFIX}*')), [])
            finally:
                if process.poll() is None:
                    process.kill(); process.wait()

    @unittest.skipIf(sys.platform == 'win32', 'process groups and SIGKILL semantics differ on Windows')
    def test_test_server_exits_and_removes_its_directory_when_its_parent_is_killed(self):
        """A SIGKILLed Playwright cannot run its own cleanup, so the server it started (via `exec`, as in playwright.config.ts) watches for it."""
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
        with tempfile.TemporaryDirectory() as root:
            env = {**os.environ, 'TMPDIR': root, 'SAP_LENS_BROWSER_TEST_PORT': str(port)}
            parent = subprocess.Popen(['sh', '-c', f'exec {sys.executable} -c "import subprocess,sys,time; subprocess.Popen([\'sh\',\'-c\',\'exec {sys.executable} {ROOT / "scripts" / "testing" / "serve-browser-tests.py"}\']); print(1, flush=True); time.sleep(120)"'],
                                      env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            try:
                parent.stdout.readline()
                deadline = time.time() + 30
                while time.time() < deadline and not list(Path(root).glob(f'{server.PREFIX}*/{server.OWNER_FILE}')):
                    time.sleep(0.1)
                markers = list(Path(root).glob(f'{server.PREFIX}*/{server.OWNER_FILE}'))
                self.assertEqual(len(markers), 1)
                pid = int(markers[0].read_text())
                parent.kill(); parent.wait()                                                       # no chance to clean up
                deadline = time.time() + 30
                while time.time() < deadline and (list(Path(root).glob(f'{server.PREFIX}*')) or runner.busy_ports_at(port)):
                    time.sleep(0.2)
                self.assertEqual(list(Path(root).glob(f'{server.PREFIX}*')), [], 'the storage directory was removed')
                self.assertFalse(runner.busy_ports_at(port), 'the port was released')
                def state_of() -> str:                                                           # a zombie awaiting an init that does not reap is already finished
                    try:
                        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0]
                    except OSError:
                        return 'gone'
                deadline = time.time() + 30
                while time.time() < deadline and state_of() not in {'Z', 'gone'}:
                    time.sleep(0.1)
                state = state_of()
                self.assertIn(state, {'Z', 'gone'}, 'the server process ended')
            finally:
                if parent.poll() is None:
                    parent.kill(); parent.wait()
                parent.stdout.close()                                                                # no unclosed pipe (ResourceWarning)

    @unittest.skipIf(sys.platform == 'win32', 'signals differ on Windows')
    def test_runner_stops_the_processes_it_started_when_it_receives_SIGTERM(self):
        script = (
            "import importlib.util,subprocess,sys,time\n"
            f"spec=importlib.util.spec_from_file_location('r','{ROOT / 'scripts' / 'run-tests.py'}');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)\n"
            "with r.cleanup_on_signals():\n"
            "    child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'],start_new_session=True);r.OWNED.append(child)\n"
            "    print(child.pid,flush=True)\n"
            "    try:\n"
            "        time.sleep(120)\n"
            "    finally:\n"
            "        r.stop_owned()\n")
        process = subprocess.Popen([sys.executable, '-c', script], stdout=subprocess.PIPE, text=True)
        try:
            child = int(process.stdout.readline())
            process.send_signal(signal.SIGTERM)
            self.assertEqual(process.wait(30), 128 + signal.SIGTERM)
            deadline = time.time() + 20
            while time.time() < deadline:
                try:
                    os.kill(child, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.1)
            with self.assertRaises(ProcessLookupError):
                os.kill(child, 0)
        finally:
            if process.poll() is None:
                process.kill(); process.wait()
            process.stdout.close()

    def test_parallel_jobs_use_distinct_ports_and_storage(self):
        ports = [runner.BASE_PORT + index for index in range(runner.BROWSER_JOBS_MAX)]
        self.assertEqual(len(set(ports)), runner.BROWSER_JOBS_MAX)
        self.assertEqual(len({f'{server.PREFIX}{name}' for name in ('a', 'b')}), 2)
        text = (ROOT / 'scripts' / 'testing' / 'serve-browser-tests.py').read_text()
        self.assertIn('tempfile.TemporaryDirectory(prefix=PREFIX)', text, 'every server creates its own storage directory')
        self.assertIn("os.environ['SAP_LENS_CONFIG_DIR'] = directory", text)


class ParallelExecutionTests(unittest.TestCase):
    """The browser suite can use up to three isolated processes: deterministic, balanced, bounded and always cleaned up."""

    def test_spec_distribution_is_deterministic_complete_and_balanced(self):
        files = [f'tests/{name}.spec.ts' for name in runner.browser_specs()]
        for jobs in (2, 3):
            groups = runner.split_specs(files, jobs)
            self.assertEqual(groups, runner.split_specs(list(reversed(files)), jobs), 'independent of the input order')
            self.assertEqual(sorted(file for group in groups for file in group), sorted(files), 'every spec file runs exactly once')
            hints = runner.load_map()['browser_seconds_hint']
            loads = [sum(hints.get(Path(file).name[:-8], runner.DEFAULT_SPEC_SECONDS) for file in group) for group in groups]
            self.assertLess(max(loads), 1.1 * sum(loads) / len(loads), f'{jobs} processes are balanced within 10 percent: {loads}')

    def test_every_hint_names_a_spec_and_new_specs_get_a_default(self):
        self.assertEqual(runner.coverage_problems(), [])
        groups = runner.split_specs(['tests/brand-new.spec.ts', 'tests/a11y-audit.spec.ts'], 2)
        self.assertEqual(sorted(len(group) for group in groups), [1, 1])

    def test_browser_processes_are_bounded_and_fall_back_conservatively(self):
        from unittest.mock import patch
        for cpus, expected in ((1, 1), (2, 1), (3, 2), (4, 3), (16, 3)):
            with patch.object(runner.os, 'cpu_count', return_value=cpus):
                self.assertEqual(runner.browser_jobs_value('auto', 1), expected, f'{cpus} CPUs')
        self.assertEqual(runner.browser_jobs_value('8', 1), runner.BROWSER_JOBS_MAX, 'never more than three')
        self.assertEqual(runner.browser_jobs_value('2', 1), 2)
        self.assertEqual(runner.browser_jobs_value(None, 1), 1, 'one process unless asked')
        with patch.dict(os.environ, {'SAP_LENS_BROWSER_JOBS': '2'}):
            self.assertEqual(runner.browser_jobs_value(None, 1), 2)
            self.assertEqual(runner.browser_jobs_value('1', 1), 1, 'the option wins over the environment')
        self.assertEqual(runner.jobs_value('auto', 'browser'), 1)

    def test_playwright_reports_are_summarised_per_test(self):
        report = {'suites': [{'file': 'a.spec.ts', 'suites': [{'specs': [{'file': 'a.spec.ts', 'title': 'slow', 'tests': [{'status': 'expected', 'results': [{'duration': 4000}]}]},
                                                                      {'file': 'a.spec.ts', 'title': 'broken', 'tests': [{'status': 'unexpected', 'results': [{'duration': 500}, {'duration': 250}]}]}]}]}]}
        self.assertEqual(runner.playwright_tests(report), [(4.0, 'a.spec.ts', 'slow', 'expected'), (0.75, 'a.spec.ts', 'broken', 'unexpected')])

    @unittest.skipIf(sys.platform == 'win32', 'process groups are POSIX')
    def test_cleanup_stops_only_the_processes_the_runner_started(self):
        owned = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
        stranger = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
        try:
            runner.OWNED.append(owned)
            runner.stop_owned(grace=10)
            self.assertIsNotNone(owned.poll(), 'the owned process was stopped')
            self.assertIsNone(stranger.poll(), 'a process the runner did not start is never signalled')
            self.assertEqual(runner.OWNED, [])
        finally:
            for process in (owned, stranger):
                if process.poll() is None:
                    process.kill()
                process.wait()


class ChangeSelectionTests(unittest.TestCase):
    """Fast Validation runs what a change can affect, and never less than the safe baseline for core changes."""
    def plan(self, *files):
        return runner.plan_changes(list(files))

    def test_paths_are_classified_and_unknown_paths_are_core(self):
        expected = {'docs/features/SOD.md': 'docs', 'README.md': 'docs', 'assets/sap-lens.png': 'docs', 'backend/tests/test_server.py': 'backend_tests',
                    'frontend/tests/a11y-audit.spec.ts': 'frontend_tests', 'frontend/src/components/Shared/Select.tsx': 'frontend', 'frontend/package-lock.json': 'frontend',
                    'frontend/vite.config.ts': 'frontend', 'backend/main.py': 'core', 'backend/routers/sod.py': 'core', 'scripts/run-tests.py': 'core', '.github/workflows/validate.yml': 'core',
                    'backend/requirements.txt': 'core', 'ruff.toml': 'core', 'compose.yml': 'core', 'deploy/linux/sap-lens.service': 'core', 'something/new/file.bin': 'core'}
        for path, category in expected.items():
            self.assertEqual(runner.classify(path), category, path)

    def test_documentation_only_changes_run_the_repository_checks_and_nothing_else(self):
        plan = self.plan('docs/deployment/RELEASES.md', 'docs/validation/validation-items.csv', 'README.md')
        self.assertEqual((plan['backend'], plan['frontend'], plan['browser']), ('repository', False, False))
        self.assertIn('test_repository_integrity', plan['modules']); self.assertNotIn('test_sod_reports', plan['modules'])

    def test_backend_sources_scripts_workflows_and_dependencies_run_the_whole_backend(self):
        for path in ('backend/main.py', 'backend/routers/sod.py', 'backend/sod_reports.py', 'scripts/deployment/deployment-release.py', '.github/workflows/build-deployments.yml',
                     'backend/requirements-dev.txt', 'scripts/test-map.json', 'backend/tests/__init__.py', 'backend/tests/helpers.py', 'unknown.cfg'):
            with self.subTest(path=path):
                plan = self.plan(path)
                self.assertEqual(plan['backend'], 'full'); self.assertTrue(plan['reasons'])
        self.assertFalse(self.plan('backend/main.py')['frontend'])

    def test_a_changed_backend_test_module_runs_that_module_with_the_repository_checks(self):
        plan = self.plan('backend/tests/test_sod_reports.py', 'backend/tests/test_server.py')
        self.assertEqual(plan['backend'], 'modules'); self.assertIn('test_sod_reports', plan['modules']); self.assertIn('test_repository_integrity', plan['modules'])
        self.assertEqual(self.plan('backend/tests/test_deleted_long_ago.py')['backend'], 'repository', 'a deleted module has nothing to run')

    def test_frontend_changes_run_build_lint_and_browser_smoke_and_changed_specs(self):
        plan = self.plan('frontend/src/components/Shared/Select.tsx')
        self.assertEqual((plan['backend'], plan['frontend'], plan['browser'], plan['specs']), ('repository', True, True, []))
        plan = self.plan('frontend/tests/select-family.spec.ts', 'frontend/tests/sod-fixture.ts', 'frontend/tests/not-a-spec.spec.ts')
        self.assertEqual((plan['frontend'], plan['specs']), (True, ['select-family']), 'a spec runs itself; a helper or an unknown spec only triggers the smoke baseline')
        self.assertTrue(self.plan('frontend/package-lock.json')['browser'])

    def test_a_mixed_change_unions_the_needs_of_each_part(self):
        plan = self.plan('docs/x.md', 'frontend/src/App.tsx', 'backend/deployment.py')
        self.assertEqual((plan['backend'], plan['frontend'], plan['browser']), ('full', True, True))

    def test_an_unusable_base_selects_the_safe_baseline(self):
        for base in (None, '', '0' * 40, 'not-a-commit-at-all'):
            with self.subTest(base=base):
                plan = runner.plan_changes(runner.changed_files(base))
                self.assertEqual((plan['backend'], plan['frontend'], plan['browser']), ('full', True, True))
        self.assertTrue(runner.plan_changes(None)['reasons'])

    def test_changed_files_compares_with_a_real_commit(self):
        files = runner.changed_files('HEAD')
        self.assertIsInstance(files, list)  # the working tree against HEAD; empty or the current edits


class FrontendUnitTestWiringTests(unittest.TestCase):
    """Node unit tests were once present but executed by nothing; keep them reachable from the script and both validation workflows."""
    def test_unit_tests_are_run_by_the_package_script_and_the_workflows(self):
        import json
        files = sorted((ROOT / 'frontend/tests/unit').glob('*.test.ts'))
        self.assertTrue(files)
        script = json.loads((ROOT / 'frontend/package.json').read_text())['scripts']['test:unit']
        self.assertIn('tests/unit/*.test.ts', script)
        for workflow in ('validate.yml', 'full-validation.yml'):
            text = (ROOT / '.github/workflows' / workflow).read_text()
            self.assertIn('run unit -- npm --prefix frontend run test:unit', text, workflow)
            self.assertRegex(text, r'CI_(?:REQUIRED|OPTIONAL): [^\n]*\bunit\b', workflow)

    def test_frontend_source_and_unit_test_changes_run_the_frontend_stage_without_extra_specs(self):
        for path in ('frontend/src/lib/sessionState.ts', 'frontend/tests/unit/sod-bulk.test.ts'):
            plan = runner.plan_changes([path])
            self.assertTrue(plan['frontend'], path)   # the stage that now includes the unit step
            self.assertEqual(plan['specs'], [], path)  # no browser spec is named by these paths


if __name__ == '__main__':
    unittest.main()
