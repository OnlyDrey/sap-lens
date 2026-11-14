"""Static contracts of scripts/test-windows-exe.ps1 and the root causes behind the Desktop smoke failures. Linux evidence only: the script itself
runs on native Windows."""
import re
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / 'scripts/test-windows-exe.ps1').read_text(encoding='utf-8')


class SmokeScriptContracts(unittest.TestCase):
    def test_every_failure_class_is_distinguished(self):
        for name in ('process_exited_before_readiness', 'runtime_record_missing', 'runtime_not_owned', 'http_unavailable', 'instance_id_mismatch',
                     'health_status_incorrect', 'configuration_required', 'service_identity_incorrect', 'cached_roles_incorrect', 'window_initialization_failed', 'readiness_timeout',
                     'prerequisite_existing_instance', 'instance_not_released', 'process_creation_failed', 'windows_application_control_blocked'):
            self.assertIn(f"'{name}'", SCRIPT, name)

    def test_diagnostics_carry_the_required_facts(self):
        for fact in ('Scenario:', 'Executable:', 'Launcher PID:', 'Runtime PID', 'Launcher exit code', 'Owned processes (parent/child)', 'runtime.json present',
                     'Last health:', '(expected $($state.ExpectedStatus))', '(expected $($state.ExpectedRoles))', 'Process readiness:', 'Last readiness condition', 'Elapsed:', 'Application log (last lines, secrets redacted)'):
            self.assertIn(fact, SCRIPT, fact)
        self.assertIn('<redacted>', SCRIPT)

    def test_single_instance_guard_name_matches_the_application(self):
        import instance_name
        self.assertIn(instance_name.NAME, SCRIPT.replace("'", ''))

    def test_ownership_checks_and_name_based_termination_rules_are_unchanged(self):
        self.assertIn("if (-not $ids.Contains([int]$record.pid))", SCRIPT)
        self.assertNotRegex(SCRIPT, r'(?i)(Stop-Process|taskkill|Get-Process\s+-Name[^|\n]*\|\s*(Stop|Kill))')
        self.assertIn('Never terminate processes by name', SCRIPT)
        self.assertIn('$health.status -ne $contract.Status', SCRIPT)
        self.assertIn('$health.cached_roles -ne $contract.Roles', SCRIPT)
        self.assertIn("$health.app -ne 'sap-lens'", SCRIPT)
        self.assertIn('AddSeconds(60)', SCRIPT, 'the readiness timeout is unchanged')

    def test_application_control_uses_structured_correlated_bounded_evidence(self):
        helper = SCRIPT[SCRIPT.index('function Get-ApplicationControlEvidence'):SCRIPT.index('function Format-DiagnosticsCore')]
        for contract in ('Microsoft-Windows-CodeIntegrity/Operational', 'Id = @(3077, 3033)', 'StartTime = $attemptedAt.AddSeconds(-2)',
                         'EndTime = $failedAt.AddSeconds(2)', '-MaxEvents 128', 'Select-CorrelatedCodeIntegrityEvents',
                         "(Get-PolicyBlockName $code) -or $evidence.Matches.Count -gt 0",
                         'Get-AuthenticodeSignature -LiteralPath $path', 'NoMatchingEventsFound', 'Code Integrity log unavailable'):
            self.assertIn(contract, helper)
        self.assertNotIn('$event.Message', helper)
        self.assertIn('$correlated = @()', helper, 'PowerShell regex matching must not replace the event accumulator via automatic $Matches')
        module = (ROOT / 'scripts/testing/windows-app-control-evidence.ps1').read_text(encoding='utf-8')
        for contract in ('[xml]$xml = $Event.ToXml()', "$fields['filename']", '[System.StringComparison]::OrdinalIgnoreCase', '-notin @(3077, 3033)'):
            self.assertIn(contract, module, contract)
        self.assertNotIn('$Event.Message', module)
        self.assertNotIn('-like', helper[:helper.index('} catch {\n        if ($_.FullyQualifiedErrorId')])
        self.assertIn('QueryDosDevice', SCRIPT, 'NT paths must use an actual drive mapping, not a suffix guess')

    def test_startup_diagnostics_preserve_original_error_and_success_path(self):
        launch = SCRIPT[SCRIPT.index('function Start-Application'):SCRIPT.index('function Get-ScenarioContract')]
        self.assertIn('try { return Start-Process -FilePath $executable -PassThru -ErrorAction Stop }', launch)
        self.assertIn('$original = $_.Exception', launch)
        self.assertIn('New-SmokeException $diagnostic.Class $original.Message $null $original', launch)
        self.assertIn('Get-LaunchNativeErrorCode $original', launch, 'diagnostic failure cannot erase a known policy block')
        self.assertIn('$script:State.LaunchDiagnostics = $diagnostic.Text', launch)
        self.assertIn('foreach ($process in $owned.Values)', SCRIPT, 'a failed start has no handle to clean up')

    def test_fresh_and_configured_scenarios_have_exact_health_contracts(self):
        policy = SCRIPT[SCRIPT.index('function Get-ScenarioContract'):SCRIPT.index('function Wait-Ready')]
        self.assertIn("$scenario -eq 'first-launch'", policy)
        self.assertIn("Status = 'needs_configuration'; Roles = 0", policy)
        self.assertIn("@('configured', 'relaunch', 'port-conflict')", policy)
        self.assertIn("Status = 'ok'; Roles = 2", policy)
        self.assertIn('throw "Unknown smoke scenario:', policy)
        self.assertIn("@('first-launch', 'configured', 'relaunch', 'port-conflict')", SCRIPT)
        self.assertIn("$scenario -in @('configured', 'port-conflict')", SCRIPT)
        self.assertIn("schema_version = 3; data_csv_path = $csvPath; source_modes = @{ roles = 'dynamic' }", SCRIPT)
        self.assertIn("Join-Path $testRoot 'configured'", SCRIPT)

    def test_launch_environment_is_isolated_and_restored(self):
        launch = SCRIPT[SCRIPT.index('function Start-Application'):SCRIPT.index('function Get-ScenarioContract')]
        for name in ('SAP_LENS_CONFIG_DIR', 'SAP_LENS_DATA_DIR', 'SAP_LENS_DEPLOYMENT_MODE', 'DATA_CSV_PATH'):
            self.assertIn('$env:' + name, launch.split('finally')[0])
            self.assertIn('$env:' + name, launch.split('finally')[1])
        self.assertIn("$env:DATA_CSV_PATH = ''", launch)
        self.assertIn("$env:SAP_LENS_DEPLOYMENT_MODE = 'desktop'", launch)
        self.assertIn('$env:SAP_LENS_DATA_DIR = $directory', launch)

    def test_process_readiness_is_required_in_addition_to_configuration(self):
        wait = SCRIPT[SCRIPT.index('function Wait-Ready'):SCRIPT.index('try {\n    $version')]
        self.assertIn('/health/ready', wait)
        self.assertIn("if ($ready.status -eq 'ready')", wait)
        self.assertLess(wait.index("if ($ready.status -eq 'ready')"), wait.index('return $record'))
        self.assertIn("$state.Health.status -eq 'needs_configuration' -and $contract.Status -eq 'ok'", wait)
        self.assertNotIn("$health.status -notin", wait, 'do not accept arbitrary non-error health states')

    def test_configuration_diagnostics_do_not_print_source_values(self):
        helper = SCRIPT[SCRIPT.index('function Get-SmokeConfigurationSummary'):SCRIPT.index('function Format-DiagnosticsCore')]
        self.assertIn("Join-SafePath $directory 'settings.json'", helper)
        self.assertIn('source_configured=$configured; source_exists=$exists; source_mode=$mode', helper)
        self.assertNotIn('$($settings.data_csv_path)', helper)
        self.assertIn('Configuration summary (no values or paths)', SCRIPT)
        for item in ('fixture_path_matches=$fixtureMatches', 'source_readable=$readable', 'source_bytes=$bytes', 'source_read_error=$readError', '$stream.Dispose()'):
            self.assertIn(item, helper)
        summary = SCRIPT[SCRIPT.index('function Get-SmokeLoadSummary'):SCRIPT.index('function Get-LaunchNativeErrorCode')]
        self.assertIn('-Tail 400', summary)
        self.assertIn('csv_failure_seen=$csvFailure', summary)
        self.assertIn('Source initialization/import failed', summary)
        self.assertIn("'unconfigured', 'backup_failed'", summary)
        self.assertIn('stage=$($entry.stage), result=$($entry.result)', summary)
        self.assertNotIn('$entry.error', summary)
        self.assertNotIn('$entry.traceback', summary)

    def test_existing_instance_is_reported_before_any_launch(self):
        self.assertLess(SCRIPT.index("'prerequisite_existing_instance'"), SCRIPT.index("foreach ($scenario in"))

    def test_original_exception_is_preserved_and_windows_powershell_51_syntax_only(self):
        self.assertIn('New-Object System.Exception($message, $inner)', SCRIPT)
        # NT path prefixes and regex quantifiers inside single-quoted literals are not language operators.
        syntax = re.sub(r"'(?:[^']|'')*'", "''", SCRIPT)
        for token in (r'\?\?', r'\?\.', r'-AsHashtable', r'-Parallel', r'\$IsWindows', r'\s&&\s', r'\?\s*\$'):
            self.assertIsNone(re.search(token, syntax), token)


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


POWERSHELL = shutil.which('powershell') or shutil.which('pwsh')


@unittest.skipUnless(POWERSHELL and os.name == 'nt', 'Windows PowerShell unavailable; mocked launch/event behavior uses Windows paths (native EXE acceptance remains separate)')
class LaunchDiagnosticBehavior(unittest.TestCase):
    """Execute the actual functions with mocked OS calls; never launch an EXE or change host policy."""

    def invoke(self, body):
        names = ('Get-LaunchNativeErrorCode', 'Get-DosDeviceName', 'Get-ApplicationControlEvidence', 'Get-LaunchFailureDiagnostic', 'Start-Application')
        module = (ROOT / 'scripts/testing/windows-app-control-evidence.ps1').read_text(encoding='utf-8')
        functions = module + '\n' + '\n'.join(re.search(r'^function ' + re.escape(name) + r'\b.*?(?=^function |\Z)', SCRIPT, re.M | re.S)[0] for name in names)
        setup = r'''
$ErrorActionPreference = 'Stop'
$executable = 'C:\synthetic\SAP-Lens.exe'
$script:State = @{}
function Get-DosDeviceName { param($drive) return '\Device\HarddiskVolume7' }
function Get-AuthenticodeSignature { param($LiteralPath, $ErrorAction) return @{Status='NotSigned'} }
function Get-WinEvent { param($FilterHashtable, $MaxEvents, $ErrorAction) return @() }
function New-SmokeException { param($class, $detail, $application, $inner)
    $failure = New-Object System.Exception($detail, $inner)
    $failure.Data['SmokeClass'] = $class
    return $failure
}
function New-TestEvent { param($file, $id=3077, $time=(Get-Date))
    $row = [pscustomobject]@{Id=$id;TimeCreated=$time;RawXml="<Event><EventData><Data Name='FileName'>$file</Data><Data Name='PolicyID'>{00000000-0000-0000-0000-000000000001}</Data></EventData></Event>"}
    $row | Add-Member -MemberType ScriptMethod -Name ToXml -Value { return $this.RawXml }
    return $row
}
'''
        source = functions + setup + '\n' + body + '\n$result | ConvertTo-Json -Depth 6 -Compress'
        encoded = base64.b64encode(source.encode('utf-16-le')).decode('ascii')
        process = subprocess.run([POWERSHELL, '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                                 capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
        return json.loads(process.stdout.strip().splitlines()[-1])

    def test_success_returns_the_process_and_restores_environment_without_diagnostics(self):
        result = self.invoke(r'''
function Start-Process { param($FilePath, [switch]$PassThru, $ErrorAction) return @{Id=42} }
function Get-LaunchFailureDiagnostic { throw 'must not run on success' }
$env:SAP_LENS_CONFIG_DIR = 'original'
$process = Start-Application 'C:\isolated'
$result = @{Id=$process.Id; Restored=$env:SAP_LENS_CONFIG_DIR; Diagnostics=$script:State.LaunchDiagnostics}
''')
        self.assertEqual(result, {'Id': 42, 'Restored': 'original', 'Diagnostics': None})

    def test_wrapped_policy_failure_keeps_native_code_and_original_exception(self):
        result = self.invoke(r'''
function Start-Process { throw (New-Object System.InvalidOperationException('synthetic outer', (New-Object System.ComponentModel.Win32Exception(1260)))) }
try { Start-Application 'C:\isolated'; throw 'unexpected success' }
catch { $result = @{Class=$_.Exception.Data['SmokeClass']; Inner=$_.Exception.InnerException.Message; Text=$script:State.LaunchDiagnostics} }
''')
        self.assertEqual(result['Class'], 'windows_application_control_blocked')
        self.assertIn('synthetic outer', result['Inner'])
        self.assertIn('native_error_code=1260', result['Text'])
        self.assertIn('Authenticode=NotSigned', result['Text'])
        self.assertIn('executable_started=False', result['Text'])

    def test_missing_event_log_never_erases_native_policy_error(self):
        result = self.invoke(r'''
function Get-WinEvent { throw (New-Object System.UnauthorizedAccessException('synthetic denied')) }
$result = Get-LaunchFailureDiagnostic (New-Object System.ComponentModel.Win32Exception(1260)) $executable (Get-Date) (Get-Date)
''')
        self.assertEqual(result['Class'], 'windows_application_control_blocked')
        self.assertIn('Code Integrity log unavailable', result['Text'])

    def test_system_integrity_policy_violation_code_is_a_block_and_records_the_verdict(self):
        result = self.invoke(r'''
$r = Get-LaunchFailureDiagnostic (New-Object System.ComponentModel.Win32Exception(4551)) $executable (Get-Date) (Get-Date)
$result = @{Class=$r.Class; Text=$r.Text; Status=$script:LaunchEvidence.status; Reason=$script:LaunchEvidence.reason; Started=$script:LaunchEvidence.executable_started}
''')
        self.assertEqual((result['Class'], result['Status'], result['Reason'], result['Started']), ('windows_application_control_blocked', 'blocked', 'environment_policy_blocked', False))
        self.assertIn('NATIVE ACCEPTANCE BLOCKED [environment_policy_blocked]', result['Text'])

    def test_unsigned_executable_with_a_generic_creation_error_stays_a_failure(self):
        result = self.invoke(r'''
$r = Get-LaunchFailureDiagnostic (New-Object System.ComponentModel.Win32Exception(2)) $executable (Get-Date) (Get-Date)
$result = @{Class=$r.Class; Status=$script:LaunchEvidence.status}
''')
        self.assertEqual(result, {'Class': 'process_creation_failed', 'Status': 'failed'})

    def test_correlated_device_path_and_policy_id_classify_localized_error(self):
        result = self.invoke(r'''
function Get-WinEvent { return @(New-TestEvent '\Device\HarddiskVolume7\synthetic\SAP-Lens.exe') }
$result = Get-LaunchFailureDiagnostic (New-Object System.Exception('localized launch error')) $executable (Get-Date) (Get-Date)
''')
        self.assertEqual(result['Class'], 'windows_application_control_blocked')
        self.assertIn('event_id=3077', result['Text'])
        self.assertIn('policy_id={00000000-0000-0000-0000-000000000001}', result['Text'])

    def test_unrelated_old_and_audit_only_events_do_not_classify_unsigned_file_as_blocked(self):
        result = self.invoke(r'''
function Get-WinEvent { return @(
    (New-TestEvent 'C:\other\SAP-Lens.exe'),
    (New-TestEvent '\Device\HarddiskVolume8\synthetic\SAP-Lens.exe'),
    (New-TestEvent 'C:\synthetic\SAP-Lens.exe' 3077 (Get-Date).AddMinutes(-1)),
    (New-TestEvent 'C:\synthetic\SAP-Lens.exe' 3076)
) }
$result = Get-LaunchFailureDiagnostic (New-Object System.ComponentModel.Win32Exception(577)) $executable (Get-Date) (Get-Date)
''')
        self.assertEqual(result['Class'], 'process_creation_failed')
        self.assertIn('No correlated blocking events found', result['Text'])
        self.assertIn('Authenticode=NotSigned', result['Text'])

    def test_diagnostic_failure_preserves_original_policy_error_without_a_process(self):
        result = self.invoke(r'''
function Start-Process { throw (New-Object System.ComponentModel.Win32Exception(1260, 'original launch failure')) }
function Get-LaunchFailureDiagnostic { throw 'secondary diagnostic failure' }
$owned = @{}
try { $process = Start-Application 'C:\isolated'; $owned[$process.Id] = $process }
catch { $result = @{Class=$_.Exception.Data['SmokeClass']; Inner=$_.Exception.InnerException.Message; Owned=$owned.Count} }
''')
        self.assertEqual(result, {'Class': 'windows_application_control_blocked', 'Inner': 'original launch failure', 'Owned': 0})


if __name__ == '__main__':
    unittest.main()
