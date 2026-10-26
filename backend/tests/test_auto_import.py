"""Synthetic automatic activation, replacement and failure recovery contracts."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
import cache,config
from employee_directory import HEADERS,store
from main import create_app
H={'X-SAP-Lens':'synthetic-auto-session'}

class AutomaticImportTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  self.environment=patch.dict(os.environ,{'SAP_LENS_CONFIG_DIR':str(self.root/'private'),'DATA_CSV_PATH':''});self.environment.start();self.addCleanup(self.environment.stop)
  config.get_settings.cache_clear();cache.clear_cache();store.clear();self.addCleanup(config.get_settings.cache_clear);self.addCleanup(cache.clear_cache);self.addCleanup(store.clear)
  self.roles=self.root/'roles.csv';self.users=self.root/'users.csv';self.employees=self.root/'employees.csv'
  self.roles.write_text('FUNCTION_KEY,AGR_NAME,CHILD_AGR,TCODE\nMM,ZC:SYN:A,ZS:SYN:A,MIGO\n')
  self.users.write_text('USERNAME,ROLE_NAME,EMAIL,ROLE_VALID_FROM,ROLE_VALID_TO\nSYN_A,ZC:SYN:A,synthetic@example.test,20000101,99991231\n')
  record={key:'' for key in HEADERS};record.update(Name='Synthetic Person',SamAccountName='synthetic_ad',Mail='synthetic@example.test',Enabled='True')
  self.employees.write_text(';'.join(HEADERS)+'\n'+';'.join(record[key] for key in HEADERS)+'\n')
  self.app=create_app(session_token=H['X-SAP-Lens']);self.client=TestClient(self.app,base_url='http://127.0.0.1:18743')
 def select(self,source,path=None,mode='static',revision=None,**extra):
  return self.client.post(f'/api/data-sources/{source}/select',headers=H,json={'path':str(path or getattr(self,source)),'mode':mode,'revision':config.get_settings().revision if revision is None else revision,**extra})
 def test_all_sources_activate_durably_without_preview_confirmation_or_feature_enablement(self):
  for source in ('roles','users','employees'):
   response=self.select(source);self.assertEqual(response.status_code,200,response.text);body=response.json();self.assertEqual(body['records'],1);self.assertIsNotNone(body['refresh']['id'])
   preview=self.client.get(f'/api/data-sources/{source}/preview',headers=H).json();self.assertTrue(preview['loaded']);self.assertEqual(preview['total'],1)
  self.assertFalse(config.get_settings().features.employee_directory)
  self.assertIsNotNone(config.get_settings().employee_snapshot_id);self.assertEqual(len(cache.get_snapshot().users.users),1)
 def test_invalid_empty_blank_and_missing_inputs_never_replace_previous_source(self):
  self.assertEqual(self.select('roles').status_code,200);revision=config.get_settings().revision;previous=cache.get_snapshot()
  for content in ['', 'AGR_NAME,TCODE\n', 'UNSUPPORTED\nSYNTHETIC\n']:
   invalid=self.root/'invalid.csv';invalid.write_text(content);response=self.select('roles',invalid);self.assertGreaterEqual(response.status_code,400);self.assertIs(cache.get_snapshot(),previous);self.assertEqual(config.get_settings().revision,revision)
  for path in ['   ',self.root/'missing.csv']:
   self.assertGreaterEqual(self.select('roles',path).status_code,400);self.assertIs(cache.get_snapshot(),previous)
 def test_same_path_reselection_replaces_removes_stale_records_and_reports_changes(self):
  self.select('roles');self.roles.write_text('FUNCTION_KEY,AGR_NAME,CHILD_AGR,TCODE\nFI,ZC:SYN:B,ZS:SYN:B,FB03\n')
  response=self.select('roles');self.assertEqual(response.status_code,200,response.text);self.assertEqual(set(cache.get_snapshot().roles),{'ZC:SYN:B'})
  result=next(row for row in response.json()['refresh']['sources'] if row['source']=='roles');self.assertEqual((result['added'],result['removed']),(1,1))
 def test_static_snapshot_survives_original_removal_and_dynamic_refresh_rejects_empty(self):
  self.select('roles');self.roles.unlink();cache.clear_cache();store.clear()
  from csv_lifecycle import load
  load(operation='startup');self.assertIn('ZC:SYN:A',cache.get_snapshot().roles)
  self.roles.write_text('FUNCTION_KEY,AGR_NAME,CHILD_AGR,TCODE\nMM,ZC:SYN:DYNAMIC,ZS:SYN:DYNAMIC,MIGO\n');self.select('roles',mode='dynamic')
  self.roles.write_text('AGR_NAME,TCODE\n');report=load(operation='refresh');self.assertEqual(report['status'],'failed');self.assertIn('ZC:SYN:DYNAMIC',cache.get_snapshot().roles)
 def test_source_profiles_unrelated_preferences_and_revision_guards_are_preserved(self):
  current=config.get_settings().model_copy(deep=True);current.organization.name='Synthetic local preference';config.save_configuration(current,current.revision)
  old=current.revision;response=self.select('roles');self.assertEqual(response.status_code,200,response.text);self.assertEqual(config.get_settings().organization.name,'Synthetic local preference')
  self.assertEqual(self.select('roles',revision=old).status_code,409)
  self.assertEqual(self.client.post('/api/data-sources/users/select',json={'path':str(self.users),'mode':'static','revision':config.get_settings().revision}).status_code,403)
 def test_missing_email_is_a_warning_and_duplicate_assignment_intervals_remain_distinct(self):
  self.select('roles');self.users.write_text('USERNAME,ROLE_NAME,ROLE_VALID_FROM,ROLE_VALID_TO\nSYN_A,ZC:SYN:A,20000101,99991231\nSYN_A,ZC:SYN:A,20010101,20020101\nSYN_A,ZC:SYN:A,20000101,99991231\n')
  response=self.select('users');self.assertEqual(response.status_code,200,response.text);self.assertEqual(len(cache.get_snapshot().users.assignments),2)
  self.employees.write_text(';'.join(HEADERS)+'\n'+';'.join({'Name':'Synthetic Missing Mail','SamAccountName':'synthetic_missing'}.get(key,'') for key in HEADERS)+'\n')
  response=self.select('employees');self.assertEqual(response.status_code,200,response.text);self.assertEqual(cache.get_snapshot().directory.report()['missing_emails'],1)
 def test_file_changed_during_staging_cannot_be_published(self):
  self.select('roles');previous=cache.get_snapshot();self.roles.write_text('AGR_NAME,TCODE\nZC:SYN:NEW,VA03\n')
  from csv_lifecycle import write_private as original
  changed=False
  def mutate(kind,value):
   nonlocal changed
   result=original(kind,value)
   if kind=='snapshots' and not changed:self.roles.write_text('AGR_NAME,TCODE\nZC:SYN:ALTERED_AFTER_VALIDATION,FB03\n');changed=True
   return result
  with patch('csv_lifecycle.write_private',side_effect=mutate):response=self.select('roles')
  self.assertEqual(response.status_code,400,response.text);self.assertIs(cache.get_snapshot(),previous)
 def test_read_failure_and_storage_failure_preserve_last_valid_snapshot(self):
  self.select('roles');previous=cache.get_snapshot();settings=config.get_settings().model_dump()
  with patch('cache._build_catalog',side_effect=PermissionError('synthetic network unavailable')):
   self.assertEqual(self.select('roles').status_code,400)
  with patch('csv_lifecycle.write_private',side_effect=OSError('synthetic storage unavailable')):
   self.assertEqual(self.select('roles').status_code,400)
  self.assertIs(cache.get_snapshot(),previous);self.assertEqual(config.get_settings().model_dump(),settings)
 def test_empty_user_and_employee_replacements_retain_durable_records(self):
  for source in ('users','employees'):
   self.assertEqual(self.select(source).status_code,200)
   previous=cache.get_snapshot();settings=config.get_settings().model_dump()
   path=getattr(self,source);path.write_text('USERNAME,ROLE_NAME\n' if source=='users' else ';'.join(HEADERS)+'\n')
   self.assertEqual(self.select(source).status_code,400)
   self.assertIs(cache.get_snapshot(),previous);self.assertEqual(config.get_settings().model_dump(),settings)
 def test_snapshot_preview_survives_source_removal_and_reports_progress(self):
  self.assertEqual(self.select('employees').status_code,200);self.employees.unlink()
  result=self.client.post('/api/data-sources/employees/inspect',headers=H,json={'path':'snapshot','revision':config.get_settings().revision})
  self.assertEqual(result.status_code,200,result.text)
  self.assertEqual(self.app.state.loader.progress['stage'],'Completed')
  self.assertEqual(self.client.get('/api/data-sources/employees/preview',headers=H).json()['total'],1)
 def test_overlapping_selection_is_rejected_without_a_second_reader(self):
  import threading
  from concurrent.futures import ThreadPoolExecutor
  entered=threading.Event();release=threading.Event();original=cache._build_catalog
  def blocked(*args,**kwargs):
   entered.set()
   if not release.wait(5):raise RuntimeError('Synthetic reader gate was not released')
   return original(*args,**kwargs)
  with patch('cache._build_catalog',side_effect=blocked),ThreadPoolExecutor(max_workers=1) as pool:
   first=pool.submit(self.select,'roles')
   try:
    self.assertTrue(entered.wait(5))
    second=self.select('users');self.assertEqual(second.status_code,409,second.text)
    self.assertEqual(self.app.state.loader.progress['stage'],'Reading file')
   finally:release.set()
   self.assertEqual(first.result(timeout=5).status_code,200)
  self.assertEqual(self.app.state.loader.progress['stage'],'Completed')
