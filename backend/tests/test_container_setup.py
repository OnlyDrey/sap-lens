"""Host-only container files: a generated certificate, supplied certificates, keys and tokens are created once and never replaced."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import ssl
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import container_setup as setup
import healthcheck


@unittest.skipIf(os.name == 'nt', 'Container host files use POSIX modes')
class ContainerSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_generated_certificate_covers_the_names_is_a_private_server_pair_and_loads(self):
        details = setup.generate_tls(self.root, ['lens.example.test', '192.0.2.10'])
        self.assertTrue(details['self_signed']); self.assertFalse(details['expired'])
        self.assertEqual(details['names'], ['lens.example.test', '192.0.2.10', 'localhost', '127.0.0.1', '::1'])
        self.assertEqual((self.root / 'tls.key').stat().st_mode & 0o777, 0o640)   # owner and the container group, nobody else
        self.assertEqual((self.root / 'tls.crt').stat().st_mode & 0o777, 0o644)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.load_cert_chain(self.root / 'tls.crt', self.root / 'tls.key')
        from cryptography import x509
        certificate = x509.load_pem_x509_certificate((self.root / 'tls.crt').read_bytes())
        self.assertFalse(certificate.extensions.get_extension_for_class(x509.BasicConstraints).value.ca)   # cannot sign other certificates
        self.assertLessEqual(certificate.not_valid_after_utc - certificate.not_valid_before_utc, timedelta(days=setup.VALID_DAYS))
        self.assertNotIn(b'ENCRYPTED', (self.root / 'tls.key').read_bytes())

    def test_existing_certificate_key_and_secrets_are_never_replaced(self):
        setup.generate_tls(self.root, ['localhost']); setup.backup_key(self.root); setup.proxy_token(self.root)
        before = {path.name: path.read_bytes() for path in self.root.iterdir()}
        for call in (lambda: setup.generate_tls(self.root, ['localhost']), lambda: setup.backup_key(self.root), lambda: setup.proxy_token(self.root),
                     lambda: setup.install_tls(self.root, self.root / 'tls.crt', self.root / 'tls.key', ['localhost'])):
            with self.assertRaises(setup.SetupError): call()
        self.assertEqual({path.name: path.read_bytes() for path in self.root.iterdir()}, before)
        (self.root / 'tls.crt').unlink()                                           # half a pair is not completed with a new key
        with self.assertRaises(setup.SetupError): setup.generate_tls(self.root, ['localhost'])
        self.assertEqual((self.root / 'tls.key').read_bytes(), before['tls.key'])
        self.assertEqual(setup.main(['backup-key', '--directory', str(self.root)]), 1)

    def test_a_link_in_place_of_a_key_is_refused_and_its_target_untouched(self):
        target = self.root / 'elsewhere'; target.write_text('retain')
        (self.root / 'config').mkdir(); (self.root / 'config/backup.key').symlink_to(target)
        with self.assertRaises(setup.SetupError): setup.backup_key(self.root / 'config')
        self.assertEqual(target.read_text(), 'retain')

    def test_wildcards_unspecified_addresses_and_malformed_names_are_not_issued(self):
        for host in ('*.example.test', '0.0.0.0', 'bad name', 'a' * 300, '-lead.example.test'):
            with self.assertRaises(setup.SetupError, msg=host): setup.generate_tls(self.root, [host])
            self.assertEqual(list(self.root.iterdir()), [], host)

    def test_supplied_certificate_must_match_its_key_be_valid_and_cover_the_host(self):
        source, other = self.root / 'source', self.root / 'other'; source.mkdir(); other.mkdir()
        setup.generate_tls(source, ['lens.example.test']); setup.generate_tls(other, ['lens.example.test'])
        target = self.root / 'installed'; target.mkdir()
        with self.assertRaises(setup.SetupError): setup.install_tls(target, source / 'tls.crt', other / 'tls.key', ['lens.example.test'])     # mismatched pair
        with self.assertRaises(setup.SetupError): setup.install_tls(target, source / 'tls.crt', source / 'tls.key', ['other.example.test'])   # name not covered
        expired = self.root / 'expired'; expired.mkdir()
        setup.generate_tls(expired, ['lens.example.test'], now=datetime.now(timezone.utc) - timedelta(days=setup.VALID_DAYS + 5))
        with self.assertRaises(setup.SetupError): setup.install_tls(target, expired / 'tls.crt', expired / 'tls.key', ['lens.example.test'])
        self.assertEqual(list(target.iterdir()), [])
        details = setup.install_tls(target, source / 'tls.crt', source / 'tls.key', ['lens.example.test'])
        self.assertEqual((target / 'tls.key').read_bytes(), (source / 'tls.key').read_bytes())
        self.assertEqual((target / 'tls.key').stat().st_mode & 0o777, 0o640); self.assertIn('lens.example.test', details['names'])

    def test_backup_key_is_what_the_application_reads_and_nothing_secret_is_printed(self):
        import contextlib, io
        import backup_crypto as crypto
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(setup.main(['backup-key', '--directory', str(self.root)]), 0)
            self.assertEqual(setup.main(['proxy-token', '--directory', str(self.root)]), 0)
            self.assertEqual(setup.main(['generate-tls', '--directory', str(self.root), '--host', 'localhost']), 0)
        with patch.dict(os.environ, {'SAP_LENS_BACKUP_KEY_GROUP_READ': '1'}):
            self.assertEqual(len(crypto.read_key(self.root / 'backup.key', self.root / 'data')), 32)
        with patch.dict(os.environ, {'SAP_LENS_BACKUP_KEY_GROUP_READ': ''}), self.assertRaises(crypto.BackupCryptoError):
            crypto.read_key(self.root / 'backup.key', self.root / 'data')         # group read stays an explicit opt-in
        self.assertGreaterEqual(len((self.root / 'proxy-token.secret').read_text().strip()), 32)
        printed = output.getvalue()
        for name in ('backup.key', 'proxy-token.secret'): self.assertNotIn((self.root / name).read_text().strip(), printed)
        self.assertNotIn('PRIVATE KEY', printed)


class HealthProbeTests(unittest.TestCase):
    def test_the_probe_verifies_the_configured_certificate_and_never_disables_verification(self):
        source = Path(healthcheck.__file__).read_text(encoding='utf-8')
        for forbidden in ('CERT_NONE', 'check_hostname = False', 'check_hostname=False', '_create_unverified_context'): self.assertNotIn(forbidden, source)
        self.assertIn('ssl.PROTOCOL_TLS_CLIENT', source); self.assertIn('load_verify_locations(certificate)', source)

    @unittest.skipIf(os.name == 'nt', 'Loopback TLS listener test uses POSIX host files')
    def test_the_probe_accepts_the_configured_certificate_and_rejects_another_one(self):
        import http.server, threading
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); served, other = root / 'served', root / 'other'; served.mkdir(); other.mkdir()
            setup.generate_tls(served, ['lens.example.test']); setup.generate_tls(other, ['lens.example.test'])
            class Ready(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200 if self.path == '/health/ready' else 404); self.end_headers()
                def log_message(self, *args): pass
            server = http.server.HTTPServer(('127.0.0.1', 0), Ready)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.load_cert_chain(served / 'tls.crt', served / 'tls.key')
            server.socket = context.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            import socket
            original = socket.getaddrinfo
            try:
                port = str(server.server_address[1])
                environment = {'SAP_LENS_PUBLIC_ORIGIN': f'https://lens.example.test:{port}', 'SAP_LENS_PORT': port}
                self.assertTrue(healthcheck.probe({**environment, 'SAP_LENS_TLS_CERT_FILE': str(served / 'tls.crt')}))
                socket.getaddrinfo = original
                with self.assertRaises(OSError): healthcheck.probe({**environment, 'SAP_LENS_TLS_CERT_FILE': str(other / 'tls.crt')})   # a different certificate
                socket.getaddrinfo = original
                with self.assertRaises(OSError): healthcheck.probe({**environment, 'SAP_LENS_PUBLIC_ORIGIN': f'https://wrong.example.test:{port}', 'SAP_LENS_TLS_CERT_FILE': str(served / 'tls.crt')})   # a name it does not cover
            finally:
                socket.getaddrinfo = original; server.shutdown(); server.server_close()


if __name__ == '__main__':
    unittest.main()
