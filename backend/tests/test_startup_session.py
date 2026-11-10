"""The automatic start-up restore relies on the guarded desktop document. These tests pin down who may obtain a fresh capability, what an old or missing one gets, and that
configuration failures are never mistaken for a lost session."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import test_server  # noqa: E402

NAVIGATION = {'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'document', 'Sec-Fetch-Site': 'same-origin'}
ORIGIN = 'http://127.0.0.1:18743'


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = Path(self.temp.name)
        (directory / 'index.html').write_text('<html><head></head><body>synthetic</body></html>')
        patcher = patch.object(main, 'frontend_dir', directory)
        patcher.start()
        self.addCleanup(patcher.stop)

    def desktop(self, token, **extra):
        app = main.create_app(origin=ORIGIN, session_token=token, instance_id='synthetic', browser_access=True)
        return TestClient(app, base_url=ORIGIN, client=('127.0.0.1', 1234), **extra)


class RestoreBoundary(Base):
    def test_a_missing_or_old_capability_is_reported_as_a_lost_session_and_leaks_nothing(self):
        client = self.desktop('capability-of-this-run')
        for headers in ({}, {'X-SAP-Lens': '1'}, {'X-SAP-Lens': 'capability-of-an-earlier-run'}):
            response = client.get('/api/configuration', headers=headers)
            self.assertEqual((response.status_code, response.json()['code']), (403, 'stale_session'))
            self.assertNotIn('capability-of-this-run', response.text + str(dict(response.headers)))

    def test_the_capability_is_stable_within_a_run_so_a_restore_cannot_invalidate_other_windows(self):
        client = self.desktop('capability-of-this-run')
        first = client.get('/', headers=NAVIGATION).text
        second = client.get('/', headers=NAVIGATION).text
        self.assertIn('capability-of-this-run', first)
        self.assertIn('capability-of-this-run', second)
        self.assertEqual(client.get('/api/configuration', headers={'X-SAP-Lens': 'capability-of-this-run'}).status_code, 200)

    def test_a_restarted_process_issues_a_new_capability_and_only_a_verified_navigation_receives_it(self):
        restarted = self.desktop('capability-after-restart')
        self.assertEqual(restarted.get('/api/configuration', headers={'X-SAP-Lens': 'capability-before-restart'}).json()['code'], 'stale_session')
        self.assertIn('capability-after-restart', restarted.get('/', headers=NAVIGATION).text)
        for headers in (
            {},                                                                                                    # a script or tool
            {**NAVIGATION, 'Sec-Fetch-Site': 'cross-site'},                                                        # a page on another site
            {**NAVIGATION, 'Sec-Fetch-Dest': 'iframe'},                                                            # framed
            {**NAVIGATION, 'Sec-Fetch-Mode': 'cors'},                                                              # fetch/XHR
            {**NAVIGATION, 'Origin': 'https://attacker.example.test'},                                             # foreign origin
        ):
            with self.subTest(headers=headers):
                self.assertNotIn('capability-after-restart', restarted.get('/', headers=headers).text)

    def test_unauthorized_peers_hosts_and_ports_receive_neither_the_document_nor_the_capability(self):
        app = main.create_app(origin=ORIGIN, session_token='capability-of-this-run', instance_id='synthetic', browser_access=True)
        for base, peer in ((ORIGIN, '192.0.2.10'), ('http://127.0.0.1:18744', '127.0.0.1'), ('http://attacker.example.test:18743', '127.0.0.1')):
            with self.subTest(base=base, peer=peer):
                response = TestClient(app, base_url=base, client=(peer, 1234)).get('/', headers=NAVIGATION)
                self.assertEqual(response.status_code, 403)
                self.assertNotIn('capability-of-this-run', response.text)

    def test_a_restore_never_changes_stored_data(self):
        client = self.desktop('capability-of-this-run')
        with patch('config.atomic_write') as write:
            client.get('/api/configuration', headers={'X-SAP-Lens': 'capability-of-an-earlier-run'})
            client.get('/', headers=NAVIGATION)
        write.assert_not_called()


class ConfigurationFailures(Base):
    def test_a_configuration_or_storage_failure_is_a_server_error_never_a_lost_session(self):
        client = self.desktop('capability-of-this-run', raise_server_exceptions=False)
        with patch('configuration_routes.get_settings', side_effect=RuntimeError('database disk image is malformed')):
            response = client.get('/api/configuration', headers={'X-SAP-Lens': 'capability-of-this-run'})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('stale_session', response.text)
        self.assertNotIn('capability-of-this-run', response.text)
        self.assertRegex(response.headers['X-Request-ID'], r'^[a-f0-9]{32}$')

    def test_the_service_answers_health_while_the_configuration_is_unavailable(self):
        client = self.desktop('capability-of-this-run', raise_server_exceptions=False)
        self.assertEqual(client.get('/health').status_code, 200)


class ServerHosting(test_server.ServerTestBase):
    def test_server_mode_has_no_desktop_bootstrap_and_no_stale_session_answer(self):
        with patch.dict(test_server.os.environ, {'SAP_LENS_AUTH': 'basic'}):
            client = self.client()
        response = client.get('/api/configuration', headers={'X-SAP-Lens': 'anything'})
        self.assertEqual(response.status_code, 401)
        self.assertNotIn('stale_session', response.text)
        document = client.get('/', headers=NAVIGATION)
        self.assertEqual(document.status_code, 401)
        authorized = client.get('/', headers={**NAVIGATION, **self.basic()})
        self.assertEqual(authorized.status_code, 200)
        self.assertNotIn('sap-lens-session', authorized.text)                      # no capability is ever injected for server-hosted access

    def test_a_remote_client_without_credentials_cannot_use_a_loopback_style_header_to_get_in(self):
        response = self.client(peer='192.0.2.20').get('/api/configuration', headers={'X-SAP-Lens': '1', **NAVIGATION})
        self.assertEqual(response.status_code, 401)


if __name__ == '__main__':
    unittest.main()
