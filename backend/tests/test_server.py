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
from urllib.parse import quote

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
        path=uploaded.json()['path']
        # Confinement is judged on canonical paths: the data directory is resolved once (on Windows runners the temporary directory is an 8.3 short path
        # that resolves to a different spelling), so the unresolved fixture path is never the right yardstick.
        self.assertTrue(Path(path).resolve().is_relative_to((self.data/'uploads').resolve()))
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



CONTENT=b'AGR_NAME,TEXT,TCODE\nZC:DEMO,Synthetic,MIGO\n'
LOCAL={'X-SAP-Lens':'1'}


class UploadPathTests(ServerTestBase):
    """Upload staging and source confinement on canonical paths (Linux and Windows)."""
    def stage(self,client,name='synthetic.csv',content=CONTENT):
        header=name if name.isascii() else quote(name)  # a browser sends non-ASCII names percent-encoded
        return client.post('/api/server/uploads/roles',content=content,headers={**LOCAL,'X-Upload-Filename':header,'Content-Type':'text/csv'})

    def preview(self,client,path):
        return client.post('/api/import/preview',headers=LOCAL,json={'data_csv_path':str(path)})

    def alias(self):
        """The data directory reached through a second spelling (a symlink here; an 8.3 short name on Windows runners)."""
        self.data.mkdir(parents=True,exist_ok=True);alias=self.root/'alias'
        try: alias.symlink_to(self.data,target_is_directory=True)
        except OSError: self.skipTest('Native Windows symlink privilege is not guaranteed.')
        return alias

    def test_the_staged_file_is_canonical_absolute_and_directly_inside_the_canonical_uploads_directory(self):
        client=self.client();staged=self.stage(client,'Mixed Case Name.CSV')
        self.assertEqual(staged.status_code,200,staged.text)
        path=Path(staged.json()['path'])
        self.assertTrue(path.is_absolute());self.assertEqual(path,path.resolve(),'the returned path is already canonical')
        self.assertEqual(path.parent,(self.data/'uploads').resolve());self.assertTrue(path.is_file())
        self.assertRegex(path.name,r'^[0-9a-f]{32}-Mixed Case Name\.csv$')  # an opaque prefix, the sanitised stem and a lower-case extension
        self.assertEqual(self.preview(client,path).status_code,200)

    def test_a_data_directory_reached_through_an_alias_is_stored_and_checked_canonically(self):
        alias=self.alias()
        with patch.dict(os.environ,{'SAP_LENS_DATA_DIR':str(alias),'SAP_LENS_CONFIG_DIR':str(alias)}):
            config.get_settings.cache_clear();client=self.client();staged=self.stage(client)
            self.assertEqual(staged.status_code,200,staged.text)
            path=Path(staged.json()['path'])
            self.assertEqual(path.parent,(self.data/'uploads').resolve(),'stored under the real directory, not under the alias')
            self.assertFalse(path.is_relative_to(alias),'the alias spelling is not what the application reports')
            self.assertEqual(self.preview(client,path).status_code,200)
            self.assertEqual(self.preview(client,alias/'uploads'/path.name).status_code,200,'the alias spelling resolves to the same confined file')
            self.assertEqual(self.preview(client,alias/'uploads'/'..'/'..'/'external.csv').status_code,400)

    def test_invalid_and_traversing_names_never_create_a_file(self):
        client=self.client()
        names=['../private.csv','..\\private.csv','a/../b.csv','a\\b.csv','%2e%2e%2fx.csv','a%5Cb.csv','a%2Fb.csv','C%3Aevil.csv','c:evil.csv','x.csv:stream',
               'x.csv.','x.csv%00.txt','%00.csv','a<b.csv','a%7Cb.csv','x*.csv','bad.txt','csv','.csv.exe','%ff.csv','x'*201+'.csv','']
        for name in names:
            with self.subTest(name=name[:30]):
                self.assertEqual(self.stage(client,name).status_code,400)
        uploads=self.data/'uploads'
        self.assertEqual(list(uploads.glob('**/*')) if uploads.exists() else [],[],'a refused name leaves nothing staged')

    def test_names_with_spaces_unicode_and_upper_case_extensions_are_staged_safely(self):
        client=self.client()
        for name in ('Roles Q1 2026.csv','roles-æøå.csv','ROLES.CSV'):
            with self.subTest(name=name):
                staged=self.stage(client,name);self.assertEqual(staged.status_code,200,staged.text)
                path=Path(staged.json()['path']);self.assertEqual(path.parent,(self.data/'uploads').resolve());self.assertTrue(path.suffix=='.csv')

    def test_preview_and_confirmation_accept_only_canonical_paths_inside_the_roots(self):
        client=self.client();path=Path(self.stage(client).json()['path'])
        self.assertEqual(self.preview(client,path).status_code,200)
        outside=self.root/'external.csv';outside.write_bytes(CONTENT)
        inside_source=self.sources/'roles.csv';inside_source.write_bytes(CONTENT)
        self.assertEqual(self.preview(client,inside_source).status_code,200,'the configured source directory is a root too')
        self.assertEqual(self.preview(client,outside).status_code,400)
        self.assertEqual(self.preview(client,path.parent/'..'/'..'/'external.csv').status_code,400,'a parent segment cannot leave the root')
        self.assertEqual(self.preview(client,Path('uploads')/path.name).status_code,400,'a relative path is refused')
        self.assertEqual(self.preview(client,self.data/'uploads'/'missing.csv').status_code,400)
        if sys.platform=='win32':
            self.assertEqual(self.preview(client,str(path).upper()).status_code,200,'Windows paths compare case-insensitively')
        settings=client.get('/api/configuration').json()['settings'];settings['data_csv_path']=str(outside);settings['source_modes']['roles']='static'
        self.assertEqual(client.post('/api/configuration',headers=LOCAL,json=settings).status_code,400,'an outside path cannot be confirmed')
        settings['data_csv_path']=str(path)
        self.assertEqual(client.post('/api/configuration',headers=LOCAL,json=settings).status_code,200)
        self.assertEqual(client.get('/api/roles').json()[0]['agr_name'],'ZC:DEMO')

    def test_a_link_inside_the_uploads_directory_cannot_reach_outside(self):
        client=self.client();path=Path(self.stage(client).json()['path'])
        outside=self.root/'external.csv';outside.write_bytes(CONTENT);link=path.parent/'escape.csv'
        try: link.symlink_to(outside)
        except OSError: self.skipTest('Native Windows symlink privilege is not guaranteed.')
        self.assertEqual(self.preview(client,link).status_code,400)


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
