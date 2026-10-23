"""Synthetic-only directory parsing, enrichment, atomic replacement and privacy regressions."""
import csv
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
import cache
from config_models import AppConfig
from employee_directory import HEADERS, parse_directory, store, DirectoryStore
from main import create_app
from portable_config import export_configuration, read_portable, PortableConfig

H = {'X-SAP-Lens': '1'}


class EmployeeDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': str(self.root), 'DATA_CSV_PATH': ''})
        self.env.start(); config.get_settings.cache_clear(); cache.clear_cache(); store.clear()
        self.client = TestClient(create_app(session_token='1'), base_url='http://127.0.0.1:18743')
        self.path = self.root / 'Employee Éxport.csv'
        self.write([{'Name': 'Demo Employee', 'Mail': ' employee@example.test ', 'Enabled': 'true', 'ManagerMail': 'manager@example.test', 'ManagerName': 'Demo Manager'},
                    {'Name': 'Demo Manager', 'Mail': 'manager@example.test', 'Enabled': 'false'}])

    def tearDown(self):
        store.clear(); cache.clear_cache(); config.get_settings.cache_clear(); self.env.stop(); self.temp.cleanup()

    def write(self, rows, headers=HEADERS):
        with self.path.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream, delimiter=';')
            writer.writerow(headers)
            for row in rows: writer.writerow([row.get(key, '') for key in HEADERS])

    def request(self, suffix, **extra):
        return self.client.post('/api/employees/' + suffix, headers=H,
            json=dict(path=str(self.path), revision=config.get_settings().revision, **extra))

    def import_data(self):
        preview = self.request('preview'); self.assertEqual(preview.status_code, 200, preview.text)
        result = self.request('import', digest=preview.json()['digest'])
        self.assertEqual(result.status_code, 200, result.text)
        return result

    def enable(self, value=True):
        settings = config.get_settings().model_copy(deep=True)
        settings.features.employee_directory = value
        config.save_configuration(settings, settings.revision)

    def test_utf8_bom_quotes_trim_and_case_insensitive_headers(self):
        self.write([{'Name': ' Démø; Employee ', 'Mail': ' EMPLOYEE@Example.test '}], [h.lower() for h in HEADERS])
        directory = parse_directory(self.path)
        self.assertEqual(directory.rows[0]['Name'], 'Démø; Employee')
        self.assertEqual(directory.match([' employee@example.TEST '])['status'], 'matched')
        self.assertEqual(directory.match(['employee@example.test'])['employee']['email'], 'EMPLOYEE@Example.test')

    def test_exact_matching_never_uses_names_or_partial_email(self):
        directory = parse_directory(self.path)
        for email in ['employee', 'other@example.test', 'Demo Employee']:
            self.assertEqual(directory.match([email])['status'], 'unmatched')
        self.assertEqual(directory.match(['', ' '])['status'], 'missing_email')
        self.assertEqual(directory.match(['employee@example.test', 'another@example.test'])['status'], 'ambiguous_sap_email')

    def test_duplicate_email_never_selects_a_record(self):
        self.write([{'Mail': 'same@example.test'}, {'Mail': ' SAME@example.test '}])
        directory = parse_directory(self.path)
        self.assertEqual(directory.match(['same@example.test']), dict(status='duplicate_email', employee=None))
        self.assertEqual(directory.report()['duplicate_emails'], 1)

    def test_manager_resolution_and_account_status(self):
        directory = parse_directory(self.path)
        employee = directory.match(['employee@example.test'])['employee']
        self.assertEqual(employee['manager']['employee_id'], '1')
        self.assertEqual(employee['account_status'], 'Enabled')
        self.assertEqual(directory.view(directory.rows[1])['account_status'], 'Disabled')

    def test_manager_missing_ambiguous_self_and_cycle_are_bounded(self):
        for rows, expected in [
            ([{'Mail': 'a@example.test'}], 'missing'),
            ([{'Mail': 'a@example.test', 'ManagerMail': 'missing@example.test'}], 'unresolved'),
            ([{'Mail': 'a@example.test', 'ManagerMail': 'a@example.test'}], 'self_reference'),
            ([{'Mail': 'a@example.test', 'ManagerMail': 'b@example.test'}, {'Mail': 'b@example.test'}, {'Mail': 'B@example.test'}], 'ambiguous'),
            ([{'Mail': 'a@example.test', 'ManagerMail': 'b@example.test'}, {'Mail': 'b@example.test', 'ManagerMail': 'a@example.test'}], 'resolved')]:
            with self.subTest(expected=expected):
                self.write(rows); directory = parse_directory(self.path)
                self.assertEqual(directory.view(directory.rows[0])['manager']['status'], expected)

    def test_manager_dn_and_username_fallback_require_unique_keys(self):
        for source, target in [('ManagerDN', 'DistinguishedName'), ('ManagerSamAccountName', 'SamAccountName')]:
            self.write([{source: 'DEMO_KEY'}, {target: 'demo_key'}])
            directory = parse_directory(self.path)
            self.assertEqual(directory.manager(directory.rows[0])[0], 'resolved')
        self.write([{'ManagerMail': 'absent@example.test', 'ManagerSamAccountName': 'key'}, {'SamAccountName': 'key'}])
        directory = parse_directory(self.path)
        self.assertEqual(directory.manager(directory.rows[0])[0], 'unresolved')

    def test_invalid_headers_empty_invalid_utf8_and_malformed_rows(self):
        for text in ['', ';'.join(HEADERS), 'Name;Mail\nDemo;demo@example.test', ';'.join(HEADERS) + '\nToo;few', ';'.join(HEADERS) + '\n"unterminated']:
            with self.subTest(text=text[:20]):
                self.path.write_text(text, encoding='utf-8')
                self.assertEqual(self.request('preview').status_code, 400)
        self.path.write_bytes(b'\xff\xfe')
        self.assertEqual(self.request('preview').status_code, 400)

    def test_preview_is_not_published_confirmation_requires_matching_digest(self):
        preview = self.request('preview').json()
        self.assertIsNone(store.directory)
        self.assertEqual(config.get_settings().employee_csv_path, '')
        self.assertEqual(self.request('import').status_code, 409)
        self.write([{'Name': 'Changed', 'Mail': 'changed@example.test'}])
        self.assertEqual(self.request('import', digest=preview['digest']).status_code, 409)
        self.assertIsNone(store.directory)

    def test_atomic_failed_replacement_and_stale_settings_preserve_previous(self):
        self.import_data(); previous = store.directory
        self.path.write_text('invalid', encoding='utf-8')
        self.assertEqual(self.request('import', digest='0' * 64).status_code, 400)
        self.assertIs(store.directory, previous)
        self.assertEqual(config.get_settings().employee_csv_path, str(self.path))
        self.write([{'Name': 'New', 'Mail': 'new@example.test'}]); preview = self.request('preview').json()
        response = self.client.post('/api/employees/import', headers=H, json=dict(path=str(self.path), digest=preview['digest'], revision=0))
        self.assertEqual(response.status_code, 409)
        self.assertIs(store.directory, previous)

    def test_disabled_reenabled_and_restart_restores_private_snapshot(self):
        self.import_data()
        self.assertEqual(self.client.get('/api/employees', headers=H).json()['total'], 0)
        self.enable(); self.assertEqual(self.client.get('/api/employees', headers=H).json()['total'], 2)
        self.enable(False); self.assertIsNotNone(store.directory)
        self.enable(); store.clear()
        self.assertEqual(self.client.get('/api/employees', headers=H).json()['total'], 2)
        self.assertFalse(any('Demo Employee' in p.read_text(errors='ignore') for p in self.root.glob('*.json')))

    def test_optional_health_disabled_unconfigured_and_enabled_failure(self):
        self.assertEqual(self.client.get('/api/employees/status', headers=H).json()['status'], 'disabled')
        self.enable(); self.assertEqual(self.client.get('/api/employees/status', headers=H).json()['status'], 'not_configured')
        self.import_data(); store.clear(); self.path.unlink()
        status = self.client.get('/api/employees/status', headers=H).json()
        self.assertEqual(status['status'], 'healthy')
        self.assertTrue(status['persisted'])
        self.assertEqual(self.client.get('/health').status_code, 200)
        self.assertEqual(self.client.get('/api/access/users', headers=H).status_code, 200)

    def test_diagnostics_export_excludes_personal_data_and_paths(self):
        self.import_data(); self.enable()
        response = self.client.get('/api/diagnostics/export', headers=H)
        self.assertEqual(response.status_code, 200)
        for private in [str(self.path), self.path.name, 'Demo Employee', 'employee@example.test']:
            self.assertNotIn(private, response.text)
        self.assertEqual(response.json()['employee_directory']['report']['records'], 2)

    def test_clear_preserves_original_file_and_feature_setting(self):
        from employee_directory import snapshot_path
        self.import_data(); self.enable()
        snapshot=snapshot_path(config.get_settings().employee_snapshot_id)
        self.assertEqual(self.request('clear').status_code, 200)
        self.assertTrue(self.path.exists()); self.assertIsNone(store.directory)
        self.assertFalse(snapshot.exists())
        self.assertTrue(config.get_settings().features.employee_directory)
        self.assertEqual(config.get_settings().employee_csv_path, '')

    def test_search_pagination_manager_navigation_and_generation_guard(self):
        self.import_data(); self.enable()
        result = self.client.get('/api/employees?search=manager&limit=1', headers=H).json()
        self.assertEqual(result['total'], 2); self.assertEqual(len(result['items']), 1)
        response = self.client.get('/api/employees/record/1?generation=' + result['generation'], headers=H)
        self.assertEqual(response.json()['name'], 'Demo Manager')
        self.assertEqual(self.client.get('/api/employees/record/1?generation=' + '0' * 64, headers=H).status_code, 409)
        self.assertEqual(self.client.get('/api/employees/record/-1?generation=' + result['generation'], headers=H).status_code, 404)

    def test_source_cannot_bypass_preview_through_generic_configuration(self):
        settings = config.get_settings().model_dump(); settings['employee_csv_path'] = str(self.path)
        self.assertEqual(self.client.post('/api/configuration', json=settings, headers=H).status_code, 400)

    def test_legacy_configuration_and_portable_privacy(self):
        old = AppConfig().model_dump(); old.pop('features'); old.pop('employee_csv_path')
        self.assertFalse(AppConfig.model_validate(old).features.employee_directory)
        settings = AppConfig(employee_csv_path=str(self.path)); settings.features.employee_directory = True
        exported = export_configuration(settings, include_private=True)
        self.assertEqual(exported['settings']['employee_csv_path'], '')
        package = PortableConfig.model_validate(exported)
        self.assertTrue(read_portable(package, '').features.employee_directory)

    def test_session_and_bounds_preserved(self):
        self.assertEqual(self.client.get('/api/employees', headers={'X-SAP-Lens': 'wrong'}).status_code, 403)
        self.assertEqual(self.client.get('/api/employees?limit=101', headers=H).status_code, 422)
        self.assertEqual(self.client.get('/api/employees?offset=-1', headers=H).status_code, 422)
        with patch('employee_directory.MAX_BYTES', 2):
            self.assertEqual(self.request('preview').status_code, 400)
        self.assertEqual(self.client.get('/api/employees/match/DEMO', headers=H).json()['status'], 'directory_unavailable')

    def test_store_retains_last_valid_data_after_failed_read(self):
        local = DirectoryStore(); previous = local.get(str(self.path))
        missing = str(self.root / 'missing.csv')
        self.assertIs(local.get(missing), previous)
        self.assertIsNotNone(local.error)

    def test_sap_email_match_integration_and_optional_isolation(self):
        users = self.root / 'users.csv'
        users.write_text('USERNAME,ROLE_NAME,EMAIL\nDEMO_MATCH,, EMPLOYEE@example.test \nDEMO_MISSING,,\nDEMO_UNKNOWN,,unmatched@example.test\n', encoding='utf-8')
        settings = config.get_settings().model_dump(); settings['user_csv_path'] = str(users)
        self.assertEqual(self.client.post('/api/configuration', headers=H, json=settings).status_code, 200)
        self.import_data(); self.enable()
        for username, status in [('DEMO_MATCH', 'matched'), ('DEMO_MISSING', 'missing_email'), ('DEMO_UNKNOWN', 'unmatched')]:
            self.assertEqual(self.client.get('/api/employees/match/' + username, headers=H).json()['status'], status)
        user = self.client.get('/api/access/users/DEMO_MATCH', headers=H).json()
        self.assertEqual(user['email'], 'EMPLOYEE@example.test')
        self.enable(False)
        self.assertEqual(self.client.get('/api/access/users/DEMO_MATCH', headers=H).json(), user)

    def test_clear_invalidates_in_flight_read_without_blocking(self):
        import threading
        local = DirectoryStore()
        started, finish = threading.Event(), threading.Event()
        candidate = parse_directory(self.path)
        def slow(_):
            started.set(); finish.wait(2); return candidate
        with patch('employee_directory.parse_directory', side_effect=slow):
            worker = threading.Thread(target=local.get, args=(str(self.path),))
            worker.start(); self.assertTrue(started.wait(1)); local.clear(); finish.set(); worker.join(2)
        self.assertIsNone(local.directory)
        self.assertIsNone(local.attempted_path)

    def test_restart_restores_confirmed_snapshot_without_original_csv(self):
        from employee_directory import snapshot_path
        imported = self.import_data().json()
        self.assertFalse(imported['enabled']); self.assertTrue(imported['persisted'])
        identity = config.get_settings().employee_snapshot_id
        self.assertTrue(snapshot_path(identity).is_file())
        self.path.unlink(); store.clear(); config.get_settings.cache_clear()
        disabled = self.client.get('/api/employees/status', headers=H).json()
        self.assertTrue(disabled['loaded']); self.assertFalse(disabled['enabled'])
        self.assertEqual(disabled['report']['imported_at'], imported['report']['imported_at'])
        self.enable(); store.clear(); config.get_settings.cache_clear()
        restored = self.client.get('/api/employees', headers=H).json()
        self.assertEqual(restored['total'], 2)
        # A new Python process reads actual on-disk settings and snapshot, not globals.
        import subprocess
        result = subprocess.run([sys.executable, '-c',
            'from config import get_settings; from employee_directory import DirectoryStore; s=get_settings(); assert s.features.employee_directory; d=DirectoryStore().get(s.employee_csv_path,s.employee_snapshot_id); assert len(d.rows)==2'],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_failed_snapshot_or_settings_write_preserves_last_import(self):
        from employee_directory import snapshot_path
        self.import_data(); previous=store.directory; identity=config.get_settings().employee_snapshot_id
        self.write([{'Name':'Replacement','Mail':'new@example.test'}]); preview=self.request('preview').json()
        for target in ['routers.employees.persist_directory','routers.employees.save_configuration']:
            with self.subTest(target=target), patch(target, side_effect=OSError('private details')):
                result=self.request('import',digest=preview['digest'])
                self.assertEqual(result.status_code,409); self.assertNotIn('private details',result.text)
                self.assertIs(store.directory,previous)
                self.assertEqual(config.get_settings().employee_snapshot_id,identity)
                self.assertTrue(snapshot_path(identity).exists())
        self.assertEqual(len(list((self.root/'employee-directory').glob('*.json'))),1)

    def test_corrupt_snapshot_is_optional_failure_and_does_not_leak_contents(self):
        from employee_directory import snapshot_path
        self.import_data(); self.enable()
        snapshot_path(config.get_settings().employee_snapshot_id).write_text('private malformed data')
        store.clear()
        result=self.client.get('/api/employees/status',headers=H)
        self.assertEqual(result.json()['status'],'error'); self.assertNotIn('private malformed',result.text)
        self.assertEqual(self.client.get('/health').status_code,200)
        self.assertEqual(self.client.get('/api/roles',headers=H).status_code,200)

    def test_mapping_disabled_preserves_data_dependencies_and_reenables_without_reimport(self):
        users=self.root/'users.csv'
        users.write_text('USERNAME,ROLE_NAME,EMAIL\nDEMO_EMPLOYEE,ZC:FI:VIEW,employee@example.test\n',encoding='utf-8')
        current=config.get_settings().model_dump(); current['user_csv_path']=str(users)
        self.assertEqual(self.client.post('/api/configuration',headers=H,json=current).status_code,200)
        self.import_data(); self.enable(); identity=config.get_settings().employee_snapshot_id
        self.assertEqual(self.client.get('/api/employees/status',headers=H).json()['coverage']['matched'],1)
        current=config.get_settings().model_dump(); current['features']['user_role_mapping']=False
        self.assertEqual(self.client.post('/api/configuration',headers=H,json=current).status_code,200)
        config.get_settings.cache_clear()
        self.assertFalse(config.get_settings().features.user_role_mapping)
        import subprocess
        restarted=subprocess.run([sys.executable,'-c',
            'from config import get_settings; import cache; from employee_directory import DirectoryStore; s=get_settings(); assert not s.features.user_role_mapping and s.features.employee_directory; cache.load_cache(); assert len(cache.get_snapshot().users.users)==1; assert len(DirectoryStore().get(s.employee_csv_path,s.employee_snapshot_id).rows)==2'],
            cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
        self.assertEqual(restarted.returncode,0,restarted.stderr)
        for endpoint in ['users','users/DEMO_EMPLOYEE','releases','release-options?field=group','release-assignments']:
            result=self.client.get('/api/access/'+endpoint,headers=H)
            self.assertEqual(result.status_code,409); self.assertIn('disabled',result.json()['detail'])
        status=self.client.get('/api/employees/status',headers=H).json()
        self.assertTrue(status['enabled']); self.assertTrue(status['loaded']); self.assertFalse(status['dependency_satisfied'])
        self.assertEqual(status['coverage'],{}); self.assertIn('Enable User–Role Mapping',status['coverage_reason'])
        self.assertEqual(self.client.get('/api/employees/match/DEMO_EMPLOYEE',headers=H).json()['status'],'mapping_unavailable')
        diagnostics=self.client.get('/api/diagnostics',headers=H).json()
        self.assertFalse(next(s for s in diagnostics['sources'] if s['id']=='users')['enabled'])
        self.assertEqual(self.client.get('/health').status_code,200)
        current=config.get_settings().model_dump(); current['features']['user_role_mapping']=True
        self.assertEqual(self.client.post('/api/configuration',headers=H,json=current).status_code,200)
        self.assertEqual(config.get_settings().employee_snapshot_id,identity)
        self.assertEqual(self.client.get('/api/access/users',headers=H).json()['total'],1)
        self.assertEqual(self.client.get('/api/employees/status',headers=H).json()['coverage']['matched'],1)

    def test_manager_sap_resolution_is_unique_exact_email_never_ad_username(self):
        users=self.root/'users.csv'
        for rows,expected in [
            ('DEMO_EMPLOYEE,,employee@example.test\nSAP_MANAGER,, MANAGER@example.TEST \n','matched'),
            ('DEMO_EMPLOYEE,,employee@example.test\nDemo_Manager,,other@example.test\n','unmatched'),
            ('DEMO_EMPLOYEE,,employee@example.test\nSAP_ONE,,manager@example.test\nSAP_TWO,,MANAGER@example.test\n','ambiguous')]:
            with self.subTest(expected=expected):
                users.write_text('USERNAME,ROLE_NAME,EMAIL\n'+rows,encoding='utf-8')
                current=config.get_settings().model_dump(); current['user_csv_path']=str(users)
                self.assertEqual(self.client.post('/api/configuration',headers=H,json=current).status_code,200)
                cache.load_cache()
                self.import_data(); self.enable()
                result=self.client.get('/api/employees/match/DEMO_EMPLOYEE',headers=H).json()['manager_sap']
                self.assertEqual(result['status'],expected)
                self.assertEqual(result['username'],'SAP_MANAGER' if expected=='matched' else None)
        self.write([{'Mail':'employee@example.test','ManagerName':'SAP_MANAGER','ManagerSamAccountName':'SAP_MANAGER'}]); self.import_data()
        self.assertEqual(self.client.get('/api/employees/match/DEMO_EMPLOYEE',headers=H).json()['manager_sap']['status'],'missing_email')

    def test_missing_email_is_warning_and_snapshot_never_in_portable_settings(self):
        self.write([{'Name':'No email'}]); self.import_data(); self.enable()
        status=self.client.get('/api/employees/status',headers=H).json()
        self.assertEqual(status['report']['records'],1); self.assertEqual(status['report']['missing_emails'],1)
        self.assertEqual(status['status'],'warning')
        exported=export_configuration(config.get_settings(),include_private=True)
        self.assertIsNone(exported['settings']['employee_snapshot_id'])
        bad=exported.copy(); bad['settings']=dict(exported['settings'],employee_snapshot_id='0'*64)
        with self.assertRaises(ValueError): read_portable(PortableConfig.model_validate(bad),'')

    def test_disabled_missing_mapping_source_does_not_block_catalogue_restart(self):
        roles=self.root/'roles.csv'
        roles.write_text('FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,TCODE\nMM,ZC:DEMO,Demo,ZS:DEMO,MIGO\n')
        settings=config.get_settings().model_copy(deep=True)
        settings.data_csv_path=str(roles); settings.user_csv_path=str(self.root/'missing.csv')
        settings.features.user_role_mapping=False
        config.save_configuration(settings,settings.revision); cache.clear_cache(); config.get_settings.cache_clear()
        cache.load_cache()
        self.assertEqual(len(cache.get_snapshot().roles),1)
        self.assertEqual(self.client.get('/health').json()['status'],'ok')
        self.assertEqual(self.client.get('/api/roles',headers=H).status_code,200)
        self.assertEqual(self.client.get('/api/access/users',headers=H).status_code,409)

    def test_legacy_missing_file_stays_recoverable_without_snapshot_or_core_failure(self):
        settings=config.get_settings().model_copy(deep=True)
        settings.employee_csv_path=str(self.root/'unavailable.csv'); settings.features.employee_directory=True
        config.save_configuration(settings,settings.revision);store.clear();config.get_settings.cache_clear()
        status=self.client.get('/api/employees/status',headers=H).json()
        self.assertTrue(status['configured']);self.assertFalse(status['loaded'])
        self.assertEqual(status['storage'],'legacy_path_only');self.assertEqual(status['status'],'error')
        self.assertEqual(self.client.get('/health').status_code,200)
