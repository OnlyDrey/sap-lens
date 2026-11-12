"""Backup retention: automatic backups expire after a period (default 90 days); manual and migration backups are never removed automatically.

Three classes of backup, told apart by explicit metadata, never by file names or file times:
* automatic: `origin: scheduled` in the backup's `result.json`, written when the scheduled backup was requested. Eligible after the period, counted from the
  *recorded* completion time (`completed_at`, else `requested_at`). Removal goes through the existing `backup_schedule.remove`, which refuses while any
  operation is pending and while a staged restore uses the archive.
* manual: `origin: manual`. Stays until an administrator deletes it with the existing, confirmed delete action. Never reclassified.
* migration: the pre-migration backup in `.application-backups/migration`, handled by `storage_migration` (kept until confirmed, then until explicitly deleted).
A backup without reliable metadata (no or unknown origin, unreadable `result.json`, no usable timestamp, not verified, archive missing or unsafe, digest mismatch)
is protected. Folders and archives that are links are never followed.

The policy and the approval live in `.application-backups/retention.json`, next to the backups they govern and outside the data a restore replaces: a restore
neither voids this approval nor brings an older copy of it back. Cleanup needs the same one-time administrator approval as the other retention categories and is
bound to this installation and to the previewed set. Archives can contain historical records (decisions, periods, source data) that source or review retention
removed from the live installation; restoring such an archive brings those records back, and after a restore review retention is paused and its approval void.
This retention is independent of the scheduled-backup count limit (`keep`, default 7), which stays as configured: either rule can remove an automatic backup.
The period is a maximum, not a guaranteed minimum: the count limit removes automatic backups beyond the newest `keep` as soon as a scheduled backup completes,
without approval and whatever their age, so a backup can be gone long before the period ends. The preview names the rule behind every candidate."""
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import Field

import application_backups as backups
import backup_schedule
from config_models import StrictModel

DEFAULT_DAYS, MIN_DAYS, MAX_DAYS = 90, 7, 3650
HISTORY_LIMIT = 100
FILE = 'retention.json'
ARCHIVE = 'backup.tar.gz'


class Policy(StrictModel):
    days: int = Field(default=DEFAULT_DAYS, ge=MIN_DAYS, le=MAX_DAYS)


class Approval(StrictModel):
    by: str = Field(max_length=120)
    at: str = Field(max_length=40)
    days: int = Field(ge=MIN_DAYS, le=MAX_DAYS)
    instance: str = Field(max_length=64)


class Entry(StrictModel):
    at: str = Field(max_length=40)
    trigger: Literal['automatic', 'manual', 'approval', 'policy']
    status: Literal['completed', 'partial', 'changed']
    days: int
    removed: int = 0
    bytes: int = 0
    by: str = Field(default='', max_length=120)
    message: str = Field(default='', max_length=300)


class State(StrictModel):
    version: Literal[1] = 1
    revision: int = Field(default=0, ge=0)
    policy: Policy = Field(default_factory=Policy)
    approval: Approval | None = None
    last_check: str = Field(default='', max_length=40)
    last_cleanup: str = Field(default='', max_length=40)
    last_preview: dict = Field(default_factory=dict)
    history: list[Entry] = Field(default_factory=list, max_length=HISTORY_LIMIT)


def _path(data=None):
    return backups.area(data) / FILE


def read(data=None):
    path = backups.area(data, create=False) / FILE
    try:
        if not path.is_file() or backups.engine.linked(path) or path.stat().st_size > 64000:
            return State()
        return State.model_validate_json(path.read_bytes())
    except (OSError, ValueError, TypeError, RecursionError):
        return State()                                          # unreadable: defaults apply and nothing is approved


def _write(state, data=None):
    state.revision += 1
    backups.write(_path(data), State.model_validate(state.model_dump()).model_dump(mode='json'))


def approved(state):
    import data_retention
    return bool(state.approval and state.approval.instance == data_retention.instance() and state.policy.days >= state.approval.days)


def classify(value):
    origin = value.get('origin')
    return 'automatic' if origin == 'scheduled' else 'manual' if origin == 'manual' else 'unclassified'


def _moment(text):
    try:
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def plan(days=None, now=None, data=None):
    """Eligible automatic backups and every protected backup with its reason. Pure measurement."""
    state = read(data)
    days = days or state.policy.days
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    root = backups.area(data, create=False)
    items, protected, counts = [], [], dict(automatic=0, manual=0, unclassified=0, migration=0)
    current = backups.read(data)
    staged = set()
    if root.is_dir():
        for folder in root.iterdir():
            preview = folder / 'preview.json'
            if backups.ID.fullmatch(folder.name) and not backups.engine.linked(folder) and preview.is_file() and not backups.engine.linked(preview) and preview.stat().st_size <= 32000:
                try:
                    staged.add(json.loads(preview.read_bytes()).get('archive_sha256'))
                except (ValueError, OSError):
                    staged.add(None)
    def keep(identity, kind, reason, created=None):
        protected.append(dict(id=identity, kind=kind, reason=reason, created=created.isoformat() if created else ''))
    for folder in sorted(root.iterdir()) if root.is_dir() else []:
        if not backups.ID.fullmatch(folder.name) or backups.engine.linked(folder) or not folder.is_dir():
            continue
        path = folder / 'result.json'
        try:
            if not path.is_file() or backups.engine.linked(path) or path.stat().st_size > 32000:
                continue                                             # restore previews and uploads are not backups
            value = json.loads(path.read_bytes())
        except (OSError, ValueError):
            keep(folder.name, 'unclassified', 'Unreadable metadata')
            counts['unclassified'] += 1
            continue
        if not isinstance(value, dict) or value.get('kind') != 'backup':
            continue
        if value.get('id') != folder.name:
            keep(folder.name, 'unclassified', 'Metadata does not match the backup folder')
            counts['unclassified'] += 1
            continue
        if value.get('status') == 'deleted':
            continue
        kind = classify(value)
        counts[kind] += 1
        created = _moment(value.get('completed_at')) or _moment(value.get('requested_at'))
        if kind == 'manual':
            keep(folder.name, kind, 'Manual backup: removed only by an administrator', created)
        elif kind == 'unclassified':
            keep(folder.name, kind, 'No reliable classification (protected)', created)
        elif value.get('status') != 'ready':
            keep(folder.name, kind, f"Not a completed backup ({value.get('status', 'unknown')})", created)
        elif created is None:
            keep(folder.name, kind, 'No recorded creation time', created)
        elif created >= cutoff:
            keep(folder.name, kind, f'Younger than {days} days (or exactly {days})', created)
        elif current.get('id') == folder.name and backups.pending(data):
            keep(folder.name, kind, 'Involved in an active operation', created)
        elif value.get('sha256') and value.get('sha256') in staged:
            keep(folder.name, kind, 'Protects a staged restore', created)
        elif not value.get('verified') or not re.fullmatch(r'[a-f0-9]{64}', str(value.get('sha256', ''))):
            keep(folder.name, kind, 'Not verified', created)
        else:
            archive = backups.archive_path(folder,'backup',value)
            if archive.is_symlink() or archive.exists() and not archive.is_file():
                keep(folder.name, kind, 'Archive is not a regular file', created)
            elif not archive.exists():
                items.append(dict(id=folder.name, created=created.isoformat(), bytes=0, age_days=(now - created).days, note='archive already removed; record completed'))
            elif backups.engine.digest(archive) != value['sha256']:
                keep(folder.name, kind, 'Archive does not match its recorded digest', created)
            else:
                items.append(dict(id=folder.name, created=created.isoformat(), bytes=archive.stat().st_size, age_days=(now - created).days, note=''))
    try:
        import storage_migration
        for record in storage_migration._records(backups.engine.directory(root.parent) if root.is_dir() else root.parent):
            if record.get('status') == 'migrated':
                keep(record['id'], 'migration', 'Migration backup waiting for administrator confirmation', _moment(record.get('created')))
                counts['migration'] += 1
            elif record.get('status') == 'confirmed' and storage_migration.archive_path(root.parent,record).is_file():
                keep(record['id'], 'migration', 'Migration backup confirmed: delete it explicitly when no longer needed', _moment(record.get('created')))
                counts['migration'] += 1
    except Exception:  # noqa: BLE001 - migration records are informational here; they are never candidates
        pass
    limit, over = count_limit(data)
    for item in items:                                           # the rule that makes each backup removable (information only: the digest binds ids and period)
        item['rules'] = ['age'] + (['count'] if item['id'] in over else [])
        item['rule'] = (f"Older than {days} days" + (f" and beyond the newest {limit} automatic backups" if item['id'] in over else ''))
    early = [dict(id=identity, rule=f'Beyond the newest {limit} automatic backups: removed by the count limit at the next scheduled backup, without approval') for identity in over
             if identity not in {item['id'] for item in items}]
    import hashlib
    digest = hashlib.sha256(('\n'.join(item['id'] for item in sorted(items, key=lambda row: row['id'])) + f'|{days}').encode()).hexdigest()
    reasons = {}
    for row in protected:
        reasons[row['reason']] = reasons.get(row['reason'], 0) + 1
    return dict(days=days, generated=now.isoformat(), count=len(items), bytes=sum(item['bytes'] for item in items), digest=digest, items=items, protected=protected,
                reasons=reasons, counts=counts, keep=limit, count_limit=early)


def count_limit(data=None):
    """Retain the stored legacy preference; time/approval is the only deletion rule."""
    keep = backup_schedule.Schedule.model_validate(backup_schedule.settings(data)['schedule']).keep
    return keep, []


def public(found):
    return dict(keep=found['keep'], count_limit=found['count_limit'][:100], days=found['days'], count=found['count'], bytes=found['bytes'], digest=found['digest'], reasons=found['reasons'], counts=found['counts'],
                sample=found['items'][:100], protected_sample=found['protected'][:100], truncated=len(found['items']) > 100)


def execute(trigger='automatic', actor='data-retention', now=None, data=None):
    """Remove what the current plan lists, each through the existing safe delete. Re-plans first and skips everything while an operation is pending."""
    now = now or datetime.now(timezone.utc)
    with backups.lock:
        if backups.pending(data):
            return dict(removed=0, bytes=0, skipped='An active backup or restore operation is pending.')
        state = read(data)
        found = plan(state.policy.days, now, data)
        removed, size = 0, 0
        for item in found['items']:
            try:
                backup_schedule.remove(item['id'], True, data)
                removed += 1
                size += item['bytes']
            except (ValueError, OSError):
                continue                                              # a protecting condition appeared since planning: kept
        if removed:
            state = read(data)
            state.last_cleanup = now.isoformat()
            state.history = [*state.history, Entry(at=now.isoformat(), trigger=trigger, status='completed' if removed == found['count'] else 'partial', days=state.policy.days,
                                                   removed=removed, bytes=size, by=actor[:120])][-HISTORY_LIMIT:]
            _write(state, data)
        return dict(removed=removed, bytes=size)


def check(now=None, data=None):
    now = now or datetime.now(timezone.utc)
    with backups.lock:
        state = read(data)
        found = plan(state.policy.days, now, data)
        state = read(data)
        state.last_check = now.isoformat()
        state.last_preview = {key: found[key] for key in ('days', 'count', 'bytes', 'digest', 'reasons', 'counts')}
        _write(state, data)
        if found['count'] and approved(state):
            execute('automatic', now=now, data=data)
            return 'cleaned'
        return 'awaiting_approval' if found['count'] else 'nothing'


def approve(actor, digest, now=None, data=None):
    import data_retention
    now = now or datetime.now(timezone.utc)
    with backups.lock:
        found = plan(None, now, data)
        if found['digest'] != digest:
            raise ValueError('The backups changed since the preview was created. Review the new preview and approve again.')
        state = read(data)
        state.approval = Approval(by=actor[:120], at=now.isoformat(), days=state.policy.days, instance=data_retention.instance())
        state.history = [*state.history, Entry(at=now.isoformat(), trigger='approval', status='changed', days=state.policy.days, by=actor[:120],
                                               message=f"Approved removal of {found['count']} automatic backup(s) older than {state.policy.days} days.")][-HISTORY_LIMIT:]
        _write(state, data)
        result = execute('manual', actor, now, data)
        check(now, data)
        return result


def set_policy(actor, days, now=None, data=None):
    with backups.lock:
        state = read(data)
        if days != state.policy.days:
            state.history = [*state.history, Entry(at=(now or datetime.now(timezone.utc)).isoformat(), trigger='policy', status='changed', days=days, by=actor[:120],
                                                   message=f'Automatic backups are kept {days} days.' + (' Shortening needs a new approval.' if state.approval and days < state.approval.days else ''))][-HISTORY_LIMIT:]
        state.policy = Policy(days=days)
        _write(state, data)


def status(data=None, now=None):
    state = read(data)
    now = now or datetime.now(timezone.utc)
    nxt = None
    last = _moment(state.last_check)
    if last:
        nxt = (last + timedelta(hours=24)).isoformat()
    return dict(days=state.policy.days, keep=count_limit(data)[0], state='approved' if approved(state) else 'awaiting_approval', last_preview=state.last_preview, last_cleanup=state.last_cleanup, last_check=state.last_check,
                next_check=nxt, approval=None if not state.approval else dict(by=state.approval.by, at=state.approval.at, days=state.approval.days, valid=approved(state)),
                history=[entry.model_dump() for entry in reversed(state.history[-10:])])
