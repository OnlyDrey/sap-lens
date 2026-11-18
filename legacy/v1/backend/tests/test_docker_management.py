"""CLI admission must never touch a daemon or unknown installation by accident."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]


@unittest.skipUnless(sys.platform=='linux','Linux shell deployment entry point')
class DockerManagementTests(unittest.TestCase):
    def test_help_and_invalid_arguments_do_not_call_docker_or_create_storage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);fake=root/'docker';marker=root/'called'
            fake.write_text('#!/bin/sh\nprintf called > '+str(marker)+'\nexit 77\n');fake.chmod(0o755)
            env={**os.environ,'PATH':str(root)+os.pathsep+os.environ['PATH']}
            installation=root/'new-installation'
            supplied=root/'supplied.crt';supplied.write_text('synthetic')
            cases=[(['help'],0),(['unknown',str(installation)],1),(['install',str(installation),'--unknown'],1),
                   (['install',str(installation),'--hostname','*.example.test'],1),(['install',str(installation),'--hostname','UPPER.example.test'],1),
                   (['install',str(installation),'--port','70000'],1),(['install',str(installation),'--port'],1),
                   (['install',str(installation),'--tls-cert',str(supplied)],1),(['install',str(installation),'--tls-cert',str(supplied),'--tls-key',str(root/'missing.key')],1),
                   (['upgrade',str(installation),'--new-administrator','bad name'],1),(['upgrade',str(installation),'--unknown'],1),
                   (['install',str(installation),'--allow-http'],1),(['install',str(installation),'--auth','basic'],1)]
            for args,code in cases:
                with self.subTest(args=args):
                    result=subprocess.run(['sh',str(ROOT/'deploy/docker/manage.sh'),*args],env=env,capture_output=True,text=True)
                    self.assertEqual(result.returncode,code,result.stderr)
                    self.assertFalse(marker.exists());self.assertFalse(installation.exists())

    def test_unknown_installation_does_not_reach_daemon_mutations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);fake=root/'docker';marker=root/'unexpected'
            fake.write_text('#!/bin/sh\nif [ "$1 $2" = "compose version" ]; then exit 0; fi\nprintf called > '+str(marker)+'\nexit 77\n');fake.chmod(0o755)
            env={**os.environ,'PATH':str(root)+os.pathsep+os.environ['PATH']}
            installation=root/'unrecognized';installation.mkdir();private=installation/'retain.txt';private.write_text('synthetic')
            for action in ['start','stop','backup','uninstall','activation-code','recover-administrator','status','restore']:
                result=subprocess.run(['sh',str(ROOT/'deploy/docker/manage.sh'),action,str(installation)],env=env,capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0)
                self.assertFalse(marker.exists());self.assertEqual(private.read_text(),'synthetic')


class ManagementSourceContracts(unittest.TestCase):
    def setUp(self):
        self.script=(ROOT/'deploy/docker/manage.sh').read_text(encoding='utf-8')

    def test_no_retired_access_mode_plaintext_archive_or_disabled_verification(self):
        for retired in ('SAP_LENS_AUTH=basic','server-access.secret','.tar.gz','--config-dir','ALLOW_HTTP','--insecure','verify=False','CERT_NONE'):
            self.assertNotIn(retired,self.script)
        self.assertIn('--confirm-restore --confirm-accounts',self.script)
        self.assertIn('.slbak',self.script)

    def test_host_files_are_created_only_when_missing_and_the_generated_certificate_is_announced(self):
        for name in ('backup.key','proxy-token.secret'):
            self.assertIn(f'if [ ! -e "$root/local-config/{name}" ]',self.script)
        self.assertIn('if [ -e "$root/local-config/tls.crt" ] || [ -e "$root/local-config/tls.key" ]',self.script)
        self.assertIn('Existing TLS certificate and private key kept unchanged.',self.script)
        self.assertIn('SELF-SIGNED',self.script);self.assertIn('never regenerated or overwritten',self.script)
        self.assertNotIn('rm -f "$root/local-config',self.script);self.assertNotIn('rm -rf "$root/local-config',self.script)

    def test_one_time_codes_come_from_the_local_cli_and_legacy_installations_are_never_converted_silently(self):
        self.assertEqual(self.script.count('--identity-code --data-directory /data'),2)
        self.assertIn('--migrate-legacy --new-administrator NAME',self.script)
        self.assertIn('--migrate-identity --data-directory /data',self.script)
