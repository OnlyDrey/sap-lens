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

    def test_http_follows_the_same_loopback_rule_for_ipv6_as_the_service_manager(self):
        ok = self.settings(SAP_LENS_HOST='::1', SAP_LENS_PUBLIC_ORIGIN='http://[::1]:18743', SAP_LENS_ALLOWED_HOSTS='::1,localhost', SAP_LENS_AUTH='sessions')
        self.assertIn('http://[::1]:18743', ok.origins)
        for listener, origin, hosts in (('::', 'http://[::1]:18743', '::1'), ('2001:db8::10', 'http://[::1]:18743', '::1'), ('::1', 'http://[2001:db8::10]:18743', '2001:db8::10')):
            with self.subTest(listener=listener, origin=origin):
                error = self.fails(SAP_LENS_HOST=listener, SAP_LENS_PUBLIC_ORIGIN=origin, SAP_LENS_ALLOWED_HOSTS=hosts, SAP_LENS_AUTH='sessions', SAP_LENS_ALLOW_HTTP='1')
                self.assertEqual(error.step, 'authentication boundary'); self.assertIn('HTTPS', error.detail)

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
        for text in ('Network access (HTTPS) - generate a self-signed certificate (default)', 'Network access (HTTPS) - use an existing certificate', 'Local access (HTTP) - this computer only, unencrypted'):
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
        # RSACng and GetRSAPublicKey live in System.Core, which csc adds from its default response file unless /noconfig is passed.
        for builder in ('scripts/build-service-manager.ps1', 'scripts/build_system/windows/service_manager.py'):
            self.assertNotIn('/noconfig', (Path(deployment.__file__).parents[1] / builder).read_text(encoding='utf-8'))
        self.assertIn('using System.Linq;', source)
        self.assertIn('publicKey.KeySize<CertificateKeyBits', source)       # checked natively by the build-time self-test

    def test_a_failed_save_undoes_everything_the_attempt_created_and_nothing_else(self):
        source = self.SOURCE; body = source[source.index('var undo = new List<Action>();'):source.index('public static void SelfTest()')]
        steps = ['undo.Add(() => { if (File.Exists(createdBackupKey)) File.Delete(createdBackupKey); });',     # only a backup key created now
                 'undo.Add(() => { if (File.Exists(newCert)) File.Delete(newCert); if (File.Exists(newKey)) File.Delete(newKey); });',
                 'bool dataExisted = Directory.Exists(data);',                                                 # first-run data folder of this attempt
                 'undo.Add(() => { if (old == null) File.Delete(Config); else File.WriteAllText(Config, old); });',
                 'WriteConfig(settings);', 'ValidateRuntime(settings);', 'Run(Wrapper, "install", null);', '} catch {',
                 'for (int index = undo.Count - 1; index >= 0; index--)']
        positions = [body.index(step) for step in steps]
        self.assertEqual(positions, sorted(positions))               # registered before the step, validated before the service exists
        self.assertIn('if (!File.Exists(backupKey)) {', body)        # an existing backup key is never part of the rollback
        self.assertLess(body.index('undo.Add(() => { if (File.Exists(newCert))'), body.index('GenerateCertificate(hosts, newCert, newKey);'))
        self.assertLess(body.index('for (int index = undo.Count - 1'), body.index('Acl(data, true, true);'))   # ACL changes only after success
        self.assertIn('some files created by this attempt could not be removed', body)

    def portable_rules(self, cases):
        """Compile the marked pure validation members with Mono and run them: the real C#, not a re-implementation."""
        import shutil, tempfile as temporary
        if not (shutil.which('mcs') and shutil.which('mono')): self.skipTest('Mono (mcs, mono) is needed to execute the Service Manager validation rules off Windows')
        import re
        members = ''.join(re.findall(r'// <portable-rules>[^\n]*\n(.*?)// </portable-rules>', self.SOURCE, re.S))
        self.assertIn('HttpProblem(', members); self.assertIn('ValidateHosts(', members)
        program = ('using System; using System.Linq; using System.Net; using System.Net.Sockets;\npublic static class Rules {\n' + members + """
            public static int Main(string[] args) {
                foreach (string line in Console.In.ReadToEnd().Split(new[]{'\\n'}, StringSplitOptions.RemoveEmptyEntries)) {
                    string[] part = line.Split('|'); string result;
                    try { result = part[0] == "hosts" ? String.Join(",", ValidateHosts(part[1])) : (HttpProblemText(part[1], part[2]) ?? "ALLOWED"); }
                    catch (ArgumentException error) { result = "REFUSED " + error.Message; }
                    Console.WriteLine(result.Replace("\\n", " "));
                }
                return 0; } }""")
        with temporary.TemporaryDirectory() as directory:
            source = Path(directory) / 'rules.cs'; source.write_text(program, encoding='utf-8')
            built = subprocess.run(['mcs', '-langversion:5', '-out:' + str(Path(directory) / 'rules.exe'), str(source)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            done = subprocess.run(['mono', str(Path(directory) / 'rules.exe')], input='\n'.join(cases) + '\n', capture_output=True, text=True, timeout=60)
            self.assertEqual(done.returncode, 0, done.stderr)
            return done.stdout.splitlines()

    def test_http_is_allowed_only_for_a_loopback_listener_and_loopback_names_ipv4_and_ipv6(self):
        allowed = ['http|127.0.0.1|localhost', 'http|127.0.0.1|127.0.0.1', 'http|::1|::1', 'http|::1|localhost,127.0.0.1,::1', 'http|127.0.0.5|127.0.0.1']
        self.assertEqual(self.portable_rules(allowed), ['ALLOWED'] * len(allowed))
        refused = {'http|0.0.0.0|localhost': 'Listen address: 0.0.0.0 accepts connections on every network interface',
                   'http|::|localhost': 'Listen address: :: accepts connections on every network interface',
                   'http|192.0.2.10|localhost': 'Listen address: 192.0.2.10 can be reached from the network',
                   'http|2001:db8::10|::1': 'Listen address: 2001:db8::10 can be reached from the network',
                   'http|127.0.0.1|server01': 'Server names: server01 is not a local name',
                   'http|127.0.0.1|localhost,server01.example.invalid': 'Server names: server01.example.invalid is not a local name',
                   'http|127.0.0.1|192.0.2.10': 'Server names: 192.0.2.10 is not a local name',
                   'http|127.0.0.1|localhost.example.invalid': 'is not a local name',          # a look-alike name is not loopback
                   'http|127.0.0.1|2001:db8::10': 'Server names: 2001:db8::10 is not a local name',
                   'http|not-an-address|localhost': 'Listen address: enter an IP address',
                   'http|127.0.0.1|0.0.0.0': 'wildcard or broadcast address',
                   'http|127.0.0.1|http://localhost': 'is not a DNS name or IP address'}
        for case, (line, expected) in zip(refused, zip(self.portable_rules(list(refused)), refused.values())):
            with self.subTest(case=case):
                self.assertIn(expected, line); self.assertNotEqual(line, 'ALLOWED')

    def test_server_names_accept_dns_ipv4_and_ipv6_and_refuse_wildcards_ports_and_prefixes(self):
        lines = self.portable_rules(['hosts|Server01, server01.example.invalid ,192.0.2.10,::1,2001:DB8::10', 'hosts|::', 'hosts|0.0.0.0', 'hosts|255.255.255.255',
                                     'hosts|*.example.invalid', 'hosts|server01:18743', 'hosts|https://server01', 'hosts|'])
        self.assertEqual(lines[0], 'server01,server01.example.invalid,192.0.2.10,::1,2001:db8::10')
        for line in lines[1:]: self.assertTrue(line.startswith('REFUSED '), line)

    def test_the_form_and_save_use_the_same_http_rule_and_bracket_ipv6_urls(self):
        source = self.SOURCE
        self.assertIn('string httpProblem = mode == ModeHttp ? HttpProblem(listener, hosts) : null;', source)
        self.assertIn('ServiceSetup.HttpProblemText(listener.Text,hosts.Text)', source)
        self.assertIn('listener.TextChanged += (s,e) => ApplyMode(); hosts.TextChanged += (s,e) => ApplyMode();', source)
        self.assertLess(source.index('if (httpProblem != null) throw new ArgumentException(httpProblem);'), source.index('Directory.CreateDirectory(PrivateRoot)'))
        self.assertIn('(https ? "https://" : "http://") + Bracket(hosts[0]) + ":" + port', source)
        self.assertIn('+ServiceSetup.Bracket(h)+":"+v["SAP_LENS_PORT"]', source)

    def test_service_actions_reach_the_requested_state_without_unintended_restarts_and_report_the_real_state(self):
        source = self.SOURCE; body = source[source.index('public static void Control(string command)'):source.index('static void Acl(')]
        self.assertIn('if ((command == "start" && status == "Running") || (command == "stop" && status == "Stopped")) return;', body)
        self.assertIn('if (command == "restart" && status == "Stopped") command = "start";', body)
        self.assertLess(body.index('status == "Running") ||'), body.index('Run(Wrapper, command, null);'))
        self.assertIn('service.Refresh();', body); self.assertIn('Windows reports " + service.Status', body)
        # Status is read from the Service Control Manager on every call, and every action button refreshes it afterwards.
        status = source[source.index('public static string Status()'):source.index('public static void Control')]
        self.assertIn('using (var service = new ServiceController("SAPLens")) return service.Status.ToString();', status)
        self.assertIn('try{action();RefreshStatus();}', source); self.assertIn('Button(actions,"Refresh",()=>{});', source)
        self.assertIn('ServiceSetup.Quote(ServiceSetup.LogDirectory(data.Text))', source)
        self.assertIn('File.Exists(Config) ? Settings()["SAP_LENS_DATA_DIR"] : typed', source)

    def test_http_never_generates_or_carries_a_certificate_and_needs_acknowledgement_beyond_loopback(self):
        self.assertIn('cert = ""; key = "";', self.SOURCE)
        self.assertIn('if (https) { settings["SAP_LENS_TLS_CERT_FILE"] = cert; settings["SAP_LENS_TLS_KEY_FILE"] = key; }', self.SOURCE)
        self.assertIn('HttpNeedsAcknowledgement(listener, hosts) && !acknowledgeHttp', self.SOURCE)
        self.assertIn('settings["SAP_LENS_ALLOW_HTTP"] = "1"', self.SOURCE)
        self.assertIn('Local access (HTTP) is not encrypted.', self.SOURCE)        # visible warning
        self.assertIn('httpWarning.Text=problem!=null?"Not allowed: "+problem:HttpNote', self.SOURCE)   # the reason is shown while typing
        self.assertIn('(https ? "https://" : "http://") + Bracket(hosts[0])', self.SOURCE)

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
