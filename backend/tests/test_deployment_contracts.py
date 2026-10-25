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
        self.assertEqual(service['environment']['SAP_LENS_AUTH'],'${SAP_LENS_AUTH:-basic}')
        self.assertIn('sap-lens-data:/data',service['volumes'])
        self.assertTrue(service['read_only']);self.assertEqual(service['cap_drop'],['ALL'])
        self.assertNotIn('privileged',service);self.assertNotIn('/var/run/docker.sock',str(config))
        self.assertEqual(service['restart'],'unless-stopped')
        docker=(ROOT/'Dockerfile').read_text()
        self.assertIn('USER 10001:10001',docker);self.assertIn('backend/healthcheck.py',docker)
        self.assertNotIn('requirements-dev',docker);self.assertNotIn('requirements-desktop',docker)
        self.assertIn('STOPSIGNAL SIGTERM',docker)
    def test_server_has_no_desktop_imports_and_single_worker(self):
        tree=ast.parse((ROOT/'backend/server.py').read_text())
        imports=[node.module for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
        self.assertNotIn('desktop',imports);self.assertNotIn('webview',imports)
        self.assertIn('workers=1',(ROOT/'backend/server.py').read_text())
        unit=(ROOT/'deploy/linux/sap-lens.service').read_text()
        for expected in ['User=saplens','NoNewPrivileges=true','ProtectSystem=strict','Restart=on-failure',
                         'ReadWritePaths=/var/lib/sap-lens','WantedBy=multi-user.target']:
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
