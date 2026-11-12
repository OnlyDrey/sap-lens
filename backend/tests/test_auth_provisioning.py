"""Activation is explicit/local, persisted, single-use and transactional."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from auth_store import AuthError, AuthStore
from auth_provisioning import prepare, state, issue, complete

PASSWORD='Synthetic bootstrap password å 123!'


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.store=prepare(self.root)
        self.now=1_800_000_000
        self.store.clock=lambda:self.now

    def activate(self, code):
        return complete(self.store,code,'admin','Administrator',PASSWORD)

    def test_restart_consumption_no_public_code_and_no_plaintext(self):
        code=issue(self.store)['code']
        self.assertEqual(state(self.store),dict(provider='local-sessions',setup_required=True))
        with self.store.connection() as db:
            self.assertNotIn(code,str([dict(row) for row in db.execute('SELECT * FROM one_time')]))
        restarted=AuthStore(self.store.path,lambda:self.now)
        user=complete(restarted,code,'admin','Administrator',PASSWORD)
        self.assertEqual(user['role'],'administrator')
        self.assertFalse(state(restarted)['setup_required'])
        with self.assertRaises(AuthError):self.activate(code)
        with self.assertRaises(AuthError):issue(restarted)
        self.assertEqual(restarted.login('admin',PASSWORD,'test')[0].id,user['id'])

    def test_attempt_limit_expiration_reissue_and_race(self):
        code=issue(self.store)['code']
        for _ in range(5):
            with self.assertRaises(AuthError):self.activate('x'*43)
        with self.assertRaises(AuthError):self.activate(code)
        code=issue(self.store)['code']
        self.now+=901
        with self.assertRaises(AuthError):self.activate(code)
        code=issue(self.store)['code']
        def try_setup(_):
            try:self.activate(code);return True
            except AuthError:return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(try_setup,range(2))),1)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM users').fetchone()[0],1)

    def test_recovery_preserves_identity_history_and_never_reopens_setup(self):
        self.activate(issue(self.store)['code'])
        actor,token,_=self.store.login('admin',PASSWORD,'fixture')
        code=issue(self.store,'admin')['code']
        with self.assertRaises(AuthError):self.store.session(token)
        with self.assertRaises(AuthError):self.store.login('admin',PASSWORD,'fixture')
        user=complete(self.store,code,'','',PASSWORD+'new',recovery=True)
        self.assertEqual(user['id'],actor.id)
        with self.assertRaises(AuthError):complete(self.store,code,'','',PASSWORD,recovery=True)
        self.assertFalse(state(self.store)['setup_required'])
        with self.store.connection() as db:
            self.assertGreaterEqual(db.execute('SELECT COUNT(*) FROM audit').fetchone()[0],4)
        self.assertEqual(self.store.login('admin',PASSWORD+'new','new')[0].id,actor.id)

    def test_existing_populated_corrupt_and_missing_stores_do_not_become_fresh(self):
        for name in ('settings.json','sources','unrecognized-file'):
            with tempfile.TemporaryDirectory() as root:
                (Path(root)/name).write_text('{}')
                with self.assertRaisesRegex(AuthError,'identity_migration_required'):prepare(Path(root))
                self.assertFalse((Path(root)/'security/accounts.sqlite3').exists())
        with self.store.connection(True) as db:db.execute("UPDATE meta SET value='1'")
        self.assertFalse(state(self.store)['setup_required'])
        with self.assertRaises(AuthError):issue(self.store)
        self.store.path.write_bytes(b'corrupt')
        with self.assertRaises(AuthError):prepare(self.root)
        self.assertEqual(self.store.path.read_bytes(),b'corrupt')

    def test_local_cli_issues_code_without_creating_missing_store(self):
        server=Path(__file__).resolve().parents[1]/'server.py'
        env={**os.environ,'PYTHONUTF8':'1'}
        done=subprocess.run([sys.executable,str(server),'--identity-code','--data-directory',str(self.root)],capture_output=True,text=True,timeout=20,env=env)
        self.assertEqual(done.returncode,0,done.stderr)
        self.assertGreaterEqual(len(json.loads(done.stdout)['code']),40)
        missing=self.root/'missing'
        done=subprocess.run([sys.executable,str(server),'--identity-code','--data-directory',str(missing)],capture_output=True,text=True,timeout=20,env=env)
        self.assertNotEqual(done.returncode,0)
        self.assertFalse(missing.exists())
