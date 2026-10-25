"""The shipped examples are generated, linked and imported through real local APIs."""
import csv
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
import cache
import config
from config_models import FIELDS,USER_FIELDS
from employee_directory import HEADERS
from role_matching import RoleMatcher
from user_access import parse_release_role
import test_employee_directory as employee_tests
H=employee_tests.H


class ExampleDatasetTests(unittest.TestCase):
    def rows(self,name,delimiter=','):
        with (ROOT/'examples'/name).open(encoding='utf-8-sig',newline='') as stream:return list(csv.DictReader(stream,delimiter=delimiter))

    def test_schemas_volumes_reserved_domains_and_patterns(self):
        roles=self.rows('role-catalogue.example.csv');users=self.rows('user-access.example.csv');employees=self.rows('employee-directory.example.csv',';')
        self.assertEqual(list(roles[0]),FIELDS);self.assertEqual(list(users[0]),USER_FIELDS);self.assertEqual(list(employees[0]),HEADERS)
        names={row['AGR_NAME'] for row in roles}
        self.assertTrue(100<=len(names)<=200);self.assertEqual(len({row['USERNAME'] for row in users}),70)
        self.assertTrue(150<=len(users)<=400);self.assertEqual(len(employees),75)
        self.assertEqual(RoleMatcher(names).invalid_patterns,[])
        self.assertTrue(all('*' not in row['ROLE_NAME'] for row in users))
        matcher=RoleMatcher(names)
        self.assertEqual(matcher.match('ZC:SYN:ROLE_005:ABC').status,'wildcard')
        self.assertEqual(matcher.match('ZC:SYN:ROLE_015:ABC').status,'ambiguous')
        release_names={row['ROLE_NAME'] for row in users if row['ROLE_NAME'].startswith('ZO:MM:')}
        self.assertEqual({parse_release_role(name)['document_type'] for name in release_names},{'PR','PO'})
        for name in ['role-catalogue.example.csv','user-access.example.csv','employee-directory.example.csv']:
            text=(ROOT/'examples'/name).read_text(encoding='utf-8-sig')
            self.assertFalse(re.search(r'\b(?:ENP|ENO|ENK|ENS|SCOM)\b',text))
            domains=re.findall(r'\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})',text)
            self.assertTrue(all(domain.lower() in {'example.org','example.com','example.net'} for domain in domains))

    def test_real_import_investigations_and_fresh_process_snapshot_recovery(self):
        fixture=employee_tests.EmployeeDirectoryTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        paths={}
        for source,name in [('roles','role-catalogue.example.csv'),('users','user-access.example.csv'),('employees','employee-directory.example.csv')]:
            paths[source]=fixture.root/name;shutil.copyfile(ROOT/'examples'/name,paths[source])
        fixture.path=paths['employees'];fixture.enable()
        settings=config.get_settings().model_dump();settings.update(data_csv_path=str(paths['roles']),user_csv_path=str(paths['users']))
        settings['features']['user_role_mapping']=True
        settings['source_modes']={'roles':'static','users':'static','employees':'static'}
        result=fixture.client.post('/api/configuration',headers=H,json=settings)
        self.assertEqual(result.status_code,200,result.text)
        fixture.import_data()
        snapshot=cache.get_snapshot()
        self.assertEqual(len(snapshot.roles),130);self.assertEqual(len(snapshot.users.users),70)
        self.assertEqual(len(snapshot.directory.rows),75)
        users=fixture.client.get('/api/access/users?limit=100',headers=H)
        self.assertEqual(users.status_code,200);self.assertEqual(users.json()['total'],70)
        comparison=fixture.client.get('/api/user-comparison',headers=H,params={'user_a':'SYN_U001','user_b':'SYN_U002','validity':'all','limit':100})
        self.assertEqual(comparison.status_code,200,comparison.text)
        summary=comparison.json()['summary']['roles'];self.assertGreaterEqual(summary['shared'],2)
        self.assertGreater(summary['a'],0);self.assertGreater(summary['b'],0)
        role=next(row for row in comparison.json()['items'] if row['identifier']=='ZC:SYN:ROLE_001')
        self.assertEqual(role['a_total'],2)
        releases=fixture.client.get('/api/access/releases',headers=H,params={'status':'all','limit':100})
        self.assertEqual(releases.status_code,200,releases.text)
        self.assertTrue(releases.json()['items']);self.assertTrue(releases.json()['matrix'])
        health=fixture.client.get('/api/data-health',headers=H)
        self.assertEqual(health.status_code,200,health.text)
        counts={row['id']:row['count'] for row in health.json()['findings']}
        for finding in ['unmapped','ambiguous','unknown_dates','expired','future','unparsed_release','missing_description','unknown_module','unknown_type']:self.assertGreater(counts[finding],0,finding)
        review=fixture.client.get('/api/account-review',headers=H)
        self.assertEqual(review.status_code,200,review.text);self.assertGreater(review.json()['total'],0)
        for path in paths.values():path.unlink()
        script="import csv_lifecycle,cache; r=csv_lifecycle.load(operation='startup');s=cache.get_snapshot();assert r['failed']==0;assert len(s.roles)==130;assert len(s.users.users)==70;assert len(s.directory.rows)==75"
        recovered=subprocess.run([sys.executable,'-B','-c',script],cwd=ROOT/'backend',capture_output=True,text=True)
        self.assertEqual(recovered.returncode,0,'Synthetic snapshot recovery failed: '+recovered.stderr)
