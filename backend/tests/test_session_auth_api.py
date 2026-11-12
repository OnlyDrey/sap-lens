"""Session HTTP boundary and negative permissions, entirely synthetic temporary state."""
import base64
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from deployment import ServerSettings
from auth_store import AuthStore
from main import create_app
import config

PASSWORD = 'Synthetic HTTP password 123!'


class SessionApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': str(root)})
        self.env.start(); self.addCleanup(self.env.stop)
        config.get_settings.cache_clear(); self.addCleanup(config.get_settings.cache_clear)
        self.settings = ServerSettings('127.0.0.1',18743,root,root/'sources','http://localhost:18743',('localhost',),'sessions','','',(),'info')
        self.store = AuthStore(root/'security/accounts.sqlite3')
        self.store.initialize()
        self.admin = self.store.create_user(None,'admin','Admin','administrator',PASSWORD,bootstrap=True)
        self.client = TestClient(create_app(server=self.settings),base_url='http://localhost:18743',client=('127.0.0.1',1234))
        self.addCleanup(self.client.close)

    def login(self, username='admin'):
        response = self.client.post('/api/auth/login',json=dict(username=username,password=PASSWORD),headers={'X-SAP-Lens':'1'})
        self.assertEqual(response.status_code,200,response.text)
        return {'X-SAP-Lens':'1','X-SAP-Lens-CSRF':self.client.cookies['sap-lens-csrf']}

    def test_no_basic_bypass_cookie_csrf_logout(self):
        basic='Basic '+base64.b64encode(('admin:'+PASSWORD).encode()).decode()
        self.assertEqual(self.client.get('/api/auth/me',headers={'Authorization':basic}).status_code,401)
        headers=self.login()
        me=self.client.get('/api/auth/me')
        self.assertEqual(me.json()['id'],self.admin['id'])
        self.assertEqual(me.headers['cache-control'],'no-store')
        self.assertEqual(self.client.post('/api/auth/logout',headers={'X-SAP-Lens':'1'}).status_code,403)
        self.assertEqual(self.client.post('/api/auth/logout',headers=headers).status_code,200)
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)

    def test_viewer_denied_users_writes_and_review(self):
        admin=self.store.login('admin',PASSWORD,'fixture')[0]
        self.store.create_user(admin,'viewer','Viewer','viewer',PASSWORD)
        headers=self.login('viewer')
        self.assertEqual(self.client.get('/api/auth/users').status_code,403)
        for path in ('/api/refresh','/api/configuration','/api/sod/decisions/activity','/api/sod/periods/fiction/transition'):
            self.assertEqual(self.client.post(path,json={},headers=headers).status_code,403,path)
        self.assertEqual(self.client.get('/api/runtime').status_code,200)

    def test_admin_create_update_revoke_and_password(self):
        headers=self.login()
        created=self.client.post('/api/auth/users',json=dict(username='reviewer',display_name='Reviewer',role='reviewer',password=PASSWORD),headers=headers)
        self.assertEqual(created.status_code,200,created.text)
        identity=created.json()['id']
        changed=self.client.post('/api/auth/users/'+identity,json=dict(expected_revision=0,display_name='Reviewer',role='viewer',enabled=False),headers=headers)
        self.assertEqual(changed.status_code,200,changed.text)
        self.assertEqual(self.client.post('/api/auth/users/'+identity,json=dict(expected_revision=0,display_name='Reviewer',role='viewer',enabled=True),headers=headers).status_code,409)
        self.assertEqual(self.client.post('/api/auth/password',json=dict(current_password=PASSWORD,new_password=PASSWORD+' new'),headers=headers).status_code,200)
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)

    def test_cross_origin_and_network_http_are_refused(self):
        self.assertEqual(self.client.post('/api/auth/login',json=dict(username='admin',password=PASSWORD),headers={'X-SAP-Lens':'1','Origin':'https://evil.example.invalid'}).status_code,403)
        settings=ServerSettings('0.0.0.0',18743,self.settings.data,self.settings.sources,'http://localhost:18743',('localhost',),'sessions','','',(),'info')
        with TestClient(create_app(server=settings),base_url='http://localhost:18743',client=('192.0.2.10',1000)) as client:
            self.assertEqual(client.post('/api/auth/login',json=dict(username='admin',password=PASSWORD),headers={'X-SAP-Lens':'1'}).status_code,403)

    def test_validation_never_echoes_password_and_unknown_writes_deny(self):
        secret='Sensitive synthetic value '*100
        response=self.client.post('/api/auth/login',json=dict(username='admin',password=secret),headers={'X-SAP-Lens':'1'})
        self.assertEqual(response.status_code,422)
        self.assertNotIn(secret,response.text)
        headers=self.login()
        self.assertEqual(self.client.post('/api/not-a-permitted-operation',json={},headers=headers).status_code,403)

    def test_trusted_proxy_requires_both_peer_and_secret(self):
        from session_boundary import authorize
        from dataclasses import replace
        import ipaddress
        from starlette.requests import Request
        from auth_store import AuthError
        settings=replace(self.settings,host='0.0.0.0',origin='https://localhost:18743',secret='s'*48,proxies=(ipaddress.ip_network('192.0.2.1/32'),))
        def request(peer,secret):
            return Request(dict(type='http',method='POST',scheme='http',path='/api/auth/login',query_string=b'',server=('localhost',18743),client=(peer,1000),headers=[(b'x-forwarded-proto',b'https'),(b'x-sap-lens-proxy-token',secret.encode())]))
        self.assertIsNone(authorize(self.store,request('192.0.2.1','s'*48),settings))
        for peer,secret in [('192.0.2.2','s'*48),('192.0.2.1','wrong')]:
            with self.assertRaises(AuthError):authorize(self.store,request(peer,secret),settings)

    def test_login_cookie_flags(self):
        response=self.client.post('/api/auth/login',json=dict(username='admin',password=PASSWORD),headers={'X-SAP-Lens':'1'})
        cookies=response.headers.get_list('set-cookie')
        session=next(c for c in cookies if c.startswith('sap-lens-session='))
        self.assertIn('HttpOnly',session)
        self.assertIn('SameSite=lax',session)
        self.assertNotIn('Secure',session)  # Explicit loopback HTTP only.

    def test_https_cookie_secure_and_profile_revision(self):
        from dataclasses import replace
        with TestClient(create_app(server=replace(self.settings, origin='https://localhost:18743')), base_url='https://localhost:18743', client=('127.0.0.1',1234)) as client:
            response=client.post('/api/auth/login',json=dict(username='admin',password=PASSWORD),headers={'X-SAP-Lens':'1'})
            self.assertEqual(response.status_code,200,response.text)
            self.assertTrue(all('Secure' in c for c in response.headers.get_list('set-cookie')))
            self.assertEqual(client.get('/api/auth/me').json()['revision'],0)
            headers={'X-SAP-Lens':'1','X-SAP-Lens-CSRF':client.cookies['sap-lens-csrf']}
            response=client.post('/api/auth/profile',json=dict(display_name='Updated name',expected_revision=0),headers=headers)
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(client.get('/api/auth/me').json()['revision'],1)

    def test_fresh_activation_requires_local_code_and_closes_atomically(self):
        from auth_provisioning import prepare,issue
        from dataclasses import replace
        root=self.settings.data/'fresh'
        root.mkdir()
        store=prepare(root)
        code=issue(store)['code']
        with TestClient(create_app(server=replace(self.settings,data=root)),base_url='http://localhost:18743',client=('127.0.0.1',1234)) as client:
            state=client.get('/api/auth/state')
            self.assertEqual(state.json(),dict(provider='local-sessions',setup_required=True))
            self.assertNotIn(code,state.text)
            self.assertEqual(client.post('/api/auth/issue',json={},headers={'X-SAP-Lens':'1'}).status_code,401)
            body=dict(username='admin',display_name='Administrator',password=PASSWORD,code=code)
            self.assertEqual(client.post('/api/auth/activate',json=body,headers={'X-SAP-Lens':'1','Origin':'https://evil.example.invalid'}).status_code,403)
            response=client.post('/api/auth/activate',json=body,headers={'X-SAP-Lens':'1'})
            self.assertEqual(response.status_code,200,response.text)
            self.assertFalse(client.get('/api/auth/state').json()['setup_required'])
            self.assertNotEqual(client.post('/api/auth/activate',json=body,headers={'X-SAP-Lens':'1'}).status_code,200)

    def test_viewer_receives_only_presentation_settings(self):
        from unittest.mock import patch
        from config_models import AppConfig
        admin=self.store.login('admin',PASSWORD,'fixture')[0]
        self.store.create_user(admin,'viewer','Viewer','viewer',PASSWORD)
        self.login('viewer')
        self.assertEqual(self.client.get('/api/configuration').status_code,403)
        config=AppConfig(data_csv_path='/private/synthetic-source.csv')
        with patch('configuration_routes.get_settings',return_value=config):
            response=self.client.get('/api/presentation')
        self.assertEqual(response.status_code,200,response.text)
        self.assertNotIn('/private/',response.text)
        self.assertEqual(response.json()['settings']['data_csv_path'],'')
        self.assertEqual(self.client.get('/api/branding/preview?path=/private/image.png').status_code,403)

    def test_session_reviewer_identity_is_authoritative_for_sod_and_self_acceptance(self):
        import cache
        from test_sod_governance import snapshot
        from config_models import SourceSnapshot
        self.addCleanup(cache.clear_cache)
        cache._cache=snapshot()
        settings=config.get_settings().model_copy(deep=True)
        settings.features.sod=True
        settings.data_lifecycle.sources['sod']=SourceSnapshot(snapshot='a'*64,path=str(self.settings.data/'synthetic.csv'),imported_at='2026-10-27T00:00:00+00:00',checked_at='2026-10-27T00:00:00+00:00')
        config.save_configuration(settings,settings.revision)
        admin=self.store.login('admin',PASSWORD,'fixture')[0]
        user=self.store.create_user(admin,'reviewer','Verified reviewer','reviewer',PASSWORD)
        headers=self.login('reviewer')
        data=self.client.get('/api/sod/subject?user=SYN_A&risk=R1').json()
        found=data['risk']
        body=dict(context='current',expected_revision=data['revision'],expected_generation=data['generation'],items=[dict(key=found['finding_id'],user='SYN_A',ref='R1',evidence_version=found['evidence_version'])],decision='Accepted',reviewer='Forged actor',approver='Forged approver',justification='Explicit self-acceptance')
        response=self.client.post('/api/sod/decisions/acceptance',json=body,headers=headers)
        self.assertEqual(response.status_code,200,response.text)
        event=response.json()['events'][0]
        self.assertEqual(event['reviewer'],'reviewer')
        self.assertEqual(event['approver'],'reviewer')
        self.assertEqual(event['actor_identity'],dict(id=user['id'],username='reviewer',display_name='Verified reviewer',provenance='server-session'))
        self.assertEqual(self.client.post('/api/sod/decisions/acceptance',json=body,headers=headers).status_code,409)

    def test_backup_secret_validation_is_private_and_mutations_require_admin_csrf(self):
        headers=self.login()
        secret='Synthetic backup secret '*80
        response=self.client.post('/api/backups/create',headers=headers,json={'passphrase':secret})
        self.assertEqual(response.status_code,422)
        self.assertNotIn(secret,response.text)
        self.assertEqual(self.client.post('/api/backups/key/verify',headers={'X-SAP-Lens':'1'},json={'recovery_key':'x'*44}).status_code,403)
        admin=self.store.login('admin',PASSWORD,'fixture')[0]
        self.store.create_user(admin,'reader','Reader','viewer',PASSWORD)
        headers=self.login('reader')
        for path in ('/api/backups/create','/api/backups/key/verify','/api/backups/restore'):
            self.assertEqual(self.client.post(path,headers=headers,json={}).status_code,403)
