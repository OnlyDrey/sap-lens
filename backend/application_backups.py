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
        import subprocess
        sid=subprocess.check_output(['powershell','-NoProfile','-Command','[Security.Principal.WindowsIdentity]::GetCurrent().User.Value'],text=True).strip()
        if not re.fullmatch(r'S-1-[0-9-]+',sid): raise engine.MaintenanceError('Cannot resolve private backup ownership.')
        subprocess.run(['icacls.exe',str(root),'/inheritance:r','/grant:r','*'+sid+':(OI)(CI)F','*S-1-5-18:(OI)(CI)F'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
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


def read(data=None):
    path=area(data,create=False)/'operation.json'
    if not path.exists(): return {'status':'idle'}
    if engine.linked(path) or path.stat().st_size>32000: raise engine.MaintenanceError('Backup operation metadata is invalid.')
    return json.loads(path.read_text())


def pending(data=None):
    return read(data).get('status')=='pending'


def protected(data, server=None):
    """Preserve security roots wholesale; reject credentials under a data subtree."""
    data=Path(data).resolve()
    roots={'deployment.json','.sap-lens-instance.lock','runtime.json','logs','.application-backups'}
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


def request_backup(data=None):
    with lock:
        idle_required(data)
        identity=uuid4().hex; path_for(identity,data).mkdir(mode=0o700)
        result=dict(id=identity,kind='backup',status='pending',requested_at=stamp(),message='Restart SAP Lens to create a consistent backup. Return here after restart to download it.')
        write(area(data)/'operation.json',result)
        return result


def validate_store(root, exclude=()):
    """Validate typed stores, immutable digests and snapshot references before activation."""
    from config_models import AppConfig
    from sod_decisions import Storage
    from sod_periods import Index
    from sod_reviews import ReviewStorage
    from sod_catalogue import CatalogueStorage
    models={'settings.json':AppConfig,'sod-decisions.json':Storage,'sod-periods.json':Index,'sod-reviews.json':ReviewStorage,'sod-catalogue.json':CatalogueStorage}
    snapshots={}
    assets=set()
    parsed=[]
    for item in engine.walk_files(root,exclude):
        if engine.linked(item) or item.suffix.lower() in SECRET_SUFFIXES|FORBIDDEN or item.name in {'.env','server.env','users.json','accounts.json'}:
            raise engine.MaintenanceError('Archive contains security configuration or executable content; use an application-data backup.')
        if re.fullmatch(r'[a-f0-9]{64}',item.stem):
            if engine.digest(item)!=item.stem: raise engine.MaintenanceError('Immutable file digest does not match.')
            assets.add(item.stem)
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
            if item.parent.name=='employee-directory':
                from employee_directory import validate_snapshot
                validate_snapshot(value)
            if item.parent.name=='snapshots' and isinstance(value,dict) and value.get('source') in {'roles','users','sod'}:
                from csv_lifecycle import validate_source
                validate_source(value['source'],value)
            if item.name=='saved-filters.json':
                if not isinstance(value,dict) or value.get('schema_version')!=1 or not isinstance(value.get('items'),list) or len(value['items'])>250: raise engine.MaintenanceError('Unsupported saved-filter storage.')
                if any(not isinstance(row,dict) or any(key not in row for key in ('id','name','view','filters','filter_schema','created','modified')) for row in value['items']): raise engine.MaintenanceError('Invalid saved-filter definition.')
            # Inactive configuration recovery copies may legitimately refer to
            # retired generations. Preserve them, but never activate their pointers.
            if item.relative_to(root).parts[0]!='configuration-backups': parsed.append(value)
    def references(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key in {'snapshot','evidence_snapshot','finding_snapshot','employee_snapshot_id'} and isinstance(item,str) and re.fullmatch('[a-f0-9]{64}',item) and item not in snapshots:
                    raise engine.MaintenanceError('Archive has a missing snapshot reference.')
                if key=='logo_id' and item and item not in assets: raise engine.MaintenanceError('Archive has a missing branding asset.')
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


def prepare(archive,operation,server=None,data=None):
    header=manifest(archive)
    stage=operation/'stage'
    if stage.exists(): shutil.rmtree(stage)
    stage.mkdir(mode=0o700)
    engine.restore(archive,stage/'data',header['mode'],VERSION,config=stage/'config',confirm=True,_staging=True)
    root=stage/'data'
    # Source deployment identity and credentials are never activated.
    source_protected=protected(root)
    for name in source_protected:
        candidate=root/name
        if candidate.is_dir(): shutil.rmtree(candidate)
        else: candidate.unlink(missing_ok=True)
    validate_store(root)
    destination=Path(data or config_dir())
    from config_models import AppConfig
    source=AppConfig.model_validate_json((root/'settings.json').read_bytes()) if (root/'settings.json').exists() else AppConfig()
    current=AppConfig.model_validate_json((destination/'settings.json').read_bytes()) if (destination/'settings.json').exists() else AppConfig()
    source.desktop=current.desktop
    source.refresh_schedule=current.refresh_schedule.model_copy(update={'enabled':False})
    source.cors_origins=current.cors_origins
    for name in ('roles','users','employees','sod'): setattr(source.source_modes,name,'static')
    write(root/'settings.json',source.model_dump(mode='json'))
    # Protected destination subtrees cannot be replaced by source content.
    for name in protected(destination,server):
        candidate=root/name
        if candidate.is_dir(): shutil.rmtree(candidate)
        else: candidate.unlink(missing_ok=True)
    return header,root


def register_upload(identity,data=None,server=None):
    with lock:
        idle_required(data)
        operation=path_for(identity,data)
        header,root=prepare(operation/'archive.tar.gz',operation,server,data)
        result=dict(id=identity,kind='restore',status='preview',preview=preview_data(header),archive_sha256=engine.digest(operation/'archive.tar.gz'))
        result['preview']['review_periods']=len(json.loads((root/'sod-periods.json').read_text()).get('items',[])) if (root/'sod-periods.json').exists() else 0
        stored=json.loads((root/'sod-decisions.json').read_text()) if (root/'sod-decisions.json').exists() else {}
        result['preview']['decision_events']=sum(len(events) for kinds in stored.get('contexts',{}).values() for subjects in kinds.values() for events in subjects.values())
        write(operation/'preview.json',result)
        shutil.rmtree(operation/'stage',ignore_errors=True)
        return result


def confirm_restore(identity,sha256,confirm,data=None):
    with lock:
        idle_required(data)
        operation=path_for(identity,data)
        result=json.loads((operation/'preview.json').read_text())
        if not confirm or sha256!=result['archive_sha256'] or engine.digest(operation/'archive.tar.gz')!=sha256: raise engine.MaintenanceError('Confirm the exact validated archive; it changed or was not confirmed.')
        result.update(status='pending',requested_at=stamp(),message='Restart required. Destination data will be backed up before full replacement; edits are paused until restart or cancellation.')
        write(area(data)/'operation.json',result)
        return result


def cancel(data=None):
    with lock:
        result=read(data)
        if result.get('status')=='pending':
            result.update(status='cancelled',message='Operation cancelled; application data was not replaced.')
            write(area(data)/'operation.json',result)
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
    if not state.get('id'): return
    operation=path_for(state['id'],data)
    journal_path=operation/'journal.json'
    if state.get('status')!='pending' and not journal_path.exists(): return
    try:
        if journal_path.exists():
            rollback(data,operation,json.loads(journal_path.read_text()))
            raise engine.MaintenanceError('Interrupted activation was rolled back; validate and confirm the archive again.')
        exclusions=protected(data,server)
        if state['kind']=='backup':
            engine.backup(data,operation/'backup.tar.gz',lease.mode,VERSION,_lease=lease,_exclude=exclusions-{'deployment.json'})
            state.update(status='completed',message='Backup ready. Contains sensitive personal and access data; archive is not encrypted.')
        else:
            if engine.digest(operation/'archive.tar.gz')!=state['archive_sha256']: raise engine.MaintenanceError('Uploaded archive changed after confirmation.')
            _,root=prepare(operation/'archive.tar.gz',operation,server,data)
            engine.backup(data,operation/'destination-before-restore.tar.gz',lease.mode,VERSION,_lease=lease,_exclude=exclusions-{'deployment.json'})
            old=operation/'old';old.mkdir(mode=0o700,exist_ok=True)
            journal=dict(old=[p.name for p in data.iterdir() if p.name not in exclusions],new=[p.name for p in root.iterdir() if p.name not in exclusions])
            write(journal_path,journal)
            try:
                for name in journal['old']: os.replace(data/name,old/name)
                for name in journal['new']: os.replace(root/name,data/name)
                validate_store(data,exclusions)
            except Exception:
                rollback(data,operation,journal)
                raise
            journal_path.unlink()
            shutil.rmtree(old)
            state.update(status='completed',message='Application data restored. Destination hosting/security retained. Sources are Static; reconfigure paths before enabling Dynamic refresh. Scheduling is disabled.')
        state['completed_at']=stamp()
    except Exception:
        state.update(status='failed',message='Operation failed; previous application data was preserved. Check archive compatibility, available storage and directory permissions. Use host maintenance for recovery if needed.')
        if journal_path.exists():
            state['message']='Restore recovery is incomplete. Service startup is blocked to protect data; repair storage permissions and restart or use stopped host maintenance.'
            raise RuntimeError('Restore rollback requires recovery before serving application data.') from None
    finally:
        # No source data, absolute paths or raw exceptions enter public status/logs.
        write(area(data)/'operation.json',state)
        if not journal_path.exists(): shutil.rmtree(operation/'stage',ignore_errors=True)
        if state['kind']=='restore' and not journal_path.exists(): (operation/'archive.tar.gz').unlink(missing_ok=True)


def download(identity,kind='backup',data=None):
    if kind not in {'backup','destination-before-restore'}: raise engine.MaintenanceError('Unknown backup download.')
    operation=path_for(identity,data)
    path=operation/(kind+'.tar.gz')
    if engine.linked(path) or not path.is_file(): raise engine.MaintenanceError('Backup is not available. Restart to complete a pending backup.')
    return path


@contextmanager
def uploaded(data=None):
    with lock:
        idle_required(data)
        previews=sorted((p for p in area(data).iterdir() if p.is_dir() and not engine.linked(p) and (p/'preview.json').is_file() and not (p/'destination-before-restore.tar.gz').exists()),key=lambda p:p.stat().st_mtime)
        for stale in previews[:-2]: shutil.rmtree(stale)
        identity=uuid4().hex;operation=path_for(identity,data);operation.mkdir(mode=0o700)
    try: yield identity,operation/'archive.tar.gz'
    except BaseException:
        shutil.rmtree(operation,ignore_errors=True)
        raise
