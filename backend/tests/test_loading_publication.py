"""Synthetic startup and multi-source publication regressions; no native desktop claims."""
import os
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cache
import config
from main import create_app
H={'X-SAP-Lens':'1'}
ROLES='FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,TCODE\nMM,ZC:DEMO,Demo role,ZS:DEMO,{}\n'
USERS='USERNAME,ROLE_NAME,EMAIL,ROLE_VALID_FROM,ROLE_VALID_TO\n{},ZC:DEMO,{}@example.test,20200101,99991231\n'
class LoadingPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.env=patch.dict(os.environ,{'SAP_LENS_CONFIG_DIR':str(self.root/'config'),'DATA_CSV_PATH':''});self.env.start()
        config.get_settings.cache_clear();cache.clear_cache()
        self.roles=self.root/'roles.csv';self.users=self.root/'users.csv'
        self.roles.write_text(ROLES.format('MIGO'));self.users.write_text(USERS.format('DEMO_OLD','old'))
    def tearDown(self):
        cache.clear_cache();config.get_settings.cache_clear();self.env.stop();self.temp.cleanup()
    def configured(self):
        s=config.get_settings().model_copy(deep=True);s.data_csv_path=str(self.roles);s.user_csv_path=str(self.users)
        config.save_configuration(s,s.revision)
    def client(self): return TestClient(create_app(session_token='1'),base_url='http://127.0.0.1:18743')
    def wait_ready(self,client):
        until=time.monotonic()+3
        while time.monotonic()<until:
            if not client.get('/api/configuration',headers=H).json()['loading']:return
            time.sleep(.01)
        self.fail('Synthetic load did not finish')
    def test_configured_sources_initialize_at_startup_without_page_requests(self):
        self.configured();started,finish=threading.Event(),threading.Event();original=cache.build_users
        def slow(*args):
            started.set();finish.wait(3);return original(*args)
        with patch('cache.build_users',side_effect=slow):
            with self.client() as client:
                try:
                    self.assertTrue(started.wait(1))
                    initial=client.get('/api/configuration',headers=H).json()
                    self.assertTrue(initial['loading']);self.assertEqual(initial['data_revision'],'empty')
                    self.assertIsNone(cache.get_snapshot().last_loaded)
                finally:finish.set()
                self.wait_ready(client)
                self.assertEqual(len(cache.get_snapshot().roles),1)
                self.assertEqual(len(cache.get_snapshot().users.users),1)
                self.assertNotEqual(client.get('/api/configuration',headers=H).json()['data_revision'],'empty')
    def test_refresh_retains_whole_snapshot_until_both_sources_validate(self):
        self.configured()
        with self.client() as client:
            self.wait_ready(client);previous=cache.get_snapshot();revision=client.get('/api/configuration',headers=H).json()['data_revision']
            self.roles.write_text(ROLES.format('ME21N'));self.users.write_text(USERS.format('DEMO_NEW','new'))
            started,finish=threading.Event(),threading.Event();original=cache.build_users
            def slow(*args):started.set();finish.wait(3);return original(*args)
            with patch('cache.build_users',side_effect=slow),ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(client.post,'/api/refresh',headers=H)
                try:
                    self.assertTrue(started.wait(1));self.assertIs(cache.get_snapshot(),previous)
                    status=client.get('/api/configuration',headers=H).json()
                    self.assertTrue(status['loading']);self.assertEqual(status['data_revision'],revision)
                    self.assertEqual(client.get('/api/access/users',headers=H).json()['items'][0]['username'],'DEMO_OLD')
                    self.assertEqual(len(client.get('/api/roles?tcodes=MIGO',headers=H).json()),1)
                    self.assertEqual(client.get('/api/roles?tcodes=ME21N',headers=H).json(),[])
                finally:finish.set()
                self.assertEqual(future.result(3).status_code,200)
            self.assertIsNot(cache.get_snapshot(),previous)
            self.assertNotEqual(client.get('/api/configuration',headers=H).json()['data_revision'],revision)
            self.assertEqual(client.get('/api/access/users',headers=H).json()['items'][0]['username'],'DEMO_NEW')
            self.assertEqual(client.get('/api/roles?tcodes=MIGO',headers=H).json(),[])
    def test_failed_second_source_preserves_publication_and_recovery_replaces_it(self):
        self.configured()
        with self.client() as client:
            self.wait_ready(client);previous=cache.get_snapshot();revision=client.get('/api/configuration',headers=H).json()['data_revision']
            self.roles.write_text(ROLES.format('ME21N'));self.users.write_text('invalid')
            self.assertEqual(client.post('/api/refresh',headers=H).status_code,400)
            self.assertIs(cache.get_snapshot(),previous)
            self.assertEqual(client.get('/api/configuration',headers=H).json()['data_revision'],revision)
            self.users.write_text(USERS.format('DEMO_NEW','new'))
            self.assertEqual(client.post('/api/refresh',headers=H).status_code,200)
            self.assertNotEqual(client.get('/api/configuration',headers=H).json()['data_revision'],revision)
            self.assertIsNone(client.get('/api/configuration',headers=H).json()['error'])
    def test_dashboard_reads_one_publication_for_metrics_and_email_dependencies(self):
        self.configured();cache.load_cache();old=cache.get_snapshot()
        with self.client() as client:
            self.wait_ready(client)
            with patch('cache.get_snapshot',return_value=old) as snapshot:
                result=client.get('/api/dashboard',headers=H)
            self.assertEqual(result.status_code,200);self.assertEqual(snapshot.call_count,1)
