"""Desktop browser handoff preserves the per-launch capability and loopback boundary."""
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import main

class DesktopBrowserTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        directory=Path(self.temp.name);(directory/'index.html').write_text('<html><head></head><body>synthetic</body></html>')
        self.resources=patch.object(main,'frontend_dir',directory);self.resources.start();self.addCleanup(self.resources.stop)
        self.app=main.create_app(origin='http://127.0.0.1:18743',session_token='synthetic-launch-capability',instance_id='synthetic',browser_access=True)
    def client(self,host='127.0.0.1',peer='127.0.0.1',port=18743):
        return TestClient(self.app,base_url=f'http://{host}:{port}',client=(peer,1234))
    def test_both_origins_handoff_same_capability_without_unguarding_api(self):
        for host in ('127.0.0.1','localhost'):
            client=self.client(host)
            document=client.get('/',headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document','Sec-Fetch-Site':'none'})
            self.assertEqual(document.status_code,200)
            self.assertIn('synthetic-launch-capability',document.text)
            nonce=re.search('nonce="([^"]+)"',document.text)[1]
            self.assertIn("'nonce-"+nonce+"'",document.headers['content-security-policy'])
            self.assertEqual(document.headers['cache-control'],'no-store')
            self.assertEqual(client.get('/api/application-info').status_code,403)
            headers={'X-SAP-Lens':'synthetic-launch-capability','Origin':f'http://{host}:18743'}
            self.assertEqual(client.get('/api/application-info',headers=headers).status_code,200)
            self.assertEqual(client.get('/health').json()['instance_id'],'synthetic')
    def test_cross_site_frames_fetches_and_unauthorized_origins_never_receive_secret(self):
        client=self.client()
        for headers in ({},{'Sec-Fetch-Mode':'cors','Sec-Fetch-Dest':'script','Sec-Fetch-Site':'cross-site'}, {'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'iframe','Sec-Fetch-Site':'same-origin'}, {'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document','Sec-Fetch-Site':'cross-site'}):
            response=client.get('/',headers=headers)
            self.assertNotIn('synthetic-launch-capability',response.text)
        self.assertEqual(client.get('/api/application-info',headers={'X-SAP-Lens':'synthetic-launch-capability','Origin':'https://attacker.example.test'}).status_code,403)
    def test_wrong_peer_port_host_and_mode_are_rejected(self):
        self.assertEqual(self.client(peer='192.0.2.1').get('/health').status_code,403)
        self.assertEqual(self.client(port=18744).get('/health').status_code,403)
        self.assertEqual(self.client(host='attacker.example.test').get('/health').status_code,403)
        with self.assertRaises(ValueError):main.create_app(browser_access=True)
    def test_handoff_nonce_is_fresh_and_bootstrap_is_opt_in(self):
        headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document','Sec-Fetch-Site':'none'}
        first=self.client().get('/',headers=headers);second=self.client().get('/',headers=headers)
        self.assertNotEqual(first.text,second.text)
        app=main.create_app(origin='http://127.0.0.1:18743',session_token='synthetic-launch-capability')
        self.assertNotIn('synthetic-launch-capability',TestClient(app).get('/',headers=headers).text)
