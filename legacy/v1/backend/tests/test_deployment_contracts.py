"""Deployment artifacts are offline checked; native service execution is separate."""
from pathlib import Path
import ast
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[2]


class DeploymentContracts(unittest.TestCase):
    def test_compose_has_private_defaults_and_persistent_nonprivileged_runtime(self):
        config=yaml.safe_load((ROOT/'compose.yml').read_text())
        service=config['services']['sap-lens']
        self.assertIn('127.0.0.1',service['ports'][0])
        environment=service['environment']
        self.assertEqual(environment['SAP_LENS_AUTH'],'sessions')                       # fixed: no variable can select shared or local access
        self.assertTrue(environment['SAP_LENS_PUBLIC_ORIGIN'].startswith('${SAP_LENS_PUBLIC_ORIGIN:-https://'))
        self.assertEqual(environment['SAP_LENS_TLS_CERT_FILE'],'${SAP_LENS_TLS_CERT_FILE-/run/secrets/tls_cert}')   # TLS unless deliberately emptied for a trusted proxy
        self.assertEqual(environment['SAP_LENS_BACKUP_KEY_FILE'],'/run/secrets/backup_key')
        self.assertEqual(set(config['secrets']),{'tls_cert','tls_key','backup_key','proxy_token'})
        self.assertTrue(all(item['file'].startswith('./local-config/') for item in config['secrets'].values()))   # host files, never the data volume
        text=(ROOT/'compose.yml').read_text()
        for retired in ('basic','allow_http','http://'):self.assertNotIn(retired,text.lower())
        self.assertIn('sap-lens-data:/data',service['volumes'])
        self.assertTrue(service['read_only']);self.assertEqual(service['cap_drop'],['ALL'])
        self.assertNotIn('privileged',service);self.assertNotIn('/var/run/docker.sock',str(config))
        self.assertEqual(service['restart'],'unless-stopped')
        docker=(ROOT/'Dockerfile').read_text()
        self.assertIn('USER 10001:10001',docker);self.assertIn('backend/healthcheck.py',docker)
        self.assertNotIn('requirements-dev',docker);self.assertNotIn('requirements-desktop',docker)
        self.assertIn('STOPSIGNAL SIGTERM',docker)
    def test_linux_native_files_are_started_through_the_interpreter_so_no_executable_bits_are_needed(self):
        """The 0644 archive modes are intentional: nothing is executed directly, and the installer normalizes the installed tree."""
        unit=(ROOT/'deploy/linux/sap-lens.service').read_text()
        line=next(row for row in unit.splitlines() if row.startswith('ExecStart='))
        self.assertTrue(line.startswith('ExecStart=/opt/sap-lens/.venv/bin/python /opt/sap-lens/backend/server.py'))  # script is an argument
        for hardening in ('NoNewPrivileges=true','ProtectSystem=strict','PrivateTmp=true','User=saplens','UMask=0077'):
            self.assertIn(hardening,unit)
        installer=(ROOT/'scripts/install-linux-server.py').read_text()
        self.assertIn("path.chmod(0o755 if path.is_dir() else 0o644)",installer)  # releases: root-owned, never group/world writable
        self.assertNotIn('0o777',installer);self.assertNotIn('0o4755',installer)
        for guide in ('docs/deployment/LINUX_NATIVE.md',):
            text=(ROOT/guide).read_text()
            self.assertNotIn('chmod +x',text);self.assertNotIn('\n./scripts/',text)  # direct execution is not part of the contract
            self.assertIn('python3.12 scripts/install-linux-server.py',text)
    def test_server_has_no_desktop_imports_and_single_worker(self):
        tree=ast.parse((ROOT/'backend/server.py').read_text())
        imports=[node.module for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
        self.assertNotIn('desktop',imports);self.assertNotIn('webview',imports)
        self.assertIn('workers=1',(ROOT/'backend/server.py').read_text())
        unit=(ROOT/'deploy/linux/sap-lens.service').read_text()
        for expected in ['User=saplens','NoNewPrivileges=true','ProtectSystem=strict','Restart=on-failure',
                         'ReadWritePaths=/var/lib/sap-lens','WantedBy=multi-user.target','PrivateDevices=true','ProtectKernelTunables=true',
                         'ProtectKernelModules=true','ProtectControlGroups=true','LockPersonality=true','RestrictRealtime=true','RestrictSUIDSGID=true',
                         'RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6']:
            self.assertIn(expected,unit)
    def test_service_and_build_preserve_independent_runtime_and_verification(self):
        service=(ROOT/'scripts/manage-server-service.ps1').read_text()
        build=(ROOT/'scripts/build-server-windows.ps1').read_text()
        for value in ['LocalService','sidtype SAPLens unrestricted','<startmode>Automatic</startmode>',
                      '<onfailure action="restart"','<stoptimeout>25 sec</stoptimeout>','Get-FileHash','Uninstall']:
            self.assertIn(value,service)
        for value in ['local-build.py check','local-build.py tools','--onedir','--console','--noupx','--exclude-module webview','verify-server-bundle.py']:
            self.assertIn(value,build)
        self.assertNotIn('Remove-Item $DataDirectory',service)
        self.assertNotIn('manage-server-service',(ROOT/'scripts/build-windows.ps1').read_text())
