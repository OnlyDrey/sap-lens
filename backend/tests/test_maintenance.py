"""Private backup/restore use disposable data only; never operate on a real installation."""
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
        ops.ensure_upgrade('0.1.0-dev.123', '0.1.0-dev.123.2')
        ops.ensure_upgrade('0.1.0-dev.123.2', '0.1.0-beta.1')
        with self.assertRaises(ValueError): ops.ensure_upgrade('0.1.0-dev.123.2', '0.1.0-dev.123')
        with self.assertRaises(ValueError): ops.version_key('0.1.0-beta.1.2')

    def test_backup_cli_reports_no_records_or_credentials(self):
        report=self.root/'report.json'
        result=ops.cli(['backup','--data',str(self.root/'unknown'),'--output',str(self.archive),'--application-version','0.1.0','--report',str(report)])
        self.assertEqual(result,1);value=json.loads(report.read_text())
        self.assertEqual(set(value),{'status','action','category','message','recovery'})
        self.assertNotIn('synthetic-only',report.read_text())

    def test_restore_holds_runtime_lease_before_copying_records(self):
        self.create();target=self.root/'restore-locked';configuration=self.root/'restore-config'
        original=ops.tarfile.open;seen=[]
        def inspect(*args,**kwargs):
            if target.exists():
                with self.assertRaises(RuntimeError): StorageLease(target,'server',initialize=False).acquire()
                seen.append(True)
            return original(*args,**kwargs)
        with patch.object(ops.tarfile,'open',side_effect=inspect):
            ops.restore(self.archive,target,'server','0.1.0',configuration,True)
        self.assertTrue(seen)
        lease=StorageLease(target,'server').acquire();lease.close()

    def test_restore_rechecks_copied_hashes_if_archive_changes_after_verification(self):
        self.create();manifest=ops.verify(self.archive,'server','0.1.0')
        with tarfile.open(self.archive) as source:
            payload=[(item.name,source.extractfile(item).read(),tarfile.REGTYPE) for item in source.getmembers()]
        bad=self.altered([(name,b'changed after verification' if name=='data/settings.json' else content,kind) for name,content,kind in payload])
        target=self.root/'restored-tampered'
        with patch.object(ops,'verify',return_value=manifest),self.assertRaises(ops.MaintenanceError):
            ops.restore(bad,target,'server','0.1.0',self.root/'restored-config',True)
        self.assertFalse((target/'settings.json').exists())

    def test_confirmed_purge_requires_stopped_owned_store_and_preserves_external_backups(self):
        self.create();before=(self.data/'settings.json').read_bytes()
        with self.assertRaises(ops.MaintenanceError):ops.purge(self.data,'server')
        lease=StorageLease(self.data,'server').acquire()
        try:
            with self.assertRaises(RuntimeError):ops.purge(self.data,'server',True)
        finally:lease.close()
        self.assertEqual((self.data/'settings.json').read_bytes(),before)
        (self.data/'nested').mkdir();(self.data/'nested/private.txt').write_text('synthetic')
        result=ops.purge(self.data,'server',True)
        self.assertTrue(result['purged']);self.assertTrue(self.archive.exists())
        self.assertEqual({p.name for p in self.data.iterdir()},{'.sap-lens-instance.lock'})


class WindowsToolResolution(unittest.TestCase):
    """The packaged Desktop (and its smoke test) runs with PATH limited to System32 and the Windows folder, which does not contain powershell.exe.
    A bare 'powershell' made the mandatory pre-migration backup fail (`storage_upgrade: backup_failed`)."""

    def system_root(self):
        import tempfile
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / 'Windows'
        (root / 'System32' / 'WindowsPowerShell' / 'v1.0').mkdir(parents=True)
        (root / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe').write_text('')
        (root / 'System32' / 'icacls.exe').write_text('')
        return root

    def test_tools_resolve_to_absolute_system_paths_without_relying_on_path(self):
        import os
        from unittest.mock import patch
        root = self.system_root()
        with patch.dict(os.environ, {'SystemRoot': str(root), 'PATH': str(root / 'System32')}):
            self.assertEqual(ops.windows_tool('powershell'), str(root / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'))
            self.assertEqual(ops.windows_tool('icacls.exe'), str(root / 'System32' / 'icacls.exe'))
            self.assertEqual(ops.windows_tool('missing.exe'), 'missing.exe')

    def test_owner_lookup_uses_the_absolute_powershell_under_a_minimal_path(self):
        import os
        from unittest.mock import patch
        root = self.system_root()
        calls = []

        def output(command, **kwargs):
            calls.append(command[0]); return 'S-1-5-21-1-2-3-1001\n'
        with patch.dict(os.environ, {'SystemRoot': str(root), 'PATH': str(root / 'System32')}), patch.object(ops.subprocess, 'check_output', output):
            self.assertEqual(ops.current_sid(), 'S-1-5-21-1-2-3-1001')
        self.assertEqual(len(calls), 1)
        self.assertTrue(Path(calls[0]).is_absolute() and calls[0].endswith('powershell.exe'), calls)
        sources = [(Path(ops.__file__).parent / name).read_text(encoding='utf-8') for name in ('maintenance.py', 'application_backups.py')]
        self.assertFalse(any("['powershell'" in text or "['icacls.exe'" in text for text in sources), 'no bare system tool names on the packaged path')
