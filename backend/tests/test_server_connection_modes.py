"""Server connection modes (HTTP, HTTPS self-signed, HTTPS existing certificate) and step-named configuration diagnostics."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import deployment
from deployment import ConfigError, ServerSettings

from tls_fixture import issue


class ConnectionModes(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'data').mkdir()
        from server_access import manage_user
        self.accounts = self.root / 'users.json'
        manage_user(self.accounts, dict(username='admin', password='correct-horse-battery-1', role='administrator', enabled=True))
        self.accounts.chmod(0o600)

    def certificate(self, name, san, days=30, bits=2048, **options):
        return issue(self.root, name, san, days=days, bits=bits, **options)

    # --- key strength and validity (regression: the Service Manager once produced a 1024-bit key, EE_KEY_TOO_SMALL) ----
    def test_modern_rsa_and_ec_keys_are_accepted(self):
        for label, options in (('rsa2048', dict(bits=2048)), ('rsa3072', dict(bits=3072)), ('rsa4096', dict(bits=4096)), ('p256', dict(curve='p256')), ('p384', dict(curve='p384'))):
            with self.subTest(key=label):
                cert, key = self.certificate(label, 'DNS:localhost,IP:127.0.0.1', **options)
                self.assertEqual(self.settings(SAP_LENS_TLS_CERT_FILE=cert, SAP_LENS_TLS_KEY_FILE=key).tls_cert, cert)

    def test_a_weak_rsa_key_is_refused_with_an_actionable_message_that_names_no_key_material(self):
        cert, key = self.certificate('weak', 'DNS:localhost,IP:127.0.0.1', bits=1024)
        error = self.fails(SAP_LENS_TLS_CERT_FILE=cert, SAP_LENS_TLS_KEY_FILE=key)
        self.assertEqual(error.step, 'TLS certificate key strength')
        for text in ('RSA 1024 bits', 'at least 2048 bits', 'were not changed'): self.assertIn(text, error.detail)
        self.assertNotIn('PRIVATE KEY', error.detail); self.assertNotIn('ee key too small', error.detail.lower())
        self.assertTrue(Path(cert).is_file() and Path(key).is_file())  # refused, never deleted or replaced

    def test_expired_and_not_yet_valid_certificates_are_refused(self):
        from datetime import timedelta
        for label, start in (('expired', timedelta(days=-3)), ('future', timedelta(days=2))):
            with self.subTest(case=label):
                cert, key = self.certificate(label, 'DNS:localhost,IP:127.0.0.1', days=1, start=start)
                self.assertEqual(self.fails(SAP_LENS_TLS_CERT_FILE=cert, SAP_LENS_TLS_KEY_FILE=key).step, 'TLS certificate validity period')

    def test_a_certificate_without_san_or_with_another_host_or_address_is_refused(self):
        for label, san in (('nosan', ''), ('otherhost', 'DNS:other.example.invalid,IP:127.0.0.1'), ('otherip', 'DNS:localhost,IP:192.0.2.7')):
            with self.subTest(case=label):
                cert, key = self.certificate(label, san)
                self.assertEqual(self.fails(SAP_LENS_TLS_CERT_FILE=cert, SAP_LENS_TLS_KEY_FILE=key).step, 'TLS certificate names (SAN)')

    def test_ipv6_loopback_in_the_san_is_matched(self):
        cert, key = self.certificate('v6', 'DNS:localhost,IP:127.0.0.1,IP:::1')
        self.assertIn('::1', self.settings(SAP_LENS_TLS_CERT_FILE=cert, SAP_LENS_TLS_KEY_FILE=key, SAP_LENS_ALLOWED_HOSTS='localhost,127.0.0.1,::1').hosts)

    def environment(self, **extra):
        base = {'SAP_LENS_HOST': '0.0.0.0', 'SAP_LENS_PORT': '18743', 'SAP_LENS_DATA_DIR': str(self.root / 'data'), 'SAP_LENS_AUTH': 'users', 'SAP_LENS_USERS_FILE': str(self.accounts),
                'SAP_LENS_PUBLIC_ORIGIN': 'https://localhost:18743', 'SAP_LENS_ALLOWED_HOSTS': 'localhost,127.0.0.1'}
        base.update(extra)
        return patch.dict(os.environ, base, clear=False)

    def settings(self, **extra):
        with self.environment(**extra):
            return ServerSettings.from_env()

    def fails(self, **extra):
        with self.assertRaises(ConfigError) as caught:
            self.settings(**extra)
        return caught.exception

    # --- HTTPS self-signed / existing certificate -------------------------------------------------------------------
    def test_https_with_a_certificate_covering_dns_and_ipv4_names_is_accepted_for_a_wildcard_listener(self):
        cert, key = self.certificate('ok', 'DNS:localhost,IP:127.0.0.1')
        value = self.settings(SAP_LENS_TLS_CERT_FILE=cert, SAP_LENS_TLS_KEY_FILE=key)
        self.assertEqual((value.host, value.origin, value.tls_cert != ''), ('0.0.0.0', 'https://localhost:18743', True))
        self.assertEqual(value.hosts, ('localhost', '127.0.0.1'))            # 0.0.0.0 is a listen address and never an access name

    def test_a_missing_ip_san_names_the_step_the_missing_name_and_what_the_certificate_has(self):
        cert, key = self.certificate('dns-only', 'DNS:localhost')
        error = self.fails(SAP_LENS_TLS_CERT_FILE=cert, SAP_LENS_TLS_KEY_FILE=key)
        self.assertEqual(error.step, 'TLS certificate names (SAN)')
        self.assertIn('127.0.0.1', error.detail)
        self.assertIn('DNS=localhost', error.detail)

    def test_a_key_that_does_not_match_the_certificate_fails_at_the_load_step(self):
        cert, _ = self.certificate('a', 'DNS:localhost,IP:127.0.0.1')
        _, other_key = self.certificate('b', 'DNS:localhost,IP:127.0.0.1')
        error = self.fails(SAP_LENS_TLS_CERT_FILE=cert, SAP_LENS_TLS_KEY_FILE=other_key)
        self.assertEqual(error.step, 'TLS certificate and private key (load and match)')
        self.assertIn('SSLError', error.detail)

    def test_an_expired_or_not_yet_valid_certificate_fails_at_the_validity_step(self):
        cert, key = self.certificate('short', 'DNS:localhost,IP:127.0.0.1', days=1)
        with patch('time.time', return_value=time.time() + 5 * 86400):
            error = self.fails(SAP_LENS_TLS_CERT_FILE=cert, SAP_LENS_TLS_KEY_FILE=key)
        self.assertEqual(error.step, 'TLS certificate validity period')

    def test_unreadable_or_missing_certificate_files_are_named(self):
        error = self.fails(SAP_LENS_TLS_CERT_FILE=str(self.root / 'nope.crt'), SAP_LENS_TLS_KEY_FILE=str(self.root / 'nope.key'))
        self.assertEqual(error.step, 'TLS certificate and key files')
        self.assertIn('certificate and private key', error.detail)
        self.assertEqual(self.fails(SAP_LENS_TLS_CERT_FILE=str(self.root / 'x.crt')).step, 'TLS certificate and key files')

    def test_an_invalid_host_name_is_named(self):
        cert, key = self.certificate('ok2', 'DNS:localhost,IP:127.0.0.1')
        error = self.fails(SAP_LENS_ALLOWED_HOSTS='localhost,bad_host!', SAP_LENS_TLS_CERT_FILE=cert, SAP_LENS_TLS_KEY_FILE=key)
        self.assertEqual(error.step, 'allowed hosts')

    # --- HTTP ---------------------------------------------------------------------------------------------------------
    def test_http_on_loopback_needs_no_certificate(self):
        value = self.settings(SAP_LENS_HOST='127.0.0.1', SAP_LENS_PUBLIC_ORIGIN='http://localhost:18743')
        self.assertEqual((value.origin, value.tls_cert, value.tls_key), ('http://localhost:18743', '', ''))

    def test_http_on_a_network_name_is_refused_without_the_explicit_acknowledgement(self):
        error = self.fails(SAP_LENS_PUBLIC_ORIGIN='http://server01:18743', SAP_LENS_ALLOWED_HOSTS='server01')
        self.assertEqual(error.step, 'authentication boundary')
        self.assertIn('HTTPS',error.detail)

    def test_old_http_acknowledgement_cannot_downgrade_session_password_authentication(self):
        for auth in ('sessions','users','local','basic'):
            with self.subTest(auth=auth),self.assertRaises(ConfigError):
                self.settings(SAP_LENS_PUBLIC_ORIGIN='http://server01:18743',SAP_LENS_ALLOWED_HOSTS='server01',SAP_LENS_ALLOW_HTTP='1',SAP_LENS_AUTH=auth)

    def test_loopback_hostname_does_not_authorize_a_non_loopback_http_listener(self):
        error=self.fails(SAP_LENS_HOST='0.0.0.0',SAP_LENS_PUBLIC_ORIGIN='http://localhost:18743',SAP_LENS_ALLOW_HTTP='1')
        self.assertEqual(error.step,'authentication boundary')
        self.assertIn('HTTPS',error.detail)

    def test_a_certificate_is_never_combined_with_an_http_origin_and_https_is_never_downgraded_silently(self):
        cert, key = self.certificate('c', 'DNS:localhost,IP:127.0.0.1')
        error = self.fails(SAP_LENS_HOST='127.0.0.1',SAP_LENS_PUBLIC_ORIGIN='http://localhost:18743', SAP_LENS_TLS_CERT_FILE=cert, SAP_LENS_TLS_KEY_FILE=key, SAP_LENS_ALLOW_HTTP='1')
        self.assertEqual(error.step, 'TLS certificate and key files')
        self.assertIn('not https://', error.detail)

    # --- check command ------------------------------------------------------------------------------------------------
    def test_the_check_command_prints_the_failing_step_and_never_a_generic_message(self):
        cert, key = self.certificate('d', 'DNS:localhost')
        environment = {**os.environ, 'SAP_LENS_HOST': '0.0.0.0', 'SAP_LENS_DATA_DIR': str(self.root / 'data'), 'SAP_LENS_AUTH': 'users', 'SAP_LENS_USERS_FILE': str(self.accounts),
                       'SAP_LENS_PUBLIC_ORIGIN': 'https://localhost:18743', 'SAP_LENS_ALLOWED_HOSTS': 'localhost,127.0.0.1', 'SAP_LENS_TLS_CERT_FILE': cert, 'SAP_LENS_TLS_KEY_FILE': key}
        done = subprocess.run([sys.executable, str(Path(deployment.__file__).with_name('server.py')), '--check-server-config'], env=environment, capture_output=True, text=True)
        self.assertEqual(done.returncode, 1)
        self.assertIn('Invalid server configuration at step "TLS certificate names (SAN)"', done.stderr)
        self.assertIn('127.0.0.1', done.stderr)
        self.assertNotIn('correct-horse', done.stderr + done.stdout)


class ServiceManagerContract(unittest.TestCase):
    """Static contract of deploy/windows/ServiceManager.cs (it cannot be compiled or run here; native Windows acceptance is separate)."""
    SOURCE = (Path(__file__).resolve().parents[2] / 'deploy/windows/ServiceManager.cs').read_text(encoding='utf-8')

    def test_account_actions_use_configured_store_and_do_not_silently_reset(self):
        self.assertIn('string path = AccountFile(Settings());',self.SOURCE)
        self.assertIn('Quote(path), Json.Serialize(payload)',self.SOURCE)
        self.assertIn('if (registered) Acl(path, false, false)',self.SOURCE)
        self.assertIn('current["SAP_LENS_AUTH"] == "users" ? AccountFile(current) : Users',self.SOURCE)
        self.assertIn('if (auth == "users") settings["SAP_LENS_USERS_FILE"] = accountFile;',self.SOURCE)
        # Normal account/password/role administration moved into the application;
        # legacy helpers remain for controlled compatibility, not visible actions.
        self.assertNotIn('Button(actions,"Save account"',self.SOURCE)
        self.assertNotIn('Add(table,"Password"',self.SOURCE)
        self.assertNotIn('Add(table,"Account role"',self.SOURCE)
        self.assertIn('Button(actions,"First-run activation code"',self.SOURCE)
        self.assertIn('Button(actions,"Recover administrator"',self.SOURCE)
        self.assertRegex(self.SOURCE,r'"--initialize-identity\s*"\s*\+\s*Quote\(data\)')
        self.assertIn('if (!https && HttpNeedsAcknowledgement(listener, hosts))',self.SOURCE)
        self.assertNotIn('"--manage-user " + Quote(Users)',self.SOURCE)

    def test_three_explicit_modes_with_https_self_signed_as_the_default(self):
        for text in ('HTTPS - network access, generate a self-signed certificate (default)', 'HTTPS - use an existing certificate', 'HTTP - no certificate (unencrypted)'):
            self.assertIn(text, self.SOURCE)
        self.assertIn('mode.SelectedIndex=0', self.SOURCE)
        self.assertIn('const string ModeHttp = "http", ModeSelfSigned = "selfsigned", ModeCustom = "custom"', self.SOURCE)

    def test_the_generated_certificate_key_is_created_at_its_real_size_and_checked_before_any_file_exists(self):
        source = self.SOURCE; body = source[source.index('static void GenerateCertificate'):source.index('static void WriteConfig')]
        # RSA.Create() + KeySize is ignored by the .NET Framework CSP provider (1024-bit key, EE_KEY_TOO_SMALL in the runtime).
        self.assertNotIn('RSA.Create()', body); self.assertNotIn('rsa.KeySize =', body)
        self.assertIn('public const int CertificateKeyBits = 3072;', source)
        self.assertIn('new RSACng(CertificateKeyBits)', body)
        check, first_write = body.index('p.Modulus.Length * 8 < CertificateKeyBits'), body.index('new FileStream(')
        self.assertLess(check, first_write)
        self.assertEqual(body.count('FileMode.CreateNew'), 2)      # an existing certificate or key is never overwritten
        self.assertNotIn('File.WriteAllText', body)

    def test_a_rejected_configuration_restores_the_previous_one_and_removes_only_this_attempts_certificate(self):
        source = self.SOURCE; start = source.index('try { ValidateRuntime(settings); }'); block = source[start:start + 900]
        self.assertIn('if (old == null) File.Delete(Config); else File.WriteAllText(Config, old);', block)
        self.assertIn('if (https) { try { if (File.Exists(cert)) File.Delete(cert); if (File.Exists(key)) File.Delete(key); }', block)
        self.assertLess(start, source.index('if (!installed) { Run(Wrapper, "install", null);'))  # validated before the service is registered

    def test_http_never_generates_or_carries_a_certificate_and_needs_acknowledgement_beyond_loopback(self):
        self.assertIn('cert = ""; key = "";', self.SOURCE)
        self.assertIn('if (https) { settings["SAP_LENS_TLS_CERT_FILE"] = cert; settings["SAP_LENS_TLS_KEY_FILE"] = key; }', self.SOURCE)
        self.assertIn('HttpNeedsAcknowledgement(listener, hosts) && !acknowledgeHttp', self.SOURCE)
        self.assertIn('settings["SAP_LENS_ALLOW_HTTP"] = "1"', self.SOURCE)
        self.assertIn('Passwords and SAP role data cross the network in clear text', self.SOURCE)        # visible warning
        self.assertIn('(https ? "https://" : "http://") + hosts[0]', self.SOURCE)

    def test_urls_follow_the_configured_scheme_and_existing_https_is_never_switched_to_http(self):
        self.assertIn('StartsWith("http://",StringComparison.OrdinalIgnoreCase)?"http://":"https://"', self.SOURCE)
        # An existing configuration selects its own mode when loaded: HTTP only if it already is HTTP, a stored certificate otherwise.
        self.assertIn('StartsWith("http://",StringComparison.OrdinalIgnoreCase)?2:cert.Text.Length>0?1:0', self.SOURCE)

    def test_the_runtime_validation_still_runs_before_activation_and_reports_the_step(self):
        self.assertIn('--check-server-config', self.SOURCE)
        self.assertIn('if (old == null) File.Delete(Config); else File.WriteAllText(Config, old);', self.SOURCE)
        self.assertIn('Server configuration is invalid.', self.SOURCE)


if __name__ == '__main__':
    unittest.main()
