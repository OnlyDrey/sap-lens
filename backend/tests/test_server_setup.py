"""Individual account boundaries, real TLS certificates, aliases and stale writes."""
import base64
import http.client
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
from tls_fixture import issue
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
import config
from deployment import ServerSettings
from main import create_app
from server_access import ACTOR, authenticate, manage_user, may_access, read_accounts


class AccountsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root/'users.json'
        manage_user(self.path, dict(username='admin', role='administrator', password='Synthetic-password-123!', enabled=True))

    def header(self, username='admin', password='Synthetic-password-123!'):
        return 'Basic ' + base64.b64encode(f'{username}:{password}'.encode()).decode()

    def migrate_accounts(self):
        from storage_lease import StorageLease
        from identity_migration import migrate
        from auth_store import AuthStore
        import backup_crypto as crypto
        data=self.root/'data';key=self.root/'backup.key';crypto.create_key(key,data)
        lease=StorageLease(data,'server').acquire()
        try:
            with patch.dict(os.environ,{'SAP_LENS_BACKUP_KEY_FILE':str(key)}):migrate(lease,'users',str(self.path))
        finally:lease.close()
        return AuthStore(data/'security/accounts.sqlite3')

    def login(self,client,username='admin',password='Synthetic-password-123!'):
        response=client.post('/api/auth/login',headers={'X-SAP-Lens':'1'},json=dict(username=username,password=password))
        self.assertEqual(response.status_code,200,response.text)
        return {'X-SAP-Lens':'1','X-SAP-Lens-CSRF':client.cookies['sap-lens-csrf']}

    def test_hashed_accounts_wrong_password_revocation_and_last_admin(self):
        self.assertNotIn('Synthetic-password', self.path.read_text())
        self.assertEqual(authenticate(self.path, self.header()), ('admin', 'administrator'))
        for header in [self.header(password='wrong'), self.header(username='missing'), 'Basic invalid', 'Bearer invalid']:
            self.assertIsNone(authenticate(self.path, header))
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            manage_user(self.path, dict(username='admin', role='read-only', password='', enabled=True))
        self.assertEqual(self.path.read_bytes(), before)
        manage_user(self.path, dict(username='reader', role='read-only', password='Synthetic-password-123!', enabled=True))
        self.assertEqual(authenticate(self.path, self.header('reader')), ('reader', 'read-only'))
        manage_user(self.path, dict(username='reader', role='read-only', password='', enabled=False))
        self.assertIsNone(authenticate(self.path, self.header('reader')))
        self.assertEqual(read_accounts(self.path)['schema'], 1)

    def test_passwords_and_malformed_account_files_fail_closed(self):
        for name in ['bad user', '../outside', 'a'*101]:
            with self.assertRaises(ValueError):
                manage_user(self.path, dict(username=name, role='reviewer', password='Synthetic-password-123!', enabled=True))
        with self.assertRaises(ValueError):
            manage_user(self.path, dict(username='short', role='reviewer', password='short', enabled=True))
        for text in ['[]', '{}', '{"schema":1,"users":{}}', 'invalid']:
            self.path.write_text(text)
            self.assertIsNone(authenticate(self.path, self.header()))

    def test_password_update_blank_preservation_and_reopened_store(self):
        original=read_accounts(self.path)['users']['admin']
        password='Updated-synthetic-æ-password-456!'
        manage_user(self.path,dict(username='admin',role='administrator',password=password,enabled=True))
        updated=read_accounts(self.path)['users']['admin']
        self.assertNotEqual(updated['hash'],original['hash'])
        self.assertNotEqual(updated['salt'],original['salt'])
        self.assertIsNone(authenticate(self.path,self.header()))
        self.assertEqual(authenticate(Path(str(self.path)),self.header(password=password)),('admin','administrator'))
        manage_user(self.path,dict(username='admin',role='administrator',password='',enabled=True))
        self.assertEqual(read_accounts(self.path)['users']['admin'],updated)
        self.assertNotIn(password,self.path.read_text())
        self.assertEqual(authenticate(self.path,self.header(password=password)),('admin','administrator'))
        # Fresh interpreter, same store; header/password go through stdin, not argv.
        code='import json,sys; from server_access import authenticate; p=json.load(sys.stdin); print(authenticate(p["path"],p["header"]) == ("admin","administrator"))'
        done=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).resolve().parents[1],input=json.dumps(dict(path=str(self.path),header=self.header(password=password))),capture_output=True,text=True,timeout=15)
        self.assertEqual(done.returncode,0,done.stderr)
        self.assertEqual(done.stdout.strip(),'True')

    def test_migrated_account_updates_use_application_sessions_and_persist_across_restart(self):
        identities=self.migrate_accounts()
        settings=ServerSettings('127.0.0.1',18743,self.root/'data',self.root/'sources','https://localhost:18743',('localhost',),'users','','',(),'info',accounts=str(self.path))
        with patch.dict(os.environ,{'SAP_LENS_CONFIG_DIR':str(self.root/'data')}):
            config.get_settings.cache_clear();self.addCleanup(config.get_settings.cache_clear)
            client=TestClient(create_app(server=settings),base_url='https://localhost:18743',client=('127.0.0.1',50000))
            self.assertEqual(client.get('/api/runtime',headers={'Authorization':self.header()}).status_code,401)
            self.login(client)
            self.assertEqual(client.get('/api/runtime').status_code,200)
            administrator=identities.login('admin','Synthetic-password-123!','fixture')[0]
            row=identities.create_user(administrator,'reader','Reader','viewer','Synthetic-password-123!')
            self.login(client,'reader')
            self.assertEqual(client.get('/api/runtime').json()['role'],'viewer')
            changed=identities.update_user(administrator,row['id'],row['revision'],display_name='Reader',role='reviewer',enabled=True)
            self.assertEqual(client.get('/api/runtime').status_code,401)
            reset=identities.issue_reset(administrator,row['id'],changed['revision'])
            identities.complete_reset(reset['code'],'Changed-synthetic-password-123!','reset')
            self.login(client,'reader','Changed-synthetic-password-123!')
            self.assertEqual(client.get('/api/runtime').json()['role'],'reviewer')
            restarted=TestClient(create_app(server=settings),base_url='https://localhost:18743',client=('127.0.0.1',50000))
            self.login(restarted,'reader','Changed-synthetic-password-123!')
            self.assertEqual(restarted.get('/api/runtime').status_code,200)
            latest=next(user for user in identities.users(administrator) if user['id']==row['id'])
            identities.update_user(administrator,row['id'],latest['revision'],display_name='Reader',role='reviewer',enabled=False)
            self.assertEqual(client.get('/api/runtime').status_code,401)
            self.assertEqual(restarted.get('/api/runtime').status_code,401)

    def test_current_legacy_writers_serialize_and_unknown_lock_is_never_removed(self):
        from concurrent.futures import ThreadPoolExecutor
        from server_access import account_write_lock
        def save(number):
            manage_user(self.path,dict(username='synthetic-'+str(number),role='read-only',password='Synthetic parallel password 123!',enabled=True))
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(save,range(4)))
        self.assertEqual(len(read_accounts(self.path)['users']),5)
        lock=self.path.with_suffix('.lock')
        self.assertTrue(lock.read_bytes().startswith(b'SAP Lens account lock v2'))
        lock.write_bytes(b'legacy-unknown-owner')
        with patch('server_access.time.monotonic',side_effect=[0,6]):
            with self.assertRaises(ValueError):
                with account_write_lock(self.path):self.fail('Unknown lock was bypassed.')
        self.assertEqual(lock.read_bytes(),b'legacy-unknown-owner')

    def test_account_store_error_is_logged_without_credentials_or_paths(self):
        with patch('server_access.read_accounts',side_effect=PermissionError('sensitive path or credential')),self.assertLogs('sap-lens-server',level='WARNING') as captured:
            self.assertIsNone(authenticate(self.path,self.header()))
        text=' '.join(captured.output)
        self.assertIn('PermissionError',text)
        for private in ('sensitive path','Synthetic-password',str(self.path),'admin'):
            self.assertNotIn(private,text)

    def test_roles_deny_unknown_writes_and_reserve_administration(self):
        for path in ['/api/refresh', '/api/configuration', '/api/sod/periods', '/api/sod/periods/demo/delete', '/api/server/uploads/roles']:
            self.assertFalse(may_access('read-only', 'POST', path))
            self.assertFalse(may_access('reviewer', 'POST', path))
            self.assertTrue(may_access('administrator', 'POST', path))
        for path in ['/api/account-review/decision/DEMO', '/api/sod/decisions/activity', '/api/sod/periods/demo/reviews/finding']:
            self.assertTrue(may_access('reviewer', 'POST', path))
            self.assertFalse(may_access('read-only', 'POST', path))

    def test_real_requests_authenticate_enforce_roles_and_accept_alias_origins(self):
        manage_user(self.path, dict(username='reader', role='read-only', password='Synthetic-password-123!', enabled=True))
        self.migrate_accounts()
        settings = ServerSettings('127.0.0.1',18743,self.root/'data',self.root/'sources',
            'https://server01:18743',('server01','server01.example.invalid','192.0.2.10'),
            'users','','',(),'info',accounts=str(self.path))
        with patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': str(self.root/'data')}):
            config.get_settings.cache_clear()
            try:
                app = create_app(server=settings)
                for host in settings.hosts:
                    client = TestClient(app, base_url=f'https://{host}:18743', client=('192.0.2.20',50000))
                    self.assertEqual(client.get('/api/runtime').status_code,401)
                    headers={**self.login(client,'reader'),'Origin':f'https://{host}:18743'}
                    response = client.get('/api/runtime', headers=headers)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()['username'], 'reader')
                    self.assertEqual(client.post('/api/refresh', headers=headers).status_code, 403)
                    self.assertEqual(client.get('/api/runtime', headers={**headers,'Origin':'https://evil.example.invalid'}).status_code, 403)
                    self.assertEqual(client.get('/api/runtime', headers={**headers,'Host':'evil.example.invalid'}).status_code, 400)
                self.assertEqual(ACTOR.get(), '')
            finally:
                config.get_settings.cache_clear()

    def test_server_decisions_record_authenticated_actor(self):
        import account_review
        from datetime import datetime, timezone
        from fastapi import HTTPException
        import routers.account_review as routes
        stamp = datetime.now(timezone.utc).isoformat()
        row = dict(username='DEMO', evidence_version='a'*64, identity_version='b'*64, decision={'timestamp':stamp})
        decision = routes.Decision(state='Investigating', reviewer='spoofed', rationale='Synthetic review', evidence_version='a'*64, expected_decision='')
        token = ACTOR.set('real-user')
        try:
            with patch.object(routes,'current',return_value=(None,None,[row],None)), patch.object(account_review,'save_decision') as save:
                with self.assertRaises(HTTPException) as error: routes.decision('DEMO',decision)
                self.assertEqual(error.exception.status_code,409)
                save.assert_not_called()
            with patch.object(account_review,'decisions',return_value={}), patch.object(account_review,'write_decisions') as write:
                account_review.save_decision('DEMO',{'reviewer':'spoofed'})
                saved = write.call_args.args[0]
                self.assertEqual(next(iter(saved.values()))['reviewer'],'real-user')
        finally:
            ACTOR.reset(token)


class TlsTests(unittest.TestCase):
    def test_direct_https_listener_serves_authenticated_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cert, key = root/'cert.pem', root/'key.pem'
            issue(root,'cert','DNS:localhost,IP:127.0.0.1',days=1); cert, key = root/'cert.crt', root/'cert.key'
            secret=root/'secret'; secret.write_text('synthetic-secret-'+'a'*40); secret.chmod(0o600)
            frontend=root/'frontend'; frontend.mkdir(); (frontend/'index.html').write_text('<html>synthetic</html>')
            with socket.socket() as listener:
                listener.bind(('127.0.0.1',0)); port=listener.getsockname()[1]
            env={**os.environ,'SAP_LENS_HOST':'127.0.0.1','SAP_LENS_PORT':str(port),
                 'SAP_LENS_DATA_DIR':str(root/'data'),'SAP_LENS_CONFIG_DIR':str(root/'data'),
                 'SAP_LENS_SOURCE_DIR':str(root/'sources'),'SAP_LENS_PUBLIC_ORIGIN':f'https://localhost:{port}',
                 'SAP_LENS_ALLOWED_HOSTS':'localhost,127.0.0.1','SAP_LENS_AUTH':'sessions',
                 'SAP_LENS_AUTH_SECRET_FILE':str(secret),'SAP_LENS_TLS_CERT_FILE':str(cert),'SAP_LENS_TLS_KEY_FILE':str(key),
                 'SAP_LENS_DEPLOYMENT_MODE':'server'}
            from auth_store import AuthStore
            identities=AuthStore(root/'data/security/accounts.sqlite3');identities.initialize()
            identities.create_user(None,'admin','Synthetic TLS administrator','administrator',secret.read_text(),bootstrap=True)
            source=Path(__file__).resolve().parents[1]
            command=[sys.executable,'-c',f'import sys;sys.path.insert(0,{str(source)!r});import main;from pathlib import Path;main.frontend_dir=Path({str(frontend)!r});import server;sys.exit(server.run())']
            process=subprocess.Popen(command,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            context=ssl.create_default_context(cafile=str(cert))
            def get(path, headers=None):
                connection=http.client.HTTPSConnection('127.0.0.1',port,context=context,timeout=2)
                try:
                    connection.request('GET',path,headers=headers or {})
                    response=connection.getresponse(); response.read(); return response.status
                finally: connection.close()
            try:
                deadline=time.monotonic()+20
                while True:
                    try:
                        if get('/health/live')==200:break
                    except OSError:pass
                    if time.monotonic()>deadline or process.poll() is not None:self.fail('HTTPS listener did not start.')
                    time.sleep(0.1)
                self.assertEqual(get('/api/runtime'),401)
                header='Basic '+base64.b64encode(('saplens:'+secret.read_text()).encode()).decode()
                self.assertEqual(get('/api/runtime',{'Authorization':header}),401)
                connection=http.client.HTTPSConnection('127.0.0.1',port,context=context,timeout=3)
                try:
                    connection.request('POST','/api/auth/login',json.dumps(dict(username='admin',password=secret.read_text())),headers={'X-SAP-Lens':'1','Content-Type':'application/json'})
                    response=connection.getresponse();self.assertEqual(response.status,200,response.read())
                    cookie='; '.join(value.split(';',1)[0] for key,value in response.getheaders() if key.lower()=='set-cookie')
                finally:connection.close()
                self.assertEqual(get('/api/runtime',{'Cookie':cookie}),200)
            finally:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)

    def test_certificate_sans_mismatch_and_complete_tls_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cert, key = root/'server.crt', root/'server.key'
            issue(root,'server','DNS:server01,DNS:server01.example.invalid,IP:192.0.2.10',days=1,common_name='server01')
            env = dict(SAP_LENS_HOST='0.0.0.0',SAP_LENS_PORT='19443',SAP_LENS_DATA_DIR=str(root/'data'),
                SAP_LENS_SOURCE_DIR=str(root/'sources'),SAP_LENS_PUBLIC_ORIGIN='https://server01:19443',
                SAP_LENS_ALLOWED_HOSTS='server01,server01.example.invalid,192.0.2.10',SAP_LENS_AUTH='basic',
                SAP_LENS_AUTH_SECRET_FILE=str(root/'secret'),SAP_LENS_TLS_CERT_FILE=str(cert),SAP_LENS_TLS_KEY_FILE=str(key))
            (root/'secret').write_text('synthetic-'+'a'*40); (root/'secret').chmod(0o600)
            with patch.dict(os.environ,env,clear=True):
                settings = ServerSettings.from_env()
                self.assertEqual(settings.tls_cert,str(cert))
                self.assertIn('https://192.0.2.10:19443',settings.origins)
                for changed in [{'SAP_LENS_TLS_KEY_FILE':''}, {'SAP_LENS_ALLOWED_HOSTS':'server01,other.example.invalid'},
                                {'SAP_LENS_ALLOWED_HOSTS':'server01,0.0.0.0'}, {'SAP_LENS_ALLOWED_HOSTS':'server01,evil:19443'}]:
                    with self.subTest(changed=changed), patch.dict(os.environ,changed), self.assertRaises((ValueError,OSError)):
                        ServerSettings.from_env()
