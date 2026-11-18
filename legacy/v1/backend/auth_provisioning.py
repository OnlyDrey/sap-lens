"""Explicit local activation, not an unauthenticated account recovery service.

Only a fresh data root is initialized. The API can consume a code but cannot
issue one. The local operator already needs write access to protected storage.
"""
import argparse
import json
from pathlib import Path
import secrets
import sys
from uuid import uuid4

from auth_store import AuthError, AuthStore, digest, password_hash, public


def prepare(data):
    store = AuthStore(Path(data) / 'security/accounts.sqlite3')
    store._safe()
    if not store.path.exists():
        # Called before any cache/migration/backup startup work. Unknown state is
        # an existing installation requiring migration, never an empty install.
        allowed = {'.sap-lens-instance.lock', 'deployment.json'}
        if any(p.name not in allowed for p in Path(data).iterdir()):
            raise AuthError('identity_migration_required', 503)
        store.initialize()
    state(store)  # Validate existing schema/metadata. Never recreate corruption.
    return store


def state(store):
    with store.connection() as db:
        marker = db.execute("SELECT value FROM meta WHERE key='initialized'").fetchone()
        count = db.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        if marker is None or marker[0] not in {'0', '1'} or (marker[0] == '0' and count):
            raise AuthError('security_state_invalid', 503)
        if marker[0] == '1':
            # Even if no usable administrator remains, only explicit local
            # recovery is permitted. A missing account never reopens setup.
            return dict(provider='local-sessions', setup_required=False)
        return dict(provider='local-sessions', setup_required=True)


def issue(store, username=None):
    """LOCAL administrative operation. Return the secret exactly once, no logs."""
    code, now = secrets.token_urlsafe(32), store.clock()
    with store.connection(True) as db:
        initialized = db.execute("SELECT value FROM meta WHERE key='initialized'").fetchone()[0]
        if username is None:
            if initialized != '0' or db.execute('SELECT COUNT(*) FROM users').fetchone()[0]:
                raise AuthError('bootstrap_closed', 409)
            purpose, identity = 'bootstrap', None
        else:
            if initialized != '1':
                raise AuthError('bootstrap_not_complete', 409)
            row = db.execute("SELECT * FROM users WHERE username=? AND role='administrator'", (username,)).fetchone()
            if not row:
                raise AuthError('administrator_recovery_unavailable', 409)
            purpose, identity = 'recovery', row['id']
            db.execute("UPDATE one_time SET consumed=1 WHERE purpose IN ('reset','recovery') AND user_id=?", (identity,))
            db.execute('DELETE FROM sessions WHERE user_id=?', (identity,))
            db.execute('UPDATE users SET credential_version=credential_version+1,revision=revision+1 WHERE id=?', (identity,))
        db.execute('UPDATE one_time SET consumed=1 WHERE purpose=?', (purpose,))
        db.execute('INSERT INTO one_time(id,purpose,user_id,verifier,created,expires) VALUES(?,?,?,?,?,?)', (uuid4().hex,purpose,identity,digest(code),now,now+900))
        store._audit(db, None, purpose+'.issued', identity or '')
    return dict(code=code, expires=now+900, purpose=purpose)


def complete(store, code, username, display_name, password, *, recovery=False):
    if not isinstance(code, str) or not 20 <= len(code) <= 128:
        raise AuthError('invalid_activation', 401)
    if not recovery:
        store.validate_profile(username, display_name, 'administrator')
    purpose = 'recovery' if recovery else 'bootstrap'
    with store.connection() as db:
        pending = db.execute('SELECT * FROM one_time WHERE purpose=? AND consumed=0 ORDER BY created DESC LIMIT 1', (purpose,)).fetchone()
        if not pending or pending['attempts'] >= 5 or pending['expires'] <= store.clock():
            raise AuthError('invalid_activation', 401)
    verifier = password_hash(password)
    error = None
    with store.connection(True) as db:
        marker = db.execute("SELECT value FROM meta WHERE key='initialized'").fetchone()[0]
        if not recovery and (marker != '0' or db.execute('SELECT COUNT(*) FROM users').fetchone()[0]):
            raise AuthError('bootstrap_closed', 409)
        row = db.execute('SELECT * FROM one_time WHERE purpose=? AND consumed=0 ORDER BY created DESC LIMIT 1', (purpose,)).fetchone()
        now = store.clock()
        valid = row and row['expires'] > now and row['attempts'] < 5
        if valid:
            import hmac
            valid = hmac.compare_digest(row['verifier'],digest(code))
        if not valid:
            if row:
                db.execute('UPDATE one_time SET attempts=attempts+1 WHERE id=?', (row['id'],))
            store._audit(db, None, purpose+'.rejected')
            error = AuthError('invalid_activation', 401)
        else:
            if recovery:
                user = db.execute("SELECT * FROM users WHERE id=? AND role='administrator'",(row['user_id'],)).fetchone()
                if marker != '1' or not user:
                    raise AuthError('administrator_recovery_unavailable', 409)
                identity = user['id']
                db.execute('UPDATE users SET verifier=?,enabled=1,revision=revision+1,credential_version=credential_version+1 WHERE id=?', (verifier,identity))
                db.execute('DELETE FROM sessions WHERE user_id=?', (identity,))
            else:
                identity = uuid4().hex
                db.execute("INSERT INTO users(id,username,display_name,role,enabled,verifier,created) VALUES(?,?,?,'administrator',1,?,?)", (identity,username,display_name.strip(),verifier,now))
                db.execute("UPDATE meta SET value='1' WHERE key='initialized'")
            db.execute('UPDATE one_time SET consumed=1 WHERE id=?', (row['id'],))
            result = public(db.execute('SELECT * FROM users WHERE id=?', (identity,)).fetchone())
            store._audit(db, None, purpose+'.completed', identity, after=result)
    if error:
        raise error
    return result


def cli(argv):
    parser = argparse.ArgumentParser(description='Local SAP Lens administrator activation; never send the displayed code to logs.')
    parser.add_argument('--data-directory', required=True, type=Path)
    parser.add_argument('--recover-administrator', metavar='USERNAME', help='Explicit local recovery for an existing administrator only')
    args = parser.parse_args(argv)
    try:
        # Startup must explicitly classify/prepare fresh state first. This CLI
        # never creates a new store against an operator-selected existing root.
        store = AuthStore(args.data_directory / 'security/accounts.sqlite3')
        result = issue(store, args.recover_administrator)
        print(json.dumps(result))
        return 0
    except (AuthError, OSError):
        print('Activation unavailable. Check protected storage, start the session server for a fresh installation, or complete the documented migration.', file=sys.stderr)
        return 1
