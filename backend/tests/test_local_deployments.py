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
    spec=importlib.util.spec_from_file_location(name.replace('-','_'),ROOT/'scripts'/f'{name}.py')
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
            result=subprocess.run([sys.executable,str(ROOT/'scripts/build-deployments.py'),*args],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertIn('error:',result.stderr)
        result=subprocess.run([str(ROOT/'build.sh'),'--help'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0);self.assertIn('--windows-host',result.stdout)

    def test_ci_admission_cannot_use_a_local_receipt(self):
        with patch.dict(os.environ,{'GITHUB_ACTIONS':'true'}),patch.object(pkg,'require_ci',side_effect=ValueError('CI receipt required')) as ci,patch.object(pkg,'local_tools') as local:
            with self.assertRaises(ValueError):pkg.require_inputs()
            ci.assert_called_once();local.assert_not_called()

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
            if row['stage']=='browser':row['status']='failed'
        timing.write_text('\n'.join(map(json.dumps,data)))
        with self.assertRaises(ValueError):pkg.record_local()
        for row in data:row['status']='passed'
        timing.write_text('\n'.join(map(json.dumps,data)))
        (self.root/'frontend/dist/private.csv').write_text('private')
        with self.assertRaises(ValueError):pkg.record_local()
