"""Static contracts of scripts/test-windows-exe.ps1 and the root causes behind the Desktop smoke failures. Linux evidence only: the script itself
runs on native Windows."""
import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / 'scripts/test-windows-exe.ps1').read_text(encoding='utf-8')


class SmokeScriptContracts(unittest.TestCase):
    def test_every_failure_class_is_distinguished(self):
        for name in ('process_exited_before_readiness', 'runtime_record_missing', 'runtime_not_owned', 'http_unavailable', 'instance_id_mismatch',
                     'health_status_incorrect', 'cached_roles_incorrect', 'window_initialization_failed', 'readiness_timeout',
                     'prerequisite_existing_instance', 'instance_not_released'):
            self.assertIn(f"'{name}'", SCRIPT, name)

    def test_diagnostics_carry_the_required_facts(self):
        for fact in ('Scenario:', 'Executable:', 'Launcher PID:', 'Runtime PID', 'Launcher exit code', 'Owned processes (parent/child)', 'runtime.json present',
                     'Last health:', '(expected ok)', '(expected 2)', 'Last readiness condition', 'Elapsed:', 'Application log (last lines, secrets redacted)'):
            self.assertIn(fact, SCRIPT, fact)
        self.assertIn('<redacted>', SCRIPT)

    def test_single_instance_guard_name_matches_the_application(self):
        import instance_name
        self.assertIn(instance_name.NAME, SCRIPT.replace("'", ''))

    def test_ownership_checks_and_name_based_termination_rules_are_unchanged(self):
        self.assertIn("if (-not $ids.Contains([int]$record.pid))", SCRIPT)
        self.assertNotRegex(SCRIPT, r'(?i)(Stop-Process|taskkill|Get-Process\s+-Name[^|\n]*\|\s*(Stop|Kill))')
        self.assertIn('Never terminate processes by name', SCRIPT)
        self.assertIn("$health.status -ne 'ok'", SCRIPT)
        self.assertIn('cached_roles -ne 2', SCRIPT)
        self.assertIn('AddSeconds(60)', SCRIPT, 'the readiness timeout is unchanged')

    def test_existing_instance_is_reported_before_any_launch(self):
        self.assertLess(SCRIPT.index("'prerequisite_existing_instance'"), SCRIPT.index("foreach ($scenario in"))

    def test_original_exception_is_preserved_and_windows_powershell_51_syntax_only(self):
        self.assertIn('New-Object System.Exception($message, $inner)', SCRIPT)
        for token in (r'\?\?', r'\?\.', r'-AsHashtable', r'-Parallel', r'\$IsWindows', r'\s&&\s', r'\?\s*\$'):
            self.assertIsNone(re.search(token, SCRIPT), token)


class PackagedPathContract(unittest.TestCase):
    def test_the_smoke_test_launches_with_a_minimal_path_so_the_application_must_not_rely_on_path(self):
        self.assertIn('$env:PATH = "$env:SystemRoot\\System32;$env:SystemRoot"', SCRIPT)
        for name in ('maintenance.py', 'application_backups.py'):
            text = (ROOT / 'backend' / name).read_text(encoding='utf-8')
            self.assertNotIn("['powershell'", text, name)


if __name__ == '__main__':
    unittest.main()
