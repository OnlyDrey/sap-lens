"""Windows packaging is separate from the privileged native service (SCM) acceptance: orchestration, manifest and prerequisite contracts.
Static and orchestration evidence only; the native acceptance itself is reported separately."""
import hashlib
import base64
import os
import shutil
import subprocess
import zipfile
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_system import failures  # noqa: E402


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_') + '_split', next((ROOT / 'scripts').rglob(name + '.py')))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load('build-deployments')


class ManifestSemantics(unittest.TestCase):
    def test_service_without_acceptance_is_a_valid_package_but_not_release_evidence(self):
        row = dict(runtime_smoke_tested=False, native_acceptance=dict(status='not_run'))
        self.assertTrue(builder.smoke_evidence('service', row, release=False))
        self.assertFalse(builder.smoke_evidence('service', row, release=True))
        self.assertFalse(builder.smoke_evidence('desktop', row, release=False), 'only the service may omit the SCM acceptance')
        self.assertTrue(builder.smoke_evidence('service', dict(runtime_smoke_tested=True, native_acceptance=dict(status='passed')), release=True))
        self.assertFalse(builder.smoke_evidence('service', dict(runtime_smoke_tested=False, native_acceptance=dict(status='blocked')), release=False))

    def test_verify_outputs_reads_the_split_evidence_from_the_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            name = 'sap-lens-' + builder.STEMS['service'][0] + '-v1.0.0' + builder.STEMS['service'][1]
            (directory / name).write_bytes(b'payload')
            digest = hashlib.sha256(b'payload').hexdigest()
            (directory / (name + '.sha256')).write_text(digest + '  ' + name + '\n')
            row = dict(status='passed', artifact=name, sha256=digest, built=True, package_verified=True, runtime_smoke_tested=False, native_acceptance=dict(status='not_run'))
            (directory / 'build-manifest.json').write_text(json.dumps(dict(version='1.0.0', source_commit='a' * 40, targets=dict(service=row))))
            builder.verify_outputs(directory, '1.0.0', 'a' * 40, ['service'])
            with self.assertRaisesRegex(ValueError, 'differs'):
                builder.verify_outputs(directory, '1.0.0', 'a' * 40, ['service'], release=True)

    def test_later_scm_receipt_binds_exact_zip_without_rewriting_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);version='1.0.0';source='a'*40
            package=directory/'sap-lens-win-service-x64-v1.0.0.zip';package.write_bytes(b'synthetic')
            digest=hashlib.sha256(package.read_bytes()).hexdigest()
            package.with_name(package.name+'.sha256').write_text(digest+'  '+package.name+'\n')
            manifest=directory/'build-manifest.json'
            manifest.write_text(json.dumps(dict(version=version,source_commit=source,targets=dict(service=dict(status='passed',artifact=package.name,sha256=digest,package_verified=True,runtime_smoke_tested=False,native_acceptance=dict(status='not_run'))))))
            original=manifest.read_bytes()
            receipt=dict(schema=1,kind='windows-scm',status='passed',package_kind='zip',package_sha256=digest,cleanup_complete=True,identity=dict(version=version,source_sha=source),checks=['install','start','health','version','stop','backup','restore','upgrade','uninstall','cleanup'])
            sidecar=package.with_name(package.name+'.scm-verification.json')
            sidecar.write_text(json.dumps(receipt))
            builder.verify_outputs(directory,version,source,['service'],release=True)
            self.assertEqual(manifest.read_bytes(),original)
            with self.assertRaisesRegex(ValueError,'successful build evidence'):
                builder.verify_outputs(directory,version,source,['desktop'],release=True)
            for key,value in [('package_sha256','b'*64),('cleanup_complete',False),('checks',[]),('status','failed'),('identity',dict(version=version,source_sha='b'*40)),('package_kind','directory-report')]:
                sidecar.write_text(json.dumps({**receipt,key:value}))
                with self.subTest(key=key),self.assertRaises(ValueError):builder.verify_outputs(directory,version,source,['service'],release=True)
            sidecar.write_text('{')
            self.assertFalse(builder.separate_scm_evidence(package,version,source,digest))



class PrerequisiteDiagnostics(unittest.TestCase):
    OUTPUT = 'ACCEPTANCE PREREQUISITE: the native service (SCM) acceptance needs an elevated PowerShell. Nothing was built.'

    def test_missing_elevation_is_an_acceptance_prerequisite_not_a_packaging_failure(self):
        failure = failures.StageFailure('Canonical Windows package and native smoke tests', ['powershell'], '.', 3, self.OUTPUT, 'build.log', 'service_packaging')
        self.assertEqual(failure.failure_class, 'acceptance_prerequisite')
        self.assertIn('elevated', failure.hint)
        self.assertIn('-NativeAcceptance', failure.hint)
        run = object.__new__(builder.Builder)
        run.system, run.manifest, run.stage = 'Windows', {}, 'x'
        row = run.failed_row('service', failure)
        self.assertEqual(row['status'], 'blocked')
        self.assertEqual(row['blocked_by'], 'acceptance_prerequisite')
        self.assertEqual(row['native_acceptance']['status'], 'blocked')
        self.assertFalse(row['built'])

    def test_other_failures_stay_failures(self):
        failure = failures.StageFailure('Canonical Windows package and native smoke tests', ['powershell'], '.', 1, 'FAILED (failures=2)', 'build.log', 'service_packaging')
        run = object.__new__(builder.Builder)
        run.system, run.manifest, run.stage = 'Windows', {}, 'x'
        self.assertEqual(run.failed_row('service', failure)['status'], 'failed')


class EntrypointContracts(unittest.TestCase):
    def read(self, relative):
        return (ROOT / relative).read_text(encoding='utf-8')

    def test_packaging_script_runs_the_scm_test_only_on_request_and_checks_elevation_first(self):
        text = self.read('scripts/package-windows-deployment.ps1')
        self.assertIn('[switch]$NativeAcceptance', text)
        self.assertIn("$runAcceptance = $Target -eq 'Service' -and ($NativeAcceptance -or $env:GITHUB_ACTIONS -eq 'true')", text)
        self.assertIn('if ($runAcceptance) { & ./scripts/test-server-service.ps1', text)
        self.assertLess(text.index('ACCEPTANCE PREREQUISITE'), text.index('python scripts/deployment-package.py require-inputs'), 'the prerequisite is checked before the expensive build')
        self.assertLess(text.index('exit 3'), text.index('build-server-windows.ps1'))

    def test_scm_acceptance_checks_elevation_before_changing_anything_and_runs_standalone(self):
        text = self.read('scripts/test-server-service.ps1')
        self.assertLess(text.index('IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)'), text.index('-Action Install'))
        self.assertIn('exit 3', text)
        self.assertIn('ACCEPTANCE PREREQUISITE', text)
        self.assertIn('GetTempPath()', text, 'works outside CI without RUNNER_TEMP')
        self.assertIn('An existing SAPLens service must not be changed', text, 'existing safety check preserved')

    def test_native_evidence_is_separate_and_management_uses_child_host(self):
        text=self.read('scripts/test-server-service.ps1')
        helper=self.read('scripts/testing/windows-scm-test-helpers.ps1')
        self.assertIn('& $managementHost -NoProfile -File $manage @args',text)
        self.assertNotIn('& $manage @args',text)
        self.assertIn("$reportPath=$inputBundle+'.scm-verification.json'",text)
        self.assertNotIn("$report.native_service_smoke=",text)
        self.assertLess(text.index('Write-ScmEvidence $reportPath $receipt'),text.index('Write-Host "SCM lifecycle'))
        for guard in ('CreateNew','ConvertFrom-Json','read-back validation failed','Flush($true)'):
            self.assertIn(guard,helper)

    def test_public_entrypoints_forward_the_flag(self):
        self.assertIn("@('--native-acceptance',$NativeAcceptance)", self.read('scripts/build.ps1'))
        self.assertIn('--native-acceptance', self.read('scripts/build_system/cli.py'))
        self.assertIn("command+=['--native-acceptance']", self.read('scripts/build_system/targets.py'))
        cli = SimpleNamespace()
        del cli


if __name__ == '__main__':
    unittest.main()


class ScmCleanupContracts(unittest.TestCase):
    def setUp(self):
        self.main=(ROOT/'scripts/test-server-service.ps1').read_text()
        self.helper=(ROOT/'scripts/testing/windows-scm-test-helpers.ps1').read_text()

    def test_cleanup_scope_ownership_and_reparse_checks_precede_privilege(self):
        for token in ('sap-lens-scm-', '.scm-test-owner.json', '$saved.Token -ne $Workspace.Token', '$saved.Sid -ne $Workspace.Sid', 'Path is outside the SCM test workspace', 'ReparsePoint'):
            self.assertIn(token,self.helper)
        grant=self.helper[self.helper.index('function Grant-ScmTestEntry'):self.helper.index('function Remove-ScmWorkspace')]
        self.assertLess(grant.index('Assert-ScmTestPath'),grant.index('takeown.exe'))
        self.assertLess(grant.index('Assert-NoReparse'),grant.index('takeown.exe'))
        for command in grant.splitlines():
            if command.lstrip().startswith('& '):
                self.assertNotIn('/R',command);self.assertNotIn('/T',command)
        for sid in ('S-1-1-0','S-1-5-11','S-1-5-32-545'):
            self.assertNotIn(sid,self.helper)
        self.assertIn("/grant:r ('*'+$Workspace.Sid+':F') /L",grant)
        self.assertIn('[IO.Directory]::Delete($path,$false)',self.helper)

    def test_finally_preserves_primary_error_and_requires_owned_service_removal(self):
        self.assertIn('$primary=$_.Exception',self.main)
        self.assertIn('New-Object System.Exception($detail,$primary)',self.main)
        self.assertIn('Cleanup failure(s)',self.main)
        self.assertIn('Refusing to change an unrelated SAPLens service',self.main)
        self.assertIn('$service.PathName.Trim().Trim',self.main)
        self.assertIn('$service.Dispose()',self.main)
        self.assertIn('if ($safeToRemove)',self.main)
        self.assertLess(self.main.index('Remove-ScmWorkspace $workspace'),self.main.index('Write-ScmEvidence $reportPath $receipt'))
        self.assertIn('$global:LASTEXITCODE=1',self.main)
        self.assertTrue(self.main.rstrip().endswith('exit 0'))

    def test_pristine_replacement_precedes_runtime_and_cleanup_waits_for_owned_processes(self):
        self.assertLess(self.main.index('Copy-ScmReplacementBundle'), self.main.index('-Action Install'))
        self.assertNotIn('Get-ChildItem $bundlePath | Where-Object', self.main)
        self.assertLess(self.main.index('Wait-ScmWorkspaceProcesses $workspace'), self.main.index('Remove-ScmWorkspace $workspace'))
        self.assertIn("$Report.files.PSObject.Properties.Name", self.helper)
        self.assertIn("$attempt -lt 5", self.helper)
        self.assertIn("$code -notin @(5,32,33)", self.helper)
        self.assertIn("(-bnot [IO.FileAttributes]::ReadOnly)", self.helper)
        self.assertIn("$process.ExecutablePath.StartsWith($root+'\\'", self.helper)
        self.assertNotIn('Stop-Process', self.helper)
        management=(ROOT/'scripts/manage-server-service.ps1').read_text()
        for kind in ('unexpected file', 'missing file', 'reparse point:'):
            self.assertIn(kind, management)

    def test_bundle_input_is_validated_and_copied_before_install(self):
        self.assertLess(self.main.index('Copy-ScmBundle'),self.main.index('-Action Install'))
        for token in ("$source.Extension -ieq '.zip'", 'Get-SafeScmZipPath', 'Duplicate or linked ZIP entry', '2147483648', 'ExtractToFile($entry,$target)', 'manage-server-service.ps1','app/SAP-Lens.exe'):
            self.assertIn(token,self.helper)
        self.assertIn("@('.','..')",self.helper)
        self.assertIn("$name.Contains(':')",self.helper)
        self.assertIn("$entry.Name -ne 'SAPLensService.xml'",self.helper)
        self.assertNotIn('Remove-Item $data -Recurse',self.main)
        self.assertIn("$inputBundle+'.scm-verification.json'",self.main)
        self.assertIn("WriteAllBytes($target+':Zone.Identifier',$zone)",self.helper)
        self.assertNotIn('Unblock-File',self.helper)


SHELLS = [path for path in (shutil.which('powershell'), shutil.which('pwsh')) if path]


@unittest.skipUnless(SHELLS, 'PowerShell required; no SCM lifecycle is exercised')
class EvidenceHostTests(unittest.TestCase):
    def test_child_exit_continues_and_receipt_is_readable_and_create_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);child=root/'child.ps1';child.write_text('exit 0')
            helper=str(ROOT/'scripts/testing/windows-scm-test-helpers.ps1').replace("'", "''")
            main=(ROOT/'scripts/test-server-service.ps1').read_text()
            function=main[main.index('function Invoke-ScmManage'):main.index('\ntry {\n    $bundlePath')]
            script=root/'report.ps1'
            body=f". '{helper}'\n$manage='{str(child).replace(chr(39), chr(39)*2)}'\n"
            body+='$managementHost=(Get-Process -Id $PID).Path\nfunction Test-ScmRegistered { return $false }\n'
            body+=function+'\nInvoke-ScmManage -Action Status\n'
            body+="$receipt=@{schema=1;kind='windows-scm';status='passed';package_sha256=('a'*64);cleanup_complete=$true;identity=@{version='1.0.0'}}\n"
            body+="$path=Join-Path $PSScriptRoot 'receipt.json'\nWrite-ScmEvidence $path $receipt\n$before=[IO.File]::ReadAllText($path)\n$blocked=$false\ntry { Write-ScmEvidence $path $receipt } catch { $blocked=$true }\nif (-not $blocked -or [IO.File]::ReadAllText($path) -ne $before) { throw 'Evidence overwritten' }\n"
            script.write_text(body,encoding='utf-8-sig')
            done=subprocess.run([SHELLS[0],'-NoProfile','-File',str(script)],capture_output=True,text=True,timeout=30)
            self.assertEqual(done.returncode,0,done.stdout+done.stderr)
            self.assertEqual(json.loads((root/'receipt.json').read_text())['status'],'passed')


@unittest.skipUnless(os.name == 'nt' and SHELLS, 'Native Windows PowerShell 5.1/7 is required')
class NativeSafeScmHelpers(unittest.TestCase):
    def invoke(self, body, directory, shell):
        helper=str(ROOT/'scripts/testing/windows-scm-test-helpers.ps1').replace("'", "''")
        parent=str(directory).replace("'", "''")
        source=f". '{helper}'\n$workspace=New-ScmWorkspace '{parent}'\n" + 'try {\n' + body + "\n} finally { if (Test-Path -LiteralPath $workspace.Root) { Remove-ScmWorkspace $workspace } }"
        encoded=base64.b64encode(source.encode('utf-16-le')).decode()
        done=subprocess.run([shell,'-NoProfile','-NonInteractive','-EncodedCommand',encoded],capture_output=True,text=True,timeout=60)
        self.assertEqual(done.returncode,0,done.stdout+done.stderr)

    def test_owned_cleanup_and_outside_path_rejection(self):
        for shell in SHELLS:
            with self.subTest(shell=shell), tempfile.TemporaryDirectory() as parent:
                self.invoke(r"""
$folder=Join-Path $workspace.Root 'data'
New-Item -ItemType Directory -Path $folder | Out-Null
[IO.File]::WriteAllText((Join-Path $folder 'synthetic.txt'),'synthetic')
$rejected=$false
try { $null=Assert-ScmTestPath $workspace (Join-Path $workspace.Parent 'outside') } catch { $rejected=$true }
if (-not $rejected) { throw 'Outside path was not rejected.' }
Remove-ScmWorkspace $workspace
if (Test-Path -LiteralPath $workspace.Root) { throw 'Workspace remains.' }
""", parent, shell)

    def test_zip_and_directory_inputs_and_traversal_rejection(self):
        for shell in SHELLS:
            for zipped, unsafe in ((False,False),(True,False),(True,True)):
                with self.subTest(shell=shell,zipped=zipped,unsafe=unsafe), tempfile.TemporaryDirectory() as parent:
                    source=Path(parent)/'input'; (source/'app').mkdir(parents=True)
                    for name in ('manage-server-service.ps1','SAPLensService.exe','app/SAP-Lens.exe','verification-report.json'):
                        (source/name).write_text('synthetic')
                    bundle=source
                    if zipped:
                        bundle=Path(parent)/'input.zip'
                        with zipfile.ZipFile(bundle,'w') as archive:
                            for file in source.rglob('*'):
                                if file.is_file(): archive.write(file,file.relative_to(source).as_posix())
                            if unsafe: archive.writestr('../outside.txt','must never escape')
                    escaped=str(bundle).replace("'", "''")
                    if unsafe:
                        body=f"$rejected=$false; try {{ Copy-ScmBundle '{escaped}' $workspace }} catch {{ $rejected=$true }}; if (-not $rejected) {{ throw 'Unsafe ZIP accepted.' }}"
                    else:
                        body=f"$copy=Copy-ScmBundle '{escaped}' $workspace; if (-not (Test-Path -LiteralPath (Join-Path $copy 'manage-server-service.ps1'))) {{ throw 'Bundle missing.' }}"
                    self.invoke(body,parent,shell)
                    self.assertFalse((Path(parent)/'outside.txt').exists())

    def test_locked_file_retains_workspace_then_allows_retry_after_release(self):
        for shell in SHELLS:
            with self.subTest(shell=shell), tempfile.TemporaryDirectory() as parent:
                self.invoke(r"""
$path=Join-Path $workspace.Root 'locked.txt'
[IO.File]::WriteAllText($path,'synthetic')
$handle=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
try {
    $failed=$false
    try { Remove-ScmWorkspace $workspace } catch { $failed=$true }
    if (-not $failed -or -not (Test-Path -LiteralPath $path) -or -not (Test-Path -LiteralPath (Join-Path $workspace.Root '.scm-test-owner.json'))) { throw 'Locked operation did not preserve recovery state.' }
} finally { $handle.Dispose() }
Remove-ScmWorkspace $workspace
if (Test-Path -LiteralPath $workspace.Root) { throw 'Unlocked retry did not complete.' }
""",parent,shell)

    def test_manifest_replacement_excludes_runtime_files_and_readonly_cleanup(self):
        for shell in SHELLS:
            with self.subTest(shell=shell), tempfile.TemporaryDirectory() as parent:
                self.invoke(r"""
$bundle=Join-Path $workspace.Root 'bundle'
New-Item -ItemType Directory -Path $bundle | Out-Null
[IO.File]::WriteAllText((Join-Path $bundle 'app.exe'),'synthetic')
[IO.File]::WriteAllText((Join-Path $bundle 'runtime.log'),'not a release file')
[IO.File]::WriteAllText((Join-Path $bundle 'package-manifest.json'),'transport-only metadata')
$hash=(Get-FileHash (Join-Path $bundle 'app.exe') -Algorithm SHA256).Hash.ToLowerInvariant()
$report=[pscustomobject]@{files=[pscustomobject]@{'app.exe'=$hash}}
[IO.File]::WriteAllText((Join-Path $bundle 'verification-report.json'),($report | ConvertTo-Json))
$replacement=Copy-ScmReplacementBundle $bundle $workspace $report
if ((Test-Path (Join-Path $replacement 'runtime.log')) -or (Test-Path (Join-Path $replacement 'package-manifest.json'))) { throw 'Non-replacement file entered replacement.' }
if (-not (Test-Path (Join-Path $replacement 'app.exe'))) { throw 'Verified file missing.' }
$entry=Get-Item -LiteralPath $replacement
$entry.Attributes=$entry.Attributes -bor [IO.FileAttributes]::ReadOnly
Remove-ScmWorkspace $workspace
if (Test-Path -LiteralPath $workspace.Root) { throw 'Readonly workspace remains.' }
""",parent,shell)

    def test_bootstrap_success_failure_help_and_stale_caller_exit(self):
        script=str(ROOT/'scripts/build.ps1')
        for shell in SHELLS:
            for arguments, code in ((['-Help'],0),(['-Mode','quick','-DryRun','-NonInteractive'],0),(['-Mode','invalid','-NonInteractive'],2)):
                with self.subTest(shell=shell,arguments=arguments):
                    done=subprocess.run([shell,'-NoProfile','-NonInteractive','-File',script,*arguments],capture_output=True,text=True,timeout=60)
                    self.assertEqual(done.returncode,code,done.stdout+done.stderr)
            escaped=script.replace("'", "''")
            command=f"$global:LASTEXITCODE=77; & '{escaped}' -Mode quick -DryRun -NonInteractive; if ($global:LASTEXITCODE -ne 0) {{ throw 'Stale caller exit code.' }}"
            done=subprocess.run([shell,'-NoProfile','-NonInteractive','-Command',command],capture_output=True,text=True,timeout=60)
            self.assertEqual(done.returncode,0,done.stdout+done.stderr)

    def test_junction_is_rejected_without_changing_its_target(self):
        for shell in SHELLS:
            with self.subTest(shell=shell), tempfile.TemporaryDirectory() as parent:
                self.invoke(r"""
$outside=Join-Path $workspace.Parent 'outside'
New-Item -ItemType Directory -Path $outside | Out-Null
[IO.File]::WriteAllText((Join-Path $outside 'sentinel.txt'),'keep')
$link=Join-Path $workspace.Root 'link'
New-Item -ItemType Junction -Path $link -Value $outside | Out-Null
try {
    $rejected=$false
    try { Remove-ScmWorkspace $workspace } catch { $rejected=$true }
    if (-not $rejected -or -not (Test-Path -LiteralPath (Join-Path $outside 'sentinel.txt'))) { throw 'Junction boundary failed.' }
} finally { [IO.Directory]::Delete($link,$false) }
""",parent,shell)

    def test_system_only_test_directory_cleanup_when_elevated(self):
        import ctypes
        if not ctypes.windll.shell32.IsUserAnAdmin(): self.skipTest('Elevated Windows is required for SYSTEM-owner ACL fixture')
        for shell in SHELLS:
            with self.subTest(shell=shell), tempfile.TemporaryDirectory() as parent:
                self.invoke(r"""
$folder=Join-Path $workspace.Root 'system-only'
New-Item -ItemType Directory -Path $folder | Out-Null
[IO.File]::WriteAllText((Join-Path $folder 'synthetic.txt'),'synthetic')
$acl=New-Object Security.AccessControl.DirectorySecurity
$acl.SetAccessRuleProtection($true,$false)
$system=New-Object Security.Principal.SecurityIdentifier('S-1-5-18')
$acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($system,'FullControl','ContainerInherit,ObjectInherit','None','Allow')))
Set-Acl -LiteralPath $folder -AclObject $acl
& (Join-Path $env:SystemRoot 'System32/icacls.exe') $folder /setowner '*S-1-5-18' /L /Q | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'SYSTEM-owner fixture setup failed.' }
Remove-ScmWorkspace $workspace
if (Test-Path -LiteralPath $workspace.Root) { throw 'Protected workspace remains.' }
""",parent,shell)
