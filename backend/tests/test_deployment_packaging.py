"""Offline integrity, admission and platform orchestration regression tests."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import subprocess
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('deploy_packages',ROOT/'scripts/deployment-package.py')
pkg=importlib.util.module_from_spec(spec);spec.loader.exec_module(pkg)


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.info=pkg.make_build_info('build','0.1.0','a'*40,'123','9',1)
    def tearDown(self):self.temp.cleanup()
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
            if mutation=='checks':current['checks'].remove('browser')
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
        records=[dict(stage=name,status='failed' if name=='browser' else 'passed') for name in pkg.CHECKS]
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
    def test_all_platforms_are_independent_and_build_only(self):
        spec=importlib.util.spec_from_file_location('workflow_rules',ROOT/'scripts/check-workflows.py')
        rules=importlib.util.module_from_spec(spec);spec.loader.exec_module(rules)
        current=rules.load_workflows();rules.validate(current)
        for key in ('desktop','service','docker','native'):
            self.assertEqual(current['build-deployments.yml']['jobs'][key]['needs'],'validation')
        bad=copy.deepcopy(current);bad['build-deployments.yml']['jobs']['native']['needs']='docker'
        with self.assertRaises(ValueError):rules.validate(bad)
        bad=copy.deepcopy(current);bad['build-deployments.yml']['on']['push']=''
        with self.assertRaises(ValueError):rules.validate(bad)
