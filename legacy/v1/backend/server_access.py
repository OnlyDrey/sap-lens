"""Server-only individual accounts and conservative API permissions.

Account administration is local to the server, never an unauthenticated web API.
Passwords travel to the local administration command on stdin, not the command line.
"""
import base64
from contextvars import ContextVar
from contextlib import contextmanager
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time

ACTOR = ContextVar('sap_lens_actor', default='')
ROLES = {'administrator', 'reviewer', 'read-only'}
ITERATIONS = 600_000
_lock = threading.RLock()


def actor(fallback=''):
    from review_identity import name
    return name(ACTOR.get() or fallback)


def read_accounts(path):
    from deployment import check_secret_permissions
    path = Path(path)
    with path.open('rb') as stream:
        check_secret_permissions(path, os.fstat(stream.fileno()))
        raw = stream.read(131073)
    if len(raw) > 131072:
        raise ValueError('Account file is too large.')
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get('schema') != 1 or not isinstance(value.get('users'), dict) or len(value['users']) > 100:
        raise ValueError('Invalid account file.')
    for name, row in value['users'].items():
        if not re.fullmatch(r'[A-Za-z0-9_.@-]{1,100}', name) or not isinstance(row, dict):
            raise ValueError('Invalid account name.')
        if (row.get('role') not in ROLES or type(row.get('enabled')) is not bool
                or row.get('iterations') != ITERATIONS):
            raise ValueError('Invalid account policy.')
        if len(base64.b64decode(row['salt'], validate=True)) != 32 or len(base64.b64decode(row['hash'], validate=True)) != 32:
            raise ValueError('Invalid password hash.')
    if not any(row['enabled'] and row['role'] == 'administrator' for row in value['users'].values()):
        raise ValueError('At least one administrator must remain enabled.')
    return value


@contextmanager
def account_write_lock(path):
    """Kernel-owned, recoverable lock; unknown legacy presence locks stay blocked.

    Keep the recognized stub: unlinking after unlock can split waiting writers
    across different file identities. Old binaries fail closed on the stub.
    """
    lock_path=path.with_suffix('.lock');marker=b'SAP Lens account lock v2\n'
    if any(p.is_symlink() or p.is_junction() for p in (lock_path,*lock_path.parents)):raise ValueError('Linked account lock is unsafe.')
    deadline=time.monotonic()+5;stream=None;locked=False
    try:
        while True:
            try:
                descriptor=os.open(lock_path,os.O_CREAT|os.O_EXCL|os.O_RDWR,0o600)
                stream=os.fdopen(descriptor,'r+b')
                if os.name=='nt':
                    from windows_identity import make_private
                    make_private(lock_path)
                stream.write(marker+b'0');stream.flush();os.fsync(stream.fileno())
            except FileExistsError:
                if not lock_path.is_file() or lock_path.is_symlink() or lock_path.is_junction() or lock_path.stat().st_size>64:raise ValueError('Unrecognized account lock; inspect the stopped local manager.') from None
                stream=lock_path.open('r+b')
                if stream.read(len(marker))!=marker or os.fstat(stream.fileno()).st_size!=len(marker)+1:
                    stream.close();stream=None
                    if time.monotonic()>=deadline:raise ValueError('Account administration is busy; preserve and inspect its legacy lock.') from None
                    time.sleep(0.05);continue
            try:
                stream.seek(len(marker))
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                locked=True;break
            except OSError:
                stream.close();stream=None
                if time.monotonic()>=deadline:raise ValueError('Account administration is busy; inspect the local manager lock.') from None
                time.sleep(0.05)
        yield
    finally:
        if stream:
            if locked:
                stream.seek(len(marker))
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
            stream.close()


def manage_user(path, payload):
    """Called only by an elevated local manager. Preserve the last administrator."""
    path = Path(path)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError('Use an absolute, non-linked account path.')
    name = payload.get('username', '')
    role = payload.get('role', '')
    password = payload.get('password', '')
    enabled = payload.get('enabled', True)
    if not re.fullmatch(r'[A-Za-z0-9_.@-]{1,100}', name) or role not in ROLES or type(enabled) is not bool:
        raise ValueError('Invalid account.')
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock, account_write_lock(path):
        data = read_accounts(path) if path.exists() else {'schema': 1, 'users': {}}
        if password:
            if not isinstance(password, str) or not 14 <= len(password) <= 256 or ':' in name:
                raise ValueError('Use a password of 14–256 characters.')
            salt = secrets.token_bytes(32)
            row = dict(salt=base64.b64encode(salt).decode(), iterations=ITERATIONS,
                       hash=base64.b64encode(hashlib.pbkdf2_hmac('sha256', password.encode(), salt, ITERATIONS)).decode())
        elif name in data['users']:
            row = data['users'][name].copy()
        else:
            raise ValueError('A new account requires a password.')
        row.update(role=role, enabled=enabled)
        data['users'][name] = row
        if not any(r['enabled'] and r['role'] == 'administrator' for r in data['users'].values()):
            raise ValueError('At least one enabled administrator is required.')
        if len(data['users']) > 100:
            raise ValueError('At most 100 accounts are supported.')
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix='.accounts-', dir=path.parent)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(data, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)


def authenticate(path, header):
    try:
        scheme, encoded = header.split(' ', 1)
        if scheme.lower() != 'basic' or len(encoded) > 2048:
            return None
        username, password = base64.b64decode(encoded, validate=True).decode('utf-8').split(':', 1)
        try:
            data = read_accounts(path)
        except (ValueError, KeyError, TypeError, UnicodeError, OSError) as error:
            # No username, path, credential, hash or exception text in the log.
            logging.getLogger('sap-lens-server').warning('Account store unavailable; authentication refused (%s).', type(error).__name__)
            return None
        row = data['users'].get(username)
        # Unknown users take the same expensive password derivation path.
        salt = base64.b64decode(row['salt']) if row else b'\0' * 32
        expected = base64.b64decode(row['hash']) if row else b'\0' * 32
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, ITERATIONS)
        valid = hmac.compare_digest(expected, actual)
        return (username, row['role']) if valid and row and row['enabled'] else None
    except (ValueError, KeyError, TypeError, UnicodeError, OSError):
        return None


def may_access(role, method, path):
    if role == 'administrator':
        return True
    if method in {'GET', 'HEAD', 'OPTIONS'}:
        return True
    if method != 'POST':
        return False
    # Reports are read operations, despite POST bodies. Unknown writes fail closed.
    if path in {'/api/sod/reports/preview', '/api/sod/reports/pdf', '/api/sod/reports/docx',
                '/api/sod/reports/remediation/preview', '/api/sod/reports/remediation/pdf',
                '/api/sod/reports/remediation/csv', '/api/sod/simulate'}:
        return True
    return role == 'reviewer' and (bool(re.fullmatch(r'/api/account-review/decision/[^/]+', path))
        or bool(re.fullmatch(r'/api/sod/reviews/[^/]+', path))
        or bool(re.fullmatch(r'/api/sod/periods/[^/]+/reviews/[^/]+', path))
        or path in {'/api/sod/decisions/activity', '/api/sod/decisions/assignment',
                    '/api/sod/decisions/assignment/bulk', '/api/sod/decisions/acceptance', '/api/sod/decisions/risk',
                    '/api/sod/remediation/actions'})
