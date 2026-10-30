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
        def slow(*args,**kwargs):
            started.set();finish.wait(3);return original(*args,**kwargs)
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
            def slow(*args,**kwargs):started.set();finish.wait(3);return original(*args,**kwargs)
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
    def test_failed_second_source_preserves_users_and_remaps_successful_catalogue(self):
        self.configured()
        with self.client() as client:
            self.wait_ready(client);previous=cache.get_snapshot();revision=client.get('/api/configuration',headers=H).json()['data_revision']
            self.roles.write_text(ROLES.format('ME21N'));self.users.write_text('invalid')
            result=client.post('/api/refresh',headers=H)
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.json()['refresh']['status'],'partial')
            self.assertIsNot(cache.get_snapshot(),previous)
            self.assertEqual(set(cache.get_snapshot().users.users),set(previous.users.users))
            self.assertEqual(cache.get_snapshot().users.assignments[0]['tcodes'],['ME21N'])
            self.assertNotEqual(client.get('/api/configuration',headers=H).json()['data_revision'],revision)
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


class RestartReliabilityTests(unittest.TestCase):
    """A restart restores persisted datasets, reports honest source state and never needs a manual refresh."""
    setUp=LoadingPublicationTests.setUp;tearDown=LoadingPublicationTests.tearDown
    configured=LoadingPublicationTests.configured;client=LoadingPublicationTests.client;wait_ready=LoadingPublicationTests.wait_ready
    def persist(self, static=False):
        import csv_lifecycle
        self.configured(); csv_lifecycle.load()
        if static:
            s=config.get_settings().model_copy(deep=True);s.source_modes.roles=s.source_modes.users='static'
            config.save_configuration(s,s.revision);self.roles.unlink();self.users.unlink()
    def restart(self):
        cache.clear_cache();config.get_settings.cache_clear()
    def metrics(self, client):
        return {m['id']:m for m in client.get('/api/dashboard',headers=H).json()['metrics']}
    def sources(self, client):
        return {s['id']:s for s in client.get('/api/diagnostics',headers=H).json()['sources']}

    def test_restart_restores_persisted_static_sources_and_dashboard_and_settings_agree(self):
        self.persist(static=True)
        before=None
        with self.client() as client:
            self.wait_ready(client);before=client.get('/api/configuration',headers=H).json()
        self.restart()
        with self.client() as client:
            self.wait_ready(client)  # no refresh request, no page request: startup alone restores the datasets
            metrics,sources,config_state=self.metrics(client),self.sources(client),client.get('/api/configuration',headers=H).json()
            self.assertEqual((metrics['roles']['value'],metrics['users']['value']),(1,1))
            self.assertTrue(sources['roles']['loaded'] and sources['users']['loaded'])  # Settings and Dashboard describe the same data
            self.assertIsNone(metrics['users']['unavailable_reason'])
            self.assertEqual(config_state['data_revision'],before['data_revision'])  # a restored snapshot keeps its revision ...
            self.assertEqual(config_state['instance_id'],before['instance_id'])  # ... the instance id is per process, tested below

    def test_instance_id_is_stable_within_a_process_and_new_in_a_fresh_one(self):
        import subprocess
        self.persist(static=True)
        with self.client() as client:
            here=client.get('/api/configuration',headers=H).json()['instance_id']
            self.assertEqual(here,client.get('/api/configuration',headers=H).json()['instance_id'])
        script=("import os,sys,cache,config;sys.path.insert(0,os.getcwd())\n"
                "from fastapi.testclient import TestClient\nfrom main import create_app\nimport time\n"
                "H={'X-SAP-Lens':'1'}\n"
                "with TestClient(create_app(session_token='1'),base_url='http://127.0.0.1:18743') as c:\n"
                " t=time.monotonic()\n"
                " while c.get('/api/configuration',headers=H).json()['loading'] and time.monotonic()-t<5: time.sleep(.01)\n"
                " d={m['id']:m['value'] for m in c.get('/api/dashboard',headers=H).json()['metrics']}\n"
                " print(c.get('/api/configuration',headers=H).json()['instance_id'],d['roles'],d['users'])\n")
        result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,env=os.environ.copy())
        self.assertEqual(result.returncode,0,result.stderr[-400:])
        instance,roles,users=result.stdout.split()
        self.assertNotEqual(instance,here)  # a real fresh process: new instance, persisted data restored without the original CSV files
        self.assertEqual((roles,users),('1','1'))

    def test_loader_is_loading_from_the_first_request_while_persisted_data_is_restored(self):
        self.persist(static=True);self.restart()
        started,finish=threading.Event(),threading.Event();original=cache._build_catalog
        def slow(*args,**kwargs):
            started.set();finish.wait(3);return original(*args,**kwargs)
        with patch('cache._build_catalog',side_effect=slow):
            with self.client() as client:
                try:
                    first=client.get('/api/configuration',headers=H).json()  # the very first request after startup
                    self.assertTrue(first['loading']);self.assertEqual(first['data_revision'],'empty')
                    self.assertIsNone(self.metrics(client)['users']['value'])  # empty while restoring ...
                finally:finish.set()
                self.wait_ready(client)
                self.assertEqual(self.metrics(client)['users']['value'],1)  # ... ready afterwards, nothing re-imported

    def test_genuinely_missing_source_is_reported_not_labelled_loaded(self):
        self.users.unlink();self.configured();self.restart()  # never imported, and the file is gone
        with self.client() as client:
            self.wait_ready(client)
            self.assertIsNotNone(self.metrics(client)['roles']['value'])
            users=self.metrics(client)['users']
            self.assertIsNone(users['value']);self.assertEqual(users['unavailable_reason'],'User Access CSV not loaded')
            source=self.sources(client)['users']
            self.assertTrue(source['configured']);self.assertEqual(source['error'],'missing')
            self.assertFalse(source['loaded'])

    def test_missing_file_with_a_validated_snapshot_keeps_the_data_and_flags_the_error(self):
        self.persist();self.restart();self.users.unlink()
        with self.client() as client:
            self.wait_ready(client)
            self.assertEqual(self.metrics(client)['users']['value'],1)  # the validated snapshot is restored, not discarded
            source=self.sources(client)['users']
            self.assertTrue(source['loaded']);self.assertEqual(source['error'],'missing')  # and the failed check stays visible

    def test_failed_reload_keeps_restored_data_and_recovers_on_refresh(self):
        self.persist();self.restart()
        with self.client() as client:
            self.wait_ready(client)
            self.roles.write_text('not,a,catalogue\n')
            result=client.post('/api/refresh',headers=H).json()
            self.assertNotEqual(result['refresh']['status'],'updated')
            self.assertEqual(self.metrics(client)['roles']['value'],1)  # restored data is retained, never replaced by a failure
            self.roles.write_text(ROLES.format('ME21N'))
            self.assertEqual(client.post('/api/refresh',headers=H).status_code,200)
            self.assertIsNone(client.get('/api/configuration',headers=H).json()['error'])
            self.assertEqual(self.metrics(client)['roles']['value'],1)
