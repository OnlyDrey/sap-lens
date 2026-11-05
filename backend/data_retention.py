"""Data retention: a daily non-destructive check, and cleanup of superseded source data only after a one-time administrator approval.

Scope (deliberately narrow). Only data that is *superseded and unreferenced* can ever be removed:
* superseded role / user / SoD-matrix source snapshots (`csv-data/snapshots`) and the SQLite revisions and derived values built from them;
* superseded Employee Directory snapshots (`employee-directory`);
* diagnostic leftovers: quarantined SQLite stores and pre-re-baseline copies of the lifecycle memory.
Never touched: review decisions and their events and evidence, review periods and their frozen snapshots and reports, risk acceptances, remediation actions,
account reviews, saved filters, functional groups, settings, application backups and the pre-migration backup (it has its own explicit confirmation).

Protection is by *reference*, not by file type: every 64-hex identifier that appears anywhere in the JSON stores (settings, decisions, periods, reviews,
catalogue, reports, configuration recovery copies) or in any non-source snapshot protects the snapshot it names, so a reference field added later is
honoured without changing this module. In addition the newest KEEP_PER_SOURCE superseded snapshots of each source stay (the previous approved revisions),
and nothing younger than the retention period (default 24 months) is removed. A file that cannot be classified is protected.

Approval: the first destructive cleanup after an upgrade (or a shortened retention period, or a restore onto another installation) waits for an
administrator who has seen the preview. Until then the daily check only measures. Consistency with SQLite: derived store entries are removed before the
authoritative file, the file removal is last and idempotent, and store revisions whose snapshot file is gone are removed on every run, so an interrupted
cleanup is completed by the next one."""
import hashlib
import logging
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from pydantic import Field

import source_store
import store_db
from config import atomic_write, config_dir
from config_models import StrictModel

logger = logging.getLogger('sap-lens')
FILE = 'data-retention.json'
DEFAULT_MONTHS, MIN_MONTHS, MAX_MONTHS = 24, 6, 120
KEEP_PER_SOURCE = 2
CHECK_INTERVAL = timedelta(hours=24)
HISTORY_LIMIT = 100
SAMPLE = 100
HEX = re.compile(rb'[a-f0-9]{64}')
SOURCE_TAIL = re.compile(rb'"source":"(roles|users|sod)","version":1\}\s*$')
lock = threading.RLock()


class Policy(StrictModel):
    enabled: bool = True
    months: int = Field(default=DEFAULT_MONTHS, ge=MIN_MONTHS, le=MAX_MONTHS)


class Approval(StrictModel):
    by: str = Field(max_length=120)
    at: str = Field(max_length=40)
    months: int = Field(ge=MIN_MONTHS, le=MAX_MONTHS)
    instance: str = Field(max_length=64)


class Entry(StrictModel):
    at: str = Field(max_length=40)
    trigger: Literal['automatic', 'manual', 'policy', 'approval']
    status: Literal['completed', 'partial', 'changed']
    months: int
    removed: dict[str, int] = Field(default_factory=dict, max_length=12)
    bytes: int = 0
    by: str = Field(default='', max_length=120)
    message: str = Field(default='', max_length=300)


class Storage(StrictModel):
    version: Literal[1] = 1
    revision: int = Field(default=0, ge=0)
    policy: Policy = Field(default_factory=Policy)
    approval: Approval | None = None
    last_check: str = Field(default='', max_length=40)
    last_preview: dict = Field(default_factory=dict)
    history: list[Entry] = Field(default_factory=list, max_length=HISTORY_LIMIT)


def _path():
    return config_dir() / FILE


def instance():
    """Identity of this installation for approvals: derived from the store key, which no backup carries. An approval restored onto another installation is void."""
    return hashlib.sha256(b'sap-lens-retention' + store_db.key()).hexdigest()[:32]


def read():
    path = _path()
    if not path.exists():
        return Storage()
    try:
        return Storage.model_validate_json(path.read_bytes())
    except (OSError, ValueError, TypeError, RecursionError):
        logger.warning('Data retention settings are unreadable; defaults apply and no cleanup is approved.')
        return Storage()


def _write(data):
    data.revision += 1
    atomic_write(_path(), Storage.model_validate(data.model_dump()).model_dump_json().encode('utf-8'))


def approved(data):
    """Automatic destructive cleanup is allowed only for an approval given on this installation for at least this long a retention period."""
    approval = data.approval
    return bool(approval and approval.instance == instance() and data.policy.months >= approval.months)


def state_label(data):
    if not data.policy.enabled:
        return 'disabled'
    if approved(data):
        return 'approved'
    return 'awaiting_approval'


# --- scanning -------------------------------------------------------------------------------------------------------------------------

def _ids(path):
    found = set()
    with open(path, 'rb') as stream:
        carry = b''
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            data = carry + block
            found.update(item.decode() for item in HEX.findall(data))
            carry = data[-63:]
    return found


def _kind(path):
    """'roles' / 'users' / 'sod' for a source snapshot (recognised by the tail of its canonical JSON), otherwise None: unknown kinds are protected."""
    size = path.stat().st_size
    with open(path, 'rb') as stream:
        stream.seek(max(0, size - 256))
        match = SOURCE_TAIL.search(stream.read())
    return match.group(1).decode() if match else None


def _plain_files(folder, pattern='*.json'):
    if not folder.is_dir() or folder.is_symlink():
        return []
    return [item for item in sorted(folder.glob(pattern)) if item.is_file() and not item.is_symlink()]


def referenced(snapshots):
    """Every identifier named anywhere outside source snapshots. Includes configuration recovery copies: they may still point at older generations."""
    root = config_dir()
    found = set()
    places = [*_plain_files(root), *_plain_files(root / 'configuration-backups'), *_plain_files(root / 'csv-data' / 'reports')]
    places += [item for item in snapshots if item['kind'] is None]
    for place in places:
        path = place['path'] if isinstance(place, dict) else place
        if path.name in {FILE}:
            continue
        try:
            found |= _ids(path)
        except OSError:
            raise RuntimeError('A store needed to establish references could not be read; nothing is removed.') from None
    return found


def _listing():
    root = config_dir()
    snapshots = []
    for path in _plain_files(root / 'csv-data' / 'snapshots'):
        if re.fullmatch(r'[a-f0-9]{64}', path.stem):
            stat = path.stat()
            snapshots.append(dict(path=path, id=path.stem, kind=_kind(path), bytes=stat.st_size, mtime=stat.st_mtime))
    directories = []
    for path in _plain_files(root / 'employee-directory'):
        if re.fullmatch(r'[a-f0-9]{64}', path.stem):
            stat = path.stat()
            directories.append(dict(path=path, id=path.stem, kind='directory', bytes=stat.st_size, mtime=stat.st_mtime))
    return snapshots, directories


def plan(months=None, now=None):
    """What a cleanup would remove right now. Pure measurement: nothing is changed."""
    months = months or read().policy.months
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=months * 30.4375)).timestamp()
    snapshots, directories = _listing()
    named = referenced(snapshots)
    items, protected = [], dict(referenced=0, recent=0, kept_newest=0, unclassified=0)
    groups = {}
    for entry in [*[s for s in snapshots if s['kind']], *directories]:
        if entry['id'] in named:
            protected['referenced'] += 1
            continue
        groups.setdefault(entry['kind'], []).append(entry)
    protected['unclassified'] = sum(1 for s in snapshots if s['kind'] is None)
    for kind, entries in groups.items():
        entries.sort(key=lambda e: e['mtime'], reverse=True)
        protected['kept_newest'] += min(KEEP_PER_SOURCE, len(entries))
        for entry in entries[KEEP_PER_SOURCE:]:
            if entry['mtime'] > cutoff:
                protected['recent'] += 1
                continue
            items.append(dict(category='directory snapshots' if kind == 'directory' else f'{kind} snapshots', kind=kind, id=entry['id'], bytes=entry['bytes'],
                              age_days=int((now.timestamp() - entry['mtime']) / 86400), path=str(entry['path'])))
    root = config_dir()
    for pattern, folder, label in (('sap-lens.sqlite3.corrupt-*', root / 'store', 'diagnostic copies'), ('assignment-lifecycle.json.before-rebaseline-*', root, 'diagnostic copies')):
        for path in _plain_files(folder, pattern):
            stat = path.stat()
            if stat.st_mtime <= cutoff:
                items.append(dict(category=label, kind='diagnostic', id=path.name, bytes=stat.st_size, age_days=int((now.timestamp() - stat.st_mtime) / 86400), path=str(path)))
    items.sort(key=lambda item: (item['category'], item['id']))
    summary = {}
    for item in items:
        row = summary.setdefault(item['category'], dict(count=0, bytes=0, oldest_days=0))
        row['count'] += 1
        row['bytes'] += item['bytes']
        row['oldest_days'] = max(row['oldest_days'], item['age_days'])
    digest = hashlib.sha256(('\n'.join(f"{item['category']}:{item['id']}" for item in items) + f'|{months}').encode()).hexdigest()
    return dict(months=months, generated=now.isoformat(), categories=summary, count=len(items), bytes=sum(item['bytes'] for item in items), protected=protected,
                digest=digest, items=items)


def public_plan(value):
    return {key: item for key, item in value.items() if key != 'items'} | dict(sample=[{k: v for k, v in item.items() if k != 'path'} for item in value['items'][:SAMPLE]],
                                                                                truncated=len(value['items']) > SAMPLE)


# --- execution ------------------------------------------------------------------------------------------------------------------------

def _store_cleanup(removed_ids):
    """SQLite follows the authoritative files: superseded revisions of removed snapshots, and any non-active revision whose snapshot file is gone."""
    count = 0
    for snapshot in removed_ids:
        count += source_store.remove_snapshot(snapshot)
    snapshots_dir = config_dir() / 'csv-data' / 'snapshots'
    count += source_store.drop_missing(lambda snapshot: (snapshots_dir / f'{snapshot}.json').exists())
    return count


def execute(trigger, by='', now=None):
    """Remove what the current plan lists. Re-plans first, never trusts an earlier preview, and re-checks every file immediately before removing it."""
    with lock:
        data = read()
        current = plan(data.policy.months, now)
        removed, size, errors = {}, 0, 0
        store_ids = [item['id'] for item in current['items'] if item['kind'] in {'roles', 'users', 'sod'}]
        _store_cleanup(store_ids)                                      # derived copies first: they can always be rebuilt
        for item in current['items']:
            path = Path(item['path'])
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                path.unlink()
                removed[item['category']] = removed.get(item['category'], 0) + 1
                size += item['bytes']
            except OSError:
                errors += 1
        _store_cleanup(())                                              # also completes any earlier interrupted run
        if removed or errors:
            data = read()
            data.history = [*data.history, Entry(at=(now or datetime.now(timezone.utc)).isoformat(), trigger=trigger, status='partial' if errors else 'completed', months=data.policy.months,
                                                  removed=removed, bytes=size, by=by[:120], message=f'{errors} item(s) could not be removed and will be retried.' if errors else '')][-HISTORY_LIMIT:]
            _write(data)
        return dict(removed=removed, bytes=size, errors=errors)


def check(now=None, trigger='automatic'):
    """The daily check: measure, remember, and clean up only when approved."""
    now = now or datetime.now(timezone.utc)
    with lock:
        data = read()
        if not data.policy.enabled:
            return 'disabled'
        found = plan(data.policy.months, now)
        data = read()
        data.last_check = now.isoformat()
        data.last_preview = public_plan(found) | dict(sample=[], truncated=False)
        _write(data)
        if not found['count']:
            source_store.drop_missing(lambda snapshot: (config_dir() / 'csv-data' / 'snapshots' / f'{snapshot}.json').exists())
            return 'nothing'
        if not approved(data):
            return 'awaiting_approval'
        execute(trigger, now=now)
        return 'cleaned'


def due(now=None):
    data = read()
    if not data.policy.enabled:
        return False
    if not data.last_check:
        return True
    try:
        return (now or datetime.now(timezone.utc)) - datetime.fromisoformat(data.last_check) >= CHECK_INTERVAL
    except ValueError:
        return True


def tick(now=None, loader=None):
    """Called by the scheduler loop; cheap when nothing is due. Skips while a load, refresh, backup or restore is in progress."""
    now = now or datetime.now(timezone.utc)
    if not due(now):
        return 'idle'
    try:
        from application_backups import pending
        if pending() or loader is not None and loader.loading:
            return 'skipped'
        return check(now)
    except Exception as error:  # noqa: BLE001 - retention must never disturb the application
        logger.warning('Data retention check failed (%s); it will be retried.', type(error).__name__)
        return 'failed'


def approve(actor, preview_digest, now=None):
    """Administrator approves destructive cleanup for the retention period shown in the preview they saw, and the first cleanup runs now."""
    with lock:
        data = read()
        found = plan(data.policy.months, now)
        if found['digest'] != preview_digest:
            raise ValueError('The data changed since the preview was created. Review the new preview and approve again.')
        data.approval = Approval(by=actor[:120], at=(now or datetime.now(timezone.utc)).isoformat(), months=data.policy.months, instance=instance())
        data.history = [*data.history, Entry(at=data.approval.at, trigger='approval', status='changed', months=data.policy.months, by=actor[:120],
                                             message=f"Approved cleanup of {found['count']} item(s) older than {data.policy.months} months.")][-HISTORY_LIMIT:]
        _write(data)
        result = execute('manual', actor, now)
        check(now)
        return result


def set_policy(actor, enabled, months, now=None):
    with lock:
        data = read()
        old = data.policy
        data.policy = Policy(enabled=enabled, months=months)
        if (old.enabled, old.months) != (enabled, months):
            data.history = [*data.history, Entry(at=(now or datetime.now(timezone.utc)).isoformat(), trigger='policy', status='changed', months=months, by=actor[:120],
                                                 message=f"Retention {'enabled' if enabled else 'disabled'}, {months} months." + (
                                                     ' Shortening the period needs a new approval.' if data.approval and months < data.approval.months else ''))][-HISTORY_LIMIT:]
        _write(data)
        return status()


def status():
    data = read()
    return dict(policy=data.policy.model_dump(), state=state_label(data), approval=None if not data.approval else dict(by=data.approval.by, at=data.approval.at, months=data.approval.months,
                                                                                                                  valid=approved(data)),
                last_check=data.last_check, last_preview=data.last_preview, history=[entry.model_dump() for entry in reversed(data.history[-20:])],
                scope=['Superseded role, user and SoD matrix snapshots and their SQLite copies', 'Superseded Employee Directory snapshots', 'Quarantined stores and pre-re-baseline copies'],
                protected_note='Review decisions, evidence, review periods and their reports, backups and anything still referenced are never removed.')
