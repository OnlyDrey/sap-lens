"""Durable local identity/session store; independent of the rebuildable source cache.

This foundation has no import-time I/O and never initializes merely because a
request could not read its database. Bootstrap/migration explicitly create it.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
ROLES = {'administrator', 'reviewer', 'viewer'}
SCHEMA = 1
PERMISSIONS = {
    'read': ROLES, 'export': ROLES, 'profile': ROLES,
    'review': {'administrator', 'reviewer'}, 'approve': {'administrator', 'reviewer'},
    'admin': {'administrator'}, 'accounts': {'administrator'},
}


class AuthError(ValueError):
    def __init__(self, code, status=400):
        self.code, self.status = code, status
        super().__init__(code)


@dataclass(frozen=True)
class Principal:
    id: str
    username: str
    display_name: str
    role: str
    session_id: str = ''

    def snapshot(self):
        return dict(id=self.id, username=self.username, display_name=self.display_name, provenance='server-session')


def require(principal, permission):
    if not principal or principal.role not in PERMISSIONS.get(permission, set()):
        raise AuthError('permission_denied', 403)


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def password_hash(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 1024 or len(password.encode('utf-8')) > 4096:
        raise AuthError('password_length')
    return HASHER.hash(password)


def verify_password(verifier, password):
    if not isinstance(verifier, str) or not isinstance(password, str) or len(password) > 1024 or len(password.encode('utf-8')) > 4096:
        return False
    try:
        if verifier.startswith('$argon2id$'):
            return HASHER.verify(verifier, password)
        if verifier.startswith('pbkdf2:'):
            import base64
            row = json.loads(verifier[7:])
            if row['iterations'] != 600_000:
                return False
            expected = base64.b64decode(row['hash'], validate=True)
            salt = base64.b64decode(row['salt'], validate=True)
            if len(expected) != 32 or len(salt) != 32:
                return False
            return hmac.compare_digest(expected, hashlib.pbkdf2_hmac('sha256', password.encode(), salt, row['iterations']))
    except (VerificationError, InvalidHashError, ValueError, KeyError, TypeError):
        pass
    return False


def public(row):
    result = {key: row[key] for key in ('id', 'username', 'display_name', 'role', 'enabled', 'revision', 'created', 'last_login')}
    result['enabled'] = bool(result['enabled'])
    return result


class AuthStore:
    def __init__(self, path, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        self._dummy = None
        if not self.path.is_absolute():
            raise AuthError('absolute_security_path_required')

    def _safe(self):
        if any(p.is_symlink() or p.is_junction() for p in (self.path, *self.path.parents)):
            raise AuthError('linked_security_path', 503)

    def initialize(self):
        """Explicit empty-store creation; callers must classify fresh/migration state."""
        self._safe()
        if self.path.exists():
            raise FileExistsError('Security store already exists.')
        if self.path.parent.exists() and any(self.path.parent.iterdir()):
            raise AuthError('unrecognized_security_directory', 503)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != 'nt':
            self.path.parent.chmod(0o700)
        else:
            from deployment import check_windows_secret_acl
            check_windows_secret_acl(self.path.parent)
        fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        try:
            with sqlite3.connect(self.path) as db:
                db.executescript('''
                CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT INTO meta VALUES('initialized','0');
                CREATE TABLE users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL,
                  role TEXT NOT NULL CHECK(role IN ('administrator','reviewer','viewer')), enabled INTEGER NOT NULL,
                  verifier TEXT NOT NULL, credential_version INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 0,
                  created REAL NOT NULL, last_login REAL);
                CREATE TABLE sessions(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),credential_version INTEGER NOT NULL,
                  csrf TEXT NOT NULL,created REAL NOT NULL,seen REAL NOT NULL,expires REAL NOT NULL);
                CREATE INDEX session_user ON sessions(user_id);
                CREATE TABLE policy(id INTEGER PRIMARY KEY CHECK(id=1), idle INTEGER NOT NULL, absolute INTEGER NOT NULL,revision INTEGER NOT NULL);
                INSERT INTO policy VALUES(1,1800,43200,0);
                CREATE TABLE audit(id TEXT PRIMARY KEY,at REAL NOT NULL,actor TEXT NOT NULL,operation TEXT NOT NULL,
                  target TEXT NOT NULL,before_value TEXT,after_value TEXT);
                CREATE TABLE login_limits(client TEXT PRIMARY KEY, failures INTEGER NOT NULL,until_time REAL NOT NULL);
                CREATE TABLE one_time(id TEXT PRIMARY KEY,purpose TEXT NOT NULL,user_id TEXT,verifier TEXT NOT NULL,
                  created REAL NOT NULL,expires REAL NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,consumed INTEGER NOT NULL DEFAULT 0);
                PRAGMA user_version=1;
                ''')
        except BaseException:
            # Keep failed initialization for explicit recovery; do not retry as fresh.
            raise

    @contextmanager
    def connection(self, write=False):
        self._safe()
        if not self.path.is_file():
            raise AuthError('security_store_unavailable', 503)
        try:
            db = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True, timeout=5, isolation_level=None)
        except sqlite3.Error:
            raise AuthError('security_store_unavailable', 503) from None
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA busy_timeout=5000')
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA synchronous=FULL')
            if db.execute('PRAGMA user_version').fetchone()[0] != SCHEMA:
                raise AuthError('security_schema_unsupported', 503)
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            if write:
                db.execute('COMMIT')
        except sqlite3.Error:
            if db.in_transaction:
                db.execute('ROLLBACK')
            raise AuthError('security_store_unavailable', 503) from None
        except BaseException:
            if db.in_transaction:
                db.execute('ROLLBACK')
            raise
        finally:
            db.close()

    def _audit(self, db, actor, operation, target='', before=None, after=None):
        # Only callers' public metadata is accepted; never verifier/token fields.
        def clean(value):
            return json.dumps({k: v for k, v in value.items() if k in {'id','username','display_name','role','enabled','revision','idle','absolute'}}) if value is not None else None
        db.execute('INSERT INTO audit VALUES(?,?,?,?,?,?,?)', (uuid4().hex, self.clock(), json.dumps(actor.snapshot()) if actor else 'local-bootstrap', operation, target, clean(before), clean(after)))

    def _authorize(self, db, actor, permission):
        require(actor, permission)
        row = db.execute('SELECT u.*,s.expires,s.seen,s.created AS session_created,p.idle,p.absolute,s.credential_version AS session_version FROM users u JOIN sessions s ON s.user_id=u.id JOIN policy p ON p.id=1 WHERE u.id=? AND s.id=?', (actor.id, actor.session_id)).fetchone()
        now = self.clock()
        if not row or not row['enabled'] or row['credential_version'] != row['session_version'] or min(row['expires'], row['session_created'] + row['absolute']) <= now or row['seen'] + row['idle'] <= now:
            raise AuthError('authentication_required', 401)
        if row['role'] not in PERMISSIONS.get(permission, set()):
            raise AuthError('permission_denied', 403)

    def users(self, actor):
        require(actor, 'accounts')
        with self.connection() as db:
            self._authorize(db, actor, 'accounts')
            return [public(row) for row in db.execute('SELECT * FROM users ORDER BY username')]

    @staticmethod
    def validate_profile(username, display_name, role):
        if not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_.@-]{1,100}', username):
            raise AuthError('invalid_username')
        if role not in ROLES or not isinstance(display_name, str) or not 1 <= len(display_name.strip()) <= 120:
            raise AuthError('invalid_profile')
    def create_user(self, actor, username, display_name, role, password, *, bootstrap=False):
        if not bootstrap:
            require(actor, 'accounts')
        self.validate_profile(username, display_name, role)
        verifier = password_hash(password)
        with self.connection(True) as db:
            if not bootstrap:
                self._authorize(db, actor, 'accounts')
            if bootstrap and (db.execute('SELECT COUNT(*) FROM users').fetchone()[0] or db.execute("SELECT value FROM meta WHERE key='initialized'").fetchone()[0] != '0'):
                raise AuthError('bootstrap_closed', 409)
            if db.execute('SELECT 1 FROM users WHERE username=?', (username,)).fetchone():
                raise AuthError('username_exists', 409)
            identity = uuid4().hex
            db.execute('INSERT INTO users(id,username,display_name,role,enabled,verifier,created) VALUES(?,?,?,?,1,?,?)', (identity, username, display_name.strip(), role, verifier, self.clock()))
            if bootstrap:
                if role != 'administrator':
                    raise AuthError('bootstrap_administrator_required')
                db.execute("UPDATE meta SET value='1' WHERE key='initialized'")
            result = public(db.execute('SELECT * FROM users WHERE id=?', (identity,)).fetchone())
            self._audit(db, actor, 'user.create', identity, after=result)
            return result

    def update_user(self, actor, identity, revision, *, role, enabled, display_name):
        require(actor, 'accounts')
        if role not in ROLES or type(enabled) is not bool or not isinstance(display_name, str) or not 1 <= len(display_name.strip()) <= 120:
            raise AuthError('invalid_profile')
        with self.connection(True) as db:
            self._authorize(db, actor, 'accounts')
            row = db.execute('SELECT * FROM users WHERE id=?', (identity,)).fetchone()
            if not row:
                raise AuthError('user_not_found', 404)
            if row['revision'] != revision:
                raise AuthError('stale_user', 409)
            if row['role'] == 'administrator' and row['enabled'] and (role != 'administrator' or not enabled):
                if db.execute("SELECT COUNT(*) FROM users WHERE role='administrator' AND enabled=1").fetchone()[0] <= 1:
                    raise AuthError('last_administrator', 409)
            before = public(row)
            db.execute('UPDATE users SET role=?,enabled=?,display_name=?,revision=revision+1,credential_version=credential_version+1 WHERE id=?', (role, int(enabled), display_name.strip(), identity))
            db.execute('DELETE FROM sessions WHERE user_id=?', (identity,))
            result = public(db.execute('SELECT * FROM users WHERE id=?', (identity,)).fetchone())
            self._audit(db, actor, 'user.update', identity, before, result)
            return result

    def login(self, username, password, client):
        now = self.clock()
        # Bound the client identifier; use its digest rather than storing addresses.
        client_key = digest(str(client)[:256])
        with self.connection() as db:
            blocked = db.execute('SELECT * FROM login_limits WHERE client=?', (client_key,)).fetchone()
            if blocked and blocked['until_time'] > now:
                raise AuthError('temporarily_throttled', 429)
            row = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
        if self._dummy is None:
            self._dummy = password_hash('Dummy local authentication verifier 123!')
        valid = verify_password(row['verifier'] if row else self._dummy, password)
        replacement = HASHER.hash(password) if valid and row and (not row['verifier'].startswith('$argon2id$') or HASHER.check_needs_rehash(row['verifier'])) else None
        with self.connection(True) as db:
            blocked = db.execute('SELECT * FROM login_limits WHERE client=?', (client_key,)).fetchone()
            if blocked and blocked['until_time'] > self.clock():
                raise AuthError('temporarily_throttled', 429)
            current = db.execute('SELECT * FROM users WHERE id=?', (row['id'],)).fetchone() if row else None
            pending_reset = db.execute("SELECT 1 FROM one_time WHERE purpose IN ('reset','recovery') AND user_id=? AND consumed=0", (current['id'],)).fetchone() if current else None
            if not valid or pending_reset or not current or not current['enabled'] or current['credential_version'] != row['credential_version']:
                failures = (blocked['failures'] if blocked else 0) + 1
                db.execute('INSERT INTO login_limits VALUES(?,?,?) ON CONFLICT(client) DO UPDATE SET failures=excluded.failures,until_time=excluded.until_time', (client_key, failures if failures < 5 else 0, now + 30 if failures >= 5 else 0))
                self._audit(db, None, 'session.login_denied')
                error = AuthError('invalid_credentials', 401)
            else:
                db.execute('DELETE FROM login_limits WHERE client=?', (client_key,))
                if replacement:
                    db.execute('UPDATE users SET verifier=? WHERE id=?', (replacement, current['id']))
                db.execute('UPDATE users SET last_login=? WHERE id=?', (now, current['id']))
                policy = db.execute('SELECT * FROM policy').fetchone()
                token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                key = digest(token)
                db.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?,?)', (key, current['id'], current['credential_version'], digest(csrf), now, now, now + policy['absolute']))
                principal = Principal(current['id'], current['username'], current['display_name'], current['role'], key)
                self._audit(db, principal, 'session.login', current['id'])
                error = None
        if error:
            raise error
        return principal, token, csrf

    def session(self, token):
        if not isinstance(token, str) or not 20 <= len(token) <= 128:
            raise AuthError('authentication_required', 401)
        key, now = digest(token), self.clock()
        with self.connection() as db:
            row = db.execute('SELECT s.*,u.username,u.display_name,u.role,u.enabled,u.credential_version AS actual_version,p.idle,p.absolute FROM sessions s JOIN users u ON s.user_id=u.id JOIN policy p ON p.id=1 WHERE s.id=?', (key,)).fetchone()
        if not row or not row['enabled'] or row['credential_version'] != row['actual_version'] or min(row['expires'], row['created'] + row['absolute']) <= now or row['seen'] + row['idle'] <= now:
            raise AuthError('authentication_required', 401)
        if now - row['seen'] >= 60:
            with self.connection(True) as db:
                db.execute('UPDATE sessions SET seen=? WHERE id=? AND seen<?', (now, key, now - 60))
        return Principal(row['user_id'], row['username'], row['display_name'], row['role'], key)

    def csrf(self, principal, offered):
        if not isinstance(offered, str) or len(offered) > 128:
            raise AuthError('csrf_required', 403)
        with self.connection() as db:
            row = db.execute('SELECT csrf FROM sessions WHERE id=? AND user_id=?', (principal.session_id, principal.id)).fetchone()
        if not row or not hmac.compare_digest(row['csrf'], digest(offered)):
            raise AuthError('csrf_required', 403)

    def logout(self, principal, all_sessions=False):
        with self.connection(True) as db:
            if all_sessions:
                db.execute('DELETE FROM sessions WHERE user_id=?', (principal.id,))
            else:
                db.execute('DELETE FROM sessions WHERE id=? AND user_id=?', (principal.session_id, principal.id))
            self._audit(db, principal, 'session.logout_all' if all_sessions else 'session.logout', principal.id)

    def revoke(self, actor, identity):
        require(actor, 'accounts')
        with self.connection(True) as db:
            self._authorize(db, actor, 'accounts')
            db.execute('DELETE FROM sessions WHERE user_id=?', (identity,))
            self._audit(db, actor, 'session.revoke', identity)

    def change_password(self, principal, current_password, new_password):
        with self.connection() as db:
            row = db.execute('SELECT * FROM users WHERE id=?', (principal.id,)).fetchone()
        if not row or not verify_password(row['verifier'], current_password):
            raise AuthError('invalid_credentials', 401)
        verifier = password_hash(new_password)
        with self.connection(True) as db:
            self._authorize(db, principal, 'profile')
            changed = db.execute('UPDATE users SET verifier=?,credential_version=credential_version+1,revision=revision+1 WHERE id=? AND credential_version=?', (verifier, principal.id, row['credential_version'])).rowcount
            if changed != 1:
                raise AuthError('stale_user', 409)
            db.execute('DELETE FROM sessions WHERE user_id=?', (principal.id,))
            self._audit(db, principal, 'password.change', principal.id)

    def sessions(self, principal):
        with self.connection() as db:
            return [dict(id=row['id'], created=row['created'], seen=row['seen'], expires=row['expires'], current=row['id'] == principal.session_id) for row in db.execute('SELECT * FROM sessions WHERE user_id=? ORDER BY created', (principal.id,))]

    def me(self, principal):
        with self.connection() as db:
            self._authorize(db, principal, 'profile')
            return public(db.execute('SELECT * FROM users WHERE id=?', (principal.id,)).fetchone()) | principal.snapshot()

    def policy(self, actor):
        require(actor, 'accounts')
        with self.connection() as db:
            self._authorize(db, actor, 'accounts')
            return dict(db.execute('SELECT idle,absolute,revision FROM policy WHERE id=1').fetchone())

    def update_policy(self, actor, revision, idle, absolute):
        require(actor, 'accounts')
        if type(idle) is not int or type(absolute) is not int or not 300 <= idle <= 28800 or not 3600 <= absolute <= 86400 or idle > absolute:
            raise AuthError('invalid_session_policy')
        with self.connection(True) as db:
            self._authorize(db, actor, 'accounts')
            before = dict(db.execute('SELECT * FROM policy WHERE id=1').fetchone())
            if before['revision'] != revision:
                raise AuthError('stale_policy', 409)
            db.execute('UPDATE policy SET idle=?,absolute=?,revision=revision+1 WHERE id=1', (idle, absolute))
            result = dict(db.execute('SELECT idle,absolute,revision FROM policy WHERE id=1').fetchone())
            self._audit(db, actor, 'policy.update', before=before, after=result)
            return result

    def logout_others(self, principal):
        with self.connection(True) as db:
            self._authorize(db, principal, 'profile')
            db.execute('DELETE FROM sessions WHERE user_id=? AND id<>?', (principal.id, principal.session_id))
            self._audit(db, principal, 'session.logout_others', principal.id)

    def profile(self, principal, display_name, revision):
        if not isinstance(display_name, str) or not 1 <= len(display_name.strip()) <= 120:
            raise AuthError('invalid_profile')
        with self.connection(True) as db:
            self._authorize(db, principal, 'profile')
            row = db.execute('SELECT * FROM users WHERE id=?', (principal.id,)).fetchone()
            if row['revision'] != revision:
                raise AuthError('stale_user', 409)
            db.execute('UPDATE users SET display_name=?,revision=revision+1 WHERE id=?', (display_name.strip(), principal.id))
            result = public(db.execute('SELECT * FROM users WHERE id=?', (principal.id,)).fetchone())
            self._audit(db, principal, 'profile.update', principal.id, public(row), result)
            return result

    def issue_reset(self, actor, identity, revision):
        require(actor, 'accounts')
        if identity == actor.id:
            raise AuthError('use_own_password_change')
        code = secrets.token_urlsafe(32)
        now = self.clock()
        with self.connection(True) as db:
            self._authorize(db, actor, 'accounts')
            row = db.execute('SELECT * FROM users WHERE id=?', (identity,)).fetchone()
            if not row:
                raise AuthError('user_not_found', 404)
            if row['revision'] != revision:
                raise AuthError('stale_user', 409)
            db.execute("UPDATE one_time SET consumed=1 WHERE purpose='reset' AND user_id=?", (identity,))
            db.execute("INSERT INTO one_time(id,purpose,user_id,verifier,created,expires) VALUES(?,'reset',?,?,?,?)", (uuid4().hex, identity, digest(code), now, now + 900))
            db.execute('DELETE FROM sessions WHERE user_id=?', (identity,))
            db.execute('UPDATE users SET credential_version=credential_version+1,revision=revision+1 WHERE id=?', (identity,))
            self._audit(db, actor, 'password.reset_requested', identity)
        return dict(code=code, expires=now + 900)

    def complete_reset(self, code, password, client):
        if not isinstance(code, str) or not 20 <= len(code) <= 128:
            raise AuthError('invalid_reset', 401)
        client_key = digest('reset:' + str(client)[:256])
        now = self.clock()
        with self.connection() as db:
            blocked = db.execute('SELECT * FROM login_limits WHERE client=?', (client_key,)).fetchone()
            if blocked and blocked['until_time'] > now:
                raise AuthError('temporarily_throttled', 429)
        verifier = password_hash(password)
        with self.connection(True) as db:
            blocked = db.execute('SELECT * FROM login_limits WHERE client=?', (client_key,)).fetchone()
            if blocked and blocked['until_time'] > now:
                raise AuthError('temporarily_throttled', 429)
            row = db.execute("SELECT * FROM one_time WHERE purpose='reset' AND verifier=?", (digest(code),)).fetchone()
            if not row or row['consumed'] or row['expires'] <= now:
                blocked = db.execute('SELECT * FROM login_limits WHERE client=?', (client_key,)).fetchone()
                failures = (blocked['failures'] if blocked else 0) + 1
                db.execute('INSERT INTO login_limits VALUES(?,?,?) ON CONFLICT(client) DO UPDATE SET failures=excluded.failures,until_time=excluded.until_time', (client_key, failures if failures < 5 else 0, now + 30 if failures >= 5 else 0))
                error = AuthError('invalid_reset', 401)
            else:
                db.execute('UPDATE one_time SET consumed=1 WHERE id=?', (row['id'],))
                db.execute('UPDATE users SET verifier=?,credential_version=credential_version+1,revision=revision+1 WHERE id=?', (verifier, row['user_id']))
                db.execute('DELETE FROM sessions WHERE user_id=?', (row['user_id'],))
                db.execute('DELETE FROM login_limits WHERE client=?', (client_key,))
                self._audit(db, None, 'password.reset_completed', row['user_id'])
                error = None
        if error:
            raise error
