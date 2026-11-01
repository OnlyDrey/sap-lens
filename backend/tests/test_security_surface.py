"""Security regression evidence (R8): every API operation is protected, the server boundary covers every operation,
exports neutralise spreadsheet formulas through one shared function, and responses carry the browser protections."""
import base64
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cache
import config
from csv_exports import spreadsheet_cell
from deployment import ServerSettings
from employee_directory import store
from fastapi.testclient import TestClient
from main import create_app

PUBLIC = {'/health/live', '/health/ready', '/health'}
ORIGIN = 'http://127.0.0.1:41234'
TOKEN = 'synthetic-launch-capability'


def operations(app):
    """Every method and path the application declares, taken from its OpenAPI schema (routers are nested, so app.routes is not enough)."""
    return [(method.upper(), re.sub(r'\{[^}]+\}', 'x', path)) for path, item in app.openapi()['paths'].items() for method in item if method in {'get', 'post', 'put', 'patch', 'delete'}]


class Isolated(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': str(self.root / 'config'), 'DATA_CSV_PATH': ''})
        self.env.start(); config.get_settings.cache_clear(); cache.clear_cache(); store.clear()

    def tearDown(self):
        cache.clear_cache(); store.clear(); config.get_settings.cache_clear(); self.env.stop(); self.temp.cleanup()


class DesktopBoundaryTests(Isolated):
    def test_every_api_operation_needs_the_launch_capability_an_allowed_origin_and_the_exact_host(self):
        app = create_app(origin=ORIGIN, session_token=TOKEN)
        found = operations(app)
        self.assertGreater(len(found), 100)  # the probe really sees the whole API
        with TestClient(app, base_url=ORIGIN) as client:
            for method, path in found:
                body = {} if method != 'GET' else None
                call = lambda headers: client.request(method, path, headers=headers, **({'json': body} if body is not None else {}))
                if path.startswith('/api/'):
                    self.assertEqual(call({'Origin': ORIGIN}).status_code, 403, f'{method} {path} answered without the launch capability')
                    self.assertEqual(call({'Origin': 'https://evil.example', 'X-SAP-Lens': TOKEN}).status_code, 403, f'{method} {path} accepted a foreign origin')
                    self.assertEqual(call({'Origin': ORIGIN, 'X-SAP-Lens': 'wrong'}).status_code, 403, f'{method} {path} accepted a wrong capability')
                self.assertIn(call({'Host': 'rebind.example:41234', 'X-SAP-Lens': TOKEN}).status_code, {400, 403}, f'{method} {path} accepted a foreign Host header')

    def test_only_liveness_readiness_and_health_are_outside_the_api_prefix(self):
        self.assertEqual({path for _, path in operations(create_app(origin=ORIGIN, session_token=TOKEN)) if not path.startswith('/api/')}, PUBLIC)

    def test_responses_carry_the_browser_protections_and_no_unsafe_script_policy(self):
        with TestClient(create_app(origin=ORIGIN, session_token=TOKEN), base_url=ORIGIN) as client:
            response = client.get('/api/version', headers={'X-SAP-Lens': TOKEN, 'Origin': ORIGIN})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
        self.assertEqual(response.headers['x-frame-options'], 'DENY')
        self.assertEqual(response.headers['cache-control'], 'no-store')
        policy = response.headers['content-security-policy']
        self.assertIn("frame-ancestors 'none'", policy)
        self.assertIn("object-src 'none'", policy)
        self.assertIn('camera=()', response.headers['permissions-policy'])  # the application uses no device capability
        script = next(part for part in policy.split(';') if part.strip().startswith('script-src'))
        self.assertNotIn('unsafe', script)  # no unsafe-inline or unsafe-eval for scripts

    def test_unexpected_failures_do_not_leak_details(self):
        with patch('routers.dashboard.cache.get_snapshot', side_effect=RuntimeError('secret path /home/user/private.csv')):
            with TestClient(create_app(origin=ORIGIN, session_token=TOKEN), base_url=ORIGIN, raise_server_exceptions=False) as client:
                response = client.get('/api/dashboard', headers={'X-SAP-Lens': TOKEN, 'Origin': ORIGIN})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('private.csv', response.text)
        self.assertNotIn('RuntimeError', response.text)


class ServerBoundaryTests(Isolated):
    def setUp(self):
        super().setUp()
        self.data = self.root / 'server data'; self.sources = self.root / 'sources'; self.sources.mkdir()
        self.secret = self.root / 'access.secret'; self.secret.write_text('synthetic-access-secret-' + 'a' * 40); self.secret.chmod(0o600)
        self.server_env = patch.dict(os.environ, {'SAP_LENS_DEPLOYMENT_MODE': 'server', 'SAP_LENS_DATA_DIR': str(self.data), 'SAP_LENS_CONFIG_DIR': str(self.data),
            'SAP_LENS_SOURCE_DIR': str(self.sources), 'SAP_LENS_HOST': '127.0.0.1', 'SAP_LENS_PORT': '18743', 'SAP_LENS_PUBLIC_ORIGIN': 'http://127.0.0.1:18743',
            'SAP_LENS_ALLOWED_HOSTS': '127.0.0.1', 'SAP_LENS_AUTH': 'basic', 'SAP_LENS_AUTH_SECRET_FILE': str(self.secret), 'SAP_LENS_TRUSTED_PROXIES': ''})
        self.server_env.start(); config.get_settings.cache_clear()
        frontend = self.root / 'frontend'; frontend.mkdir(); (frontend / 'index.html').write_text('<html>unit</html>')
        self.frontend_patch = patch('main.frontend_dir', frontend); self.frontend_patch.start()

    def tearDown(self):
        self.frontend_patch.stop(); self.server_env.stop(); super().tearDown()

    def test_basic_authentication_covers_every_operation_and_unsafe_methods_are_refused(self):
        app = create_app(server=ServerSettings.from_env())
        credentials = base64.b64encode(('saplens:' + self.secret.read_text()).encode()).decode()
        wrong = base64.b64encode(b'saplens:wrong-secret-wrong-secret-wrong-secret').decode()
        with TestClient(app, base_url='http://127.0.0.1:18743', client=('127.0.0.1', 50000)) as client:
            for method, path in operations(app):
                if path in PUBLIC: continue
                body = {'json': {}} if method != 'GET' else {}
                self.assertEqual(client.request(method, path, **body).status_code, 401, f'{method} {path} answered without credentials')
                app.state.auth_throttle.success('127.0.0.1')  # every probe is judged on its credentials, not on the lock-out of the probes before it
                self.assertEqual(client.request(method, path, headers={'Authorization': 'Basic ' + wrong}, **body).status_code, 401, f'{method} {path} accepted wrong credentials')
            for method in ('PUT', 'DELETE', 'PATCH'):
                refused = client.request(method, '/api/configuration', headers={'Authorization': 'Basic ' + credentials, 'X-SAP-Lens': '1'}, json={})
                self.assertEqual(refused.status_code, 405)  # the server API only reads and posts

    def test_a_secret_file_readable_by_other_users_is_rejected(self):
        self.secret.chmod(0o604)
        with self.assertRaises(ValueError):
            ServerSettings.from_env()
        self.secret.chmod(0o600)
        self.assertEqual(ServerSettings.from_env().auth, 'basic')

    def test_server_errors_are_generic(self):
        app = create_app(server=ServerSettings.from_env())
        credentials = base64.b64encode(('saplens:' + self.secret.read_text()).encode()).decode()
        with patch('routers.dashboard.cache.get_snapshot', side_effect=RuntimeError('secret path /srv/private.csv')):
            with TestClient(app, base_url='http://127.0.0.1:18743', client=('127.0.0.1', 50000), raise_server_exceptions=False) as client:
                response = client.get('/api/dashboard', headers={'Authorization': 'Basic ' + credentials})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('private.csv', response.text)


class SpreadsheetExportTests(Isolated):
    def test_the_shared_neutraliser_covers_leading_controls_bom_and_whitespace(self):
        for value in ['=1+1', '+SUM(1)', '-2', '@cmd', '\t=1', '\r=1', '\n=1', ' =1', '﻿=1', '\x01=1', '\x00@x']:
            self.assertTrue(spreadsheet_cell(value).startswith("'"), repr(value))
        for value in ['plain', 'ZC:ROLE', '12', '']:
            self.assertEqual(spreadsheet_cell(value), value)
        self.assertEqual(spreadsheet_cell(None), '')

    def test_the_refresh_changes_export_uses_it(self):
        report = {'timestamp': '2026-10-31T00:00:00Z', 'status': 'updated', 'sources': [dict(source='users', name='User Access', status='updated', changes=[
            dict(type='modified', identifier='=HYPERLINK("http://evil")', fields=[dict(field='NAME', before='﻿=1+1', after='\x01@SUM(1)')], before={}, after={})])]}
        with patch('routers.data_sources.report', return_value=report):
            with TestClient(create_app(origin=ORIGIN, session_token=TOKEN), base_url=ORIGIN) as client:
                text = client.get('/api/data-sources/reports/synthetic/export', headers={'X-SAP-Lens': TOKEN, 'Origin': ORIGIN}).text.replace('﻿', '', 1)
        cells = [cell for line in text.strip().splitlines()[1:] for cell in line.split('","')]
        for cell in cells:
            self.assertFalse(re.match(r'^"?[\s\x00-\x1f﻿]*[=+@-]', cell.lstrip('"')), cell)  # every dangerous value starts with the neutralising quote


if __name__ == '__main__':
    unittest.main()
