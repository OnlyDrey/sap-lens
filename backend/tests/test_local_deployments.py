"""Cross-host routing and local receipt tests; remote/native results are never fabricated."""
import base64
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from version import make_local_deployment_info,parse_build_info
import test_local_build as legacy


def load(name):
    spec=importlib.util.spec_from_file_location(name.replace('-','_'),next((ROOT/'scripts').rglob(name+'.py')))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


builder=load('build-deployments');pkg=load('deployment-package')


class LocalDeploymentTests(unittest.TestCase):
    def test_exact_local_version_has_no_fabricated_ci_run_or_tag(self):
        for requested in ('0.1.0','0.1.0-alpha.1','0.1.0-beta.4','0.1.0-rc.2'):
            info=make_local_deployment_info(requested,'a'*40)
            self.assertEqual(info['version'],requested);self.assertEqual(info['schema'],3)
            self.assertEqual(info['run_id'],'');self.assertEqual(info['run_number'],'')
            self.assertEqual(info['attempt'],0);self.assertEqual(info['tag'],'')
            self.assertEqual(parse_build_info(info),info)
            info['run_id']='1'
            with self.assertRaises(ValueError):parse_build_info(info)
        for requested in ('0.1.0-beta-1','0.1.0-beta.01','0.1.0+test','../out'):
            with self.assertRaises(ValueError):make_local_deployment_info(requested,'a'*40)

    def test_host_target_routing_and_all_never_skip_requested_platforms(self):
        self.assertEqual(builder.requested(['all']),list(builder.TARGETS))
        self.assertEqual(builder.requested(['desktop','service','desktop']),['desktop','service'])
        for target in builder.TARGETS:
            self.assertEqual(builder.host_for(target,'Linux'),'Windows' if target in ('desktop','service') else 'Linux')
        with tempfile.TemporaryDirectory() as temporary:
            run=object.__new__(builder.Builder)
            run.args=SimpleNamespace(platform=['all']);run.system='Linux';run.output=Path(temporary)
            run.manifest=dict(schema=1,version='0.1.0',source_commit='a'*40,targets={})
            attempted=[]
            def local(target):
                attempted.append(target)
                return dict(status='passed',artifact=target+'.synthetic',sha256='b'*64,built=True,package_verified=True,runtime_smoke_tested=True)
            with patch.object(run,'remote',side_effect=ValueError('Configure a Windows builder')),patch.object(run,'local',side_effect=local):
                self.assertEqual(run.execute(),1)
            self.assertEqual(attempted,['docker','linux-native'])
            self.assertEqual(set(run.manifest['targets']),set(builder.TARGETS))
            self.assertFalse(run.manifest['targets']['desktop']['built'])
            self.assertEqual(run.manifest['targets']['linux-native']['status'],'passed')

    def test_remote_commands_preserve_unicode_paths_and_expected_source(self):
        command=builder.remote_command('Windows','C:/Build path/Ø SAP','a'*40,'0.1.0-beta.1',['desktop','service'],[])
        decoded=base64.b64decode(command.split()[-1]).decode('utf-16le')
        self.assertIn("Set-Location 'C:/Build path/Ø SAP'",decoded)
        self.assertIn('a'*40,decoded);self.assertIn("'--platform' 'service'",decoded)
        self.assertNotIn('Invoke-Expression',decoded)
        command=builder.remote_command('Linux','/home/build path/Ø SAP','a'*40,'0.1.0',['linux-native'],[])
        self.assertIn("'/home/build path/Ø SAP'",command)
        for path in ('C:/repo;bad','/tmp/repo\ncommand','relative'):
            with self.assertRaises(ValueError):builder.remote_command('Linux',path,'a'*40,'0.1.0',['docker'],[])

    def test_cli_rejects_bad_arguments_and_never_makes_remote_calls(self):
        for args in (['--platform','invalid','--version','0.1.0'],['--version','0.1.0','--clean','--reuse-validation']):
            result=subprocess.run([sys.executable,str(ROOT/'scripts/deployment/build-deployments.py'),*args],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertIn('error:',result.stderr)
        result=subprocess.run([sys.executable,str(ROOT/'scripts/build.py'),'--help'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0);self.assertIn('--windows-host',result.stdout)

    def test_ci_admission_cannot_use_a_local_receipt(self):
        with patch.dict(os.environ,{'GITHUB_ACTIONS':'true'}),patch.object(pkg,'require_ci',side_effect=ValueError('CI receipt required')) as ci,patch.object(pkg,'local_tools') as local:
            with self.assertRaises(ValueError):pkg.require_inputs()
            ci.assert_called_once();local.assert_not_called()

    def test_native_install_smoke_does_not_inherit_validation_storage_overrides(self):
        with tempfile.TemporaryDirectory() as temporary:
            run=object.__new__(builder.Builder)
            run.log=Path(temporary)/'build.log'
            run.env={'SAP_LENS_CONFIG_DIR':'isolated-validation','PATH':'kept'}
            with patch.object(builder.subprocess,'run') as command:
                run.run('Native installation',['python','scripts/testing/test-native-deployment.py','--artifacts','synthetic'])
                self.assertEqual(command.call_args.kwargs['env'],{'PATH':'kept'})
                run.run('Backend validation',['python','test.py'])
                self.assertEqual(command.call_args.kwargs['env']['SAP_LENS_CONFIG_DIR'],'isolated-validation')

    def test_shared_validation_failure_is_not_repeated_for_another_target(self):
        run=object.__new__(builder.Builder);run.validated=False;run.validation_started=True
        with patch.object(builder,'prerequisite_versions') as prerequisites,self.assertRaisesRegex(ValueError,'No repeated full suite'):
            run.validate()
        prerequisites.assert_not_called()


class LocalDeploymentReceiptTests(unittest.TestCase):
    def setUp(self):
        self.fixture=legacy.LocalReceiptTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root
        self.sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=self.root,text=True).strip()
        self.info=make_local_deployment_info('0.1.0-beta.1',self.sha)
        pkg.write(self.root/'backend/build/build-version.json',self.info)
        self.temporary=self.root/'backend/build/validation';self.temporary.mkdir()
        records=[dict(stage=stage,status='passed') for stage in pkg.CHECKS]
        (self.temporary/'sap-lens-ci-timings.jsonl').write_text('\n'.join(map(json.dumps,records)))
        self.context=patch.multiple(pkg,ROOT=self.root,frontend_licenses=lambda:None,local_tools=lambda:legacy.local)
        self.context.start();self.addCleanup(self.context.stop)
        self.env=patch.dict(os.environ,{'GITHUB_ACTIONS':'false','RUNNER_TEMP':str(self.temporary)})
        self.env.start();self.addCleanup(self.env.stop)
        os.environ.pop('SAP_LENS_SKIPPED_CHECKS',None)  # the builder sets it when pwsh is absent; tests declare it explicitly

    def test_builder_isolates_production_data_and_global_pip_destinations(self):
        args=SimpleNamespace(version='0.1.0-beta.1',output_dir=self.root/'backend/build/output',invocation='d'*32)
        with patch.object(builder,'ROOT',self.root),patch.dict(os.environ,{'PIP_TARGET':'/do-not-use','SAP_LENS_DATA_DIR':'/private-data','SAP_LENS_DEPLOYMENT_MODE':'server'}):
            value=builder.Builder(args)
        self.assertNotIn('PIP_TARGET',value.env);self.assertNotIn('SAP_LENS_DATA_DIR',value.env)
        self.assertNotIn('SAP_LENS_DEPLOYMENT_MODE',value.env)
        self.assertEqual(value.env['USER_CSV_PATH'],'')
        self.assertTrue(Path(value.env['SAP_LENS_CONFIG_DIR']).is_relative_to(self.root/'backend/build'))

    def test_receipt_validates_source_frontend_environment_host_and_age(self):
        receipt=pkg.record_local();self.assertEqual(pkg.require_inputs()['identity'],self.info)
        path=self.root/'backend/build/deployment-local-validation.json'
        for field,value in [('host','another-platform'),('checks',[]),('validated_at',0)]:
            altered=copy.deepcopy(receipt);altered[field]=value;pkg.write(path,altered)
            with self.subTest(field=field),self.assertRaises(ValueError):pkg.require_inputs()
        pkg.write(path,receipt)
        for relative in ('frontend/dist/input.txt','backend/build/python-env/input.txt','source.py'):
            target=self.root/relative;original=target.read_bytes();target.write_bytes(b'changed')
            with self.subTest(relative=relative),self.assertRaises(ValueError):pkg.require_inputs()
            target.write_bytes(original)
        self.assertEqual(pkg.require_inputs()['identity'],self.info)

    def test_receipt_failure_categories_and_recovery_are_actionable(self):
        receipt=pkg.record_local()
        path=self.root/'backend/build/deployment-local-validation.json'
        cases=[('identity', {**self.info,'version':'0.2.0'}, 'identity-mismatch'),
               ('identity', {**self.info,'source_sha':'b'*40}, 'stale-commit'),
               ('host','another-platform','incompatible-host'),('checks',[],'incomplete-checks'),
               ('validated_at',0,'expired'),('validation_scope','targeted','scope-mismatch'),
               ('inputs',{},'changed-inputs')]
        with patch.dict(os.environ,{'SAP_LENS_BUILD_SCOPE':'full'}):
            for field,value,category in cases:
                altered={**receipt,'validation_scope':'full',field:value};pkg.write(path,altered)
                with self.subTest(category=category),self.assertRaisesRegex(pkg.DeploymentValidationError,category) as error:
                    pkg.require_inputs()
                self.assertIn('--scope full --non-interactive',str(error.exception))
                self.assertIn('without --skip-setup',str(error.exception))
        path.unlink()
        with self.assertRaisesRegex(pkg.DeploymentValidationError,'missing-receipt'):pkg.require_inputs()
        pkg.write(path,receipt)
        with patch.object(pkg,'git_sha',return_value='c'*40),self.assertRaisesRegex(pkg.DeploymentValidationError,'stale-commit'):
            pkg.require_inputs()
        self.assertEqual(pkg.require_inputs()['identity'],self.info)

    def test_tools_changes_and_missing_stage_logs_fail_with_recovery(self):
        pkg.record_local()
        with patch.object(legacy.local,'tool_versions',return_value={'python':'changed','node':'changed'}),self.assertRaisesRegex(pkg.DeploymentValidationError,'changed-inputs'):
            pkg.require_inputs()
        (self.temporary/'sap-lens-ci-timings.jsonl').unlink()
        with self.assertRaisesRegex(pkg.DeploymentValidationError,'incomplete-checks'):pkg.record_local()

    def test_cli_reports_known_receipt_reason_without_traceback(self):
        import contextlib
        import io
        stderr=io.StringIO()
        with patch.object(pkg.sys,'argv',['deployment-package.py','require-inputs']),contextlib.redirect_stderr(stderr),self.assertRaises(SystemExit) as result:
            pkg.main()
        self.assertEqual(result.exception.code,1)
        self.assertIn('[missing-receipt]',stderr.getvalue())
        self.assertIn('Recovery: python scripts/build.py package',stderr.getvalue())
        self.assertNotIn('Traceback',stderr.getvalue())

    def test_targeted_receipt_is_not_upgraded_by_consuming_it(self):
        with patch.dict(os.environ,{'SAP_LENS_BUILD_SCOPE':'targeted'}):
            receipt=pkg.record_local();self.assertEqual(receipt['validation_scope'],'targeted')
            self.assertEqual(pkg.require_inputs(),receipt)
        before=(self.root/'backend/build/deployment-local-validation.json').read_bytes()
        with patch.dict(os.environ,{'SAP_LENS_BUILD_SCOPE':'full'}),self.assertRaisesRegex(pkg.DeploymentValidationError,'scope-mismatch'):
            pkg.require_inputs()
        self.assertEqual((self.root/'backend/build/deployment-local-validation.json').read_bytes(),before)

    def test_installer_orchestration_seals_then_consumes_and_reuse_is_verified(self):
        from unittest.mock import Mock
        run=object.__new__(builder.Builder)
        run.args=SimpleNamespace(platform=['desktop'],clean=False,reuse_validation=False,no_cache=False,scope='targeted')
        run.system='Windows';run.build=self.root/'backend/build';run.info=self.info
        run.python=run.build/'python-env/Scripts/python.exe';run.audit=run.build/'audit-env/Scripts/python.exe'
        run.env={'RUNNER_TEMP':str(self.temporary),'PLAYWRIGHT_EXECUTABLE_PATH':str(self.root/'source.py')}
        run.validated=False;run.run=Mock();run.bootstrap_pip=Mock()
        run.prepare_workspace=Mock(return_value=(self.root,self.root/'frontend'))
        with patch.object(builder,'prerequisite_versions',return_value='powershell'),patch.object(builder,'module',return_value=pkg),patch.object(builder.subprocess,'check_output',return_value='v24.0.0'),patch.object(builder.frontend_workspace,'dependency_stamp'),patch.object(builder.frontend_workspace,'install'),patch.object(builder.frontend_workspace,'publish_dist',return_value=1):
            run.run_shared_validation()
        commands=[call.args[1] for call in run.run.call_args_list]
        self.assertEqual(commands[-2][-1],'record-local')
        self.assertEqual(commands[-1][-1],'require-inputs')
        self.assertTrue(run.validated)
        self.assertTrue(any('targeted' in command and 'deployment' in command for command in commands))
        self.assertTrue(any('--grep' in command and '@smoke' in command for command in commands))
        run.args.reuse_validation=True;run.validated=False;run.run.reset_mock()
        with patch.object(builder,'prerequisite_versions',return_value='powershell'),patch.object(builder,'module',return_value=pkg):
            run.run_shared_validation()
        self.assertEqual(run.run.call_count,1)
        self.assertEqual(run.run.call_args.args[1][-1],'require-inputs')
        run.validated=False;run.run.side_effect=pkg.DeploymentValidationError('stale-commit')
        with patch.object(builder,'prerequisite_versions',return_value='powershell'),patch.object(builder,'module',return_value=pkg),self.assertRaisesRegex(pkg.DeploymentValidationError,'stale-commit'):
            run.run_shared_validation()
        self.assertFalse(run.validated)

    def test_a_non_windows_receipt_may_leave_only_the_powershell_check_unverified_and_says_so(self):
        records=[dict(stage=stage,status='passed') for stage in pkg.CHECKS-{'powershell'}]
        (self.temporary/'sap-lens-ci-timings.jsonl').write_text('\n'.join(map(json.dumps,records)))
        with patch.object(pkg.sys,'platform','linux'):
            with self.assertRaises(ValueError):pkg.record_local()  # missing without the explicit declaration
            with patch.dict(os.environ,{'SAP_LENS_SKIPPED_CHECKS':'powershell,types'}):
                receipt=pkg.record_local()
            self.assertEqual(receipt['not_verified'],['powershell']);self.assertNotIn('powershell',receipt['checks']);self.assertIn('types',receipt['checks'])
            self.assertEqual(pkg.require_inputs()['identity'],self.info)
            path=self.root/'backend/build/deployment-local-validation.json'
            pkg.write(path,{**receipt,'not_verified':['types']})  # no other check may be declared unverified
            with self.assertRaises(ValueError):pkg.require_inputs()
        with patch.object(pkg.sys,'platform','win32'),patch.dict(os.environ,{'SAP_LENS_SKIPPED_CHECKS':'powershell'}),self.assertRaises(ValueError):
            pkg.record_local()

    @unittest.skipUnless(sys.platform=='linux','POSIX virtualenv interpreter links')
    def test_only_standard_local_interpreter_and_lib_aliases_are_permitted(self):
        environment=self.root/'backend/build/python-env'
        (environment/'bin').mkdir();(environment/'lib').mkdir()
        (environment/'bin/python').symlink_to(Path(sys.executable).resolve())
        (environment/'lib64').symlink_to('lib',target_is_directory=True)
        pkg.record_local();self.assertEqual(pkg.require_inputs()['identity'],self.info)
        (environment/'private-link').symlink_to(self.root/'source.py')
        with self.assertRaises(ValueError):pkg.require_inputs()

    def test_failed_validation_and_private_frontend_input_cannot_be_sealed(self):
        timing=self.temporary/'sap-lens-ci-timings.jsonl'
        data=[json.loads(line) for line in timing.read_text().splitlines()]
        for row in data:
            if row['stage']=='types':row['status']='failed'
        timing.write_text('\n'.join(map(json.dumps,data)))
        with self.assertRaises(ValueError):pkg.record_local()
        for row in data:row['status']='passed'
        timing.write_text('\n'.join(map(json.dumps,data)))
        (self.root/'frontend/dist/private.csv').write_text('private')
        with self.assertRaises(ValueError):pkg.record_local()


class SourceOutputIsolation(unittest.TestCase):
    def test_default_names_include_source_and_keep_product_version(self):
        one=builder.output_name('1.0.0-beta.2','a'*40)
        two=builder.output_name('1.0.0-beta.2','b'*40)
        self.assertNotEqual(one,two)
        self.assertEqual(one,'1.0.0-beta.2-'+'a'*12)
        source=(ROOT/'scripts/deployment/build-deployments.py').read_text()
        self.assertIn("args.output_dir or ROOT / 'dist' / output_name(args.version, self.source)",source)
        self.assertIn("'/dist/' + output_name(self.args.version, self.source)",source)
        self.assertIn("value.get('source_commit') != self.source",source)
        self.assertIn('Nothing was overwritten',source)

    def test_defaults_separate_commits_and_explicit_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            args=SimpleNamespace(version='1.0.0-beta.2',output_dir=None,invocation='d'*32)
            with patch.object(builder,'ROOT',root), patch.object(builder.subprocess,'run',return_value=SimpleNamespace(returncode=0)), patch.object(builder,'checkout',return_value='a'*40):
                one=builder.Builder(args)
            (one.output/'sentinel').write_text('keep')
            with patch.object(builder,'ROOT',root), patch.object(builder.subprocess,'run',return_value=SimpleNamespace(returncode=0)), patch.object(builder,'checkout',return_value='b'*40):
                two=builder.Builder(args)
            self.assertNotEqual(one.output,two.output)
            self.assertEqual((one.output/'sentinel').read_text(),'keep')
            args.output_dir=root/'explicit'
            with patch.object(builder,'ROOT',root), patch.object(builder.subprocess,'run',return_value=SimpleNamespace(returncode=0)), patch.object(builder,'checkout',return_value='b'*40):
                explicit=builder.Builder(args)
            self.assertTrue(explicit.output.samefile(args.output_dir))
            self.assertEqual(explicit.output,args.output_dir.resolve())
            pkg.write(explicit.output/'build-manifest.json',dict(version=args.version,source_commit='a'*40,targets={}))
            before=(explicit.output/'build-manifest.json').read_bytes()
            with patch.object(builder,'ROOT',root), patch.object(builder.subprocess,'run',return_value=SimpleNamespace(returncode=0)), patch.object(builder,'checkout',return_value='b'*40):
                with self.assertRaisesRegex(ValueError,'Nothing was overwritten'): builder.Builder(args)
            self.assertEqual((explicit.output/'build-manifest.json').read_bytes(),before)


    def test_explicit_linked_output_is_rejected_before_resolving(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / 'private'
            target.mkdir()
            link = root / 'output'
            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError:
                self.skipTest('Creating test symlinks is not permitted')
            args = SimpleNamespace(version='1.0.0-beta.2', output_dir=link, invocation='d'*32)
            with patch.object(builder, 'checkout', return_value='a'*40):
                with self.assertRaisesRegex(ValueError, 'Output may not be linked'):
                    builder.Builder(args)
            self.assertEqual(list(target.iterdir()), [])

    @unittest.skipUnless(os.name == 'nt', 'Windows 8.3 filesystem aliases require native Windows')
    def test_explicit_short_path_alias_preserves_directory_identity(self):
        import ctypes
        from ctypes import wintypes
        short_path = ctypes.WinDLL('kernel32', use_last_error=True).GetShortPathNameW
        short_path.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
        short_path.restype = wintypes.DWORD
        with tempfile.TemporaryDirectory(prefix='sap-lens-long-output-') as temporary:
            directory = Path(temporary) / 'explicit long directory name'
            directory.mkdir()
            buffer = ctypes.create_unicode_buffer(32768)
            length = short_path(str(directory), buffer, len(buffer))
            if not length or length >= len(buffer):
                self.fail(f'GetShortPathNameW failed: {ctypes.get_last_error()}')
            alias = Path(buffer.value)
            if alias == directory:
                self.skipTest('8.3 aliases are disabled on this Windows filesystem')
            args = SimpleNamespace(version='1.0.0-beta.2', output_dir=alias, invocation='d'*32)
            with patch.object(builder, 'checkout', return_value='a'*40):
                actual = builder.Builder(args).output
            self.assertTrue(actual.samefile(directory))
            self.assertTrue(actual.samefile(alias))
            self.assertEqual(actual, directory.resolve())

class UnifiedReleaseDirectoryTests(unittest.TestCase):
    """dist/<version>-<commit12>/ is shared by the portable Desktop export and the deployment builder (Server, Installer), in either order."""
    setUp = legacy.LocalExportTests.setUp
    artifacts = builder.artifacts

    def export(self):
        def verify(command, **kwargs):
            Path(command[command.index('--report') + 1]).write_text('{"verification":"passed"}')
        with patch.object(legacy.local, 'identity', return_value=self.info), patch.object(legacy.local, 'check', return_value={'stages': legacy.local.REQUIRED}), \
                patch.object(legacy.local.subprocess, 'run', side_effect=verify):
            legacy.local.export('0.1.0', self.output, self.root)

    def server(self, content=b'synthetic service package'):
        """What the deployment builder does for a passed Service target: collect the archive, record its manifest."""
        name = f"sap-lens-win-service-x64-v{self.info['version']}.zip"
        source = self.root / 'backend/build' / name; source.write_bytes(content); digest = self.artifacts.digest(source)
        self.artifacts.collect(source, self.output, self.info['version'], self.info['source_sha'], 'service', digest)
        self.artifacts.write_bound_manifest(self.output, 'server', name, digest, self.info['version'], self.info['source_sha'], dict(status='passed', artifact=name, sha256=digest))
        return name, digest

    def deployment_builder(self, source=None):
        args = SimpleNamespace(version=self.info['version'], output_dir=self.output, invocation='d' * 32)
        with patch.object(builder, 'ROOT', self.root), patch.object(builder.subprocess, 'run', return_value=SimpleNamespace(returncode=0)), \
                patch.object(builder, 'checkout', return_value=source or self.info['source_sha']), patch.object(builder, 'make_local_deployment_info', return_value=self.info):
            return builder.Builder(args)

    def sums(self):
        return dict(reversed(line.split('  ')) for line in (self.output / 'SHA256SUMS.txt').read_text(encoding='ascii').splitlines())

    def snapshot(self):
        return {path.relative_to(self.output).as_posix(): path.read_bytes() for path in sorted(self.output.rglob('*')) if path.is_file()}

    def test_server_then_desktop_keeps_the_server_artifact_manifest_checksums_and_evidence(self):
        name, digest = self.server()
        evidence = self.output / (name + '.scm-verification.json'); evidence.write_text('{"status":"passed","historical":true}')
        before = self.snapshot()
        self.export()
        after = self.snapshot()
        for path, content in before.items():
            if path not in ('release-manifest.json', 'SHA256SUMS.txt'): self.assertEqual(after[path], content, path)
        portable = f"SAP-Lens-Windows-x64-{self.info['version']}.zip"
        self.assertEqual(self.sums(), {name: digest, portable: self.artifacts.digest(self.output / portable)})
        self.assertEqual(set(json.loads(after['release-manifest.json'])['artifacts']), {name, portable})
        self.assertEqual({path for path in after if path.startswith('manifests/')},
                         {'manifests/server-build-manifest.json', 'manifests/desktop-build-manifest.json', 'manifests/desktop-verification-report.json'})

    def test_desktop_then_server_is_joined_by_the_deployment_builder_and_keeps_the_desktop_records(self):
        self.export()
        before = self.snapshot()
        value = self.deployment_builder()          # a directory started by the Desktop export is a managed output, not a foreign one
        name, digest = self.server()
        value.manifest['targets']['service'] = dict(status='passed', artifact=name, sha256=digest)
        value.save()
        after = self.snapshot()
        for path, content in before.items():
            if path not in ('release-manifest.json', 'SHA256SUMS.txt'): self.assertEqual(after[path], content, path)
        portable = f"SAP-Lens-Windows-x64-{self.info['version']}.zip"
        self.assertEqual(set(self.sums()), {name, portable})
        self.assertEqual(json.loads(after['build-manifest.json'])['targets']['service']['sha256'], digest)
        self.assertEqual(json.loads(after['manifests/server-build-manifest.json'])['sha256'], digest)

    def test_a_failed_deployment_target_does_not_drop_other_artifacts_from_the_checksum_list(self):
        self.export(); expected = self.sums()
        value = self.deployment_builder()
        value.manifest['targets']['service'] = dict(status='failed', built=False)
        value.save()
        self.assertEqual(self.sums(), expected)
        self.assertFalse((self.output / 'manifests/server-build-manifest.json').exists())

    def test_another_commit_version_or_an_unmanaged_directory_is_refused_without_changes(self):
        self.server(); before = self.snapshot()
        other = dict(self.info, source_sha='b' * 40)
        with patch.object(legacy.local, 'identity', return_value=other), self.assertRaisesRegex(ValueError, 'another version/source'):
            legacy.local.export('0.1.0', self.output, self.root)
        with self.assertRaisesRegex(ValueError, 'another version/source'): self.deployment_builder('b' * 40)
        self.assertEqual(self.snapshot(), before)
        stranger = self.root / 'dist/unmanaged'; stranger.mkdir(); (stranger / 'notes.txt').write_text('keep')
        self.output = stranger
        with self.assertRaisesRegex(ValueError, 'not a managed release directory'): self.export()
        with self.assertRaisesRegex(ValueError, 'managed build output'): self.deployment_builder()
        self.assertEqual(self.snapshot(), {'notes.txt': b'keep'})

    def test_a_second_export_or_a_conflicting_manifest_never_overwrites(self):
        self.export(); before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'already exists'): self.export()
        self.assertEqual(self.snapshot(), before)
        name, digest = self.server()
        with self.assertRaisesRegex(ValueError, 'another artifact'):
            self.artifacts.write_bound_manifest(self.output, 'server', name, 'f' * 64, self.info['version'], self.info['source_sha'], {})
        with self.assertRaisesRegex(ValueError, 'Invalid manifest key'): self.artifacts.bound_manifest_path(self.output, '../desktop')
        self.assertEqual(json.loads((self.output / 'manifests/server-build-manifest.json').read_text())['sha256'], digest)

    def test_a_failed_collection_leaves_inventory_checksums_and_artifacts_as_they_were(self):
        self.server(); before = self.snapshot()
        tampered = self.root / 'backend/build/other.zip'; tampered.write_bytes(b'changed after verification')
        with self.assertRaisesRegex(ValueError, 'verified checksum'):
            self.artifacts.collect(tampered, self.output, self.info['version'], self.info['source_sha'], 'desktop', '0' * 64)
        with patch.object(self.artifacts, 'write_sums', side_effect=OSError('disk full')), self.assertRaises(OSError):
            self.artifacts.collect(tampered, self.output, self.info['version'], self.info['source_sha'], 'desktop', self.artifacts.digest(tampered))
        self.assertFalse((self.output / 'other.zip').exists())
        self.assertEqual({path: content for path, content in self.snapshot().items() if path != 'release-manifest.json'},
                         {path: content for path, content in before.items() if path != 'release-manifest.json'})
