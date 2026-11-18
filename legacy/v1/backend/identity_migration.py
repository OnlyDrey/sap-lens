"""Versioned, stopped-store migration of legacy local accounts.

Never rewrites old credentials, settings or evidence. An encrypted, verified
logical recovery snapshot precedes the one atomic security-directory activation.
Shared-access installations require a local operator's explicit recovery identity.
"""
from contextlib import closing
from dataclasses import replace
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import sys
from uuid import uuid4

from auth_store import AuthError,AuthStore,public,password_hash
from auth_provisioning import prepare,state,issue
import maintenance as engine

FOLDER=Path('.application-backups/identity-migration')


def effective(settings):
    """Every server factory has sessions; old configuration is migration input only."""
    return replace(settings,auth='sessions',secret=settings.secret if settings.proxies else '')


def root_for(data):
    root=Path(data)/FOLDER
    if any(engine.linked(p) for p in (root,*root.parents)):raise AuthError('linked_migration_path',503)
    return root


def records(data):
    root=root_for(data)
    if not root.exists():return []
    result=[]
    for folder in sorted(root.iterdir()):
        path=folder/'record.json'
        if len(folder.name)!=32 or any(c not in '0123456789abcdef' for c in folder.name) or engine.linked(folder):continue
        if not path.exists():continue
        if engine.linked(path) or path.stat().st_size>32000:raise AuthError('migration_record_invalid',503)
        row=json.loads(path.read_bytes())
        if row.get('schema')!=1 or row.get('id')!=folder.name:raise AuthError('migration_record_invalid',503)
        result.append(row)
    return result


def write(operation,record):
    from config import atomic_write
    atomic_write(operation/'record.json',json.dumps(record,sort_keys=True).encode('utf-8'))


def new_store(path,legacy,new_administrator):
    store=AuthStore(path);store.initialize()
    with store.connection(True) as db:
        now=store.clock()
        if legacy is not None:
            for username,row in legacy['users'].items():
                role='viewer' if row['role']=='read-only' else row['role']
                verifier='pbkdf2:'+json.dumps({key:row[key] for key in ('salt','hash','iterations')},sort_keys=True,separators=(',',':'))
                identity=uuid4().hex
                db.execute('INSERT INTO users(id,username,display_name,role,enabled,verifier,created) VALUES(?,?,?,?,?,?,?)',(identity,username,username,role,int(row['enabled']),verifier,now))
                store._audit(db,None,'migration.account',identity,after=public(db.execute('SELECT * FROM users WHERE id=?',(identity,)).fetchone()))
        else:
            store.validate_profile(new_administrator,new_administrator,'administrator')
            identity=uuid4().hex
            # Unknown random password is never displayed or persisted. Local
            # recovery is mandatory; no shared/known credential is converted.
            verifier=password_hash(secrets.token_urlsafe(48))
            db.execute("INSERT INTO users(id,username,display_name,role,enabled,verifier,created) VALUES(?,?,?,'administrator',1,?,?)",(identity,new_administrator,new_administrator,verifier,now))
        db.execute("UPDATE meta SET value='1' WHERE key='initialized'")
        db.execute("INSERT INTO meta VALUES('legacy_migration','1')")
        store._audit(db,None,'migration.prepared')
    recovery=issue(store,new_administrator) if legacy is None else None
    with closing(sqlite3.connect(path)) as db:db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    return store,recovery


def activate_verified(data,operation,record,account_file=''):
    from portable_backups import validate_identity
    working=operation/'new-security';candidate=working/'accounts.sqlite3'
    archive=operation/'pre-identity.slbak'
    if engine.linked(working) or engine.linked(candidate) or engine.linked(archive) or not archive.is_file() or not candidate.is_file():raise AuthError('migration_recovery_required',503)
    if engine.digest(candidate)!=record.get('staged_sha256') or engine.digest(archive)!=record.get('sha256'):raise AuthError('migration_recovery_required',503)
    validate_identity(candidate)
    staged=AuthStore(candidate)
    with staged.connection() as db:marker=db.execute("SELECT value FROM meta WHERE key='migration_id'").fetchone()
    if not marker or marker[0]!=record['id']:raise AuthError('migration_activation_mismatch',503)
    if record['source']=='users':
        from server_access import account_write_lock
        path=Path(account_file)
        if not path.is_absolute() or any(engine.linked(p) for p in (path,*path.parents)):raise AuthError('legacy_accounts_unavailable',503)
        with account_write_lock(path):
            if engine.digest(path)!=record.get('legacy_sha256'):raise AuthError('legacy_accounts_changed',409)
            os.replace(working,data/'security')
    else:os.replace(working,data/'security')
    try:
        store=AuthStore(data/'security/accounts.sqlite3');state(store);validate_identity(store.path)
        record['status']='migrated';write(operation,record)
    except BaseException:
        os.replace(data/'security',working)
        raise


def migrate(lease,legacy_auth,account_file='',new_administrator=''):
    from storage_lease import StorageLease
    import backup_crypto as crypto
    from portable_backups import archive,validate_identity
    if not isinstance(lease,StorageLease) or not lease.stream or lease.stream.closed or lease.mode!='server':raise AuthError('stopped_server_lease_required',409)
    data=lease.directory.resolve();store=AuthStore(data/'security/accounts.sqlite3')
    store._safe()
    if store.path.exists():
        state(store)
        # A crash after atomic activation but before recording completion is
        # reconciled using the exact activated database digest, never recreated.
        for record in records(data):
            if record['status']=='backup_verified':
                with store.connection() as db:marker=db.execute("SELECT value FROM meta WHERE key='migration_id'").fetchone()
                backup=root_for(data)/record['id']/'pre-identity.slbak'
                if not marker or marker[0]!=record['id'] or engine.linked(backup) or not backup.is_file() or engine.digest(backup)!=record.get('sha256'):raise AuthError('migration_activation_mismatch',503)
                record['status']='migrated';write(root_for(data)/record['id'],record)
        return dict(state='existing',recovery=None)
    if (data/'security').exists():raise AuthError('security_store_unavailable',503)
    pending=[row for row in records(data) if row['status']=='backup_verified']
    if pending:
        if len(pending)!=1 or pending[0]['source']!=legacy_auth:raise AuthError('migration_recovery_required',503)
        record=pending[0];activate_verified(data,root_for(data)/record['id'],record,account_file)
        return dict(state='migrated',id=record['id'],recovery=None)
    # A new empty store may provision once; populated roots never reopen setup.
    allowed={'.sap-lens-instance.lock','deployment.json'}
    if legacy_auth!='users' and not any(p.name not in allowed for p in data.iterdir()):
        prepare(data);return dict(state='fresh',recovery=None)
    if legacy_auth!='users' and not new_administrator:raise AuthError('local_identity_migration_required',503)
    legacy=None
    if legacy_auth=='users':
        from server_access import read_accounts,account_write_lock
        path=Path(account_file)
        if not path.is_absolute() or any(engine.linked(p) for p in (path,*path.parents)):raise AuthError('legacy_accounts_unavailable',503)
        # Cooperate with the old elevated writer; digest is rechecked immediately
        # before activation, so unrelated processes cannot silently change scope.
        with account_write_lock(path):
            legacy=read_accounts(path);original=engine.digest(path)
    host=crypto.host_key(data) # No changes or plaintext recovery archive without a key.
    operation=root_for(data)/uuid4().hex;operation.mkdir(mode=0o700,parents=True)
    identifier=operation.name
    record=dict(schema=1,id=identifier,status='preparing',created=datetime.now(timezone.utc).isoformat(),source=legacy_auth,from_schema=0,to_schema=1)
    write(operation,record)
    working=operation/'new-security'
    try:
        converted,recovery=new_store(working/'accounts.sqlite3',legacy,new_administrator)
        with converted.connection(True) as db:db.execute("INSERT INTO meta VALUES('migration_id',?)",(identifier,))
        with closing(sqlite3.connect(converted.path)) as db:db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        # The backup has the exact new UUID/verifier mapping plus all original
        # portable business data; the old account file remains byte-for-byte.
        result=archive(data,operation,lease,crypto.plan(identifier,host),host,operation/'pre-identity.slbak',identity_source=converted.path)
        validate_identity(converted.path)
        record.update(status='backup_verified',sha256=result['sha256'],accounts=result['manifest']['portable']['identity']['accounts'],staged_sha256=engine.digest(converted.path),legacy_sha256=original if legacy is not None else '')
        write(operation,record)
        activate_verified(data,operation,record,account_file)
        return dict(state='migrated',id=identifier,recovery=recovery)
    except BaseException:
        record['status']='failed';write(operation,record)
        raise
    finally:
        # Only this explicitly created, private staging directory is removed.
        # Encrypted archive and failed record stay available to the operator.
        if working.exists():shutil.rmtree(working)


def status(data):
    return dict(items=[{key:row[key] for key in ('id','status','created','source','from_schema','to_schema') if key in row}|dict(backup_available=(root_for(data)/row['id']/'pre-identity.slbak').is_file()) for row in records(data)])


def confirm(data,identifier,actor,*,delete=False):
    store=AuthStore(Path(data)/'security/accounts.sqlite3')
    # The account writer transaction prevents concurrent role/session revocation
    # from racing an authorized destructive archive operation.
    with store.connection(True) as db:
        store._authorize(db,actor,'accounts')
        row=next((row for row in records(data) if row['id']==identifier),None)
        if not row or row['status'] not in ({'confirmed'} if delete else {'migrated'}):raise AuthError('migration_confirmation_required',409)
        operation=root_for(data)/identifier;archive=operation/'pre-identity.slbak'
        if engine.linked(archive) or not archive.is_file() or engine.digest(archive)!=row['sha256']:raise AuthError('migration_backup_integrity_failed',409)
        if delete:
            archive.unlink();row['status']='deleted'
        else:
            from portable_backups import validate_identity
            validate_identity(store.path)
            row['status']='confirmed'
        row['confirmed_by']=actor.snapshot()
        write(operation,row)
        store._audit(db,actor,'migration.backup_deleted' if delete else 'migration.confirmed',identifier)
    return status(data)


def cli(argv):
    import argparse
    from storage_lease import StorageLease
    parser=argparse.ArgumentParser(description='Stopped local identity migration; preserve and escrow the host backup key first.')
    parser.add_argument('--data-directory',required=True,type=Path)
    parser.add_argument('--legacy-auth',choices=['users','local','basic','proxy'],required=True)
    parser.add_argument('--legacy-accounts',default='')
    parser.add_argument('--new-administrator',default='')
    args=parser.parse_args(argv)
    try:
        data=engine.directory(args.data_directory)
        lease=StorageLease(data,'server').acquire()
        try:result=migrate(lease,args.legacy_auth,args.legacy_accounts,args.new_administrator)
        finally:lease.close()
        print(json.dumps(result)) # A newly issued local recovery code is displayed once, never logged.
        return 0
    except (ValueError,OSError,RuntimeError):
        print('Identity migration refused. Preserve existing data; verify the stopped runtime, legacy accounts, protected external backup key and migration diagnostics.',file=sys.stderr)
        return 1
