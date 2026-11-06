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


class DiagnosticsAreSafeWithPartialState(unittest.TestCase):
    """Regression for the hotfix after 8b23e2e: the failure reporter called `Join-Path $state.Directory ...` while the state was still empty (the
    existing-instance preflight runs before any scenario directory exists) and Windows PowerShell 5.1 raised a binding error that masked the real failure.
    The script cannot run on Linux, so these are structural contracts; native execution stays unverified until run on Windows."""

    def test_no_state_value_reaches_join_path_directly(self):
        for number, line in enumerate(SCRIPT.splitlines(), 1):
            self.assertNotRegex(line, r'Join-Path\s+\$(script:)?state\.', f'line {number}: {line.strip()}')
        self.assertNotRegex(SCRIPT, r'Join-Path\s+\$state\.Directory')

    def test_a_safe_join_returns_null_for_missing_or_blank_directories(self):
        helper = SCRIPT[SCRIPT.index('function Join-SafePath'):SCRIPT.index('function Get-SafeLogTail')]
        self.assertIn('[string]::IsNullOrWhiteSpace([string]$directory)', helper)
        self.assertIn('return $null', helper)
        self.assertLess(helper.index('IsNullOrWhiteSpace'), helper.index('return (Join-Path'))

    def test_every_diagnostic_path_goes_through_the_safe_helpers(self):
        core = SCRIPT[SCRIPT.index('function Format-DiagnosticsCore'):SCRIPT.index('function Format-Diagnostics(')]
        self.assertIn("Join-SafePath $state.Directory 'runtime.json'", core)
        self.assertIn('Get-SafeLogTail $state.Directory', core)
        self.assertIn('n/a (no scenario directory)', core)
        tail = SCRIPT[SCRIPT.index('function Get-SafeLogTail'):SCRIPT.index('function Format-DiagnosticsCore')]
        self.assertIn('Join-SafePath $directory', tail)
        self.assertIn('no scenario directory yet', tail)

    def test_the_reporter_can_never_replace_the_original_failure(self):
        wrapper = SCRIPT[SCRIPT.index('function Format-Diagnostics('):SCRIPT.index('function New-SmokeException')]
        self.assertIn('try { return (Format-DiagnosticsCore', wrapper)
        self.assertIn('catch {', wrapper)
        self.assertIn('SMOKE FAILURE [$class] $detail', wrapper, 'the class and detail survive a reporter failure')
        self.assertIn('Format-Diagnostics $class $detail $application', SCRIPT[SCRIPT.index('function New-SmokeException'):])

    def test_state_is_initialised_before_any_operation_that_can_fail(self):
        self.assertLess(SCRIPT.index('$script:State = @{'), SCRIPT.index('function Test-InstanceHeld'))
        initial = SCRIPT[SCRIPT.index('$script:State = @{'):SCRIPT.index('\n', SCRIPT.index('$script:State = @{'))]
        for key in ('Scenario', 'Directory', 'Launcher', 'Runtime', 'Condition', 'Health', 'HttpError', 'RecordSeen', 'OwnedSeen'):
            self.assertIn(key + ' =', initial, key)
        self.assertLess(SCRIPT.index("'prerequisite_existing_instance'"), SCRIPT.index("foreach ($scenario in"), 'preflight runs with the initial, empty state')

    def test_process_exit_and_timeout_paths_use_the_scenario_directory_parameter(self):
        wait = SCRIPT[SCRIPT.index('function Wait-Ready'):SCRIPT.index('try {\n    $version')]
        self.assertIn("Join-Path $directory 'runtime.json'", wait)
        for name in ("'process_exited_before_readiness'", "'readiness_timeout'", "'runtime_record_missing'", "'http_unavailable'"):
            self.assertIn(name, wait)
        self.assertIn('$application = $null', SCRIPT, 'a failed launch cannot reuse the previous scenario process')


class PackagedPathContract(unittest.TestCase):
    def test_the_smoke_test_launches_with_a_minimal_path_so_the_application_must_not_rely_on_path(self):
        self.assertIn('$env:PATH = "$env:SystemRoot\\System32;$env:SystemRoot"', SCRIPT)
        for name in ('maintenance.py', 'application_backups.py'):
            text = (ROOT / 'backend' / name).read_text(encoding='utf-8')
            self.assertNotIn("['powershell'", text, name)


if __name__ == '__main__':
    unittest.main()
