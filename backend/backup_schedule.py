"""Private backup schedule/history. Archive creation remains stopped-store only."""
from datetime import datetime, timezone
import json
import shutil

from pydantic import Field, model_validator
import cron_schedule as cron
from config_models import RefreshSchedule
import application_backups as backups


class Schedule(RefreshSchedule):
    keep: int = Field(default=7, ge=1, le=100)

    @model_validator(mode='after')
    def valid_zone_and_interval(self):
        cron.check(self.expression,self.timezone,datetime.now(timezone.utc))
        return self


def schedule_path(data=None):
    from config import config_dir
    return (data or config_dir())/'backup-schedule.json'


def settings(data=None):
    path=schedule_path(data)
    if not path.exists():path=backups.area(data,create=False)/'schedule.json'
    if not path.exists(): return dict(revision=0,schedule=Schedule().model_dump())
    if backups.engine.linked(path) or path.stat().st_size>32000: raise ValueError('Backup schedule metadata exceeds its limit.')
    value=json.loads(path.read_bytes())
    value['schedule']=Schedule.model_validate(value['schedule']).model_dump()
    return value


def save(draft,revision,data=None):
    parsed=Schedule.model_validate(draft)
    cron.check(parsed.expression,parsed.timezone,datetime.now(timezone.utc))
    if parsed.enabled:
        from backup_crypto import key_status,BackupCryptoError
        from config import config_dir
        if not key_status(data or config_dir())['escrow_verified']:raise BackupCryptoError('Verify a separately stored recovery key before enabling automatic backups.')
    with backups.lock:
        current=settings(data)
        if current['revision']!=revision: raise ValueError('Backup schedule changed; reload before saving.')
        value=dict(current,revision=revision+1,schedule=parsed.model_dump())
        backups.write(schedule_path(data),value)
        return status(data)


def remember(state,data=None):
    if state.get('id'):
        backups.write(backups.path_for(state['id'],data)/'result.json',state)


def rows(data=None):
    root=backups.area(data,create=False)
    if not root.exists(): return []
    result=[]
    for folder in root.iterdir():
        if not backups.ID.fullmatch(folder.name) or backups.engine.linked(folder): continue
        path=folder/'result.json'
        try:
            if not path.is_file() or backups.engine.linked(path) or path.stat().st_size>32000: continue
            value=json.loads(path.read_bytes())
            if value.get('id')!=folder.name or value.get('kind')!='backup': continue
            archive=backups.archive_path(folder,'backup',value)
            size=archive.stat().st_size if archive.is_file() and not backups.engine.linked(archive) else 0
            result.append(dict(id=folder.name,created_at=value.get('completed_at') or value.get('requested_at'),origin=value.get('origin','manual'),
                               status=value['status'],size=size,verified=bool(value.get('verified') and size),sha256=value.get('sha256','')))
        except (ValueError,OSError,KeyError,TypeError): continue
    return sorted(result,key=lambda row:row['created_at'] or '',reverse=True)


def history(data=None):
    items=rows(data)
    return dict(items=items[:200],total=len(items),storage_bytes=sum(row['size'] for row in items),destination='Private application data / .application-backups')


def remove(identity,confirm,data=None):
    if not confirm: raise ValueError('Confirm backup deletion.')
    with backups.lock:
        current=backups.read(data)
        if backups.pending(data): raise ValueError('An active operation prevents archive deletion.')
        row=next((row for row in rows(data) if row['id']==identity),None)
        if not row or row['status'] not in {'ready','failed','cancelled'}: raise ValueError('Only inactive backup archives can be deleted.')
        # Staged restores are independent copies; still preserve matching originals.
        root=backups.area(data)
        for folder in root.iterdir():
            preview=folder/'preview.json'
            if not backups.ID.fullmatch(folder.name) or backups.engine.linked(folder) or not preview.is_file(): continue
            if preview.stat().st_size>32000 or json.loads(preview.read_bytes()).get('archive_sha256')==row['sha256']: raise ValueError('A staged restore protects this archive.')
        operation=backups.path_for(identity,data)
        backups.archive_path(operation,'backup',json.loads((operation/'result.json').read_bytes())).unlink(missing_ok=True)
        record=json.loads((operation/'result.json').read_bytes());record.update(status='deleted',verified=False)
        remember(record,data)
        if current.get('id')==identity:
            current.update(status='cancelled',message='Backup archive deleted by request.')
            backups.write(root/'operation.json',current)
    return history(data)


def retention(data=None):
    # One canonical, installation-bound approved policy. The legacy count limit
    # cannot remove recent backups ahead of the 90-day retention window.
    import backup_retention
    return backup_retention.check(data=data)


def check_space(data,exclusions):
    members=backups.engine.inventory(data,'data',exclusions)
    required=2*sum(row[1] for row in members.values())+1024*1024
    if shutil.disk_usage(data).free<required: raise ValueError('Insufficient free space for a verified backup.')


def status(data=None):
    value=settings(data);parsed=Schedule.model_validate(value['schedule']);items=rows(data)
    value.update(next_runs=[run.isoformat() for run in cron.check(parsed.expression,parsed.timezone,datetime.now(timezone.utc))] if parsed.enabled else [],
                 description=cron.describe(parsed.expression,parsed.timezone),requires_restart=True,
                 last_success=next((row['created_at'] for row in items if row['origin']=='scheduled' and row['status']=='ready'),None),
                 last_failure=next((row['created_at'] for row in items if row['origin']=='scheduled' and row['status']=='failed'),None))
    from backup_crypto import key_status
    from config import config_dir
    value['encryption_ready']=key_status(data or config_dir())['escrow_verified']
    return value


def tick(now,cursor,loader,data=None):
    """Claim one occurrence in the single leased runtime; never replay downtime slots."""
    with backups.lock:
        value=settings(data);parsed=Schedule.model_validate(value['schedule'])
        if not parsed.enabled: return 'idle'
        runs=cron.next_runs(parsed.expression,parsed.timezone,cursor,1)
        if not runs or runs[0]>now: return 'idle'
        occurrence=runs[0].isoformat()
        if value.get('last_occurrence')==occurrence: return 'skipped'
        value['last_occurrence']=occurrence
        from backup_crypto import key_status
        from config import config_dir
        if not key_status(data or config_dir())['escrow_verified']:
            value.update(last_attempt=now.isoformat(),last_outcome='skipped: recovery key copy not verified')
        elif backups.pending(data) or loader.loading:
            value.update(last_attempt=now.isoformat(),last_outcome='skipped: another operation is running')
        else:
            backups.request_backup(data,origin='scheduled')
            value.update(last_attempt=now.isoformat(),last_outcome='waiting_for_restart')
        value['attempts']=[*value.get('attempts',[]),dict(at=now.isoformat(),occurrence=occurrence,status=value['last_outcome'])][-50:]
        backups.write(schedule_path(data),value)
        return value['last_outcome']
