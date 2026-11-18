"""SEC-02: legacy limiter compatibility and current durable session sign-in protection."""
import base64
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cache
import config
from deployment import AuthThrottle, ServerSettings
from employee_directory import store
from fastapi.testclient import TestClient
from main import create_app
from starlette.datastructures import Headers

SECRET = 'synthetic-access-secret-' + 'a' * 40
ORIGIN = 'http://127.0.0.1:18743'


class Clock:
    def __init__(self): self.now = 1000.0
    def __call__(self): return self.now


def basic(user='saplens', password=SECRET):
    return {'Authorization': 'Basic ' + base64.b64encode(f'{user}:{password}'.encode()).decode()}


class ThrottleTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock(); self.throttle = AuthThrottle(5, 60, self.clock)

    def fail(self, key='203.0.113.9', times=1):
        return [self.throttle.failure(key) for _ in range(times)]

    def test_locks_out_after_the_configured_failures_and_reports_the_remaining_time(self):
        self.assertEqual(self.fail(times=4), [0, 0, 0, 0])
        self.assertEqual(self.throttle.blocked_for('203.0.113.9'), 0)
        self.assertEqual(self.fail(), [60])
        self.assertEqual(self.throttle.blocked_for('203.0.113.9'), 60)
        self.clock.now += 20.5
        self.assertEqual(self.throttle.blocked_for('203.0.113.9'), 40)
        self.assertEqual(self.throttle.blocked_for('198.51.100.1'), 0, 'another client is not affected')

    def test_the_lockout_expires_and_the_next_one_is_longer_up_to_a_cap(self):
        self.fail(times=5); self.clock.now += 61
        self.assertEqual(self.throttle.blocked_for('203.0.113.9'), 0, 'recovers after the cooldown')
        self.assertEqual(self.fail(times=5)[-1], 120)
        cooldowns = []
        for _ in range(8): self.clock.now += 1000; self.throttle.failure('x'); cooldowns.append(max(self.fail('x', 4)))
        self.assertEqual(max(cooldowns), AuthThrottle.MAX_COOLDOWN)

    def test_failures_spread_over_more_than_the_window_do_not_add_up(self):
        for _ in range(4): self.fail(); self.clock.now += AuthThrottle.WINDOW / 2
        self.assertEqual(self.throttle.blocked_for('203.0.113.9'), 0)

    def test_a_correct_sign_in_clears_the_record(self):
        self.fail(times=4); self.throttle.success('203.0.113.9')
        self.assertEqual(self.fail(times=4), [0, 0, 0, 0])

    def test_state_is_bounded_and_active_lockouts_outlive_flooding(self):
        self.fail('locked', 5)
        for index in range(AuthThrottle.MAX_CLIENTS * 3): self.throttle.failure(f'10.{index // 65536}.{index // 256 % 256}.{index % 256}')
        self.assertLessEqual(len(self.throttle), AuthThrottle.MAX_CLIENTS)
        self.assertGreater(self.throttle.blocked_for('locked'), 0, 'idle entries are evicted before an active lock-out')

    def test_idle_records_are_dropped(self):
        self.fail(times=4); self.clock.now += AuthThrottle.IDLE + 1
        self.assertEqual(self.fail(times=4), [0, 0, 0, 0])

    def test_concurrent_failures_are_counted_exactly(self):
        throttle = AuthThrottle(5, 60)
        with ThreadPoolExecutor(16) as pool: results = list(pool.map(lambda _: throttle.failure('shared'), range(200)))
        self.assertEqual(sum(1 for value in results if value), 200 // 5)
        self.assertLessEqual(len(throttle), 1)


class ClientIdentityTests(unittest.TestCase):
    def settings(self, proxies=''):
        import ipaddress
        networks = tuple(ipaddress.ip_network(item, strict=False) for item in proxies.split(',') if item)
        return ServerSettings('127.0.0.1', 18743, Path('/x'), Path('/x'), ORIGIN, ('127.0.0.1',), 'basic', SECRET, 'saplens', networks, 'info')

    def request(self, peer, *forwarded):
        return SimpleNamespace(client=SimpleNamespace(host=peer), headers=Headers(raw=[(b'x-forwarded-for', value.encode()) for value in forwarded]))

    def test_an_untrusted_peer_cannot_choose_its_identity(self):
        self.assertEqual(self.settings().client_address(self.request('203.0.113.9', '198.51.100.7')), '203.0.113.9')
        self.assertEqual(self.settings('10.0.0.0/8').client_address(self.request('203.0.113.9', '198.51.100.7')), '203.0.113.9')

    def test_a_trusted_proxy_identifies_the_client_from_the_right(self):
        settings = self.settings('10.0.0.0/8')
        self.assertEqual(settings.client_address(self.request('10.0.0.5', '198.51.100.7')), '198.51.100.7')
        self.assertEqual(settings.client_address(self.request('10.0.0.5', '192.0.2.1, 198.51.100.7, 10.0.0.9')), '198.51.100.7', 'values to the left are caller-supplied')
        self.assertEqual(settings.client_address(self.request('10.0.0.5', '192.0.2.1', '198.51.100.7')), '198.51.100.7', 'several header lines count as one list')

    def test_malformed_or_missing_forwarding_falls_back_to_the_peer(self):
        settings = self.settings('10.0.0.0/8')
        for header in ('not-an-address', '198.51.100.7, garbage', '10.0.0.9'): self.assertEqual(settings.client_address(self.request('10.0.0.5', header)), '10.0.0.5', header)
        self.assertEqual(settings.client_address(self.request('10.0.0.5')), '10.0.0.5')
        self.assertEqual(settings.client_address(SimpleNamespace(client=None, headers=Headers())), 'unknown')

    def test_ipv6_clients_share_one_identity_per_64_and_mapped_addresses_are_ipv4(self):
        settings = self.settings()
        self.assertEqual(settings.client_address(self.request('2001:db8:1:2::1')), settings.client_address(self.request('2001:db8:1:2:ffff::9')))
        self.assertNotEqual(settings.client_address(self.request('2001:db8:1:2::1')), settings.client_address(self.request('2001:db8:1:3::1')))
        self.assertEqual(settings.client_address(self.request('::ffff:203.0.113.9')), '203.0.113.9')


class ThrottledServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); root = Path(self.temp.name)
        data = root / 'server data'; sources = root / 'sources'; sources.mkdir()
        secret = root / 'access.secret'; secret.write_text(SECRET); secret.chmod(0o600)
        frontend = root / 'frontend'; frontend.mkdir(); (frontend / 'index.html').write_text('<html>unit</html>')
        self.env = patch.dict(os.environ, {'SAP_LENS_DEPLOYMENT_MODE': 'server', 'SAP_LENS_DATA_DIR': str(data), 'SAP_LENS_CONFIG_DIR': str(data), 'SAP_LENS_SOURCE_DIR': str(sources),
            'SAP_LENS_HOST': '127.0.0.1', 'SAP_LENS_PORT': '18743', 'SAP_LENS_PUBLIC_ORIGIN': ORIGIN, 'SAP_LENS_ALLOWED_HOSTS': '127.0.0.1', 'SAP_LENS_AUTH': 'basic',
            'SAP_LENS_AUTH_SECRET_FILE': str(secret), 'SAP_LENS_TRUSTED_PROXIES': '', 'DATA_CSV_PATH': ''})
        self.env.start(); config.get_settings.cache_clear(); cache.clear_cache(); store.clear()
        self.frontend = patch('main.frontend_dir', frontend); self.frontend.start()
        from auth_store import AuthStore
        identity=AuthStore(data/'security/accounts.sqlite3');identity.initialize()
        identity.create_user(None,'saplens','Synthetic administrator','administrator',SECRET,bootstrap=True)
        self.app=create_app(server=ServerSettings.from_env());self.clock=Clock();self.app.state.identity_store.clock=self.clock

    def tearDown(self):
        self.frontend.stop(); cache.clear_cache(); store.clear(); config.get_settings.cache_clear(); self.env.stop(); self.temp.cleanup()

    def client(self, peer='203.0.113.9'):
        return TestClient(self.app,base_url='https://127.0.0.1:18743',client=(peer,50000))

    def login(self,client,user='saplens',password=SECRET,headers=None):
        return client.post('/api/auth/login',json=dict(username=user,password=password),headers={'X-SAP-Lens':'1',**(headers or {})})

    def test_success_is_unaffected_and_repeated_failures_lock_out(self):
        with self.client() as client:
            self.assertEqual(self.login(client).status_code,200)
            for attempt in range(5):
                refused=self.login(client,password='Wrong synthetic password 123!')
                self.assertEqual(refused.status_code,401,attempt)
                self.assertNotIn('WWW-Authenticate',refused.headers)
            locked=self.login(client)
            self.assertEqual(locked.status_code,429)
            self.assertEqual(locked.json()['code'],'temporarily_throttled')
            self.assertNotIn(SECRET,locked.text)
            self.assertEqual(client.get('/health/live').status_code,200)

    def test_the_lockout_ends_and_other_clients_are_never_affected(self):
        with self.client() as attacker,self.client('198.51.100.20') as other:
            for _ in range(5):self.login(attacker,password='Wrong synthetic password 123!')
            self.assertEqual(self.login(attacker).status_code,429)
            self.assertEqual(self.login(other).status_code,200)
            self.clock.now+=31
            self.assertEqual(self.login(attacker).status_code,200)

    def test_username_variants_do_not_evade_client_limits_and_audit_excludes_passwords(self):
        with self.client() as client:
            for user in ('saplens','unknown-user','saplens','other','x'):
                self.assertEqual(self.login(client,user,password='Wrong synthetic password 123!').status_code,401)
            self.assertEqual(self.login(client).status_code,429)
        with self.app.state.identity_store.connection() as db:
            rows=[dict(row) for row in db.execute('SELECT * FROM audit')]
        self.assertEqual(sum(row['operation']=='session.login_denied' for row in rows),5)
        text=str(rows)
        self.assertNotIn('Wrong synthetic password',text);self.assertNotIn(SECRET,text)

    def test_spoofed_forwarding_headers_do_not_reset_or_dodge_the_throttle(self):
        with self.client() as client:
            for index in range(5):self.login(client,password='Wrong synthetic password 123!',headers={'X-Forwarded-For':f'192.0.2.{index}'})
            self.assertEqual(self.login(client,headers={'X-Forwarded-For':'192.0.2.250'}).status_code,429)
        with self.app.state.identity_store.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM login_limits').fetchone()[0],1)

    def test_malformed_legacy_authorization_cannot_authenticate_or_poison_login_limits(self):
        with self.client() as client:
            for header in ('Bearer abc','Basic !!!','Basic '+base64.b64encode(b'nocolon').decode(),'garbage','Basic '+base64.b64encode(b'a:b').decode()):
                self.assertEqual(client.get('/api/dashboard',headers={'Authorization':header}).status_code,401)
            self.assertEqual(self.login(client).status_code,200)

    def test_limits_are_configurable_within_documented_bounds(self):
        with patch.dict(os.environ, {'SAP_LENS_AUTH_MAX_FAILURES': '3', 'SAP_LENS_AUTH_LOCKOUT_SECONDS': '10'}):
            settings = ServerSettings.from_env()
            self.assertEqual((settings.max_failures, settings.lockout_seconds), (3, 10))
        for name, value in (('SAP_LENS_AUTH_MAX_FAILURES', '2'), ('SAP_LENS_AUTH_MAX_FAILURES', '51'), ('SAP_LENS_AUTH_LOCKOUT_SECONDS', '9'), ('SAP_LENS_AUTH_LOCKOUT_SECONDS', 'soon')):
            with patch.dict(os.environ, {name: value}), self.assertRaises(ValueError): ServerSettings.from_env()
        self.assertEqual((ServerSettings.from_env().max_failures, ServerSettings.from_env().lockout_seconds), (5, 60))


class OtherModesTests(unittest.TestCase):
    def test_local_and_desktop_modes_have_no_throttle(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': root, 'DATA_CSV_PATH': ''}):
            config.get_settings.cache_clear()
            self.assertFalse(hasattr(create_app(origin='http://127.0.0.1:41234',session_token='t').state,'identity_store'))
            local = ServerSettings('127.0.0.1', 18743, Path('/x'), Path('/x'), ORIGIN, ('127.0.0.1',), 'local', '', 'saplens', (), 'info')
            self.assertTrue(hasattr(create_app(server=local).state,'identity_store'))
            config.get_settings.cache_clear()


if __name__ == '__main__':
    unittest.main()
