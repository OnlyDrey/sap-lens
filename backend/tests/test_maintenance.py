"""Private backup/restore use disposable data only; never operate on a real installation."""
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import maintenance as ops
from storage_lease import StorageLease


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name);self.data=self.root/'data';self.data.mkdir()
        (self.data/'deployment.json').write_text(json.dumps({'version':1,'mode':'server'}))
        (self.data/'settings.json').write_text(json.dumps({'schema_version':3,'data_csv_path':'synthetic-only'}))
        (self.data/'saved-filters.json').write_text('{"synthetic":true}')
        (self.data/'account-review.json').write_text('{"decision":"synthetic"}')
        (self.data/'runtime.json').write_text('{"token":"do-not-back-up"}')
        (self.data/'sap-lens.log').write_text('not required for recovery')
        self.config=self.root/'config';self.config.mkdir();(self.config/'server.env').write_text('SAP_LENS_AUTH=local\n')
        self.archive=self.root/'backups'/'synthetic.sap-lens-backup.tar.gz'

    def create(self):return ops.backup(self.data,self.archive,'server','0.1.0-beta.1',self.config)

    def test_backup_verify_restore_preserve_datasets_settings_reviews_and_config(self):
        result=self.create();self.assertEqual(result['sha256'],ops.digest(self.archive))
        manifest=ops.verify(self.archive,'server','0.1.0')
        self.assertIn('data/saved-filters.json',manifest['files']);self.assertIn('data/account-review.json',manifest['files'])
        self.assertNotIn('data/runtime.json',manifest['files']);self.assertNotIn('data/sap-lens.log',manifest['files'])
        self.assertIn('config/server.env',manifest['files'])
        restored=self.root/'restored';config=self.root/'restored-config'
        ops.restore(self.archive,restored,'server','0.1.0',config,True)
        self.assertEqual((restored/'settings.json').read_bytes(),(self.data/'settings.json').read_bytes())
        self.assertEqual((config/'server.env').read_bytes(),(self.config/'server.env').read_bytes())
        if os.name!='nt':self.assertEqual(self.archive.stat().st_mode&0o777,0o600)

    def test_restore_refuses_nonempty_store_wrong_mode_downgrade_or_missing_confirmation(self):
        self.create();original=(self.data/'settings.json').read_bytes()
        for kwargs in [dict(confirm=False),dict(confirm=True),dict(confirm=True,mode='desktop'),dict(confirm=True,target_version='0.0.9')]:
            options=dict(archive=self.archive,data=self.data,mode='server',target_version='0.1.0',config=self.config)
            options.update(kwargs)
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):ops.restore(**options)
        self.assertEqual((self.data/'settings.json').read_bytes(),original)

    def test_running_store_cannot_be_backed_up(self):
        lease=StorageLease(self.data,'server').acquire()
        try:
            with self.assertRaises(RuntimeError):self.create()
        finally:lease.close()
        self.assertFalse(self.archive.exists())

    def test_backup_no_overwrite_external_links_or_nested_output(self):
        self.create();before=self.archive.read_bytes()
        with self.assertRaises(ValueError):self.create()
        self.assertEqual(self.archive.read_bytes(),before)
        self.archive.unlink()
        with self.assertRaises(ValueError):ops.backup(self.data,self.data/'nested.tar.gz','server','0.1.0')
        if os.name!='nt':
            (self.data/'external').symlink_to(self.config/'server.env')
            with self.assertRaises(ValueError):self.create()
            self.assertFalse(self.archive.exists())

    def altered(self,names):
        bad=self.root/'bad.tar.gz'
        with tarfile.open(bad,'w:gz') as output:
            for name,value,kind in names:
                item=tarfile.TarInfo(name);item.type=kind;item.size=len(value)
                output.addfile(item,io.BytesIO(value))
        return bad

    def test_unsafe_duplicate_corrupt_and_future_schema_backups_rejected(self):
        self.create()
        with tarfile.open(self.archive) as source:
            payload=[(item.name,source.extractfile(item).read(),tarfile.REGTYPE) for item in source.getmembers()]
        cases=[payload+[('../outside',b'bad',tarfile.REGTYPE)],payload+[payload[0]],
               payload+[('data/link',b'target',tarfile.SYMTYPE)],
               [(name,b'changed' if name=='data/settings.json' else content,kind) for name,content,kind in payload]]
        for rows in cases:
            with self.subTest(rows=len(rows)),self.assertRaises((ValueError,tarfile.TarError)):
                ops.verify(self.altered(rows),'server','0.1.0')
        future=[]
        for name,content,kind in payload:
            if name=='manifest.json':
                value=json.loads(content);value['settings_schema']=999;content=json.dumps(value).encode()
            future.append((name,content,kind))
        with self.assertRaises(ValueError):ops.verify(self.altered(future),'server','0.1.0')

    def test_legacy_backup_requires_explicit_consent_and_does_not_delete_data(self):
        (self.data/'deployment.json').unlink()
        with self.assertRaises(ValueError):ops.backup(self.data,self.archive,'desktop','0.1.0')
        ops.backup(self.data,self.archive,'desktop','0.1.0',allow_legacy=True)
        self.assertTrue((self.data/'saved-filters.json').exists())
        self.assertEqual(json.loads((self.data/'deployment.json').read_text())['mode'],'desktop')

    def test_version_ordering_supports_legacy_and_semver_but_rejects_downgrades(self):
        order=['0.0.0-dev.local','0.1.0-alpha.1','0.1.0-beta-1','0.1.0-beta.2','0.1.0-rc.1','0.1.0','0.1.1']
        for previous,target in zip(order,order[1:]):
            ops.ensure_upgrade(previous,target)
            with self.assertRaises(ValueError):ops.ensure_upgrade(target,previous)
        self.assertEqual(ops.version_key('0.1.0-beta-4'),ops.version_key('0.1.0-beta.4'))

    def test_backup_cli_reports_no_records_or_credentials(self):
        report=self.root/'report.json'
        result=ops.cli(['backup','--data',str(self.root/'unknown'),'--output',str(self.archive),'--application-version','0.1.0','--report',str(report)])
        self.assertEqual(result,1);value=json.loads(report.read_text())
        self.assertEqual(set(value),{'status','action','category','message','recovery'})
        self.assertNotIn('synthetic-only',report.read_text())
