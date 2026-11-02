"""Offline integrity, admission and platform orchestration regression tests."""
import copy
import importlib.util
import json
import os
import http.server
from pathlib import Path
import shutil
import sys
import subprocess
import tarfile
import tempfile
import time
import threading
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('deploy_packages',ROOT/'scripts/deployment-package.py')
pkg=importlib.util.module_from_spec(spec);spec.loader.exec_module(pkg)


@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell 7 is required for HTTP exception regressions')
class DesktopHttpTests(unittest.TestCase):
    def test_only_a_real_forbidden_response_passes_the_session_check(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            code = 403

            def do_GET(self):
                self.send_response(self.code)
                self.end_headers()

            def log_message(self, *_args):
                pass

        # Extract the production helper without launching a Windows GUI or
        # changing caller configuration. Exercise real HTTP exceptions in pwsh.
        script = r'''
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $env:SMOKE_TEST_ROOT 'scripts/test-windows-exe.ps1'), [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Desktop smoke syntax failed.' }
$definition = $ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Assert-DesktopSessionDenied'
}, $false)
if ($definition.Count -ne 1) { throw 'Desktop HTTP helper is missing.' }
. ([scriptblock]::Create($definition[0].Extent.Text))
Assert-DesktopSessionDenied $env:SMOKE_TEST_ORIGIN
'''
        with http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            env = {**os.environ, 'SMOKE_TEST_ROOT': str(ROOT),
                   'SMOKE_TEST_ORIGIN': f'http://127.0.0.1:{server.server_port}'}
            try:
                for code in (403, 200, 401, 500):
                    Handler.code = code
                    with self.subTest(status=code):
                        result = subprocess.run(['pwsh', '-NoProfile', '-Command', script],
                                                env=env, capture_output=True, timeout=20)
                        self.assertEqual(result.returncode == 0, code == 403, result.stderr.decode(errors='replace'))
            finally:
                server.shutdown()
                thread.join(timeout=5)
        # A connection failure must never count as evidence of denied access.
        result = subprocess.run(['pwsh', '-NoProfile', '-Command', script],
                                env=env, capture_output=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.info=pkg.make_build_info('build','0.1.0','a'*40,'123','9',1)
    def tearDown(self):self.temp.cleanup()
    def test_all_platform_names_agree_with_publisher_and_local_builder(self):
        def load(name):
            spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py')
            value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
        release=load('deployment-release');builder=load('build-deployments')
        cases=[('Windows-Desktop-x64','windows-desktop','desktop','sap-lens-win-desktop-x64-v'),
               ('Windows-Service-x64','windows-service','service','sap-lens-win-service-x64-v'),
               ('Linux-Docker-amd64','linux-docker','docker','sap-lens-linux-docker-amd64-v'),
               ('Linux-Native-x64','linux-native','linux-native','sap-lens-linux-native-x64-v')]
        for platform,package,target,prefix in cases:
            with self.subTest(platform=platform):
                source=self.root/platform;source.mkdir();(source/'README.md').write_text('synthetic')
                with patch.object(pkg,'identity',return_value=self.info):
                    archive=pkg.finish(source,platform,self.root/'out')
                extension='.zip' if platform.startswith('Windows') else '.tar.gz'
                self.assertEqual(archive.name,prefix+self.info['version']+extension)
                self.assertEqual(release.PACKAGES[package][2:4],builder.STEMS[target])
                self.assertEqual(archive.name,f'sap-lens-{builder.STEMS[target][0]}-v{self.info["version"]}{extension}')

    def test_renamed_desktop_archive_still_runs_desktop_distribution_verifier(self):
        spec=importlib.util.spec_from_file_location('download',ROOT/'scripts/check-deployment-download.py')
        download=importlib.util.module_from_spec(spec);spec.loader.exec_module(download)
        source=self.root/'source';source.mkdir();(source/'README.md').write_text('synthetic')
        with patch.object(pkg,'identity',return_value=self.info):
            pkg.finish(source,'Windows-Desktop-x64',self.root/'out')
            with patch.object(download.importlib.util,'module_from_spec',return_value=pkg), \
                    patch.object(download.importlib.util,'spec_from_file_location') as loader, \
                    patch.object(subprocess,'run') as verifier:
                loader.return_value.loader.exec_module.return_value=None
                download.check(self.root/'out')
            self.assertIn('verify-desktop-distribution.py',str(verifier.call_args.args[0]))
            verifier.assert_called_once()

    def test_repeated_packaging_preserves_existing_archive_and_rejects_output_inside_bundle(self):
        for platform in ('Windows-Desktop-x64','Linux-Native-x64'):
            source=self.root/platform;source.mkdir();(source/'README.md').write_text('synthetic')
            with patch.object(pkg,'identity',return_value=self.info):
                archive=pkg.finish(source,platform,self.root/'out')
                sidecar=archive.with_name(archive.name+'.sha256');before=(archive.read_bytes(),sidecar.read_bytes())
                (source/'README.md').write_text('changed')
                with self.assertRaisesRegex(ValueError,'already exists'):pkg.finish(source,platform,self.root/'out')
                self.assertEqual((archive.read_bytes(),sidecar.read_bytes()),before)
                for output in (source,source/'nested'):
                    with self.assertRaisesRegex(ValueError,'outside'):pkg.finish(source,platform,output)
    def test_archive_roundtrip_checksum_extra_members_and_private_inputs(self):
        source=self.root/'source';source.mkdir();(source/'README.md').write_text('synthetic')
        with patch.object(pkg,'identity',return_value=self.info):archive=pkg.finish(source,'Linux-Native-x64',self.root/'out')
        manifest=pkg.verify_extract(archive,self.root/'restored',pkg.sha(archive))
        self.assertEqual(manifest['identity'],self.info)
        with self.assertRaises(ValueError):pkg.verify_extract(archive,self.root/'bad','0'*64)
        with tarfile.open(self.root/'extra.tar.gz','w:gz') as out:
            out.add(source/'package-manifest.json',arcname='package-manifest.json')
            out.add(source/'README.md',arcname='README.md')
            out.add(source/'README.md',arcname='extra.txt')
        with self.assertRaises(ValueError):pkg.verify_extract(self.root/'extra.tar.gz',self.root/'extra',pkg.sha(self.root/'extra.tar.gz'))
        for name in ['settings.json','records.csv','csv-data/snapshots/private.json','access.secret','../outside']:
            with self.subTest(name=name),self.assertRaises(ValueError):pkg.privacy([name])
    def test_desktop_manifest_is_grouped_and_exact_contents_survive_roundtrip(self):
        source=self.root/'installer';source.mkdir();(source/'Setup.exe').write_bytes(b'synthetic')
        (source/'metadata').mkdir();(source/'metadata/installer-verification.json').write_text('{}')
        with patch.object(pkg,'identity',return_value=self.info):archive=pkg.finish(source,'Windows-Desktop-x64',self.root/'out')
        restored=self.root/'restored-desktop';manifest=pkg.verify_extract(archive,restored,pkg.sha(archive))
        self.assertEqual(manifest['layout'],'installer-only-v1')
        self.assertTrue((restored/'metadata/package-manifest.json').is_file())
        self.assertFalse((restored/'package-manifest.json').exists())

    def test_zip_traversal_duplicates_and_symlinks_rejected(self):
        for names in [['../escape'],['same','SAME']]:
            archive=self.root/'bad.zip'
            with zipfile.ZipFile(archive,'w') as out:
                for name in names:out.writestr(name,b'bad')
            with self.assertRaises(ValueError):pkg.verify_extract(archive,self.root/'target',pkg.sha(archive))
        archive=self.root/'link.zip'
        with zipfile.ZipFile(archive,'w') as out:
            entry=zipfile.ZipInfo('link');entry.external_attr=0o120777<<16;out.writestr(entry,'private')
        with self.assertRaises(ValueError):pkg.verify_extract(archive,self.root/'target2',pkg.sha(archive))
    def receipt(self):
        data=b'<html>synthetic</html>'
        receipt=dict(schema=1,identity=self.info,checks=sorted(pkg.CHECKS),validated_at=time.time(),files={'frontend/index.html':__import__('hashlib').sha256(data).hexdigest()})
        return receipt,data
    def test_attestation_rejects_other_commit_run_attempt_tampering_and_missing_checks(self):
        receipt,data=self.receipt()
        for mutation in ['run','attempt','commit','tamper','checks','expired']:
            current=copy.deepcopy(receipt);env={'GITHUB_ACTIONS':'true','GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1'}
            payload=data
            if mutation=='run':env['GITHUB_RUN_ID']='999'
            if mutation=='attempt':env['GITHUB_RUN_ATTEMPT']='2'
            if mutation=='commit':current['identity']=pkg.make_build_info('build','0.1.0','b'*40,'123','9',1)
            if mutation=='tamper':payload=b'changed'
            if mutation=='checks':current['checks'].remove('types')
            if mutation=='expired':current['validated_at']-=90000
            archive=self.root/'validation.zip'
            with zipfile.ZipFile(archive,'w') as out:out.writestr('validation.json',json.dumps(current));out.writestr('frontend/index.html',payload)
            with patch.object(pkg,'ROOT',self.root),patch.object(pkg,'git_sha',return_value='a'*40),patch.dict(os.environ,env),self.subTest(mutation=mutation),self.assertRaises(ValueError):pkg.consume(archive)
    def test_native_installer_refuses_os_data_directory_before_any_mutation(self):
        prefix=self.root/'not-created'
        result=subprocess.run([sys.executable,str(ROOT/'scripts/install-linux-server.py'),'install','--user','--prefix',str(prefix),'--data','/','--config',str(self.root/'config/env')],capture_output=True)
        self.assertNotEqual(result.returncode,0);self.assertFalse(prefix.exists())

    def test_failed_shared_stage_cannot_issue_attestation(self):
        temp=self.root/'timings';temp.mkdir()
        records=[dict(stage=name,status='failed' if name=='types' else 'passed') for name in pkg.CHECKS]
        (temp/'sap-lens-ci-timings.jsonl').write_text('\n'.join(map(json.dumps,records)))
        with patch.dict(os.environ,{'RUNNER_TEMP':str(temp)}),self.assertRaises(ValueError):pkg.seal(self.root/'sealed.zip')

    def test_valid_same_run_assets_consumed_and_modified_assets_rejected(self):
        receipt,data=self.receipt();archive=self.root/'validation.zip'
        with zipfile.ZipFile(archive,'w') as out:out.writestr('validation.json',json.dumps(receipt));out.writestr('frontend/index.html',data)
        with patch.object(pkg,'ROOT',self.root),patch.object(pkg,'git_sha',return_value='a'*40),patch.dict(os.environ,{'GITHUB_ACTIONS':'true','GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1'}):
            pkg.consume(archive)
            with patch.object(pkg.subprocess,'run'):self.assertEqual(pkg.require_ci()['identity'],self.info)
            (self.root/'frontend/dist/index.html').write_text('changed')
            with patch.object(pkg.subprocess,'run'),self.assertRaises(ValueError):pkg.require_ci()


class OrchestrationTests(unittest.TestCase):
    def test_native_installer_compiler_preflight_cannot_be_removed_skipped_or_delayed(self):
        spec=importlib.util.spec_from_file_location('installer_workflow_rules',ROOT/'scripts/check-workflows.py')
        rules=importlib.util.module_from_spec(spec);spec.loader.exec_module(rules)
        current=rules.load_workflows();rules.validate(current)
        for change in ('removed','conditional','late','broad-diagnostics','always-diagnostics'):
            bad=copy.deepcopy(current);steps=bad['build-deployments.yml']['jobs']['desktop']['steps']
            compiler=next(step for step in steps if 'build-desktop-installer.ps1 -CompileCheck' in step.get('run',''))
            diagnostics=next(step for step in steps if step.get('name')=='Preserve isolated installer setup diagnostics on failure')
            if change=='removed':steps.remove(compiler)
            elif change=='conditional':compiler['if']='false'
            elif change=='broad-diagnostics':diagnostics['with']['path']='${{ runner.temp }}/**'
            elif change=='always-diagnostics':diagnostics['if']='always()'
            else:steps.remove(compiler);steps.append(compiler)
            with self.subTest(change=change),self.assertRaises(ValueError):rules.validate(bad)

    def test_all_platforms_are_independent_and_build_only(self):
        spec=importlib.util.spec_from_file_location('workflow_rules',ROOT/'scripts/check-workflows.py')
        rules=importlib.util.module_from_spec(spec);spec.loader.exec_module(rules)
        current=rules.load_workflows();rules.validate(current)
        for key in ('desktop','service','docker','native'):
            self.assertEqual(current['build-deployments.yml']['jobs'][key]['needs'],['plan','validation'])
        bad=copy.deepcopy(current);bad['build-deployments.yml']['jobs']['native']['needs']='docker'
        with self.assertRaises(ValueError):rules.validate(bad)
        bad=copy.deepcopy(current);bad['build-deployments.yml']['jobs']['native']['needs']=['plan','validation','docker']
        with self.assertRaises(ValueError):rules.validate(bad)  # packages never wait for one another
        bad=copy.deepcopy(current);bad['build-deployments.yml']['jobs']['docker']['if']="${{ inputs.build_target == 'all' }}"
        with self.assertRaises(ValueError):rules.validate(bad)  # selection is decided by the plan alone
        bad=copy.deepcopy(current);bad['build-deployments.yml']['jobs']['validation']['needs']=[]
        with self.assertRaises(ValueError):rules.validate(bad)  # an invalid selection must stop before validation
        bad=copy.deepcopy(current);bad['build-deployments.yml']['on']['push']=''
        with self.assertRaises(ValueError):rules.validate(bad)

    def test_native_auditor_and_desktop_identity_are_required_on_package_jobs(self):
        spec=importlib.util.spec_from_file_location('workflow_package_rules',ROOT/'scripts/check-workflows.py')
        rules=importlib.util.module_from_spec(spec);spec.loader.exec_module(rules)
        current=rules.load_workflows();rules.validate(current)
        for change in ('missing-audit','late-audit','conditional-audit','missing-identity','wrong-identity'):
            bad=copy.deepcopy(current);jobs=bad['build-deployments.yml']['jobs'];steps=jobs['native']['steps']
            audit=next(step for step in steps if step.get('run')=='python -m pip install -r scripts/requirements-audit.txt')
            if change=='missing-audit':steps.remove(audit)
            elif change=='late-audit':steps.remove(audit);steps.append(audit)
            elif change=='conditional-audit':audit['if']='false'
            elif change=='missing-identity':jobs['desktop']['env'].pop('SAP_LENS_EXPECTED_BUILD_JSON')
            else:jobs['desktop']['env']['SAP_LENS_EXPECTED_BUILD_JSON']='${{ inputs.version }}'
            with self.subTest(change=change),self.assertRaises(ValueError):rules.validate(bad)

    def test_server_data_sources_resolve_from_nested_spec_directory(self):
        from pathlib import PureWindowsPath
        import re
        script=(ROOT/'scripts/build-server-windows.ps1').read_text()
        # Use the actual script's rooted variables and data arguments, not another packaging implementation.
        assignments=dict(re.findall(r"\$(\w+)=Join-Path \$root '([^']+)'",script))
        sources=re.findall(r'--add-data "\$(\w+);([^"\n]+)"',script)
        self.assertEqual(len(sources),5)
        with tempfile.TemporaryDirectory(prefix='SAP Lens server ø ') as directory:
            root=Path(directory);spec=root/'backend/build/server';spec.mkdir(parents=True)
            for variable,destination in sources:
                self.assertIn(variable,assignments)
                source=root/assignments[variable]
                if variable in {'frontendDist','resources'}:source.mkdir(parents=True);(source/'synthetic.json').write_text('{}')
                else:source.parent.mkdir(parents=True,exist_ok=True);source.write_bytes(b'synthetic asset')
                self.assertTrue(source.is_absolute() and source.exists())
                self.assertFalse((spec/assignments[variable]).exists())
                windows_source=PureWindowsPath('D:/a/SAP Lens ø')/assignments[variable]
                self.assertTrue(windows_source.is_absolute())
                self.assertIn(destination,{'frontend/dist','assets','.','resources'})
            self.assertIn("--paths (Join-Path $root 'backend')",script)
