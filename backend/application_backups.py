"""Private Settings backup/restore, activated only at startup under the runtime lease.

The stopped-store maintenance engine remains canonical for archive integrity. No
HTTP request replaces a live store. Deployment secrets never travel with exports.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import threading
from uuid import uuid4

import maintenance as engine
from config import atomic_write, config_dir
from version import VERSION

lock = threading.RLock()
_secured=set()
MAX_UPLOAD = 256 * 1024 * 1024
ID = re.compile(r'^[a-f0-9]{32}$')
SECRET_SUFFIXES = {'.pem','.key','.pfx','.p12','.secret','.env','.crt','.cer'}
FORBIDDEN = {'.exe','.dll','.py','.pyc','.ps1','.sh','.bat','.cmd','.so'}


def stamp(): return datetime.now(timezone.utc).isoformat()


def area(data=None, *, create=True):
    configured=Path(data or config_dir()).expanduser()
    if not configured.is_absolute(): raise engine.MaintenanceError('Use an absolute application data directory.')
    # The configured runtime root may be an administrator-selected alias. Resolve
    # it once; archive/staging members and the private operation directory may not be links.
    data = engine.directory(configured.resolve())
    root = engine.directory(data / '.application-backups')
    if not create: return root
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    if os.name != 'nt': root.chmod(0o700)
    elif (str(root),root.stat().st_ino) not in _secured:
        import windows_identity
        try: windows_identity.make_private(root,inherit_children=True)
        except windows_identity.WindowsIdentityError as error: raise engine.MaintenanceError(f'Cannot make the backup area private: {error}') from error
        if len(_secured)>128: _secured.clear()
        _secured.add((str(root),root.stat().st_ino))
    return root


def path_for(identity, data=None):
    if not ID.fullmatch(identity): raise engine.MaintenanceError('Invalid backup operation.')
    path=area(data)/identity
    if engine.linked(path): raise engine.MaintenanceError('Backup operation cannot be a link.')
    return path


def write(path,value):
    atomic_write(path,(json.dumps(value,ensure_ascii=False,sort_keys=True)+'\n').encode())
    engine.private_file(path)


def journals(data=None):
    root=area(data,create=False)
    if not root.exists(): return []
    return [p/'journal.json' for p in root.iterdir() if ID.fullmatch(p.name) and not engine.linked(p) and (p/'journal.json').exists()]


def read(data=None):
    path=area(data,create=False)/'operation.json'
    if not path.exists():
        if journals(data): return dict(status='failed',recovery_required=True,message='Restore recovery requires an administrator restart. Editing remains paused to protect data.')
        return {'status':'idle'}
    try:
        if engine.linked(path) or path.stat().st_size>32000: raise ValueError('Invalid metadata')
        result=json.loads(path.read_text())
        if not isinstance(result,dict) or result.get('status') not in {'idle','pending','waiting_for_restart','preparing','creating','ready','completed','failed','cancelled'}: raise ValueError('Invalid state')
        if result.get('status')!='idle' and (not ID.fullmatch(result.get('id','')) or result.get('kind') not in {'backup','restore'}): raise ValueError('Invalid operation')
        if result.get('status')=='pending': result['status']='waiting_for_restart'
        if result.get('status')=='completed' and result.get('kind')=='backup': result['status']='ready'
        result.pop('recovery_required',None) # Derived from actual journals, never a persisted lock.
        if journals(data): result['recovery_required']=True
        if result.get('status')=='ready':
            archive=archive_path(path_for(result['id'],data),'backup',result)
            if engine.linked(archive) or not archive.is_file():
                result.update(status='failed',message='Backup archive is unavailable. No application data was changed; create a new backup or check storage permissions.')
        return result
    except (ValueError,TypeError,OSError):
        return dict(status='failed',recovery_required=bool(journals(data)),message='Backup operation metadata is unavailable or invalid. No new operation can replace an unfinished restore; retry status or ask an administrator to inspect storage permissions.')


def pending(data=None):
    state=read(data)
    return state.get('recovery_required',False) or state.get('status') in {'waiting_for_restart','preparing','creating'}


def protected(data, server=None):
    """Preserve security roots wholesale; reject credentials under a data subtree."""
    data=Path(data).resolve()
    roots={'backup-key-location.json','.backup-key-confirmation.json','deployment.json','.sap-lens-instance.lock','runtime.json','logs','.application-backups','cache','store','security'}
    values=[os.environ.get('SAP_LENS_AUTH_SECRET_FILE',''),os.environ.get('SAP_LENS_USERS_FILE','')]
    if server: values.extend([server.accounts,server.tls_cert,server.tls_key])
    values.extend(os.environ.get(key,'') for key in ('SAP_LENS_TLS_CERT_FILE','SAP_LENS_TLS_KEY_FILE'))
    for value in values:
        if value:
            candidate=Path(value).expanduser().resolve()
            if candidate.is_relative_to(data): roots.add(candidate.relative_to(data).parts[0])
    for item in engine.walk_files(data,{'.application-backups'}):
        if item.suffix.lower() in SECRET_SUFFIXES or item.name in {'.env','server.env','users.json','accounts.json'}:
            roots.add(item.relative_to(data).parts[0])
    return roots


def manifest(archive):
    # Bounded header read before canonical full archive verification.
    with tarfile.open(archive,'r:gz') as source:
        item=source.getmember('manifest.json')
        if not item.isfile() or item.size>16*1024*1024: raise engine.MaintenanceError('Invalid archive manifest.')
        header=json.load(source.extractfile(item))
    if header.get('mode') not in {'desktop','server'}: raise engine.MaintenanceError('Unsupported backup deployment mode.')
    verified=engine.verify(archive,header['mode'],VERSION)
    if not isinstance(verified.get('created_at'),str) or len(verified['created_at'])>64 or datetime.fromisoformat(verified['created_at']).tzinfo is None:
        raise engine.MaintenanceError('Invalid archive creation time.')
    return verified


def preview_data(header):
    files=header['files']; names=[name.removeprefix('data/') for name in files if name.startswith('data/')]
    return dict(source_mode=header['mode'],source_version=header['application_version'],created_at=header['created_at'],
                files=len(files),snapshots=sum('/snapshots/' in name for name in names),
                categories=sorted({name.split('/')[0] for name in names if name not in {'deployment.json','settings.json'}}),
                warning='Full replacement, not a merge. Source paths are retained for reference in Static mode; reconfigure before enabling Dynamic mode. Scheduling is disabled. Destination accounts, TLS and hosting remain unchanged.')


def idle_required(data=None):
    if pending(data): raise engine.MaintenanceError('A restart operation is already pending. Cancel it before another operation.')


def archive_path(operation,kind,state=None):
    state=state or {}
    return operation/(kind+('.slbak' if state.get('format')==2 else '.tar.gz'))


def request_backup(data=None, *, origin='manual', passphrase=''):
    with lock:
        idle_required(data)
        import backup_crypto as crypto
        host=crypto.host_key(data or config_dir())
        identity=uuid4().hex
        planned=crypto.plan(identity,host,passphrase)
        path_for(identity,data).mkdir(mode=0o700)
        result=dict(format=2,crypto_plan=planned,id=identity,kind='backup',origin=origin,status='waiting_for_restart',requested_at=stamp(),message='Waiting for restart: a stopped-store snapshot keeps datasets, review decisions and history consistent. Return to Backup & Restore after restarting to download the archive.')
        publish(result,data)
        return result


def publish(state,data=None):
    from backup_schedule import remember
    remember(state,data)
    write(area(data)/'operation.json',state)


def validate_store(root, exclude=()):
    """Validate typed stores, immutable digests and snapshot references before activation."""
    from config_models import AppConfig
    from sod_decisions import Storage
    from sod_periods import Index
    from sod_reviews import ReviewStorage
    from sod_catalogue import CatalogueStorage
    from assignment_lifecycle import Storage as LifecycleStorage
    from data_retention import Storage as RetentionStorage
    models={'settings.json':AppConfig,'sod-decisions.json':Storage,'sod-periods.json':Index,'sod-reviews.json':ReviewStorage,'sod-catalogue.json':CatalogueStorage,'assignment-lifecycle.json':LifecycleStorage,'data-retention.json':RetentionStorage}
    snapshots={}
    assets=set()
    parsed=[]
    for item in engine.walk_files(root,exclude):
        if engine.linked(item) or item.suffix.lower() in SECRET_SUFFIXES|FORBIDDEN or item.name in {'.env','server.env','users.json','accounts.json'}:
            raise engine.MaintenanceError('Archive contains security configuration or executable content; use an application-data backup.')
        if re.fullmatch(r'[a-f0-9]{64}',item.stem):
            if engine.digest(item)!=item.stem: raise engine.MaintenanceError('Immutable file digest does not match.')
            assets.add(item.stem)
        if item.parent.name=='branding':
            from branding import sanitize_image
            sanitize_image(item.read_bytes(),formats=frozenset({'PNG'}))
        if item.suffix=='.json':
            if item.stat().st_size>256*1024*1024: raise engine.MaintenanceError('Application record exceeds its supported limit.')
            raw=item.read_bytes();value=json.loads(raw)
            if re.fullmatch(r'[a-f0-9]{64}',item.stem):
                if hashlib.sha256(raw).hexdigest()!=item.stem: raise engine.MaintenanceError('Immutable snapshot digest does not match.')
                snapshots[item.stem]=value
            if item.parent==root and item.name in models: models[item.name].model_validate(value)
            if item.parent==root and item.name=='account-review.json':
                from account_review import validate_storage
                validate_storage(value)
            if item.parent==root and item.name=='functional-groups.json':
                from functional_groups import validate_storage as validate_groups
                try: validate_groups(value)
                except (ValueError,KeyError,TypeError): raise engine.MaintenanceError('Functional Group data is invalid or has broken references.') from None
            if item.parent.name=='employee-directory':
                from employee_directory import validate_snapshot
                validate_snapshot(value)
            if item.parent.name=='snapshots' and isinstance(value,dict) and value.get('source') in {'roles','users','sod'}:
                from csv_lifecycle import validate_source
                validate_source(value['source'],value)
            if item.name=='saved-filters.json':
                if not isinstance(value,dict) or value.get('schema_version')!=1 or not isinstance(value.get('items'),list) or len(value['items'])>250: raise engine.MaintenanceError('Unsupported saved-filter storage.')
                if any(not isinstance(row,dict) or any(key not in row for key in ('id','name','view','filters','filter_schema','created','modified')) for row in value['items']): raise engine.MaintenanceError('Invalid saved-filter definition.')
            if item.parent==root and item.name=='reviewer-profile.json':
                from review_identity import ActorSnapshot
                if value.get('version')!=1 or type(value.get('revision')) is not int or value['revision']<0:raise engine.MaintenanceError('Invalid local reviewer profile.')
                profile=ActorSnapshot.model_validate(value['identity'])
                if profile.provenance!='desktop-local':raise engine.MaintenanceError('A local profile cannot impersonate a server account.')
            if item.parent==root and item.name=='backup-schedule.json':
                from backup_schedule import Schedule
                Schedule.model_validate(value['schedule'])
                if type(value.get('revision')) is not int or value['revision']<0:raise engine.MaintenanceError('Invalid backup schedule.')
            if item.parent==root and item.name=='report-branding.json':
                if not isinstance(value,dict) or (value.get('logo_id') is not None and not re.fullmatch('[a-f0-9]{64}',str(value['logo_id']))):raise engine.MaintenanceError('Invalid report branding.')
            # Inactive configuration recovery copies may legitimately refer to
            # retired generations. Preserve them, but never activate their pointers.
            if item.relative_to(root).parts[0]!='configuration-backups': parsed.append(value)
    def references(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key in {'snapshot','evidence_snapshot','finding_snapshot','employee_snapshot_id'} and isinstance(item,str) and re.fullmatch('[a-f0-9]{64}',item) and item not in snapshots:
                    raise engine.MaintenanceError('Archive has a missing snapshot reference.')
                if key=='logo_id' and item and (item not in assets or not (root/'branding'/f'{item}.png').is_file()): raise engine.MaintenanceError('Archive has a missing branding asset.')
                if key=='snapshots' and isinstance(item,list) and any(isinstance(x,str) and re.fullmatch('[a-f0-9]{64}',x) and x not in snapshots for x in item): raise engine.MaintenanceError('Archive has missing historical snapshots.')
                references(item)
        elif isinstance(value,list):
            for item in value: references(item)
    for value in parsed: references(value)
    if (root/'settings.json').exists():
        settings=AppConfig.model_validate_json((root/'settings.json').read_bytes())
        from csv_lifecycle import validate_source
        import cache
        catalogue={}
        for source in ('roles','users','sod'):
            ref=settings.data_lifecycle.sources.get(source)
            if not ref: continue
            rows,report=validate_source(source,snapshots[ref.snapshot])
            if source=='roles': catalogue=cache._build_catalog(settings.data_csv_path,settings,records=rows,report=report).roles
            elif source=='users':
                profile=next(p for p in settings.user_import_profiles if p.id==settings.active_user_import)
                cache.build_users(settings.user_csv_path,profile,catalogue,records=rows,report=report)
            else:
                from sod_import import build_sod
                build_sod(rows,report)


def prepare(archive,operation,server=None,data=None, *, encrypted=False):
    header=manifest(archive)
    stage=operation/'stage'
    if stage.exists(): shutil.rmtree(stage)
    stage.mkdir(mode=0o700)
    engine.restore(archive,stage/'data',header['mode'],VERSION,config=stage/'config',confirm=True,_staging=True)
    root=stage/'data'
    portable=header.get('portable')
    if portable is not None and (not encrypted or portable.get('format')!=2):raise engine.MaintenanceError('Portable account/state backups require authenticated encryption.')
    accounts=bool(portable and portable.get('identity'))
    if accounts != (root/'security/accounts.sqlite3').is_file():raise engine.MaintenanceError('Account component inventory is inconsistent.')
    if accounts:
        from portable_backups import clear_transferred_capabilities,validate_identity
        files={p.relative_to(root/'security').as_posix() for p in engine.walk_files(root/'security')}
        if files!={'accounts.sqlite3'}:raise engine.MaintenanceError('Unsupported portable security files.')
        actual=validate_identity(root/'security/accounts.sqlite3',portable=True)
        if actual!=portable['identity']:raise engine.MaintenanceError('Account component metadata does not match its database.')
        clear_transferred_capabilities(root/'security/accounts.sqlite3')
    # Hosting credentials/keys are never activated; portable account state is an explicit component.
    source_protected=protected(root)-( {'security'} if accounts else set())
    for name in source_protected:
        candidate=root/name
        if candidate.is_dir(): shutil.rmtree(candidate)
        else: candidate.unlink(missing_ok=True)
    validate_store(root,{'security'} if accounts else ())
    destination=Path(data or config_dir())
    from config_models import AppConfig
    source=AppConfig.model_validate_json((root/'settings.json').read_bytes()) if (root/'settings.json').exists() else AppConfig()
    current=AppConfig.model_validate_json((destination/'settings.json').read_bytes()) if (destination/'settings.json').exists() else AppConfig()
    from backup_schedule import settings as schedule_settings,Schedule
    schedule_path=root/'backup-schedule.json'
    scheduled=json.loads(schedule_path.read_bytes()) if schedule_path.exists() else schedule_settings(destination)
    scheduled=dict(revision=scheduled['revision']+1,schedule=Schedule.model_validate(scheduled['schedule']).model_copy(update={'enabled':False}).model_dump())
    write(schedule_path,scheduled)
    source.desktop=current.desktop
    source.refresh_schedule=current.refresh_schedule.model_copy(update={'enabled':False})
    source.cors_origins=current.cors_origins
    for name in ('roles','users','employees','sod'): setattr(source.source_modes,name,'static')
    write(root/'settings.json',source.model_dump(mode='json'))
    # Protected destination subtrees cannot be replaced by source content.
    for name in protected(destination,server)-( {'security'} if accounts else set()):
        candidate=root/name
        if candidate.is_dir(): shutil.rmtree(candidate)
        else: candidate.unlink(missing_ok=True)
    return header,root


def register_upload(identity,data=None,server=None, *, secret='', allow_legacy=True):
    with lock:
        idle_required(data)
        operation=path_for(identity,data)
        import backup_crypto as crypto
        incoming=operation/'archive.tar.gz'
        with incoming.open('rb') as stream:encrypted=stream.read(len(crypto.MAGIC))==crypto.MAGIC
        canonical=incoming
        if encrypted:
            with incoming.open('rb') as stream:envelope,_=crypto.envelope(stream)
            host=None
            if envelope['key_mode']=='host-key':host=crypto.decode(secret.strip(),32) if secret else crypto.host_key(data or config_dir())
            canonical=operation/'validated.tar.gz'
            crypto.unseal(incoming,canonical,passphrase=secret,host=host)
        elif not allow_legacy:
            raise engine.MaintenanceError('Explicitly acknowledge importing a legacy unencrypted backup.')
        header,root=prepare(canonical,operation,server,data,encrypted=encrypted)
        result=dict(format=2 if encrypted else 1,encrypted=encrypted,id=identity,kind='restore',status='preview',preview=preview_data(header),archive_sha256=engine.digest(incoming),canonical_sha256=engine.digest(canonical))
        result['preview'].update(encrypted=encrypted,accounts=(header.get('portable') or {}).get('identity'),warning=('Account/password and application data rollback: explicit acknowledgement is required. Sessions are invalidated.' if (header.get('portable') or {}).get('identity') else 'Destination accounts remain unchanged.')+' Sources become Static and scheduling is disabled.')
        result['preview']['review_periods']=len(json.loads((root/'sod-periods.json').read_text()).get('items',[])) if (root/'sod-periods.json').exists() else 0
        stored=json.loads((root/'sod-decisions.json').read_text()) if (root/'sod-decisions.json').exists() else {}
        result['preview']['decision_events']=sum(len(events) for kinds in stored.get('contexts',{}).values() for subjects in kinds.values() for events in subjects.values())
        write(operation/'preview.json',result)
        shutil.rmtree(operation/'stage',ignore_errors=True)
        return result


def discard_upload(identity,data=None):
    """Discard only an inactive preview, never an active restore or recovery archive."""
    with lock:
        idle_required(data)
        operation=path_for(identity,data)
        preview=operation/'preview.json'
        if not preview.is_file() or engine.linked(preview) or any((operation/('destination-before-restore'+suffix)).exists() for suffix in ('.tar.gz','.slbak')):
            raise engine.MaintenanceError('Only an inactive staged restore can be cancelled.')
        shutil.rmtree(operation)
        return dict(status='cancelled',message='Restore preview cancelled. No application data was changed.')


def confirm_restore(identity,sha256,confirm,data=None, *, confirm_accounts=False):
    with lock:
        idle_required(data)
        operation=path_for(identity,data)
        result=json.loads((operation/'preview.json').read_text())
        if not confirm or sha256!=result['archive_sha256'] or engine.digest(operation/'archive.tar.gz')!=sha256: raise engine.MaintenanceError('Confirm the exact validated archive; it changed or was not confirmed.')
        if result['preview'].get('accounts') and not confirm_accounts:raise engine.MaintenanceError('Acknowledge account/password and data rollback before restoring.')
        # Verify the destination can create its encrypted recovery backup before pausing edits.
        import backup_crypto as crypto
        crypto.host_key(data or config_dir())
        result['confirm_accounts']=bool(confirm_accounts)
        result.update(status='waiting_for_restart',requested_at=stamp(),message='Restart required. Destination data will be backed up before full replacement; edits are paused until restart or cancellation.')
        publish(result,data)
        return result


def cancel(data=None):
    with lock:
        result=read(data)
        if result.get('recovery_required') or result.get('status') in {'preparing','creating'}:
            raise engine.MaintenanceError('An active or interrupted operation owns recovery; cancellation cannot release it.')
        if result.get('status')=='waiting_for_restart':
            result.update(status='cancelled',message='Operation cancelled; application data was not replaced.')
            publish(result,data)
            operation=path_for(result['id'],data)
            if result['kind']=='restore': shutil.rmtree(operation,ignore_errors=True)
        return result


def rollback(data,operation,journal):
    old=operation/'old';stage=operation/'stage'/'data'
    for name in journal['new']:
        current=data/name
        if not (stage/name).exists() and current.exists() and (name not in journal['old'] or (old/name).exists()):
            if current.is_dir(): shutil.rmtree(current)
            else: current.unlink()
    for name in journal['old']:
        if (old/name).exists(): os.replace(old/name,data/name)
    (operation/'journal.json').unlink(missing_ok=True)


def startup(lease,server=None):
    """Called before configuration/cache initialization or listener startup."""
    data=lease.directory.resolve();state=read(data)
    if not state.get('id'):
        if state.get('recovery_required'): raise RuntimeError('Restore journal exists without valid operation metadata; stopped host recovery is required.')
        return
    operation=path_for(state['id'],data)
    if any(path.parent!=operation for path in journals(data)):
        raise RuntimeError('An unmatched restore journal requires stopped host recovery before startup.')
    journal_path=operation/'journal.json'
    if state.get('status') in {'preparing','creating'} and not journal_path.exists():
        state.update(status='failed',message='Backup was interrupted. No application data was changed; you can safely retry.')
        publish(state,data)
        return
    if state.get('status')!='waiting_for_restart' and not journal_path.exists(): return
    try:
        if journal_path.exists():
            rollback(data,operation,json.loads(journal_path.read_text()))
            raise engine.MaintenanceError('Interrupted activation was rolled back; validate and confirm the archive again.')
        exclusions=protected(data,server)
        if state['kind']=='backup':
            state.update(status='creating',message='Creating and validating the backup archive before application startup.')
            publish(state,data)
            from backup_schedule import check_space
            check_space(data,exclusions-{'deployment.json'})
            from portable_backups import archive
            import backup_crypto as crypto
            if state.get('format')!=2 or not state.get('crypto_plan'):raise engine.MaintenanceError('Prepare this legacy pending backup again with encryption configured.')
            result=archive(data,operation,lease,state['crypto_plan'],crypto.host_key(data),operation/'backup.slbak',server)
            state.pop('crypto_plan',None)
            state.update(status='ready',verified=True,sha256=result['sha256'],encryption=result['encryption'],key_mode=result['key_mode'],message='Encrypted backup is ready to download. Keep the passphrase or separately escrowed recovery key available.')
        else:
            if engine.digest(operation/'archive.tar.gz')!=state['archive_sha256']: raise engine.MaintenanceError('Uploaded archive changed after confirmation.')
            canonical=operation/('validated.tar.gz' if state.get('encrypted') else 'archive.tar.gz')
            if engine.linked(canonical) or engine.digest(canonical)!=state.get('canonical_sha256'):raise engine.MaintenanceError('Validated restore staging changed.')
            header,root=prepare(canonical,operation,server,data,encrypted=state.get('encrypted',False))
            has_accounts=bool((header.get('portable') or {}).get('identity'))
            if has_accounts and not state.get('confirm_accounts'):raise engine.MaintenanceError('Account rollback was not acknowledged.')
            if has_accounts:exclusions.discard('security')
            if not (root/'reviewer-profile.json').exists():exclusions.add('reviewer-profile.json')
            from backup_schedule import check_space
            check_space(data,exclusions-{'deployment.json'})
            import backup_crypto as crypto
            from portable_backups import archive
            host=crypto.host_key(data)
            recovery_plan=crypto.plan(operation.name,host)
            recovery=archive(data,operation,lease,recovery_plan,host,operation/'destination-before-restore.slbak',server)
            state['recovery_sha256']=recovery['sha256']
            state['format']=2
            old=operation/'old';old.mkdir(mode=0o700,exist_ok=True)
            journal=dict(old=[p.name for p in data.iterdir() if p.name not in exclusions],new=[p.name for p in root.iterdir() if p.name not in exclusions])
            write(journal_path,journal)
            try:
                for name in journal['old']: os.replace(data/name,old/name)
                for name in journal['new']: os.replace(root/name,data/name)
                validate_store(data,exclusions|{'security'})
                if has_accounts:
                    from portable_backups import validate_identity
                    validate_identity(data/'security/accounts.sqlite3',portable=True)
            except Exception:
                rollback(data,operation,journal)
                raise
            journal_path.unlink()
            shutil.rmtree(old)
            try:
                import data_retention
                data_retention.after_restore(directory=data)
            except Exception:  # noqa: BLE001 - retention bookkeeping never turns a verified restore into a failure
                pass
            state.update(status='completed',message='Application data restored. Destination hosting and recovery key retained; acknowledged account state restored and sessions invalidated. Sources are Static; reconfigure paths before enabling Dynamic refresh. Scheduling is disabled.')
        state['completed_at']=stamp()
    except Exception:
        state.update(status='failed',message='Operation failed; previous application data was preserved. Check archive compatibility, available storage and directory permissions. Use host maintenance for recovery if needed.')
        if journal_path.exists():
            state['message']='Restore recovery is incomplete. Service startup is blocked to protect data; repair storage permissions and restart or use stopped host maintenance.'
            raise RuntimeError('Restore rollback requires recovery before serving application data.') from None
    finally:
        # No source data, absolute paths or raw exceptions enter public status/logs.
        publish(state,data)
        if not journal_path.exists(): shutil.rmtree(operation/'stage',ignore_errors=True)
        if state['kind']=='restore' and not journal_path.exists(): (operation/'archive.tar.gz').unlink(missing_ok=True)
    if state['kind']=='backup' and state.get('status')=='ready':
        from backup_schedule import retention
        try: retention(data)
        except (ValueError,OSError): pass # Retention failure must never invalidate a verified archive.


def download(identity,kind='backup',data=None):
    if kind not in {'backup','destination-before-restore'}: raise engine.MaintenanceError('Unknown backup download.')
    operation=path_for(identity,data)
    record_path=operation/'result.json'
    record=json.loads(record_path.read_bytes()) if record_path.is_file() else {}
    path=archive_path(operation,kind,record)
    if engine.linked(path) or not path.is_file(): raise engine.MaintenanceError('Backup archive is unavailable. Check operation status.')
    expected=record.get('sha256' if kind=='backup' else 'recovery_sha256')
    if record.get('format')==2:
        if not expected or engine.digest(path)!=expected:raise engine.MaintenanceError('Encrypted archive integrity changed; download refused.')
    else:manifest(path)
    return path


@contextmanager
def uploaded(data=None):
    with lock:
        idle_required(data)
        previews=sorted((p for p in area(data).iterdir() if p.is_dir() and not engine.linked(p) and (p/'preview.json').is_file() and not any((p/('destination-before-restore'+suffix)).exists() for suffix in ('.tar.gz','.slbak'))),key=lambda p:p.stat().st_mtime)
        for stale in previews[:-2]: shutil.rmtree(stale)
        identity=uuid4().hex;operation=path_for(identity,data);operation.mkdir(mode=0o700)
    try: yield identity,operation/'archive.tar.gz'
    except BaseException:
        shutil.rmtree(operation,ignore_errors=True)
        raise
