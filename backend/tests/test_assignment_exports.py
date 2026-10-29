"""Fully synthetic, snapshot-consistent semicolon assignment exports."""
import csv
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cache
import config
from main import create_app
from csv_exports import ASSIGNMENT_COLUMNS, spreadsheet_cell
H={'X-SAP-Lens':'1'}
PR='ZO:MM:M:PR_REL_ST_SH_N6:ALL';PO='ZO:MM:M:PO_REL_ST_PG_P1:ALL'

class AssignmentExports(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.addCleanup(self.temp.cleanup)
  self.env=patch.dict(os.environ,{'SAP_LENS_CONFIG_DIR':str(self.root/'private'),'DATA_CSV_PATH':''});self.env.start();self.addCleanup(self.env.stop)
  config.get_settings.cache_clear();cache.clear_cache();self.addCleanup(config.get_settings.cache_clear);self.addCleanup(cache.clear_cache)
  roles=self.root/'roles.csv';self.users=self.root/'users.csv'
  roles.write_text('FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,TCODE\nBC,ZC:SYN:A,Alpha,ZS:SYN:A,MIGO\nBC,ZC:SYN:A,Alpha,ZS:SYN:A,ME23N\nMM,ZC:SYN:B,Beta,ZS:SYN:B,MIGO\nFI,ZC:SYN:W:*,Wildcard,ZS:SYN:W,FB03\n')
  self.columns='USERNAME,ROLE_NAME,USER_GROUP,FIRST_NAME,LAST_NAME,EMAIL,ROLE_VALID_FROM,ROLE_VALID_TO'.split(',')
  rows=[['SYN_A',role,group,'Åse; "Example"','=SYNTHETIC()','alpha@example.test',start,end] for role,group,start,end in [
   ('ZC:SYN:A','G1','20000101','99991231'),('ZC:SYN:B','G1','20000101','99991231'),('ZC:SYN:B','G1','20010101','20020101'),('ZC:SYN:W:ENP','G1','20000101','99991231'),('ZD:SYN:TECH','G1','',''),(PR,'G1','20000101','99991231'),(PR,'G1','20010101','20020101'),(PO,'G2','20000101','99991231')]]
  rows += [['SYN_B',role,group,'Beta','Synthetic','beta@example.test','20000101','99991231'] for role,group in [('ZC:SYN:B','G2'),(PR,'G1')]]
  rows += [['SYN_EMPTY','','G0','Empty','Synthetic','','','']]
  with self.users.open('w',newline='',encoding='utf-8') as stream:writer=csv.writer(stream);writer.writerow(self.columns);writer.writerows(rows)
  settings=config.get_settings().model_copy(deep=True);settings.data_csv_path=str(roles);settings.user_csv_path=str(self.users);config.save_configuration(settings,settings.revision);cache.load_cache()
  self.client=TestClient(create_app(session_token='1'),base_url='http://127.0.0.1:18743')
 def export(self,view,query=''):
  response=self.client.get('/api/access/exports/'+view+query,headers=H);self.assertEqual(response.status_code,200,response.text)
  self.assertTrue(response.content.startswith(b'\xef\xbb\xbf'));self.assertIn('no-store',response.headers['cache-control'])
  reader=csv.DictReader(io.StringIO(response.content.decode('utf-8-sig')),delimiter=';');rows=list(reader)
  self.assertEqual(reader.fieldnames,ASSIGNMENT_COLUMNS);self.assertEqual(int(response.headers['x-sap-lens-assignment-count']),len(rows))
  self.assertEqual(response.headers['x-sap-lens-data-revision'],cache.get_snapshot().last_loaded.isoformat())
  return response,rows
 def test_matching_users_export_all_roles_and_intervals_with_explicit_filter_contribution(self):
  _,hidden=self.export('users','?group=G1&tcodes=MIGO&search=%C3%85se')
  self.assertEqual(len(hidden),6);self.assertNotIn('Expired',{r['ASSIGNMENT_STATUS'] for r in hidden})
  rows=hidden;self.assertEqual({r['USERNAME'] for r in rows},{'SYN_A'})
  self.assertEqual(sum(r['MATCHED_FILTER']=='Yes' for r in rows),2)
  _,shown=self.export('users','?group=G1&tcodes=MIGO&search=%C3%85se&show_expired=true')
  self.assertEqual(len(shown),8)
  expired=next(r for r in shown if r['ROLE_NAME']=='ZC:SYN:B' and r['ASSIGNMENT_STATUS']=='Expired')
  self.assertEqual(expired['ROLE_VALID_TO'],'01.01.2002')
  self.assertIn('ZC:SYN:W:ENP',{r['ROLE_NAME'] for r in rows});self.assertIn('ZD:SYN:TECH',{r['ROLE_NAME'] for r in rows})
  self.assertEqual(rows[0]['FIRST_NAME'],'Åse; "Example"');self.assertEqual(rows[0]['LAST_NAME'],"'=SYNTHETIC()")
  self.assertEqual(cache.get_snapshot().users.users['SYN_A']['names'][0][1],'=SYNTHETIC()')
 def test_expired_assignments_follow_the_show_expired_toggle_in_listing_count_and_export(self):
  count=lambda query:self.client.get('/api/access/users'+query,headers=H).json()['export_assignments']
  _,off=self.export('users','?search=SYN_A');_,on=self.export('users','?search=SYN_A&show_expired=true');_,explicit=self.export('users','?search=SYN_A&status=expired')
  self.assertEqual((len(off),len(on)),(6,8));self.assertTrue(all(r['ASSIGNMENT_STATUS']!='Expired' for r in off));self.assertEqual(sum(r['ASSIGNMENT_STATUS']=='Expired' for r in on),2)
  self.assertTrue(any(r['ASSIGNMENT_STATUS']=='Expired' for r in explicit))
  self.assertEqual((count('?search=SYN_A'),count('?search=SYN_A&show_expired=true')),(6,8))
 def test_role_group_and_expired_filters_share_directory_membership(self):
  _,rows=self.export('users','?role=ZC:SYN:B&group=G1&show_expired=true')
  self.assertEqual(len(rows),8);matched=[r for r in rows if r['MATCHED_FILTER']=='Yes'];self.assertEqual(len(matched),2)
  self.assertEqual({r['ROLE_NAME'] for r in matched},{'ZC:SYN:B'});self.assertIn('Expired',{r['ASSIGNMENT_STATUS'] for r in matched})
  _,rows=self.export('users','?tcodes=MIGO&tcodes=NO_SUCH_CODE');self.assertEqual(rows,[])
  _,rows=self.export('users','?tcodes=MIGO&tcodes=NO_SUCH_CODE&transaction_mode=or');self.assertEqual({r['USERNAME'] for r in rows},{'SYN_A','SYN_B'})
 def test_release_filters_dates_and_table_matrix_use_one_assignment_set(self):
  base='?document_type=PR&release_group=SH&strategy=N6&group=G1&status=all'
  first,rows=self.export('releases',base);second,again=self.export('releases',base+'&group_by_user_group=true&matrix_offset=200&offset=100')
  self.assertEqual(first.content,second.content);self.assertEqual(rows,again);self.assertEqual(len(rows),3)
  self.assertEqual({r['PR_PO'] for r in rows},{'PR'});self.assertTrue(all(r['MATCHED_FILTER']=='Yes' for r in rows))
  _,expired=self.export('releases',base+'&username=SYN_A&role=PR_REL_ST_SH&valid_to_max=2002-01-01');self.assertEqual(len(expired),1);self.assertEqual(expired[0]['ASSIGNMENT_STATUS'],'Expired')
  _,po=self.export('releases','?document_type=PO&release_group=PG&strategy=P1');self.assertEqual(len(po),1);self.assertEqual(po[0]['ROLE_NAME'],PO)
 def test_export_completeness_exceeds_user_pagination(self):
  with self.users.open('a',newline='',encoding='utf-8') as stream:
   writer=csv.writer(stream)
   for i in range(125):writer.writerow([f'PAGE_{i:03}','ZC:SYN:B','G_PAGE','Synthetic','Page','','20000101','99991231'])
  cache.load_cache();page=self.client.get('/api/access/users?search=PAGE_&limit=1',headers=H).json()
  self.assertEqual(page['total'],125);self.assertEqual(len(page['items']),1);self.assertEqual(page['export_assignments'],125)
  _,rows=self.export('users','?search=PAGE_&offset=100&limit=1');self.assertEqual(len(rows),125);self.assertEqual(len({r['USERNAME'] for r in rows}),125)
 def test_empty_assignment_set_and_feature_authorization_are_explicit(self):
  _,rows=self.export('users','?search=SYN_EMPTY');self.assertEqual(rows,[])
  self.assertEqual(self.client.get('/api/access/exports/users').status_code,403)
  settings=config.get_settings().model_copy(deep=True);settings.features.user_role_mapping=False;config.save_configuration(settings,settings.revision)
  self.assertEqual(self.client.get('/api/access/exports/users',headers=H).status_code,409)
  self.assertEqual(self.client.get('/api/access/exports/releases',headers=H).status_code,409)
 def test_spreadsheet_safety_preserves_normal_unicode_and_identifiers(self):
  for value in ['=1',' +SUM(A1)','-1','@SYN','\t=1','\rvalue','\ufeff=1']:
   self.assertTrue(spreadsheet_cell(value).startswith("'"))
  for value in ['ZC:SYN:ROLE:EN*','Åse; "Example"','9999-12-31','normal']:
   self.assertEqual(spreadsheet_cell(value),value)

 def test_stream_remains_on_captured_generation_when_cache_changes(self):
  from csv_exports import spreadsheet_cell as original
  previous=cache.get_snapshot().last_loaded.isoformat();changed=False
  def replace_once(value):
   nonlocal changed
   if not changed: cache.clear_cache();changed=True
   return original(value)
  with patch('csv_exports.spreadsheet_cell',side_effect=replace_once):
   response=self.client.get('/api/access/exports/users?search=SYN_A&show_expired=true',headers=H)
  self.assertEqual(response.status_code,200);self.assertEqual(response.headers['x-sap-lens-data-revision'],previous)
  rows=list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig')),delimiter=';'));self.assertEqual(len(rows),8)
  self.assertEqual({row['USERNAME'] for row in rows},{'SYN_A'})
