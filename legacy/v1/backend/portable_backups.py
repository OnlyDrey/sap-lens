"""Complete portable-state staging; canonical maintenance owns archive validation.

Called with the stopped runtime lease. Authentication uses SQLite's snapshot API;
all other authoritative state is copied while application writers are stopped.
"""
import base64
from contextlib import closing, contextmanager
import json
from pathlib import Path
import secrets
import shutil
import sqlite3
import time

import maintenance as engine
from auth_store import SCHEMA
from version import VERSION

HOST_ONLY={'backup-key-location.json','.backup-key-confirmation.json'}
AUTH_TABLES={'meta','users','sessions','policy','audit','login_limits','one_time'}


def validate_identity(path, *, portable=False):
    """Reject unsupported/malformed executable SQLite schema before activation."""
    from auth_store import AuthError, AuthStore
    from argon2 import extract_parameters
    from argon2.low_level import Type
    store=AuthStore(Path(path))
    try:
        with store.connection() as db:
            if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError()
            objects=list(db.execute("SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
            if any(row['type'] not in {'table','index'} for row in objects):raise ValueError()
            if {row['name'] for row in objects if row['type']=='table'}!=AUTH_TABLES:raise ValueError()
            if db.execute("SELECT value FROM meta WHERE key='initialized'").fetchone()[0]!='1':raise ValueError()
            users=list(db.execute('SELECT * FROM users'))
            if not users or not any(row['role']=='administrator' and row['enabled']==1 for row in users):raise ValueError()
            ids=set()
            for row in users:
                store.validate_profile(row['username'],row['display_name'],row['role'])
                if len(row['id'])!=32 or any(c not in '0123456789abcdef' for c in row['id']) or row['id'] in ids:raise ValueError()
                ids.add(row['id'])
                if row['enabled'] not in {0,1} or row['revision']<0 or row['credential_version']<0:raise ValueError()
                verifier=row['verifier']
                if verifier.startswith('pbkdf2:'):
                    legacy=json.loads(verifier[7:])
                    if legacy['iterations']!=600_000 or any(len(base64.b64decode(legacy[key],validate=True))!=32 for key in ('salt','hash')):raise ValueError()
                else:
                    params=extract_parameters(verifier)
                    if params.type!=Type.ID or params.version!=19 or not 16384<=params.memory_cost<=262144 or not 1<=params.time_cost<=8 or not 1<=params.parallelism<=8 or not 16<=params.salt_len<=64 or not 32<=params.hash_len<=64:raise ValueError()
            if portable:
                if db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] or db.execute('SELECT COUNT(*) FROM login_limits').fetchone()[0]:raise ValueError()
                if db.execute('SELECT COUNT(*) FROM one_time WHERE consumed<>0 OR purpose NOT IN (\'reset\',\'recovery\') OR expires<>0 OR attempts<5').fetchone()[0]:raise ValueError()
    except (AuthError,sqlite3.Error,ValueError,TypeError,KeyError,OverflowError):
        raise engine.MaintenanceError('Portable account storage is invalid or incompatible. Existing accounts were preserved.') from None
    return dict(schema=SCHEMA,accounts=len(users),administrators=sum(row['role']=='administrator' and row['enabled']==1 for row in users))


def snapshot_identity(source,destination):
    # Caller has the runtime lease; other local administration commands can still
    # briefly hold a SQLite transaction. SQLite backup is consistent and bounded.
    deadline=time.monotonic()+30
    def progress(status,remaining,total):
        if time.monotonic()>deadline:raise engine.MaintenanceError('Account snapshot exceeded its database deadline.')
    source=Path(source);destination=Path(destination)
    from auth_store import AuthStore
    AuthStore(source)._safe()
    if engine.linked(destination) or destination.exists():raise engine.MaintenanceError('Choose an unused account snapshot.')
    destination.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    try:
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True,timeout=5)) as original:
            with closing(sqlite3.connect(destination,timeout=5)) as copied:
                engine.private_file(destination)
                original.backup(copied,pages=128,progress=progress,sleep=0.05)
                copied.execute('DELETE FROM sessions');copied.execute('DELETE FROM login_limits')
                # Retain reset-required markers while making EVERY original code
                # unusable. Old passwords must never become valid after restore.
                copied.execute("DELETE FROM one_time WHERE consumed<>0 OR purpose NOT IN ('reset','recovery')")
                for row in copied.execute('SELECT id FROM one_time').fetchall():
                    copied.execute('UPDATE one_time SET verifier=?,expires=0,attempts=5 WHERE id=?',(secrets.token_hex(32),row[0]))
                copied.commit();copied.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        return validate_identity(destination,portable=True)
    except BaseException:
        destination.unlink(missing_ok=True)
        for suffix in ('-wal','-shm'):Path(str(destination)+suffix).unlink(missing_ok=True)
        raise


def clear_transferred_capabilities(path):
    # Validation is before any mutation, including SQLite journal/schema handling.
    validate_identity(path,portable=True)
    with closing(sqlite3.connect(path,timeout=5)) as db:
        db.execute('DELETE FROM sessions');db.execute('DELETE FROM login_limits')
        db.commit()


@contextmanager
def stage(data,operation,lease,server=None,*,identity_source=None):
    from application_backups import protected, validate_store
    from storage_lease import StorageLease
    data=engine.directory(data)
    if not isinstance(lease,StorageLease) or not lease.stream or lease.stream.closed or lease.directory.resolve()!=data:raise engine.MaintenanceError('A stopped application storage lease is required.')
    root=Path(operation)/'portable-state'
    if root.exists() or engine.linked(root):raise engine.MaintenanceError('Portable staging already exists; preserve it for recovery.')
    root.mkdir(mode=0o700)
    exclusions=protected(data,server)|HOST_ONLY
    try:
        for source in engine.walk_files(data,exclusions-{'deployment.json'}):
            target=root/source.relative_to(data)
            target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            shutil.copyfile(source,target);engine.private_file(target)
        # Scheduling is portable configuration, unlike installation-bound history/approval.
        from backup_schedule import settings as schedule_settings
        from application_backups import write
        schedule=schedule_settings(data)
        write(root/'backup-schedule.json',dict(revision=schedule['revision'],schedule=schedule['schedule']))
        identity=None
        source_identity=identity_source or data/'security/accounts.sqlite3'
        if Path(source_identity).exists():
            identity=snapshot_identity(source_identity,root/'security/accounts.sqlite3')
        validate_store(root,exclude={'security'})
        components=sorted({p.relative_to(root).parts[0] for p in engine.walk_files(root)})
        manifest=dict(format=2,application_version=VERSION,identity=identity,components=components,
                      excluded=['active sessions','one-time codes','TLS private keys','service credentials','host bindings','runtime locks','rebuildable cache','backup recovery keys'],
                      cache='rebuildable-not-exported')
        staged_lease=StorageLease(root,lease.mode).acquire()
        try:yield root,staged_lease,manifest
        finally:staged_lease.close()
    finally:
        # Private staging contains the same sensitive state as the active store;
        # never publish it as a portable/downloadable artifact.
        shutil.rmtree(root)


def archive(data,operation,lease,plan,host,output,server=None,*,identity_source=None):
    import backup_crypto as crypto
    from application_backups import manifest as read_manifest
    key,header=crypto.unwrap(Path(operation).name,plan,host)
    raw=Path(operation)/'portable-plaintext.tar.gz'
    verified=Path(operation)/'portable-verification.tar.gz'
    if raw.exists() or verified.exists():raise engine.MaintenanceError('An interrupted archive needs recovery before retry.')
    try:
        with stage(data,operation,lease,server,identity_source=identity_source) as (root,staged_lease,components):
            engine.backup(root,raw,lease.mode,VERSION,_lease=staged_lease,_exclude={'.sap-lens-instance.lock'},_manifest_extra={'portable':components})
            read_manifest(raw)
        crypto.seal(raw,output,key,header)
        crypto.unseal(output,verified,key=key)
        result=read_manifest(verified)
        if engine.digest(raw)!=engine.digest(verified):raise engine.MaintenanceError('Encrypted archive round-trip verification failed.')
        return dict(sha256=engine.digest(output),manifest=result,encryption='AES-256-GCM',key_mode=header['key_mode'])
    finally:
        raw.unlink(missing_ok=True);verified.unlink(missing_ok=True)


@contextmanager
def readable(archive,data=None,secret='',allow_legacy=False):
    """Authenticate before invoking the canonical archive parser; no secret in argv."""
    import backup_crypto as crypto
    import tempfile
    archive=Path(archive)
    if engine.linked(archive):raise engine.MaintenanceError('Linked archives are not allowed.')
    with archive.open('rb') as stream:encrypted=stream.read(len(crypto.MAGIC))==crypto.MAGIC
    if not encrypted:
        if not allow_legacy:raise engine.MaintenanceError('Explicit --allow-legacy is required for an unencrypted archive.')
        yield archive,False
        return
    with tempfile.TemporaryDirectory(prefix='sap-lens-authenticated-archive-') as folder:
        path=Path(folder)/'verified.tar.gz'
        with archive.open('rb') as stream:header,_=crypto.envelope(stream)
        host=None
        if header['key_mode']=='host-key':host=crypto.decode(secret.strip(),32) if secret else crypto.host_key(data)
        crypto.unseal(archive,path,passphrase=secret,host=host)
        yield path,True


def backup_stopped(data,output,mode,allow_legacy=False):
    """Public offline backup uses exactly the same complete encrypted snapshot."""
    from uuid import uuid4
    import tempfile
    import backup_crypto as crypto
    data=engine.directory(data);output=Path(output)
    engine.directory(output.parent)
    if output.resolve().is_relative_to(data) or engine.linked(output):raise engine.MaintenanceError('Choose a dedicated backup location outside application data.')
    if output.exists():raise engine.MaintenanceError('Backup output already exists; never overwrite an archive.')
    host=crypto.host_key(data)
    if output.parent.resolve()==crypto.key_path(data).parent.resolve():raise engine.MaintenanceError('Store the encrypted archive separately from its host recovery key.')
    with engine.stopped(data,mode,allow_legacy) as lease:
        output.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='sap-lens-offline-backup-') as folder:
            operation=Path(folder)/uuid4().hex;operation.mkdir(mode=0o700)
            return archive(data,operation,lease,crypto.plan(operation.name,host),host,output)


def restore_empty(archive,data,mode,confirm=False,confirm_accounts=False,secret='',allow_legacy=False):
    """Empty-target only; in-app journal owns activation/rollback and account gates."""
    from application_backups import uploaded,register_upload,confirm_restore,startup,read
    from storage_lease import StorageLease
    import backup_crypto as crypto
    if not confirm:raise engine.MaintenanceError('Restore requires explicit --confirm-restore.')
    data=engine.directory(data)
    if data.exists() and any(data.iterdir()):raise engine.MaintenanceError('Restore only into an empty directory. Existing state is preserved.')
    crypto.host_key(data) # Fail before creating a destination or pausing anything.
    existed=data.exists()
    data.mkdir(mode=0o700,parents=True,exist_ok=True)
    try:
        with uploaded(data) as (identifier,incoming):
            shutil.copyfile(archive,incoming);engine.private_file(incoming)
            preview=register_upload(identifier,data,secret=secret,allow_legacy=allow_legacy)
    except BaseException:
        # A refused archive (wrong key, modified content, unsupported version) must leave the target as empty as it was, or the
        # next attempt is rejected as "not empty". Nothing was activated yet: only this call's own working folders exist, and
        # they are removed only when they hold no operation and nothing else is in the directory.
        work=data/'.application-backups'
        if set(p.name for p in data.iterdir())<={work.name} and not engine.linked(work):
            folders=[p for p in sorted(work.rglob('*'),reverse=True)] if work.is_dir() else []
            if all(p.is_dir() and not engine.linked(p) for p in folders):
                for folder in folders:folder.rmdir()
                if work.is_dir():work.rmdir()
                if not existed:data.rmdir()
        raise
    confirm_restore(identifier,preview['archive_sha256'],True,data,confirm_accounts=confirm_accounts)
    lease=StorageLease(data,mode).acquire()
    try:startup(lease)
    finally:lease.close()
    result=read(data)
    if result['status']!='completed':raise engine.MaintenanceError(result['message'])
    return dict(restored=True,mode=mode,accounts=preview['preview'].get('accounts'),sessions_invalidated=True)
