"""Startup failure evidence: the host and the backend entry explain WHY the backend did not become ready, the evidence survives and is redacted, and the PowerShell
classifier tells the cases apart on the real output. Linux only; runs the real host and the real bundled runtime (a private copy that each scenario modifies and restores)."""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path

import support
from support import HOST, RUNTIME

WINDOWS = support.ROOT / 'windows'
PWSH = shutil.which('pwsh')


def setUpModule():
    support.need_runtime(None)


class StartupDiagnostics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix='poc-startup-'))
        cls.runtime = cls.base / 'runtime'
        shutil.copytree(RUNTIME, cls.runtime, symlinks=True)
        cls.backend = cls.runtime / 'app' / 'backend'
        cls.counter = 0

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def run_host(self, *extra, runtime=None, timeout=60):
        type(self).counter += 1
        data = self.base / f'data-{self.counter}'
        started = time.monotonic()
        result = subprocess.run([str(HOST), '--runtime', str(runtime or self.runtime), '--data', str(data), *extra], capture_output=True, text=True, timeout=timeout)
        result.elapsed = time.monotonic() - started
        result.data = data
        return result

    @contextmanager
    def replaced(self, path, content=None):
        """Temporarily replace (or, with content None, move away) a file or directory of the runtime copy, and always restore it."""
        path = Path(path)
        saved = path.with_name(path.name + '.saved')
        is_link = path.is_symlink()
        target = os.readlink(path) if is_link else None
        path.rename(saved)
        try:
            if content is not None:
                path.write_text(content)
                path.chmod(0o755)
            yield
        finally:
            if path.is_symlink() or path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
            saved.rename(path)
            if is_link:
                self.assertEqual(os.readlink(path), target)

    @contextmanager
    def fake_main(self, source):
        """Replace the backend's main module (and its precompiled copy, which Python would otherwise run unchecked)."""
        pyc = list((self.backend / '__pycache__').glob('main.cpython-312.pyc'))
        moved = []
        for item in pyc:
            moved.append((item, item.with_name(item.name + '.saved')))
            item.rename(moved[-1][1])
        try:
            with self.replaced(self.backend / 'main.py', source):
                yield
        finally:
            for original, saved in moved:
                saved.rename(original)

    def classify(self, exit_code, stderr, integrity='@()'):
        with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False, dir=self.base) as handle:
            handle.write(stderr)
        command = f". '{WINDOWS}/Phase1Common.ps1'; $t = Get-Content -Raw -LiteralPath '{handle.name}'; Resolve-StartupFailure {exit_code} $t {integrity} | ConvertTo-Json -Compress"
        result = subprocess.run([PWSH, '-NoProfile', '-Command', command], capture_output=True, text=True, timeout=60)
        return json.loads(result.stdout.strip().splitlines()[-1])

    # ---- success ---------------------------------------------------------------------------------------------------------------------------
    def test_successful_start_records_every_phase_and_the_ready_handshake(self):
        result = self.run_host('--exit-after-ready')
        self.assertEqual(result.returncode, 0, result.stderr[-800:])
        self.assertRegex(result.stdout, r'^READY url=http://127\.0\.0\.1:\d+/ pid=\d+ ms=\d+')
        for phase in ('phase=spawn ', 'phase=spawned', 'phase=handoff_written', 'phase=listening port=', 'phase=ready', 'poc: t=', 'phase=frontend_check index_html_exists=True',
                      'phase=imported_uvicorn', 'phase=imported_main', 'phase=app_created', 'phase=serving'):
            self.assertIn(phase, result.stderr, phase)
        self.assertIn('sys.path=', result.stderr)
        self.assertIn('env_names=', result.stderr)
        self.assertNotIn('SAP_LENS_POC_DATA=', result.stderr)  # names only, never values

    # ---- failures before the backend runs ----------------------------------------------------------------------------------------------------
    def test_early_host_failure_is_reported_with_exit_code_2(self):
        result = self.run_host(runtime=self.base / 'no-such-runtime')
        self.assertEqual(result.returncode, 2)
        self.assertIn('no Python interpreter in the runtime tree', result.stderr)

    # ---- failures inside the backend (exit code 4, evidence preserved) ---------------------------------------------------------------------------
    def test_missing_frontend_assets_fail_fast_with_a_clear_message(self):
        with self.replaced(self.runtime / 'app' / 'frontend'):
            result = self.run_host('--start-timeout', '20s')
        self.assertEqual(result.returncode, 4, result.stderr[-600:])
        self.assertIn('frontend assets are missing', result.stderr)
        self.assertIn('backend exited with code 13', result.stderr)
        self.assertIn('phase=child_exit', result.stderr)
        self.assertLess(result.elapsed, 15, 'it must not wait for the timeout')
        verdict = self.classify(4, result.stderr)
        self.assertEqual((verdict['Status'], verdict['Class']), ('FAIL', 'backend_exited_before_ready'))
        self.assertIn('frontend_assets_missing', verdict['Detail'])

    def test_python_import_failure_keeps_the_traceback_and_exit_codes(self):
        with self.fake_main('raise ImportError("synthetic import failure")\n'):
            result = self.run_host('--start-timeout', '20s')
        self.assertEqual(result.returncode, 4, result.stderr[-600:])
        self.assertIn('ImportError: synthetic import failure', result.stderr)
        self.assertIn('Traceback (most recent call last)', result.stderr)
        self.assertIn('phase=failed_before_serving', result.stderr)
        self.assertIn('backend exited with code 12', result.stderr)
        verdict = self.classify(4, result.stderr)
        self.assertIn('startup_error', verdict['Detail'])
        self.assertIn('ImportError', verdict['Detail'])

    def test_missing_runtime_dependency_is_named(self):
        site = self.runtime / 'python' / 'lib' / 'python3.12' / 'site-packages'
        with self.replaced(site / 'uvicorn'):
            result = self.run_host('--start-timeout', '20s')
        self.assertEqual(result.returncode, 4, result.stderr[-600:])
        self.assertIn("ModuleNotFoundError: No module named 'uvicorn'", result.stderr)
        self.assertIn('backend exited with code 12', result.stderr)
        verdict = self.classify(4, result.stderr)
        self.assertIn('ModuleNotFoundError', verdict['Detail'])

    # ---- timeouts before READY ------------------------------------------------------------------------------------------------------------------
    def test_a_start_that_stalls_after_listening_reports_the_stage_and_where_it_is_stuck(self):
        with self.fake_main('import time\n\ndef create_app(**kwargs):\n    time.sleep(120)\n'):
            result = self.run_host('--start-timeout', '7s')
        self.assertEqual(result.returncode, 3, result.stderr[-800:])
        self.assertIn('phase=listening port=', result.stderr)
        self.assertIn('phase=timeout stage=waiting_for_health', result.stderr)
        self.assertIn('exit_code_meaning=3 start timeout', result.stderr)
        self.assertRegex(result.stderr, r'File ".*main\.py", line \d+ in create_app', 'the stack dump must show where the start is stuck')
        verdict = self.classify(3, result.stderr)
        self.assertEqual((verdict['Status'], verdict['Class']), ('FAIL', 'startup_timeout_before_health'))
        self.assertIn('imported_main', verdict['Detail'])
        self.assertGreater(result.elapsed, 6)

    def test_a_start_that_never_reports_listening_is_named_as_such(self):
        python3 = self.runtime / 'python' / 'bin' / 'python3'
        with self.replaced(python3, '#!/bin/sh\nexec sleep 30\n'):
            result = self.run_host('--start-timeout', '3s')
        self.assertEqual(result.returncode, 3, result.stderr[-800:])
        self.assertIn('phase=timeout stage=waiting_for_listening', result.stderr)
        verdict = self.classify(3, result.stderr)
        self.assertEqual(verdict['Class'], 'startup_timeout_before_listening')
        self.assertIn('no phase output', verdict['Detail'])

    # ---- evidence handling -----------------------------------------------------------------------------------------------------------------------
    def test_a_backend_that_prints_the_capability_is_redacted_and_the_failure_is_preserved(self):
        source = ('import os\n\ndef create_app(origin, session_token, **kwargs):\n'
                  '    import sys\n    sys.stderr.write("leaked " + session_token + "\\n")\n'
                  '    open(os.path.join(os.environ["SAP_LENS_POC_DATA"], "leak.txt"), "w").write(session_token)\n'
                  '    raise RuntimeError("boom after leaking")\n')
        with self.fake_main(source):
            result = self.run_host('--start-timeout', '20s')
        self.assertEqual(result.returncode, 4, result.stderr[-600:])
        leaked = (result.data / 'leak.txt').read_text()
        self.assertGreaterEqual(len(leaked), 32)
        self.assertNotIn(leaked, result.stderr + result.stdout, 'the capability must never reach the evidence')
        self.assertIn('<redacted>', result.stderr)
        self.assertIn('RuntimeError: boom after leaking', result.stderr)

    @unittest.skipUnless(PWSH, 'pwsh not available')
    def test_diagnostic_text_protection_removes_profile_names_and_credentials(self):
        command = (f". '{WINDOWS}/Phase1Common.ps1'; $env:USERPROFILE = '/home/someone-private'; "
                   "Protect-DiagnosticText 'path /home/someone-private/x capability=ABCDEFGH12345678 and token: zzz'")
        result = subprocess.run([PWSH, '-NoProfile', '-Command', command], capture_output=True, text=True, timeout=60)
        self.assertNotIn('someone-private', result.stdout)
        self.assertNotIn('ABCDEFGH12345678', result.stdout)
        self.assertIn('%USERPROFILE%', result.stdout)

    # ---- distinction between an App Control block and an application failure ----------------------------------------------------------------------------
    @unittest.skipUnless(PWSH, 'pwsh not available')
    def test_an_enforced_integrity_record_is_blocked_but_the_same_failure_without_one_is_fail(self):
        with self.fake_main('raise ImportError("synthetic import failure")\n'):
            result = self.run_host('--start-timeout', '20s')
        enforced = "@(@{ Id = 3077; Relative = 'python/Lib/site-packages/lxml/etree.pyd'; PolicyId = 'p'; Enforced = $true })"
        audit = "@(@{ Id = 3076; Relative = 'python/python.exe'; PolicyId = 'p'; Enforced = $false })"
        self.assertEqual(self.classify(4, result.stderr, enforced)['Status'], 'BLOCKED')
        self.assertEqual(self.classify(4, result.stderr, audit)['Status'], 'FAIL')
        self.assertEqual(self.classify(4, result.stderr)['Status'], 'FAIL')

    # ---- direct backend probe (the harness's W07a diagnostic) --------------------------------------------------------------------------------------
    def probe(self, runtime):
        data = self.base / f'probe-{time.monotonic_ns()}'
        command = (f". '{WINDOWS}/Phase1Common.ps1'; $d = '{data}'; $e = Get-BackendEnvironment $d 8; "
                   f"$r = Invoke-DirectBackendProbe '{runtime}/python/bin/python3' $d $e 20 25; "
                   "[ordered]@{ listening = $r.ListeningMs; health = $r.HealthMs; exit = $r.ExitCode; started = $r.Started; stderr = $r.Stderr; stdout = $r.Stdout } | ConvertTo-Json -Compress")
        result = subprocess.run([PWSH, '-NoProfile', '-Command', command], capture_output=True, text=True, timeout=120)
        return json.loads(result.stdout.strip().splitlines()[-1])

    @unittest.skipUnless(PWSH, 'pwsh not available')
    def test_direct_probe_starts_the_backend_without_the_host_and_keeps_its_output(self):
        outcome = self.probe(self.runtime)
        self.assertTrue(outcome['started'])
        self.assertIsNotNone(outcome['listening'])
        self.assertIsNotNone(outcome['health'])
        self.assertEqual(outcome['exit'], 0)
        self.assertIn('phase=serving', outcome['stderr'])
        self.assertNotRegex(outcome['stderr'] + outcome['stdout'], r'[A-Za-z0-9_-]{43}.*capability')

    @unittest.skipUnless(PWSH, 'pwsh not available')
    def test_direct_probe_reports_a_backend_that_cannot_start(self):
        with self.replaced(self.runtime / 'app' / 'frontend'):
            outcome = self.probe(self.runtime)
        self.assertIsNone(outcome['health'])
        self.assertIsNone(outcome['listening'])
        self.assertEqual(outcome['exit'], 13)
        self.assertIn('frontend assets are missing', outcome['stderr'])


if __name__ == '__main__':
    unittest.main()
