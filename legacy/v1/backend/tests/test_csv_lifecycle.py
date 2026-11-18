"""Synthetic full replacements, durable recovery and partial refresh evidence."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cache
import config
from csv_lifecycle import load, diff_records, history, read_private
from employee_directory import HEADERS, store


class CsvLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': str(self.root / 'config'), 'DATA_CSV_PATH': ''})
        self.env.start(); config.get_settings.cache_clear(); cache.clear_cache(); store.clear()
        self.roles, self.users, self.directory = [self.root / name for name in ('roles.csv', 'users.csv', 'directory.csv')]
        self.roles.write_text('AGR_NAME,TEXT,TCODE\nZC:DEMO,Demo,MIGO\n', encoding='utf-8')
        self.users.write_text('USERNAME,ROLE_NAME,EMAIL,ROLE_VALID_FROM,ROLE_VALID_TO\nDEMO_A,ZC:DEMO,a@example.test,20200101,99991231\nDEMO_B,ZC:DEMO,b@example.test,20200101,99991231\n', encoding='utf-8')
        import csv
        with self.directory.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=HEADERS, delimiter=';'); writer.writeheader()
            for name in ('A', 'B'):
                writer.writerow(dict(Name='Example ' + name, SamAccountName='demo_' + name, Mail=name.lower()+'@example.test', Enabled='true'))
        settings = config.get_settings().model_copy(deep=True)
        settings.data_csv_path, settings.user_csv_path, settings.employee_csv_path = map(str, (self.roles, self.users, self.directory))
        settings.features.employee_directory = True
        settings.source_modes.employees = 'dynamic'
        config.save_configuration(settings, settings.revision)

    def tearDown(self):
        cache.clear_cache(); store.clear(); config.get_settings.cache_clear(); self.env.stop(); self.temp.cleanup()

    def test_full_replacement_removes_users_directory_records_and_indexes(self):
        first = load()
        self.assertEqual(first['updated'], 3)
        lines = self.users.read_text().splitlines(); self.users.write_text('\n'.join(lines[:2])+'\n')
        lines = self.directory.read_text().splitlines(); self.directory.write_text('\n'.join(lines[:2])+'\n')
        self.roles.write_text('AGR_NAME,TEXT,TCODE\nZC:DEMO,Demo,ME21N\n')
        result = load()
        self.assertEqual(set(cache.get_snapshot().users.users), {'DEMO_A'})
        self.assertEqual(cache.get_snapshot().users.assignments[0]['tcodes'], ['ME21N'])
        self.assertNotIn('MIGO', cache.get_snapshot().tcode_index)
        self.assertEqual(len(store.directory.rows), 1)
        self.assertNotIn('b@example.test', store.directory.indexes['Mail'])
        self.assertEqual(next(r for r in result['sources'] if r['source']=='employees')['removed'], 1)

    def test_reordering_is_unchanged_and_does_not_publish_a_new_generation(self):
        load(); previous = cache.get_snapshot()
        lines = self.users.read_text().splitlines(); self.users.write_text('\n'.join([lines[0], *reversed(lines[1:])])+'\n')
        result = load()
        self.assertEqual(result['status'], 'unchanged')
        self.assertIs(cache.get_snapshot(), previous)
        self.assertEqual(result['unchanged'], 3)

    def test_independent_failure_keeps_old_users_and_rebinds_new_catalogue(self):
        load()
        self.users.write_text('WRONG\ninvalid\n')
        self.roles.write_text('AGR_NAME,TEXT,TCODE\nZC:DEMO,Updated,ME21N\n')
        result = load()
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['failed'], 1)
        self.assertEqual(set(cache.get_snapshot().users.users), {'DEMO_A', 'DEMO_B'})
        self.assertEqual(cache.get_snapshot().users.assignments[0]['tcodes'], ['ME21N'])
        self.assertEqual(next(r for r in result['sources'] if r['source']=='users')['category'], 'headers')

    def test_restart_recovers_snapshots_when_original_files_are_missing(self):
        load(); revision = cache.get_snapshot().last_loaded
        for path in (self.roles, self.users, self.directory): path.unlink()
        cache.clear_cache(); store.clear(); config.get_settings.cache_clear()
        result = load(operation='startup')
        self.assertEqual(result['failed'], 3)
        self.assertEqual(len(cache.get_snapshot().users.users), 2)
        self.assertEqual(len(cache.get_snapshot().roles), 1)
        self.assertEqual(len(store.directory.rows), 2)
        self.assertEqual(cache.get_snapshot().last_loaded, revision)

    def test_static_and_disabled_sources_are_not_read_and_preferences_survive(self):
        load()
        settings = config.get_settings().model_copy(deep=True)
        settings.source_modes.roles = settings.source_modes.users = settings.source_modes.employees = 'static'
        settings.features.user_role_mapping = False
        config.save_configuration(settings, settings.revision)
        for path in (self.roles, self.users, self.directory): path.unlink()
        cache.clear_cache(); store.clear(); config.get_settings.cache_clear()
        result = load(operation='startup')
        self.assertEqual(result['skipped'], 3); self.assertEqual(result['failed'], 0)
        self.assertEqual(len(cache.get_snapshot().users.users), 2)
        self.assertFalse(config.get_settings().features.user_role_mapping)
        settings = config.get_settings().model_copy(deep=True); settings.features.user_role_mapping = True
        config.save_configuration(settings, settings.revision)
        self.assertEqual(len(cache.get_snapshot().users.users), 2)

    def test_transaction_failure_keeps_settings_and_all_active_datasets(self):
        load(); before = cache.get_snapshot(); directory = store.directory
        saved = config.get_settings().model_dump()
        self.roles.write_text('AGR_NAME,TCODE\nZC:NEW,ME21N\n')
        with patch('csv_lifecycle.save_configuration', side_effect=PermissionError('private location')):
            result = load()
        self.assertEqual(result['status'], 'failed')
        self.assertIs(cache.get_snapshot(), before); self.assertIs(store.directory, directory)
        self.assertEqual(config.get_settings().model_dump(), saved)
        self.assertTrue(all(r.get('category')=='activation' for r in result['sources']))

    def test_staging_failure_cannot_activate_the_failed_source(self):
        load(); before = cache.get_snapshot()
        self.roles.write_text('AGR_NAME,TCODE\nZC:NEW,ME21N\n')
        original = __import__('csv_lifecycle').write_private
        def denied(kind, value):
            if kind=='snapshots' and value.get('source')=='roles': raise PermissionError('private')
            return original(kind, value)
        with patch('csv_lifecycle.write_private', side_effect=denied): result = load()
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(cache.get_snapshot().roles, before.roles)
        self.assertNotIn('ZC:NEW', cache.get_snapshot().roles)

    def test_bounded_history_keeps_actual_field_changes_not_row_order(self):
        load()
        for i in range(6):
            self.roles.write_text(f'AGR_NAME,TEXT,TCODE\nZC:DEMO,Description {i},MIGO\n'); load()
        reports = history()
        self.assertEqual(len(reports), 5)
        detail = read_private('reports', reports[0]['id'])
        change = detail['sources'][0]['changes'][0]
        self.assertEqual(change['type'], 'modified')
        self.assertEqual(change['fields'], [dict(field='TEXT', before='Description 4', after='Description 5')])

    def test_missing_email_is_not_identity_and_intervals_are_not_collapsed(self):
        before = [dict(SamAccountName='demo_a', Name='Example A', Mail=''), dict(SamAccountName='demo_b', Name='Example B', Mail='')]
        after = [{**before[0], 'Name': 'Updated A'}, before[1]]
        delta = diff_records('employees', before, after)
        self.assertEqual((delta['modified'], delta['unchanged']), (1, 1))
        rows = [dict(USERNAME='DEMO_A', ROLE_NAME='ZC:DEMO', USER_GROUP='DEMO', ROLE_VALID_TO=value) for value in ('20200101', '99991231')]
        delta = diff_records('users', rows, list(reversed(rows)))
        self.assertEqual(delta['unchanged'], 2); self.assertEqual(delta['changes'], [])

    def test_ambiguous_identifier_groups_do_not_invent_modified_pairings(self):
        before = [dict(SamAccountName='shared', Name=value) for value in ('One', 'Two')]
        after = [dict(SamAccountName='shared', Name=value) for value in ('Three', 'Four')]
        delta = diff_records('employees', before, after)
        self.assertEqual((delta['modified'], delta['added'], delta['removed']), (0, 2, 2))
        self.assertEqual(delta['ambiguous_identifiers'], 1)

    def test_real_process_restart_restores_static_sources_without_original_csvs(self):
        import subprocess
        load()
        settings = config.get_settings().model_copy(deep=True)
        settings.source_modes.roles = settings.source_modes.users = 'static'
        config.save_configuration(settings, settings.revision)
        self.roles.unlink(); self.users.unlink()
        script = "import csv_lifecycle,cache; r=csv_lifecycle.load(operation='startup'); assert len(cache.get_snapshot().roles)==1; assert len(cache.get_snapshot().users.users)==2; assert cache.get_snapshot().users.assignments[0]['tcodes']==['MIGO']; assert r['failed']==0"
        result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, 'Fresh-process snapshot recovery failed')

    def test_corrupt_static_snapshot_is_not_reported_as_available(self):
        from csv_lifecycle import private_path
        load()
        settings = config.get_settings().model_copy(deep=True); settings.source_modes.roles = 'static'
        config.save_configuration(settings, settings.revision)
        private_path('snapshots', settings.data_lifecycle.sources['roles'].snapshot).write_bytes(b'corrupt')
        cache.clear_cache()
        result = load(operation='startup')
        source = next(row for row in result['sources'] if row['source']=='roles')
        self.assertEqual(source['category'], 'snapshot'); self.assertFalse(source['previous_preserved'])
        self.assertEqual(cache.get_snapshot().roles, {})

    def test_large_directory_shrink_removes_exactly_fifteen_records(self):
        import csv
        def write(count):
            with self.directory.open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=HEADERS, delimiter=';'); writer.writeheader()
                for index in range(count): writer.writerow(dict(Name=f'Example {index}',SamAccountName=f'demo_{index}',Mail=f'demo_{index}@example.test'))
        write(1310); load(); write(1295); result = load()
        source = next(row for row in result['sources'] if row['source']=='employees')
        self.assertEqual((source['removed'], source['records']), (15, 1295))
        self.assertEqual(len(store.directory.rows), 1295)
        self.assertNotIn('demo_1300@example.test', store.directory.indexes['Mail'])

    def test_reports_are_authenticated_paginated_export_safe_and_diagnostics_redacted(self):
        from fastapi.testclient import TestClient
        from main import create_app
        load()
        self.roles.write_text('AGR_NAME,TEXT,TCODE\nZC:DEMO,=SYNTHETIC(),MIGO\n')
        result = load()
        # Do not enter lifespan: the test already activated its exact generation.
        client = TestClient(create_app(session_token='synthetic-session'),base_url='http://127.0.0.1:18743')
        headers = {'X-SAP-Lens':'synthetic-session'}
        url = '/api/data-sources/reports/' + result['id']
        self.assertEqual(client.get(url).status_code,403)
        detail = client.get(url+'?source=roles&kind=modified&limit=1',headers=headers).json()
        self.assertEqual((detail['total'],len(detail['items'])),(1,1))
        self.assertEqual(client.get(url+'?offset=1',headers=headers).json()['items'],[])
        exported = client.get(url+'/export',headers=headers).text
        self.assertIn("'=SYNTHETIC()",exported)
        safe = client.get('/api/diagnostics/export',headers=headers).text
        for private in ('=SYNTHETIC()', str(self.root), 'a@example.test', result['id']): self.assertNotIn(private,safe)
        portable = client.post('/api/configuration/export',headers=headers).json()
        self.assertEqual(portable['settings']['data_lifecycle']['sources'],{})
        self.assertEqual(portable['settings']['data_lifecycle']['history'],[])
        self.assertIsNone(portable['settings']['data_lifecycle']['last_successful_refresh'])
        self.assertNotIn(str(self.root),str(portable))

    def test_preview_missing_emails_are_not_duplicate_email_keys(self):
        import asyncio
        from routers.employees import preview, ImportRequest
        self.directory.write_text(';'.join(HEADERS)+'\n'+''.join(';Example;demo_'+str(i)+';;;;;;;;;;;;;\n' for i in range(3)))
        value = asyncio.run(preview(ImportRequest(path=str(self.directory),revision=config.get_settings().revision)))
        self.assertEqual(value['missing_emails'],3); self.assertEqual(value['duplicate_emails'],0)
        self.assertEqual(value['total'],3)

    def test_disabled_mapping_preserves_directory_preference_and_matching_resumes(self):
        from routers.employees import directory_status, match_user
        load()
        settings = config.get_settings().model_copy(deep=True); settings.features.user_role_mapping=False
        config.save_configuration(settings, settings.revision)
        state = directory_status()
        self.assertTrue(state['enabled']); self.assertTrue(state['directory_operational'])
        self.assertFalse(state['enrichment']['operational']); self.assertEqual(match_user('DEMO_A')['status'],'mapping_unavailable')
        settings=config.get_settings().model_copy(deep=True);settings.features.user_role_mapping=True
        config.save_configuration(settings,settings.revision)
        self.assertTrue(directory_status()['enrichment']['operational'])
        self.assertEqual(match_user('DEMO_A')['status'],'matched')

    def test_source_changed_during_streaming_validation_is_rejected(self):
        from csv_import import CsvImport
        from config_models import ImportProfile
        parser = CsvImport(self.roles, ImportProfile(id='default',name='Synthetic'))
        rows = parser.records()
        self.assertEqual(next(rows)['AGR_NAME'],'ZC:DEMO')
        self.roles.write_text('AGR_NAME,TCODE\nZC:CHANGED,ME21N\n')
        with self.assertRaisesRegex(ValueError,'changed while being read'):
            list(rows)

    def test_history_uses_compact_metadata_without_reading_complete_reports(self):
        load()
        with patch('csv_lifecycle.read_private',side_effect=AssertionError('History reread a complete report')):
            self.assertEqual(len(history()),1)

    def test_role_preview_is_independent_and_explicit_clear_removes_active_references(self):
        from fastapi.testclient import TestClient
        from main import create_app
        load()
        self.users.unlink()
        client=TestClient(create_app(session_token='synthetic-session'),base_url='http://127.0.0.1:18743')
        headers={'X-SAP-Lens':'synthetic-session'}
        self.assertEqual(client.post('/api/import/preview',headers=headers,data=None,json={'data_csv_path':str(self.roles)}).status_code,200)
        current=config.get_settings().model_dump()
        current['data_csv_path']=current['user_csv_path']=''
        result=client.post('/api/configuration',headers=headers,json=current)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(config.get_settings().data_lifecycle.sources,{})
        self.assertEqual(cache.get_snapshot().roles,{})
        self.assertEqual(cache.get_snapshot().users.users,{})

    def test_corrupt_content_addressed_target_is_repaired_from_validated_bytes(self):
        from csv_lifecycle import write_private, private_path
        value=dict(version=1,source='roles',records=[],report={})
        identity=write_private('snapshots',value)
        private_path('snapshots',identity).write_bytes(b'corrupt')
        self.assertEqual(write_private('snapshots',value),identity)
        self.assertEqual(read_private('snapshots',identity),value)

    def test_captured_generation_keeps_its_directory_during_cross_source_replacement(self):
        from routers.employees import directory_status, match_user, available
        load(); old=cache.get_snapshot()
        self.assertTrue(old.directory_bound)
        self.users.write_text(self.users.read_text().replace('a@example.test','new_a@example.test'))
        self.directory.write_text(self.directory.read_text().replace('Example A','Updated A').replace('a@example.test','new_a@example.test'))
        load(); current=cache.get_snapshot()
        self.assertIsNot(current.directory,old.directory)
        self.assertEqual(directory_status(snapshot=old)['coverage']['matched'],2)
        self.assertEqual(available(old).match(['a@example.test'])['employee']['name'],'Example A')
        self.assertEqual(available(current).match(['a@example.test'])['status'],'unmatched')
        with patch('cache.get_snapshot',return_value=old) as read:
            response=match_user('DEMO_A')
            self.assertEqual(response['employee']['name'],'Example A')
            self.assertEqual(read.call_count,1)
        self.assertEqual(match_user('DEMO_A')['employee']['name'],'Updated A')

    def test_directory_failure_is_visible_but_keeps_operational_records_until_recovery(self):
        from routers.employees import directory_status
        load(); before=cache.get_snapshot().directory
        valid=self.directory.read_text()
        self.directory.write_text('WRONG\ninvalid\n')
        result=load()
        self.assertEqual(result['status'],'partial')
        self.assertIs(cache.get_snapshot().directory,before)
        status=directory_status()
        self.assertTrue(status['loaded']); self.assertTrue(status['directory_operational'])
        self.assertIsNotNone(status['error'])
        self.directory.write_text(valid);load()
        self.assertIsNone(directory_status()['error'])
