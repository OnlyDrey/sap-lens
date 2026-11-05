"""pip bootstrap and locked-dependency checks (scripts/build_system/python_env.py). Pure mocks: nothing is installed, no network is used."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))

from build_system import python_env as env, prerequisites as deps  # noqa: E402

TLS = 'ERROR: Could not fetch URL https://pypi.org/simple/pip/: There was a problem confirming the ssl certificate: [SSL: CERTIFICATE_VERIFY_FAILED]'


class Recorder:
    """Scripted `run(label, command)`: pops (code, output) answers and records the commands issued."""
    def __init__(self, answers):
        self.answers = list(answers); self.commands = []

    def __call__(self, label, command):
        self.commands.append([str(item) for item in command])
        return self.answers.pop(0) if self.answers else (0, '')


def with_versions(*versions):
    queue = list(versions)
    return patch.object(env, 'pip_version', side_effect=lambda python: queue.pop(0) if len(queue) > 1 else queue[0])


class PipVersionTests(unittest.TestCase):
    def test_parsing(self):
        self.assertEqual(env.parse_pip_version('pip 24.0 from C:\\x\\pip (python 3.12)'), (24, 0))
        self.assertEqual(env.parse_pip_version('pip 26.3 from /x (python 3.12)'), (26, 3))
        self.assertIsNone(env.parse_pip_version('No module named pip')); self.assertIsNone(env.parse_pip_version(''))

    def test_project_pins_a_pip_new_enough_for_the_system_trust_store(self):
        pin = env.pinned_pip(ROOT); self.assertIsNotNone(pin)
        self.assertGreaterEqual(tuple(map(int, pin.split('.')[:2])), env.MINIMUM_PIP)


class EnsurePipTests(unittest.TestCase):
    def test_every_known_certificate_failure_wording_is_recognized(self):
        for text in (TLS, 'pip._vendor.urllib3.exceptions.SSLError', "ssl.SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate",
                     'SSLCertVerificationError: unable to get local issuer certificate'):
            self.assertTrue(env.TLS_FAILURE.search(text), text)
        self.assertFalse(env.TLS_FAILURE.search('Connection refused'))

    def test_a_current_pip_changes_nothing_and_repeats_cleanly(self):
        run = Recorder([])
        with with_versions((26, 2)):
            self.assertEqual(env.ensure_pip('python', ROOT, run), 'ok'); self.assertEqual(env.ensure_pip('python', ROOT, run), 'ok')
        self.assertEqual(run.commands, [])

    def test_missing_pip_is_seeded_then_checked(self):
        run = Recorder([(0, '')])
        with with_versions(None, (26, 2)):
            self.assertEqual(env.ensure_pip('python', ROOT, run), 'seeded')
        self.assertIn('ensurepip', run.commands[0])

    def test_pip_that_cannot_be_seeded_gives_actionable_guidance(self):
        with with_versions(None), self.assertRaises(RuntimeError) as raised:
            env.ensure_pip('python', ROOT, Recorder([(1, 'boom')]))
        self.assertIn('left untouched', str(raised.exception))

    def test_outdated_pip_is_upgraded_to_the_pinned_version_without_any_trust_flag(self):
        run = Recorder([(0, '')]); pin = env.pinned_pip(ROOT)
        with with_versions((24, 0), (26, 2)):
            self.assertEqual(env.ensure_pip('python', ROOT, run), 'upgraded')
        self.assertEqual(len(run.commands), 1); self.assertIn(f'pip=={pin}', run.commands[0]); self.assertNotIn('--use-feature=truststore', run.commands[0])

    def test_tls_failure_retries_once_with_the_system_trust_store_and_keeps_verification_on(self):
        run = Recorder([(1, TLS), (0, '')]); said = []
        with with_versions((24, 0), (26, 2)):
            self.assertEqual(env.ensure_pip('python', ROOT, run, said.append), 'upgraded')
        self.assertEqual(len(run.commands), 2)
        self.assertNotIn('--use-feature=truststore', run.commands[0]); self.assertIn('--use-feature=truststore', run.commands[1])
        flat = ' '.join(' '.join(command) for command in run.commands)
        for forbidden in ('--trusted-host', '--cert', 'PIP_CERT', 'verify'): self.assertNotIn(forbidden, flat)
        self.assertTrue(said)

    def test_untrusted_certificate_after_the_retry_explains_how_to_trust_the_ca(self):
        run = Recorder([(1, TLS), (1, TLS)])
        with with_versions((24, 0)), self.assertRaises(RuntimeError) as raised:
            env.ensure_pip('python', ROOT, run)
        message = str(raised.exception)
        self.assertIn('corporate CA', message); self.assertIn('never disables certificate verification', message)
        self.assertEqual(len(run.commands), 2)  # one plain attempt, one trust-store attempt, no endless loop

    def test_non_tls_failure_is_not_retried_with_the_trust_flag(self):
        run = Recorder([(1, 'Connection refused')])
        with with_versions((24, 0)), self.assertRaises(RuntimeError) as raised:
            env.ensure_pip('python', ROOT, run)
        self.assertEqual(len(run.commands), 1); self.assertIn('network', str(raised.exception))

    def test_pip_that_stays_old_after_the_upgrade_is_reported(self):
        with with_versions((24, 0)), self.assertRaises(RuntimeError) as raised:
            env.ensure_pip('python', ROOT, Recorder([(0, '')]))
        self.assertIn('still older', str(raised.exception))


class LockedDependencyTests(unittest.TestCase):
    def test_real_requirement_files_are_exactly_pinned(self):
        pins = env.parse_pins(ROOT, ['backend/requirements-dev.txt', 'backend/requirements-build.txt'])
        self.assertTrue(pins); self.assertIn('fastapi', pins); self.assertIn('pip', pins)

    def test_installed_versions_decide_whether_an_install_is_needed(self):
        pins = env.parse_pins(ROOT, ['backend/requirements-dev.txt'])
        with patch.object(env, 'installed_packages', return_value=dict(pins)):
            self.assertTrue(env.dependencies_satisfied('python', ROOT, ['backend/requirements-dev.txt']))
        missing = dict(pins); missing.pop('fastapi')
        wrong = dict(pins); wrong['fastapi'] = '0.0.1'
        for installed in (missing, wrong, None, {}):
            with self.subTest(installed=bool(installed)), patch.object(env, 'installed_packages', return_value=installed):
                self.assertFalse(env.dependencies_satisfied('python', ROOT, ['backend/requirements-dev.txt']))

    def test_unpinned_or_unparseable_lines_always_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / 'backend').mkdir()
            (root / 'backend/a.txt').write_text('requests>=2\n')
            self.assertIsNone(env.parse_pins(root, ['backend/a.txt']))
            with patch.object(env, 'installed_packages', return_value={'requests': '2.0'}):
                self.assertFalse(env.dependencies_satisfied('python', root, ['backend/a.txt']))


class PrepareEnvironmentFlowTests(unittest.TestCase):
    def prepared(self, **patches):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); python = root / '.venv' / ('Scripts/python.exe' if deps.os.name == 'nt' else 'bin/python')
            python.parent.mkdir(parents=True); python.touch()
            runner = type('R', (), {'calls': [], 'last_output': None, 'directory': None})()
            runner.run = lambda label, command, timeout=0: runner.calls.append(label)
            with patch.object(deps.subprocess, 'check_output', return_value='[3,12,64]'), patch.object(deps, 'locate', return_value='npm'), patch.object(deps, 'frontend_current', return_value=True), \
                 patch.object(deps.python_env, 'pip_version', return_value=(26, 2)), patch.object(deps.python_env, 'dependencies_satisfied', return_value=patches['satisfied']):
                deps.prepare_environment(root, runner)
            return runner.calls

    def test_second_run_with_valid_dependencies_installs_nothing(self):
        calls = self.prepared(satisfied=True)
        self.assertFalse(any('Install' in call or 'Create' in call for call in calls)); self.assertIn('Check local Python dependencies', calls)

    def test_missing_locked_dependencies_trigger_one_install(self):
        calls = self.prepared(satisfied=False)
        self.assertEqual([call for call in calls if call.startswith('Install')], ['Install locked project Python dependencies'])


class NodeAndFrontendTests(unittest.TestCase):
    def test_unsupported_node_and_missing_npm_have_actionable_guidance(self):
        with patch.object(deps, 'locate', return_value='node'), patch.object(deps.subprocess, 'check_output', return_value='22.22.0'), self.assertRaises(deps.BuildError) as raised:
            deps.inspect_tool('node')
        self.assertIn('22.22.0', str(raised.exception)); self.assertIn('does not replace your global Node.js', str(raised.exception))
        with patch.object(deps, 'locate', return_value=None):
            self.assertIsNone(deps.inspect_tool('npm'))

    def test_frontend_freshness_follows_the_hidden_lockfile(self):
        import os, time
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / 'frontend/node_modules').mkdir(parents=True)
            for name in ('package.json', 'package-lock.json'): (root / 'frontend' / name).write_text('{}')
            self.assertFalse(deps.frontend_current(root))                       # never installed
            hidden = root / 'frontend/node_modules/.package-lock.json'; hidden.write_text('{}')
            self.assertTrue(deps.frontend_current(root))                        # installed after the manifests
            later = time.time() + 100; os.utime(root / 'frontend/package-lock.json', (later, later))
            self.assertFalse(deps.frontend_current(root))                       # lockfile changed afterwards


if __name__ == '__main__':
    unittest.main()
