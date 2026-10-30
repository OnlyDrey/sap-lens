"""Literal SAP search patterns; joins and role-assignment matching are unchanged."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from search_matching import text_matches,search_fields
from transaction_filters import matching_role_names
import test_investigation_filters as fixtures

CASES=[('ME23N','ME*',True),('ME23N','*23N',True),('ME23N','*me*',True),('ME23N','ME*23*',True),('XME23N','ME*',False),('ME23NX','*23N',False),('abc','',True),('abc','b',True),('abc','*',True),('abc','a?c',False),('[a].+','[a].*',True),('a','a*a',False),('Åse','å*',True),('ab','a**b',True),('','**',True)]
class SearchMatchingTests(unittest.TestCase):
 def test_patterns_are_literal_case_insensitive_and_anchored(self):
  for value,query,expected in CASES:
   with self.subTest(value=value,query=query):self.assertEqual(text_matches(value,query),expected)
 def test_fields_and_long_patterns(self):
  self.assertTrue(search_fields('USER*','USER_A','Other identity'))
  self.assertTrue(search_fields('first last','USER_A','First Last'))
  self.assertFalse(text_matches('a'*10000,'a*'*1000+'b'))
 def test_transaction_and_or_combines_pattern_groups_not_expanded_codes(self):
  index={'ME21N':['A'],'ME23N':['B'],'MIGO':['A','B']}
  self.assertEqual(matching_role_names(index,['ME*','MI*']),{'A','B'})
  self.assertEqual(matching_role_names(index,['ME21N','*23N']),set())
  self.assertEqual(matching_role_names(index,['ME21N','*23N'],'or'),{'A','B'})
class SearchAPIContractTests(unittest.TestCase):
 setUp=fixtures.InvestigationFilterTests.setUp
 tearDown=fixtures.InvestigationFilterTests.tearDown
 def test_role_directory_and_transaction_patterns_share_canonical_filters(self):
  roles=self.client.get('/api/roles',headers=fixtures.H,params={'search':'ZC:MM:*'});self.assertEqual([r['agr_name'] for r in roles.json()],['ZC:MM:A'])
  roles=self.client.get('/api/roles',headers=fixtures.H,params={'tcodes':['ME*','MI*']});self.assertEqual([r['agr_name'] for r in roles.json()],['ZC:MM:A'])
  users=self.client.get('/api/access/users',headers=fixtures.H,params={'search':'DEMO_O*','tcodes':'ME*'});self.assertEqual([r['username'] for r in users.json()['items']],['DEMO_ONE'])

 def test_assignment_distribution_drilldown_and_export_use_same_population(self):
  counts=[]
  for band in ['0','1–5','6–20','21+']:
   response=self.client.get('/api/access/users',headers=fixtures.H,params={'assignment_band':band})
   self.assertEqual(response.status_code,200);counts.append(response.json()['total'])
  self.assertEqual(sum(counts),3)
  self.assertEqual(self.client.get('/api/access/users',headers=fixtures.H,params={'assignment_band':'unexpected'}).status_code,422)
 def test_five_assignment_bands_cover_every_user_exactly_once_and_match_the_drilldown(self):
  from user_access import ASSIGNMENT_BANDS, assignment_band, in_assignment_band
  self.assertEqual([assignment_band(n) for n in (0,5,6,10,11,20,21,30,31,200)],['0–5','0–5','6–10','6–10','11–20','11–20','21–30','21–30','31+','31+'])
  for count in range(0,80):self.assertEqual(sum(in_assignment_band(count,band) for band in ASSIGNMENT_BANDS),1)
  data=self.client.get('/api/dashboard',headers=fixtures.H).json()
  self.assertEqual(list(data['assignment_distribution']),list(ASSIGNMENT_BANDS))
  self.assertEqual(sum(data['assignment_distribution'].values()),data['review_population'])
  for band,count in data['assignment_distribution'].items():
   response=self.client.get('/api/access/users',headers=fixtures.H,params={'assignment_band':band})
   self.assertEqual((response.status_code,response.json()['total']),(200,count),band)
 def test_wildcard_filters_pagination_export_and_saved_definition_agree(self):
  import csv,io
  params={'search':'DEMO_O*','tcodes':['ME*','MI*'],'assignment_band':'1–5'}
  result=self.client.get('/api/access/users',headers=fixtures.H,params={**params,'limit':1}).json()
  self.assertEqual(result['total'],1);self.assertEqual(result['items'][0]['username'],'DEMO_ONE')
  exported=self.client.get('/api/access/exports/users',headers=fixtures.H,params=params)
  self.assertEqual(exported.status_code,200)
  rows=list(csv.DictReader(io.StringIO(exported.content.decode('utf-8-sig')),delimiter=';'))
  self.assertEqual({row['USERNAME'] for row in rows},{'DEMO_ONE'})
  self.assertEqual(len(rows),2)
  self.assertEqual({row['ROLE_NAME']:row['MATCHED_FILTER'] for row in rows},{'ZC:MM:A':'Yes','ZO:MM:M:PR_REL_ST_G1_N1:ALL':'No'})
  with_expired=list(csv.DictReader(io.StringIO(self.client.get('/api/access/exports/users',headers=fixtures.H,params={**params,'show_expired':'true'}).content.decode('utf-8-sig')),delimiter=';'))
  self.assertEqual({row['ROLE_NAME']:row['ASSIGNMENT_STATUS'] for row in with_expired}['ZC:FI:B'],'Expired')
  saved=self.client.post('/api/saved-filters',headers=fixtures.H,json={'name':'Synthetic wildcard investigation','view':'users','filters':{'search':'DEMO_O*','tcodes':['ME*','MI*'],'assignmentBand':'1–5'}})
  self.assertEqual(saved.status_code,200,saved.text)
  self.assertEqual(saved.json()['filters']['tcodes'],['ME*','MI*'])

 def test_release_pattern_availability_agrees_with_matching_assignments(self):
  for field,pattern in [('username','DEMO_O*'),('role','ZO:MM:*')]:
   with self.subTest(field=field):
    response=self.client.get('/api/access/release-options',headers=fixtures.H,params={'field':field,'search':pattern,'selected':pattern})
    self.assertEqual(response.status_code,200)
    self.assertGreater(response.json()['total'],0)
    self.assertTrue(response.json()['selected_available'])
  missing=self.client.get('/api/access/release-options',headers=fixtures.H,params={'field':'username','selected':'SYNTHETIC_MISSING*'}).json()
  self.assertFalse(missing['selected_available'])
  exact_group=self.client.get('/api/access/release-options',headers=fixtures.H,params={'field':'group','selected':'G*'}).json()
  self.assertFalse(exact_group['selected_available'])
 def test_complete_release_list_retains_filters_and_sort_from_one_snapshot(self):
  params={'status':'all','sort':'role_name','descending':True,'limit':1}
  paged=self.client.get('/api/access/releases',headers=fixtures.H,params=params)
  complete=self.client.get('/api/access/releases',headers=fixtures.H,params={**params,'list_complete':True,'offset':100})
  self.assertEqual(complete.status_code,200,complete.text)
  data=complete.json()
  self.assertEqual(len(data['items']),data['total'])
  self.assertEqual(data['offset'],0)
  self.assertEqual(data['items'][:1],paged.json()['items'])
  filtered=self.client.get('/api/access/releases',headers=fixtures.H,params={**params,'list_complete':True,'role':'NONEXISTENT'}).json()
  self.assertEqual(filtered['items'],[])
  self.assertEqual(filtered['total'],0)
