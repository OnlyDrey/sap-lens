"""Durable account/session contracts in isolated temporary stores; no real accounts."""
import base64
import json
from pathlib import Path
import tempfile
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from auth_store import AuthStore, AuthError, password_hash, require, verify_password

PASSWORD = 'Synthetic long password æ 123!'


class SecurityStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 1_800_000_000
        self.store = AuthStore(Path(self.temp.name) / 'security/accounts.sqlite3', lambda: self.now)
        self.store.initialize()
        self.admin_row = self.store.create_user(None, 'admin', 'Administrator', 'administrator', PASSWORD, bootstrap=True)
        self.admin, self.token, self.csrf_token = self.store.login('admin', PASSWORD, 'test-client')

    def test_random_hashes_unicode_and_limits(self):
        one, two = password_hash(PASSWORD), password_hash(PASSWORD)
        self.assertNotEqual(one, two)
        self.assertTrue(verify_password(one, PASSWORD))
        self.assertFalse(verify_password(one, 'wrong'))
        self.assertFalse(verify_password(None, PASSWORD))
        for value in ('short', 'æ' * 1025):
            with self.assertRaises(AuthError): password_hash(value)
        self.assertTrue(verify_password(password_hash('å' * 1024), 'å' * 1024))

    def test_session_csrf_expiry_and_reopen(self):
        self.assertEqual(AuthStore(self.store.path, lambda: self.now).session(self.token).id, self.admin.id)
        self.store.csrf(self.admin, self.csrf_token)
        with self.assertRaisesRegex(AuthError, 'csrf_required'): self.store.csrf(self.admin, 'forged')
        self.now += 1801
        with self.assertRaisesRegex(AuthError, 'authentication_required'): self.store.session(self.token)

    def test_no_plaintext_tokens_or_passwords_in_database_or_audit(self):
        with self.store.connection() as db:
            for table in ('users', 'sessions', 'audit'):
                stored = str([dict(row) for row in db.execute('SELECT * FROM ' + table)])
                self.assertNotIn(PASSWORD, stored)
                self.assertNotIn(self.token, stored)
                self.assertNotIn(self.csrf_token, stored)
        self.assertTrue(self.admin.id)
        self.assertEqual(self.admin.snapshot()['provenance'], 'server-session')

    def test_last_administrator_and_stale_revisions(self):
        with self.assertRaisesRegex(AuthError, 'last_administrator'):
            self.store.update_user(self.admin, self.admin.id, 0, role='viewer', enabled=True, display_name='Admin')
        row = self.store.create_user(self.admin, 'reader', 'Reader', 'viewer', PASSWORD)
        self.store.update_user(self.admin, row['id'], 0, role='reviewer', enabled=True, display_name='Reviewer')
        with self.assertRaisesRegex(AuthError, 'stale_user'):
            self.store.update_user(self.admin, row['id'], 0, role='viewer', enabled=True, display_name='Reader')

    def test_disabled_user_and_revocation(self):
        row = self.store.create_user(self.admin, 'reviewer', 'Reviewer', 'reviewer', PASSWORD)
        principal, token, _ = self.store.login('reviewer', PASSWORD, 'reviewer-client')
        self.store.update_user(self.admin, row['id'], 0, role='reviewer', enabled=False, display_name='Reviewer')
        with self.assertRaises(AuthError): self.store.session(token)
        with self.assertRaisesRegex(AuthError, 'invalid_credentials'): self.store.login('reviewer', PASSWORD, 'reviewer-client')
        with self.assertRaises(AuthError): self.store.change_password(principal, PASSWORD, PASSWORD + 'new')

    def test_central_permissions_default_deny_and_recheck(self):
        row = self.store.create_user(self.admin, 'viewer', 'Viewer', 'viewer', PASSWORD)
        viewer, _, _ = self.store.login('viewer', PASSWORD, 'viewer-client')
        require(viewer, 'read'); require(viewer, 'export')
        for permission in ('accounts', 'admin', 'review', 'approve', 'new_unknown_operation'):
            with self.assertRaises(AuthError): require(viewer, permission)
        with self.assertRaises(AuthError): self.store.create_user(viewer, 'x', 'X', 'administrator', PASSWORD)
        self.store.revoke(self.admin, self.admin.id)
        with self.assertRaises(AuthError): self.store.create_user(self.admin, 'x', 'X', 'viewer', PASSWORD)
        self.assertEqual(row['role'], 'viewer')

    def test_password_change_revokes_all_sessions(self):
        _, second, _ = self.store.login('admin', PASSWORD, 'second-client')
        self.store.change_password(self.admin, PASSWORD, PASSWORD + 'changed')
        for token in (self.token, second):
            with self.assertRaises(AuthError): self.store.session(token)
        with self.assertRaises(AuthError): self.store.login('admin', PASSWORD, 'login')
        self.assertEqual(self.store.login('admin', PASSWORD + 'changed', 'login')[0].id, self.admin.id)

    def test_logout_one_and_all(self):
        _, second, _ = self.store.login('admin', PASSWORD, 'second-client')
        self.store.logout(self.admin)
        with self.assertRaises(AuthError): self.store.session(self.token)
        self.store.logout(self.store.session(second), True)
        with self.assertRaises(AuthError): self.store.session(second)

    def test_wrong_unknown_and_temporary_throttle(self):
        for _ in range(5):
            with self.assertRaisesRegex(AuthError, 'invalid_credentials'): self.store.login('missing', 'wrong', 'limited-client')
        with self.assertRaisesRegex(AuthError, 'temporarily_throttled'): self.store.login('admin', PASSWORD, 'limited-client')
        self.now += 31
        self.assertEqual(self.store.login('admin', PASSWORD, 'limited-client')[0].id, self.admin.id)

    def test_repeated_failures_lock_longer_up_to_a_cap_and_relax_after_idle_time(self):
        def fail():
            with self.assertRaisesRegex(AuthError, 'invalid_credentials'): self.store.login('admin', 'wrong', 'escalating')
        def locked():
            with self.assertRaisesRegex(AuthError, 'temporarily_throttled'): self.store.login('admin', PASSWORD, 'escalating')
        for _ in range(5): fail()
        locked(); self.now += 31
        for expected in (60, 120, 240, 480, 900, 900):          # each further failure doubles the lock, never beyond 15 minutes
            fail(); locked()
            self.now += expected - 1; locked()
            self.now += 2
        self.assertEqual(self.store.login('admin', PASSWORD, 'escalating')[0].id, self.admin.id)   # the correct password clears the record
        for _ in range(4): fail()
        self.assertEqual(self.store.login('admin', PASSWORD, 'escalating')[0].id, self.admin.id)
        for _ in range(5): fail()
        self.now += self.store.LOCK_IDLE + 31                    # quiet for half an hour after the lock: the count starts over
        for _ in range(4): fail()
        self.assertEqual(self.store.login('admin', PASSWORD, 'escalating')[0].id, self.admin.id)
        with self.assertRaisesRegex(AuthError, 'invalid_credentials'): self.store.login('admin', 'wrong', 'someone-else')   # other clients are unaffected

    def test_limit_and_denial_records_are_bounded_without_touching_locks_or_administrative_audit(self):
        self.store.LIMIT_ROWS, self.store.DENIAL_ROWS = 20, 30
        for _ in range(5):
            with self.assertRaises(AuthError): self.store.login('admin', 'wrong', 'locked-client')
        actor = self.store.login('admin', PASSWORD, 'trusted')[0]
        created = self.store.create_user(actor, 'kept', 'Kept', 'viewer', PASSWORD)
        for index in range(320):
            with self.assertRaises(AuthError): self.store.login('admin', 'wrong', f'flood-{index}')
        with self.store.connection() as db:
            self.assertLessEqual(db.execute('SELECT COUNT(*) FROM login_limits').fetchone()[0], 21)
            denied = db.execute("SELECT COUNT(*) FROM audit WHERE operation='session.login_denied'").fetchone()[0]
            operations = [row[0] for row in db.execute("SELECT operation FROM audit WHERE operation<>'session.login_denied'")]
            newest = db.execute("SELECT MAX(at) FROM audit WHERE operation='session.login_denied'").fetchone()[0]
        self.assertTrue(30 <= denied <= 30 + 256 + 1, denied); self.assertEqual(newest, self.now)
        self.assertIn('user.create', operations); self.assertIn('session.login', operations)      # nothing but denial noise is ever removed
        with self.assertRaisesRegex(AuthError, 'temporarily_throttled'): self.store.login('admin', PASSWORD, 'locked-client')   # flooding did not lift the lock
        self.assertEqual(created['username'], 'kept')

    def test_concurrent_last_admin_protection(self):
        row = self.store.create_user(self.admin, 'other', 'Other administrator', 'administrator', PASSWORD)
        other, _, _ = self.store.login('other', PASSWORD, 'other-client')
        def demote(pair):
            actor, target = pair
            try:
                self.store.update_user(actor, target, 0, role='viewer', enabled=True, display_name='Former admin')
                return True
            except AuthError: return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(demote, [(self.admin, self.admin.id), (other, row['id'])]))
        self.assertEqual(sum(results), 1)
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM users WHERE role='administrator' AND enabled=1").fetchone()[0], 1)

    def test_legacy_pbkdf2_upgrades_without_changing_password(self):
        import hashlib
        salt = b'x' * 32
        row = dict(iterations=600_000, salt=base64.b64encode(salt).decode(), hash=base64.b64encode(hashlib.pbkdf2_hmac('sha256', PASSWORD.encode(), salt, 600_000)).decode())
        with self.store.connection(True) as db:
            db.execute('UPDATE users SET verifier=? WHERE id=?', ('pbkdf2:' + json.dumps(row), self.admin.id))
        self.assertEqual(self.store.login('admin', PASSWORD, 'legacy')[0].id, self.admin.id)
        with self.store.connection() as db:
            self.assertTrue(db.execute('SELECT verifier FROM users').fetchone()[0].startswith('$argon2id$'))

    def test_reset_consumption_revocation_and_replay(self):
        row=self.store.create_user(self.admin,'reset-user','Reset user','reviewer',PASSWORD)
        _,token,_=self.store.login('reset-user',PASSWORD,'before-reset')
        reset=self.store.issue_reset(self.admin,row['id'],0)
        with self.assertRaises(AuthError):self.store.session(token)
        with self.assertRaises(AuthError):self.store.login('reset-user',PASSWORD,'before-reset')
        with self.store.connection() as db:
            self.assertNotIn(reset['code'],str([dict(row) for row in db.execute('SELECT * FROM one_time')]))
        self.store.complete_reset(reset['code'],PASSWORD+'new','reset-client')
        with self.assertRaises(AuthError):self.store.complete_reset(reset['code'],PASSWORD+'again','reset-client')
        self.assertEqual(self.store.login('reset-user',PASSWORD+'new','new-client')[0].id,row['id'])
        with self.assertRaises(AuthError):self.store.issue_reset(self.admin,self.admin.id,0)

    def test_policy_revision_shortening_and_own_profile(self):
        policy=self.store.policy(self.admin)
        self.store.update_policy(self.admin,policy['revision'],300,3600)
        with self.assertRaisesRegex(AuthError,'stale_policy'):self.store.update_policy(self.admin,policy['revision'],300,3600)
        changed=self.store.profile(self.admin,'New display name',0)
        self.assertEqual(changed['id'],self.admin.id)
        self.assertEqual(self.store.session(self.token).display_name,'New display name')
        self.now+=301
        with self.assertRaises(AuthError):self.store.session(self.token)

    def test_missing_or_existing_store_never_initializes_implicitly(self):
        with self.assertRaises(FileExistsError): self.store.initialize()
        missing = AuthStore(Path(self.temp.name) / 'missing.sqlite3')
        with self.assertRaisesRegex(AuthError, 'security_store_unavailable'): missing.login('x', PASSWORD, 'x')
        self.assertFalse(missing.path.exists())
        with self.assertRaisesRegex(AuthError, 'bootstrap_closed'):
            self.store.create_user(None, 'new', 'New', 'administrator', PASSWORD, bootstrap=True)


class ConnectionLifecycleTests(unittest.TestCase):
    """Every connection the account store opens is closed when the operation returns, successful or not.

    SQLite on Windows opens files without delete sharing: one connection left to the garbage collector keeps accounts.sqlite3 locked,
    so a data directory cannot be removed, restored over or migrated (WinError 32). The store therefore never relies on collection.
    """
    def test_no_operation_leaves_a_connection_open_and_the_store_can_be_removed_at_once(self):
        import gc
        import sqlite3
        from unittest.mock import patch
        import auth_store
        import auth_provisioning
        opened, connect = [], sqlite3.connect
        def recording(*args, **kwargs):
            connection = connect(*args, **kwargs); opened.append(connection); return connection
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'data'; root.mkdir()
            gc.disable()   # nothing may depend on the collector releasing a connection
            try:
                with patch.object(auth_store.sqlite3, 'connect', recording):
                    store = auth_provisioning.prepare(root)                            # fresh initialization
                    code = auth_provisioning.issue(store)['code']
                    with self.assertRaises(AuthError): auth_provisioning.complete(store, 'x' * 43, 'admin', 'Admin', PASSWORD)   # refused code
                    auth_provisioning.complete(store, code, 'admin', 'Admin', PASSWORD)
                    actor, token, csrf = store.login('admin', PASSWORD, 'client')
                    with self.assertRaises(AuthError): store.login('admin', 'wrong', 'client')                                  # failure paths too
                    with self.assertRaises(AuthError): store.session('z' * 43)
                    with self.assertRaises(AuthError): store.create_user(actor, 'admin', 'Duplicate', 'viewer', PASSWORD)
                    store.session(token); store.csrf(actor, csrf); store.users(actor); store.sessions(actor); store.logout(actor)
                    with self.assertRaises(FileExistsError): store.initialize()
                self.assertGreater(len(opened), 10)
                for connection in opened:
                    with self.assertRaises(sqlite3.ProgrammingError): connection.execute('SELECT 1')   # closed, not merely unused
                (root / 'security/accounts.sqlite3').unlink()      # on Windows this is refused while any handle is open
                self.assertEqual([path.name for path in (root / 'security').iterdir() if path.name.startswith('accounts.sqlite3')], [])   # no -wal or -shm left behind
            finally:
                gc.enable()
