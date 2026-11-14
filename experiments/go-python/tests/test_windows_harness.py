"""Static and logic checks of the Windows harness on any platform with PowerShell (pwsh). Windows execution itself is NOT covered here."""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / 'windows'
SCRIPTS = sorted(WINDOWS.glob('*.ps1'))
PWSH = shutil.which('pwsh')

# Anything that could change policy, security settings, services, registry or installations. The harness must stay read-mostly and isolated.
FORBIDDEN = [r'Set-ExecutionPolicy', r'-ExecutionPolicy\s+Bypass', r'Set-MpPreference', r'Add-MpPreference', r'Remove-MpPreference', r'CiTool(\.exe)?["\']?\s+--(update|remove|set|enable|disable)',
             r'\bbcdedit\b', r'\breg(\.exe)?\s+(add|delete|import)\b', r'New-Service', r'Set-Service', r'Stop-Service', r'Start-Service', r'\bsc(\.exe)?\s+(create|config|delete|stop)\b',
             r'Set-ItemProperty\s+[^\n]*HK(LM|CU)', r'New-ItemProperty', r'Remove-ItemProperty', r'HKLM:', r'HKCU:', r'Invoke-Expression', r'\biex\b', r'Add-AppxPackage',
             r'msiexec', r'RunAs', r'netsh', r'Disable-', r'Unblock-File', r'Add-Type\s+-TypeDefinition', r'DownloadString', r'DownloadFile', r'Invoke-WebRequest\s+[^\n]*https?://[^l]']


class Static(unittest.TestCase):
    def test_scripts_exist(self):
        self.assertEqual({p.name for p in SCRIPTS}, {'Phase1Common.ps1', 'Test-Phase1Logic.ps1', 'Test-WindowsFeasibility.ps1', 'Get-AppControlDiagnostics.ps1'})

    def test_no_forbidden_operations(self):
        for script in SCRIPTS:
            text = '\n'.join(line for line in script.read_text(encoding='utf-8').splitlines() if not line.lstrip().startswith('#'))
            for pattern in FORBIDDEN:
                self.assertIsNone(re.search(pattern, text, re.IGNORECASE), f'{script.name}: {pattern}')

    def test_no_non_ascii_and_no_em_dash(self):
        for script in SCRIPTS:
            data = script.read_bytes()
            self.assertNotIn(b'\xe2\x80\x94', data, script.name)
            data.decode('ascii')  # Windows PowerShell 5.1 reads BOM-less files as ANSI; stay ASCII

    def test_only_isolated_writes(self):
        text = (WINDOWS / 'Test-WindowsFeasibility.ps1').read_text()
        self.assertIn("'SAP Lens'", text)  # refuses inputs inside an SAP Lens installation or data directory
        self.assertIn("Contains('saplens-poc-')", text)  # cleanup only ever removes its own temp identity folder

    def test_wrong_capability_check_uses_the_real_header(self):
        text = (WINDOWS / 'Test-WindowsFeasibility.ps1').read_text()
        self.assertIn("'X-SAP-Lens'", text)
        self.assertNotIn('X-SAP-Lens-Session', text)


@unittest.skipUnless(PWSH, 'pwsh not available')
class Powershell(unittest.TestCase):
    def test_parse(self):
        for script in SCRIPTS:
            command = f"$e=$null;[void][System.Management.Automation.Language.Parser]::ParseFile('{script}',[ref]$null,[ref]$e);exit $e.Count"
            self.assertEqual(subprocess.run([PWSH, '-NoProfile', '-Command', command], capture_output=True, timeout=60).returncode, 0, script.name)

    def test_logic_self_test(self):
        result = subprocess.run([PWSH, '-NoProfile', '-File', str(WINDOWS / 'Test-Phase1Logic.ps1')], capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout[-800:])

    def test_non_windows_run_reports_not_executed_for_every_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([PWSH, '-NoProfile', '-File', str(WINDOWS / 'Test-WindowsFeasibility.ps1'), '-HostExe', '/bin/true', '-RuntimeDir', tmp, '-OutDir', tmp + '/out'],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 3)
            report = json.loads(Path(tmp, 'out', 'phase1-windows-result.json').read_text())
            self.assertEqual(report['overall'], 'NOT EXECUTED')
            self.assertEqual(report['platform'], 'not-windows')
            self.assertEqual({s['status'] for s in report['stages']}, {'NOT EXECUTED'})
            self.assertEqual(len(report['stages']), 14)

    def test_diagnostics_not_executed_off_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([PWSH, '-NoProfile', '-File', str(WINDOWS / 'Get-AppControlDiagnostics.ps1'), '-RuntimeDir', tmp], capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 3)


if __name__ == '__main__':
    unittest.main()
