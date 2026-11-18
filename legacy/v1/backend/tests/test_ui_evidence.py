"""Response-only preview/matching evidence; no persistence or matching reinterpretation."""
import unittest
import test_employee_directory as directory_tests
import config
import cache

H={'X-SAP-Lens':'1'}


class UiEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.fixture=directory_tests.EmployeeDirectoryTests();self.fixture.setUp()
    def tearDown(self):self.fixture.tearDown()
    def users(self,email):
        f=self.fixture;path=f.root/'users.csv'
        path.write_text('USERNAME,ROLE_NAME,EMAIL\nDEMO_SAP,ZC:DEMO,'+email+'\n')
        settings=config.get_settings().model_dump();settings['user_csv_path']=str(path)
        response=f.client.post('/api/configuration',json=settings,headers=H)
        self.assertEqual(response.status_code,200,response.text)
    def test_conflict_details_are_bounded_and_do_not_select_or_drop_duplicates(self):
        f=self.fixture
        f.write([{'Name':f'Demo {i}','Mail':'same@example.test','Enabled':''} for i in range(30)])
        f.enable();f.import_data();self.users('same@example.test')
        result=f.client.get('/api/employees/match/DEMO_SAP',headers=H).json()
        self.assertEqual(result['status'],'duplicate_email');self.assertIsNone(result['employee'])
        evidence=result['diagnostics'];self.assertEqual(evidence['candidate_count'],30)
        self.assertEqual(len(evidence['candidates']),25);self.assertEqual(evidence['matching_method'],'Normalized exact email')
        self.assertEqual(len(cache.get_snapshot().directory.rows),30)
        self.assertTrue(all(row['account_status']=='Unknown' for row in evidence['candidates']))
        f.enable(False)
        self.assertNotIn('diagnostics',f.client.get('/api/employees/match/DEMO_SAP',headers=H).json())
    def test_unique_match_unknown_ad_and_import_vs_refresh_remain_distinct(self):
        f=self.fixture;f.write([{'Name':'Demo','Mail':'demo@example.test','Enabled':'unsupported'}])
        f.enable();f.import_data();self.users('demo@example.test')
        result=f.client.get('/api/employees/match/DEMO_SAP',headers=H).json()
        self.assertEqual(result['status'],'matched');self.assertEqual(result['employee']['account_status'],'Unknown')
        self.assertEqual(result['diagnostics']['candidate_count'],1)
        health=f.client.get('/api/diagnostics',headers=H).json()
        self.assertIsNone(health['last_successful_refresh'])
        self.assertTrue(health['employee_directory']['report']['imported_at'])
    def test_user_preview_is_bounded_response_only_and_not_diagnostic_export(self):
        f=self.fixture;path=f.root/'preview.csv'
        path.write_text('USERNAME,ROLE_NAME,EMAIL\n'+''.join(f'DEMO_PRIVATE_PERSON_{i},ZC:DEMO,private_{i}@example.test\n' for i in range(30)))
        before=cache.get_snapshot()
        response=f.client.post('/api/user-import/preview',json={'data_csv_path':str(path)},headers=H)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(len(response.json()['samples']),20)
        self.assertEqual(response.json()['samples'][0]['EMAIL'],'private_0@example.test')
        self.assertEqual(before.users.report.get('samples',[]),[])
        self.assertIs(cache.get_snapshot(),before)
        exported=f.client.get('/api/diagnostics/export',headers=H).text
        self.assertNotIn('DEMO_PRIVATE_PERSON_0',exported)
        self.assertNotIn('private_0@example.test',exported)
