"""Individual account boundaries, real TLS certificates, aliases and stale writes."""
import base64
import http.client
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
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
        settings = ServerSettings('127.0.0.1',18743,self.root/'data',self.root/'sources',
            'https://server01:18743',('server01','server01.example.invalid','192.0.2.10'),
            'users','','',(),'info',accounts=str(self.path))
        with patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': str(self.root/'data')}):
            config.get_settings.cache_clear()
            try:
                app = create_app(server=settings)
                for host in settings.hosts:
                    client = TestClient(app, base_url=f'https://{host}:18743', client=('192.0.2.20',50000))
                    headers = {'Authorization': self.header('reader'), 'X-SAP-Lens':'1', 'Origin':f'https://{host}:18743'}
                    response = client.get('/api/runtime', headers=headers)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()['username'], 'reader')
                    self.assertEqual(client.post('/api/refresh', headers=headers).status_code, 403)
                    self.assertEqual(client.get('/api/runtime').status_code, 401)
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


@unittest.skipUnless(shutil.which('openssl'), 'OpenSSL is needed to generate test certificates')
class TlsTests(unittest.TestCase):
    def test_direct_https_listener_serves_authenticated_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cert, key = root/'cert.pem', root/'key.pem'
            subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=localhost',
                            '-addext','subjectAltName=DNS:localhost,IP:127.0.0.1','-keyout',str(key),'-out',str(cert)],check=True,capture_output=True)
            secret=root/'secret'; secret.write_text('synthetic-secret-'+'a'*40); secret.chmod(0o600)
            frontend=root/'frontend'; frontend.mkdir(); (frontend/'index.html').write_text('<html>synthetic</html>')
            with socket.socket() as listener:
                listener.bind(('127.0.0.1',0)); port=listener.getsockname()[1]
            env={**os.environ,'SAP_LENS_HOST':'127.0.0.1','SAP_LENS_PORT':str(port),
                 'SAP_LENS_DATA_DIR':str(root/'data'),'SAP_LENS_CONFIG_DIR':str(root/'data'),
                 'SAP_LENS_SOURCE_DIR':str(root/'sources'),'SAP_LENS_PUBLIC_ORIGIN':f'https://localhost:{port}',
                 'SAP_LENS_ALLOWED_HOSTS':'localhost,127.0.0.1','SAP_LENS_AUTH':'basic',
                 'SAP_LENS_AUTH_SECRET_FILE':str(secret),'SAP_LENS_TLS_CERT_FILE':str(cert),'SAP_LENS_TLS_KEY_FILE':str(key),
                 'SAP_LENS_DEPLOYMENT_MODE':'server'}
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
                self.assertEqual(get('/api/runtime',{'Authorization':header}),200)
            finally:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)

    def test_certificate_sans_mismatch_and_complete_tls_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cert, key = root/'server.crt', root/'server.key'
            subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
                '-subj','/CN=server01','-addext','subjectAltName=DNS:server01,DNS:server01.example.invalid,IP:192.0.2.10',
                '-keyout',str(key),'-out',str(cert)],check=True,capture_output=True)
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
