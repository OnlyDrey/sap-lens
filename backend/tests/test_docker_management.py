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
            cases=[(['help'],0),(['unknown',str(installation)],1),(['install',str(installation),'--unknown'],1)]
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
            for action in ['start','stop','backup','uninstall']:
                result=subprocess.run(['sh',str(ROOT/'deploy/docker/manage.sh'),action,str(installation)],env=env,capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0)
                self.assertFalse(marker.exists());self.assertEqual(private.read_text(),'synthetic')
