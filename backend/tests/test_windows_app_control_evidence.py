"""Windows App Control evidence logic, executed with PowerShell against synthetic Code Integrity events (no policy is touched, no EXE is run).
Runs wherever pwsh exists; native acceptance on a policy-enforced Windows host remains a separate, unexecuted check."""
import json
import sys
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
MODULE = ROOT / 'scripts/testing/windows-app-control-evidence.ps1'
POWERSHELL = shutil.which('pwsh')
EXPECTED = r'C:\synthetic\SAP-Lens.exe'
POLICY = '{0283ac0f-fff1-49ae-ada1-8a933130cad6}'


@unittest.skipUnless(POWERSHELL, 'PowerShell (pwsh) is required')
class EvidenceFunctions(unittest.TestCase):
    def run_ps(self, body):
        script = f". '{str(MODULE).replace(chr(39), chr(39) * 2)}'\n" + r'''
$now = Get-Date
function New-Event($id, $file, $offset = 0, $fileField = 'File Name', $policyField = 'PolicyID', $policy = '{0283ac0f-fff1-49ae-ada1-8a933130cad6}') {
    $xml = "<Event><EventData><Data Name='$fileField'>$file</Data><Data Name='Process Name'>\Device\HarddiskVolume3\Windows\System32\WindowsPowerShell\v1.0\powershell.exe</Data><Data Name='$policyField'>$policy</Data></EventData></Event>"
    $row = [pscustomobject]@{ Id = $id; TimeCreated = $now.AddSeconds($offset); RawXml = $xml }
    $row | Add-Member -MemberType ScriptMethod -Name ToXml -Value { return $this.RawXml }
    return $row
}
$expected = 'C:\synthetic\SAP-Lens.exe'
$from = $now.AddSeconds(-2); $to = $now.AddSeconds(2)
''' + body + '\n$result | ConvertTo-Json -Depth 8 -Compress'
        done = subprocess.run([POWERSHELL, '-NoProfile', '-NonInteractive', '-Command', script], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        return json.loads(done.stdout.strip().splitlines()[-1])

    def test_3077_with_spaced_field_names_is_correlated_with_its_policy_id(self):
        result = self.run_ps(r'''$selected = Select-CorrelatedCodeIntegrityEvents @(New-Event 3077 $expected) $expected $null $from $to
$result = @{ n = @($selected.Records).Count; id = $selected.Records[0].Id; policy = $selected.Records[0].PolicyId; kind = $selected.Records[0].Correlation }''')
        self.assertEqual((result['n'], result['id'], result['policy'], result['kind']), (1, 3077, POLICY, 'exact_path'))

    def test_3033_is_diagnosed_and_unspaced_field_names_are_accepted(self):
        result = self.run_ps(r'''$selected = Select-CorrelatedCodeIntegrityEvents @(New-Event 3033 $expected 0 'FileName' 'PolicyGUID') $expected $null $from $to
$result = @{ ids = @($selected.Records | ForEach-Object { $_.Id }); policy = $selected.Records[0].PolicyId }''')
        self.assertEqual((result['ids'], result['policy']), ([3033], POLICY))

    def test_nt_device_path_is_matched_with_or_without_a_drive_mapping(self):
        result = self.run_ps(r'''$device = '\Device\HarddiskVolume7\synthetic\SAP-Lens.exe'
$mapped = Select-CorrelatedCodeIntegrityEvents @(New-Event 3077 $device) $expected '\Device\HarddiskVolume7' $from $to
$mappedKind = $mapped.Records[0].Correlation
$mapped = Select-CorrelatedCodeIntegrityEvents @(New-Event 3077 $device) $expected '\Device\HarddiskVolume7\synthetic\SAP-Lens.exe' $from $to
$fallback = Select-CorrelatedCodeIntegrityEvents @(New-Event 3077 $device) $expected $null $from $to
$prefixed = Select-CorrelatedCodeIntegrityEvents @(New-Event 3077 '\??\C:\synthetic\SAP-Lens.exe') $expected $null $from $to
$result = @{ mapped = $mapped.Records[0].Correlation; fallback = $fallback.Records[0].Correlation; prefixed = $prefixed.Records[0].Correlation }''')
        self.assertEqual(result, {'mapped': 'device_path', 'fallback': 'volume_relative_path', 'prefixed': 'exact_path'})

    def test_unrelated_old_audit_and_basename_only_events_are_not_correlated(self):
        result = self.run_ps(r'''$events = @(
  (New-Event 3077 'C:\other\SAP-Lens.exe'),                                       # same file name, another path
  (New-Event 3077 '\Device\HarddiskVolume7\other\SAP-Lens.exe'),                  # another path below a volume device
  (New-Event 3077 $expected -60),                                                  # outside the bounded window
  (New-Event 3077 $expected 60),
  (New-Event 3076 $expected),                                                      # audit-only event, not a block
  (New-Event 3077 'C:\synthetic\sub\SAP-Lens.exe'))
$selected = Select-CorrelatedCodeIntegrityEvents $events $expected $null $from $to
$result = @{ n = @($selected.Records).Count }''')
        self.assertEqual(result['n'], 0)

    def test_unparseable_events_become_limitations_not_failures(self):
        result = self.run_ps(r'''$bad = [pscustomobject]@{ Id = 3077; TimeCreated = $now }
$bad | Add-Member -MemberType ScriptMethod -Name ToXml -Value { return '<not xml' }
$selected = Select-CorrelatedCodeIntegrityEvents @($bad, (New-Event 3077 $expected)) $expected $null $from $to
$result = @{ n = @($selected.Records).Count; limitations = @($selected.Limitations) }''')
        self.assertEqual(result['n'], 1)
        self.assertEqual(len(result['limitations']), 1)
        self.assertRegex(result['limitations'][0], r'could not be parsed')

    def test_only_documented_policy_codes_are_proof_and_unsigned_is_not(self):
        result = self.run_ps(r'''$result = @{ a = (Get-PolicyBlockName 1260); b = (Get-PolicyBlockName 4551); c = (Get-PolicyBlockName 577); d = (Get-PolicyBlockName $null); e = (Get-PolicyBlockName 5) }''')
        self.assertEqual(result, {'a': 'ERROR_ACCESS_DISABLED_BY_POLICY', 'b': 'ERROR_SYSTEM_INTEGRITY_POLICY_VIOLATION', 'c': None, 'd': None, 'e': None})

    def test_verdict_separates_blocked_from_failed(self):
        result = self.run_ps(r'''$result = @{ blocked = (Get-NativeSmokeVerdict 'windows_application_control_blocked'); started = (Get-NativeSmokeVerdict 'http_unavailable'); creation = (Get-NativeSmokeVerdict 'process_creation_failed'); timeout = (Get-NativeSmokeVerdict 'readiness_timeout') }''')
        self.assertEqual(result['blocked'], {'Status': 'blocked', 'Reason': 'environment_policy_blocked'})
        for name, reason in (('started', 'http_unavailable'), ('creation', 'process_creation_failed'), ('timeout', 'readiness_timeout')):
            self.assertEqual(result[name], {'Status': 'failed', 'Reason': reason})

    def test_result_file_has_a_stable_schema_and_never_throws_on_a_bad_path(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'nested' / 'result.json'
            self.run_ps(f"""Write-NativeResult '{target}' @{{ kind = 'windows-native-smoke'; status = 'blocked'; reason = 'environment_policy_blocked'; executable = 'SAP-Lens.exe'; executable_started = $false; native_error_code = 4551 }}
Write-NativeResult '/proc/definitely/not/writable/result.json' @{{ status = 'failed' }}
$result = @{{ ok = $true }}""")
            written = json.loads(target.read_text(encoding='utf-8'))
        self.assertEqual((written['schema'], written['status'], written['reason'], written['executable_started'], written['native_error_code']), (1, 'blocked', 'environment_policy_blocked', False, 4551))
        self.assertNotRegex(json.dumps(written), r'(?i)token|password|secret|\\Users\\')


class SmokeScriptWiring(unittest.TestCase):
    SCRIPT = (ROOT / 'scripts/test-windows-exe.ps1').read_text(encoding='utf-8')

    def test_the_smoke_script_uses_the_shared_evidence_module_and_writes_one_result(self):
        self.assertIn("'testing/windows-app-control-evidence.ps1'", self.SCRIPT)
        for contract in ("[string]$ResultPath='backend/build/native-smoke-result.json'", 'Select-CorrelatedCodeIntegrityEvents', 'Get-NativeSmokeVerdict',
                         "status = 'passed'", 'Write-NativeResult $ResultPath', '(Get-PolicyBlockName $code) -or $evidence.Matches.Count -gt 0',
                         'NATIVE ACCEPTANCE BLOCKED [environment_policy_blocked]'):
            self.assertIn(contract, self.SCRIPT, contract)
        self.assertIsNone(re.search(r'\$event\.Message', self.SCRIPT), 'events are read by structured fields, never by message text')

    def test_a_blocked_run_still_throws_so_the_build_cannot_report_success(self):
        catch = self.SCRIPT[self.SCRIPT.index('} catch {\n    # One machine-readable result per run'):self.SCRIPT.index('} finally {\n    # Never terminate processes by name')]
        self.assertTrue(catch.rstrip().endswith('throw'), catch[-80:])


@unittest.skipUnless(POWERSHELL, 'PowerShell (pwsh) is required')
class InstallerEvidenceFunctions(EvidenceFunctions):
    """Reuses the synthetic-event harness for the installer-specific correlation and log sanitising."""

    def test_installer_temp_payload_is_correlated_only_when_asked_and_only_for_the_exact_shape(self):
        result = self.run_ps(r'''$temp = '\Device\HarddiskVolume3\Users\x\AppData\Local\Temp\is-AB12C.tmp\SAP-Lens.exe'
$off = Select-CorrelatedCodeIntegrityEvents @(New-Event 3077 $temp) 'C:\work\Setup.exe' $null $from $to
$on = Select-CorrelatedCodeIntegrityEvents @(New-Event 3077 $temp) 'C:\work\Setup.exe' $null $from $to -InstallerTempPayload
$other = Select-CorrelatedCodeIntegrityEvents @((New-Event 3077 '\Device\HarddiskVolume3\Users\x\AppData\Local\Temp\other\SAP-Lens.exe'), (New-Event 3077 '\Device\HarddiskVolume3\Users\x\AppData\Local\Temp\is-AB12C.tmp\Other.exe')) 'C:\work\Setup.exe' $null $from $to -InstallerTempPayload
$setup = Select-CorrelatedCodeIntegrityEvents @(New-Event 3033 'C:\work\Setup.exe') 'C:\work\Setup.exe' $null $from $to -InstallerTempPayload
$result = @{ off = @($off.Records).Count; on = @($on.Records).Count; kind = $on.Records[0].Correlation; other = @($other.Records).Count; setup = $setup.Records[0].Correlation }''')
        self.assertEqual(result, {'off': 0, 'on': 1, 'kind': 'installer_temp_payload_pattern', 'other': 0, 'setup': 'exact_path'})

    def test_setup_log_tail_is_bounded_abbreviated_and_redacted(self):
        result = self.run_ps(r'''$lines = @('first') + (1..40 | ForEach-Object { "line $_ in C:\Users\someone\AppData\Local\Programs token=abc123 and a very long tail " + ('x' * 400) })
$tail = ConvertTo-SafeLogTail $lines @{ 'C:\Users\someone' = '%USERPROFILE%' } 25 240
$result = @{ n = @($tail).Count; first = $tail[0]; maxlen = (($tail | ForEach-Object { $_.Length } | Measure-Object -Maximum).Maximum) }''')
        self.assertEqual(result['n'], 25)
        self.assertIn('%USERPROFILE%', result['first'])
        self.assertNotIn('someone', result['first'])
        self.assertNotIn('abc123', result['first'])
        self.assertIn('token=<redacted>', result['first'])
        self.assertLessEqual(result['maxlen'], 243)


class InstallerHarnessContracts(unittest.TestCase):
    HARNESS = (ROOT / 'scripts/test-desktop-installer.ps1').read_text(encoding='utf-8')
    INSTALLER = (ROOT / 'deploy/windows/desktop-installer.iss').read_text(encoding='utf-8')

    def test_the_harness_proves_the_missing_key_refusal_before_the_first_installation(self):
        text = self.HARNESS
        refusal, provision, first = (text.index(f"$stage='{name}'") for name in ('refusal without a protected backup key', 'provision isolated backup key', 'first isolated installation'))
        self.assertLess(refusal, provision); self.assertLess(provision, first)
        body = text[text.index('function Assert-InstallRefusedWithoutKey'):text.index('function Uninstall-TestPackage')]
        for contract in ("check-backup-key --data $plan.data", 'a backup key is already configured', '$process.ExitCode -eq 0', "Join-Path $plan.application 'SAP-Lens.exe'",
                         '-ne $before', "-Filter '*.tar.gz'", "Invoke-Plan 'unregistered'", "Invoke-Plan 'verify-production'", 'NATIVE ACCEPTANCE BLOCKED [environment_policy_blocked]'):
            self.assertIn(contract, body, contract)
        self.assertLess(body.index('Get-InstallerBlockEvidence'), body.index('$process.ExitCode -eq 0'), 'a policy block must be recognised before the refusal is accepted')

    def test_the_isolated_key_lives_outside_the_data_directory_and_is_restored_afterwards(self):
        self.assertIn("$keyDirectory=Join-Path $plan.root 'keys'", self.HARNESS)
        self.assertIn("init-backup-key --data $plan.data --output $keyFile", self.HARNESS)
        self.assertIn("'SAP_LENS_BACKUP_KEY_FILE'", self.HARNESS.split('$names=@(')[1].split(')')[0])
        self.assertNotRegex(self.HARNESS, r'(?i)plaintext|--allow-unencrypted|encryption.{0,20}(off|disabled)')

    def test_the_installer_checks_the_key_first_and_never_falls_back_or_skips_the_backup(self):
        text = self.INSTALLER
        check, backup = text.index('--maintenance check-backup-key --data'), text.index('--maintenance backup --mode desktop --allow-legacy')
        self.assertLess(check, backup)
        self.assertLess(text.index('if DirExists(DataDirectory) and HasFiles(DataDirectory) then begin'), check)
        self.assertIn('Nothing was installed or changed and your data is intact.', text)
        self.assertIn('never skips this backup and never creates an unencrypted one', text)
        self.assertNotIn('--secret', text.replace('--secret-stdin', ''))

    def test_failures_and_blocks_never_publish_the_success_receipt(self):
        text = self.HARNESS
        failure = text[text.index('if ($primary -or $cleanupErrors.Count -or -not $completed) {'):text.index('$identity=$plan.identity')]
        self.assertIn('native-installer-result.json', failure)
        self.assertTrue(failure.rstrip().endswith('}'))
        self.assertIn('throw $message', failure)
        self.assertLess(text.index('native-installer-result.json'), text.index("$result=@{schema=1;identity=$identity"))
        self.assertIn("-Filter '*.tar.gz'", text)


class BackupCommandContract(unittest.TestCase):
    """The exact command the installer runs, against a throw-away directory (never a real installation or data): fail closed without a key,
    encrypted with one, and existing data untouched either way."""

    def run_cli(self, directory, *arguments, key=None):
        import os
        env = {key_: value for key_, value in os.environ.items() if key_ != 'SAP_LENS_BACKUP_KEY_FILE'}
        env['SAP_LENS_CONFIG_DIR'] = str(Path(directory) / 'data')
        if key: env['SAP_LENS_BACKUP_KEY_FILE'] = str(key)
        return subprocess.run([sys.executable, str(ROOT / 'backend/maintenance.py'), *arguments], capture_output=True, text=True, env=env, timeout=60)

    def test_without_a_key_the_check_and_the_backup_fail_closed_and_data_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / 'data'; data.mkdir(); (Path(directory) / 'backups').mkdir()
            (data / 'settings.json').write_text('{"schema_version":3,"data_csv_path":""}', encoding='utf-8')
            before = sorted(path.name for path in data.iterdir())
            self.assertNotEqual(self.run_cli(directory, 'check-backup-key', '--data', str(data)).returncode, 0)
            from version import VERSION
            done = self.run_cli(directory, 'backup', '--mode', 'desktop', '--allow-legacy', '--data', str(data), '--output', str(Path(directory) / 'backups' / 'x.tar.gz'), '--application-version', VERSION)
            self.assertNotEqual(done.returncode, 0)
            self.assertIn('BackupCryptoError', done.stdout + done.stderr)
            self.assertEqual(list((Path(directory) / 'backups').iterdir()), [], 'no plaintext fallback archive')
            self.assertEqual(sorted(path.name for path in data.iterdir()), before)
            self.assertEqual((data / 'settings.json').read_text(encoding='utf-8'), '{"schema_version":3,"data_csv_path":""}')

    def test_with_a_key_outside_the_data_directory_the_backup_succeeds_and_is_encrypted(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / 'data'; data.mkdir(); (Path(directory) / 'backups').mkdir(); keys = Path(directory) / 'keys'; keys.mkdir()
            content = '{"schema_version":3,"data_csv_path":""}'
            (data / 'settings.json').write_text(content, encoding='utf-8')
            key = keys / 'backup.key'
            self.assertEqual(self.run_cli(directory, 'init-backup-key', '--data', str(data), '--output', str(key)).returncode, 0)
            self.assertEqual(self.run_cli(directory, 'check-backup-key', '--data', str(data), key=key).returncode, 0)
            from version import VERSION
            archive = Path(directory) / 'backups' / 'x.tar.gz'
            done = self.run_cli(directory, 'backup', '--mode', 'desktop', '--allow-legacy', '--data', str(data), '--output', str(archive), '--application-version', VERSION, key=key)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertTrue(archive.is_file())
            self.assertNotIn(b'schema_version', archive.read_bytes(), 'the archive must not contain plaintext settings')
            self.assertNotIn(b'data_csv_path', archive.read_bytes())
            self.assertEqual((data / 'settings.json').read_text(encoding='utf-8'), content)


if __name__ == '__main__':
    unittest.main()
