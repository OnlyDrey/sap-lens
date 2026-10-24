"""Synthetic server boundaries, upload confinement, leases and real process lifecycle."""
import base64
import http.client
import json
import os
from pathlib import Path
import socket
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cache
import config
from deployment import ServerSettings
from employee_directory import store
from fastapi.testclient import TestClient
from main import create_app
from storage_lease import StorageLease


class ServerTestBase(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.data=self.root/'server data';self.sources=self.root/'sources';self.sources.mkdir()
        self.secret=self.root/'access.secret';self.secret.write_text('synthetic-access-secret-'+'a'*40);self.secret.chmod(0o600)
        self.env=patch.dict(os.environ,{'SAP_LENS_DEPLOYMENT_MODE':'server','SAP_LENS_DATA_DIR':str(self.data),
            'SAP_LENS_CONFIG_DIR':str(self.data),'SAP_LENS_SOURCE_DIR':str(self.sources),'SAP_LENS_HOST':'127.0.0.1',
            'SAP_LENS_PORT':'18743','SAP_LENS_PUBLIC_ORIGIN':'http://127.0.0.1:18743','SAP_LENS_ALLOWED_HOSTS':'127.0.0.1',
            'SAP_LENS_AUTH':'local','SAP_LENS_AUTH_SECRET_FILE':str(self.secret),'SAP_LENS_TRUSTED_PROXIES':'','DATA_CSV_PATH':''})
        self.env.start();config.get_settings.cache_clear();cache.clear_cache();store.clear()
        # Unit boundaries must not depend on an ignored production build being present.
        frontend=self.root/'unit-frontend';frontend.mkdir();(frontend/'index.html').write_text('<html>synthetic unit frontend</html>')
        self.frontend_patch=patch('main.frontend_dir',frontend);self.frontend_patch.start()
    def tearDown(self):
        self.frontend_patch.stop();config.get_settings.cache_clear();cache.clear_cache();store.clear();self.env.stop();self.temp.cleanup()
    def client(self,peer='127.0.0.1',origin='http://127.0.0.1:18743'):
        return TestClient(create_app(server=ServerSettings.from_env()),base_url=origin,client=(peer,50000))
    def basic(self): return {'Authorization':'Basic '+base64.b64encode(('saplens:'+self.secret.read_text()).encode()).decode(),'X-SAP-Lens':'1'}


class ServerTests(ServerTestBase):
    def test_local_defaults_and_invalid_exposure(self):
        s=ServerSettings.from_env();self.assertEqual((s.host,s.auth),('127.0.0.1','local'))
        for values in [{'SAP_LENS_HOST':'0.0.0.0'},{'SAP_LENS_ALLOWED_HOSTS':'*'},{'SAP_LENS_PORT':'0'},
                       {'SAP_LENS_PUBLIC_ORIGIN':'http://lens.example.test','SAP_LENS_ALLOWED_HOSTS':'lens.example.test'},
                       {'SAP_LENS_AUTH':'proxy','SAP_LENS_TRUSTED_PROXIES':'0.0.0.0/0'}]:
            with patch.dict(os.environ,values),self.assertRaises(ValueError):ServerSettings.from_env()
        self.assertEqual(self.client(peer='192.0.2.20').get('/api/configuration').status_code,401)
    def test_basic_boundary_guards_frontend_reads_writes_and_origins(self):
        with patch.dict(os.environ,{'SAP_LENS_AUTH':'basic'}):client=self.client()
        for path in ['/','/api/configuration','/api/roles','/api/server/uploads/users']:
            self.assertEqual(client.get(path).status_code,401)
        headers=self.basic()
        self.assertEqual(client.get('/',headers=headers).status_code,200)
        result=client.get('/api/configuration',headers=headers)
        self.assertEqual(result.status_code,200);self.assertNotIn(self.secret.read_text(),result.text)
        self.assertEqual(client.post('/api/refresh',headers={**headers,'Origin':'https://evil.example.test'}).status_code,403)
        self.assertEqual(client.get('/api/roles',headers={**headers,'Host':'evil.example.test'}).status_code,400)
        self.assertEqual(client.get('/health/live').json(),{'status':'alive'})
        self.assertEqual(client.get('/health/ready').json(),{'status':'ready'})
        self.assertEqual(client.get('/health').status_code,401)
    def test_proxy_requires_real_peer_secret_identity_and_https_attestation(self):
        with patch.dict(os.environ,{'SAP_LENS_AUTH':'proxy','SAP_LENS_TRUSTED_PROXIES':'127.0.0.1/32',
            'SAP_LENS_PUBLIC_ORIGIN':'https://lens.example.test','SAP_LENS_ALLOWED_HOSTS':'lens.example.test'}):
            client=self.client(origin='https://lens.example.test');external=self.client(peer='192.0.2.10',origin='https://lens.example.test')
        headers={'X-SAP-Lens-Proxy-Token':self.secret.read_text(),'X-SAP-Lens-Identity':'synthetic-analyst','X-Forwarded-Proto':'https'}
        self.assertEqual(client.get('/api/roles',headers=headers).status_code,200)
        self.assertEqual(external.get('/api/roles',headers={**headers,'X-Forwarded-For':'127.0.0.1'}).status_code,401)
        for key in headers:
            self.assertEqual(client.get('/api/roles',headers={k:v for k,v in headers.items() if k!=key}).status_code,401)
    def test_csv_upload_preview_confirmation_path_confinement_and_redaction(self):
        client=self.client();headers={'X-SAP-Lens':'1','X-Upload-Filename':'synthetic.csv','Content-Type':'text/csv'}
        content=b'AGR_NAME,TEXT,TCODE\nZC:DEMO,Synthetic,MIGO\n'
        for name in ['../private.csv','a%2Fprivate.csv','bad.txt','C%3Aevil.csv']:
            self.assertEqual(client.post('/api/server/uploads/roles',content=content,headers={**headers,'X-Upload-Filename':name}).status_code,400)
        self.assertEqual(client.post('/api/server/uploads/roles',content=b'',headers=headers).status_code,400)
        self.assertEqual(client.post('/api/server/uploads/roles',content=content,headers={**headers,'X-Upload-Filename':'%ff.csv'}).status_code,400)
        uploaded=client.post('/api/server/uploads/roles',content=content,headers=headers)
        self.assertEqual(uploaded.status_code,200,uploaded.text)
        path=uploaded.json()['path'];self.assertTrue(Path(path).is_relative_to(self.data/'uploads'))
        self.assertEqual(client.get('/api/roles').json(),[])
        self.assertEqual(client.post('/api/import/preview',headers={'X-SAP-Lens':'1'},json={'data_csv_path':path}).status_code,200)
        settings=client.get('/api/configuration').json()['settings'];settings['data_csv_path']=path
        self.assertEqual(client.post('/api/configuration',headers={'X-SAP-Lens':'1'},json=settings).status_code,400)
        settings['source_modes']['roles']='static'
        saved=client.post('/api/configuration',headers={'X-SAP-Lens':'1'},json=settings)
        self.assertEqual(saved.status_code,200,saved.text)
        self.assertEqual(client.get('/api/roles').json()[0]['agr_name'],'ZC:DEMO')
        external=self.root/'external.csv';external.write_bytes(content)
        self.assertEqual(client.post('/api/import/preview',headers={'X-SAP-Lens':'1'},json={'data_csv_path':str(external)}).status_code,400)
        link=self.sources/'linked.csv'
        try: link.symlink_to(external)
        except OSError: pass  # Native Windows symlink privilege is not guaranteed.
        else: self.assertEqual(client.post('/api/import/preview',headers={'X-SAP-Lens':'1'},json={'data_csv_path':str(link)}).status_code,400)
        self.assertEqual(client.post('/api/branding/preview',headers={'X-SAP-Lens':'1'},json={'path':str(external)}).status_code,403)
        exported=client.get('/api/diagnostics/export').text
        self.assertNotIn(str(self.root),exported);self.assertNotIn('ZC:DEMO',exported)
    def test_server_mode_factory_cannot_omit_authentication(self):
        with patch.dict(os.environ,{'SAP_LENS_AUTH':'basic'}):
            client=TestClient(create_app(),base_url='http://127.0.0.1:18743')
        self.assertEqual(client.get('/api/configuration').status_code,401)

    def test_uploads_keep_sources_independent_and_reject_oversized_stream(self):
        client=self.client();headers={'X-SAP-Lens':'1','X-Upload-Filename':'Synthetic.csv'}
        users=client.post('/api/server/uploads/users',headers=headers,content=b'USERNAME,ROLE_NAME\nDEMO,ZC:DEMO\n')
        self.assertEqual(users.status_code,200)
        self.assertEqual(client.post('/api/user-import/preview',headers={'X-SAP-Lens':'1'},json={'data_csv_path':users.json()['path']}).status_code,200)
        self.assertEqual(client.get('/api/access/users').json()['total'],0)
        # Stream large chunks instead of buffering the whole file in the endpoint.
        too_large=client.post('/api/server/uploads/employees',headers=headers,content=(b'x'*1024*1024 for _ in range(51)))
        self.assertEqual(too_large.status_code,413)
        self.assertTrue(Path(users.json()['path']).is_file())
        self.assertEqual(client.get('/api/configuration').json()['settings']['employee_csv_path'],'')

    def test_shared_storage_lease_and_deployment_isolation(self):
        first=StorageLease(self.data,'server').acquire()
        try:
            with self.assertRaises(RuntimeError):StorageLease(self.data,'server').acquire()
        finally:first.close()
        with self.assertRaises(RuntimeError):StorageLease(self.data,'desktop').acquire()
        second=StorageLease(self.data,'server').acquire();second.close()


class ServerProcessTests(ServerTestBase):
    @unittest.skipIf(os.name=='nt','POSIX process signal lifecycle; Windows service Ctrl+C/SCM requires native acceptance tests')
    def test_headless_process_shutdown_port_conflicts_and_restart_persistence(self):
        with socket.socket() as reserve:reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
        env={**os.environ,'SAP_LENS_PORT':str(port),'SAP_LENS_PUBLIC_ORIGIN':f'http://127.0.0.1:{port}'}
        # Exercise the real entry point with isolated source/assets, not a prebuilt checkout.
        runtime=self.root/'runtime';backend=runtime/'backend';backend.mkdir(parents=True)
        source=Path(__file__).resolve().parents[1]
        for file in source.glob('*.py'):shutil.copyfile(file,backend/file.name)
        shutil.copytree(source/'routers',backend/'routers',ignore=shutil.ignore_patterns('__pycache__'))
        frontend=runtime/'frontend/dist';frontend.mkdir(parents=True);(frontend/'index.html').write_text('<html>synthetic process frontend</html>')
        command=[sys.executable,str(backend/'server.py')]
        def start():
            process=subprocess.Popen(command,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            deadline=time.monotonic()+8
            while time.monotonic()<deadline:
                try:
                    if request('GET','/health/live')[0]==200:return process
                except OSError:pass
                if process.poll() is not None:break
                time.sleep(.05)
            process.terminate();process.wait(5);self.fail('Headless server did not start')
        def request(method,path,body=None):
            connection=http.client.HTTPConnection('127.0.0.1',port,timeout=3)
            try:
                connection.request(method,path,json.dumps(body) if body else None,headers={'X-SAP-Lens':'1','Content-Type':'application/json'})
                response=connection.getresponse();return response.status,response.read()
            finally:connection.close()
        process=start()
        try:
            self.assertIn(b'<html',request('GET','/')[1])
            duplicate=subprocess.run(command,env=env,capture_output=True,timeout=5)
            self.assertNotEqual(duplicate.returncode,0)
            other={**env,'SAP_LENS_DATA_DIR':str(self.root/'other'),'SAP_LENS_CONFIG_DIR':str(self.root/'other')}
            self.assertNotEqual(subprocess.run(command,env=other,capture_output=True,timeout=5).returncode,0)
            source=self.sources/'catalogue.csv';source.write_text('AGR_NAME,TCODE\nZC:DEMO,MIGO\n')
            settings=json.loads(request('GET','/api/configuration')[1])['settings'];settings['data_csv_path']=str(source);settings['source_modes']['roles']='static'
            self.assertEqual(request('POST','/api/configuration',settings)[0],200)
            source.unlink()
        finally:process.terminate();self.assertIn(process.wait(8),(0,-15))
        process=start()
        try:
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                if json.loads(request('GET','/api/roles')[1]):break
                time.sleep(.05)
            self.assertEqual(json.loads(request('GET','/api/roles')[1])[0]['agr_name'],'ZC:DEMO')
        finally:process.terminate();self.assertIn(process.wait(8),(0,-15))
