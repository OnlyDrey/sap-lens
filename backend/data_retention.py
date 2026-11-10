"""Data retention: a daily non-destructive check, and cleanup only after a one-time administrator approval, in two separate categories.

* **Source retention** (this module): superseded source data. Aged from a *logical* moment, never from file times alone: the time the revision was superseded
  (recorded in the SQLite store), or, for data that predates that record (older installations, directory snapshots), the time retention first saw it unreferenced.
  Data without a reliable moment is protected until it is classified. File times are only an additional guard (nothing with a recent file time is removed).
* **Review retention** (`review_retention.py`): completed review periods and the records they exclusively own, aged from their completion timestamp, with their
  own period, approval and journalled, recoverable removal. Source rules are never applied to review records.

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
    months: int = Field(default=DEFAULT_MONTHS, ge=MIN_MONTHS, le=MAX_MONTHS)               # source retention
    review_months: int = Field(default=DEFAULT_MONTHS, ge=MIN_MONTHS, le=MAX_MONTHS)


class Approval(StrictModel):
    by: str = Field(max_length=120)
    at: str = Field(max_length=40)
    months: int = Field(ge=MIN_MONTHS, le=MAX_MONTHS)
    instance: str = Field(max_length=64)


class Entry(StrictModel):
    at: str = Field(max_length=40)
    trigger: Literal['automatic', 'manual', 'policy', 'approval', 'restore']
    status: Literal['completed', 'partial', 'changed']
    category: Literal['source', 'review'] = 'source'
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
    review_approval: Approval | None = None
    quiet_until: str = Field(default='', max_length=40)
    first_seen: dict[str, str] = Field(default_factory=dict, max_length=5000)
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


def _approval(data, category):
    return data.approval if category == 'source' else data.review_approval


def months_of(data, category):
    return data.policy.months if category == 'source' else data.policy.review_months


def approved(data, category='source'):
    """Automatic destructive cleanup is allowed only for an approval given on this installation for at least this long a retention period."""
    approval = _approval(data, category)
    return bool(approval and approval.instance == instance() and months_of(data, category) >= approval.months)


def state_label(data, category='source'):
    if not data.policy.enabled:
        return 'disabled'
    return 'approved' if approved(data, category) else 'awaiting_approval'


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


def _stamp_in_name(name):
    match = re.search(r'(\d{8}T\d{6})', name)
    if match:
        try:
            return datetime.strptime(match.group(1), '%Y%m%dT%H%M%S').replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _moment(text):
    try:
        value = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def plan(months=None, now=None):
    """What a source cleanup would remove right now. Pure measurement: nothing is changed (first sightings are returned in `observed`, persisted by check())."""
    stored = read()
    months = months or stored.policy.months
    now = now or datetime.now(timezone.utc)
    cutoff_moment = now - timedelta(days=months * 30.4375)
    cutoff = cutoff_moment.timestamp()
    snapshots, directories = _listing()
    named = referenced(snapshots) | {state['snapshot'] for state in (source_store.active(name) for name in source_store.SOURCES) if state}   # the active revision is current data
    items, observed = [], {}
    protected = dict(referenced=0, recent=0, kept_newest=0, unclassified=0, unrecognised=sum(1 for s in snapshots if s['kind'] is None))
    groups = {}
    for entry in [*[s for s in snapshots if s['kind']], *directories]:
        if entry['id'] in named:
            protected['referenced'] += 1
            continue
        retired = source_store.retired_at(entry['id']) if entry['kind'] in {'roles', 'users', 'sod'} else None
        moment = _moment(retired) or _moment(stored.first_seen.get(entry['id']))
        if moment is None:
            observed[entry['id']] = now.isoformat()                       # classified from now on; protected until then
        entry['moment'] = moment
        groups.setdefault(entry['kind'], []).append(entry)
    for kind, entries in groups.items():
        entries.sort(key=lambda e: (e['moment'].timestamp() if e['moment'] else e['mtime']), reverse=True)
        protected['kept_newest'] += min(KEEP_PER_SOURCE, len(entries))
        for entry in entries[KEEP_PER_SOURCE:]:
            if entry['moment'] is None:
                protected['unclassified'] += 1
            elif entry['moment'] > cutoff_moment or entry['mtime'] > cutoff:
                protected['recent'] += 1
            else:
                items.append(dict(category='directory snapshots' if kind == 'directory' else f'{kind} snapshots', kind=kind, id=entry['id'], bytes=entry['bytes'],
                                  age_days=int((now - entry['moment']).total_seconds() / 86400), path=str(entry['path'])))
    root = config_dir()
    for pattern, folder in (('sap-lens.sqlite3.corrupt-*', root / 'store'), ('assignment-lifecycle.json.before-rebaseline-*', root)):
        for path in _plain_files(folder, pattern):
            stat = path.stat()
            moment = _stamp_in_name(path.name) or _moment(stored.first_seen.get(path.name))
            if moment is None:
                observed[path.name] = now.isoformat()
                protected['unclassified'] += 1
            elif moment <= cutoff_moment and stat.st_mtime <= cutoff:
                items.append(dict(category='diagnostic copies', kind='diagnostic', id=path.name, bytes=stat.st_size, age_days=int((now - moment).total_seconds() / 86400), path=str(path)))
    items.sort(key=lambda item: (item['category'], item['id']))
    summary = {}
    for item in items:
        row = summary.setdefault(item['category'], dict(count=0, bytes=0, oldest_days=0))
        row['count'] += 1
        row['bytes'] += item['bytes']
        row['oldest_days'] = max(row['oldest_days'], item['age_days'])
    digest = hashlib.sha256(('\n'.join(f"{item['category']}:{item['id']}" for item in items) + f'|{months}').encode()).hexdigest()
    return dict(months=months, generated=now.isoformat(), categories=summary, count=len(items), bytes=sum(item['bytes'] for item in items), protected=protected,
                digest=digest, items=items, observed=observed)


def public_plan(value):
    return {key: item for key, item in value.items() if key not in {'items', 'observed'}} | dict(sample=[{k: v for k, v in item.items() if k != 'path'} for item in value['items'][:SAMPLE]],
                                                                                                    truncated=len(value['items']) > SAMPLE)


def review_plan(months=None, now=None):
    import review_retention
    months = months or read().policy.review_months
    found = review_retention.plan(months, now, read().first_seen)
    digest = hashlib.sha256(('\n'.join(item['id'] for item in found['items']) + f'|{months}').encode()).hexdigest()
    return dict(review_retention.public(found), observed=found['observed'], months=months, digest=digest, generated=(now or datetime.now(timezone.utc)).isoformat(), bytes=0)


def backup_plan(now=None):
    import backup_retention
    return backup_retention.public(backup_retention.plan(now=now))


def plan_for(category, now=None):
    return plan(now=now) if category == 'source' else review_plan(now=now) if category == 'review' else backup_plan(now)


# --- execution ------------------------------------------------------------------------------------------------------------------------

def _store_cleanup(removed_ids):
    """SQLite follows the authoritative files: superseded revisions of removed snapshots, and any non-active revision whose snapshot file is gone."""
    count = 0
    for snapshot in removed_ids:
        count += source_store.remove_snapshot(snapshot)
    snapshots_dir = config_dir() / 'csv-data' / 'snapshots'
    count += source_store.drop_missing(lambda snapshot: (snapshots_dir / f'{snapshot}.json').exists())
    return count


def _append(data, entry):
    data.history = [*data.history, entry][-HISTORY_LIMIT:]


def execute(trigger, by='', now=None):
    """Source cleanup: re-plans first, never trusts an earlier preview, re-checks every file immediately before removing it."""
    with lock:
        data = read()
        current = plan(data.policy.months, now)
        removed, size, errors = {}, 0, 0
        store_ids = [item['id'] for item in current['items'] if item['kind'] in {'roles', 'users', 'sod'}]
        _store_cleanup(store_ids)                                      # derived copies first: they can always be rebuilt
        gone = []
        for item in current['items']:
            path = Path(item['path'])
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                path.unlink()
                gone.append(item['id'])
                removed[item['category']] = removed.get(item['category'], 0) + 1
                size += item['bytes']
            except OSError:
                errors += 1
        source_store.forget_retired(gone)
        _store_cleanup(())                                              # also completes any earlier interrupted run
        if removed or errors:
            data = read()
            for name in gone:
                data.first_seen.pop(name, None)
            _append(data, Entry(at=(now or datetime.now(timezone.utc)).isoformat(), trigger=trigger, status='partial' if errors else 'completed', category='source', months=data.policy.months,
                                removed=removed, bytes=size, by=by[:120], message=f'{errors} item(s) could not be removed and will be retried.' if errors else ''))
            _write(data)
        return dict(removed=removed, bytes=size, errors=errors)


def record_review_cleanup(removed, files, months, actor, now):
    data = read()
    _append(data, Entry(at=now.isoformat(), trigger='manual' if actor != 'data-retention' else 'automatic', status='completed', category='review', months=months,
                        removed={'review periods': removed['periods'], 'decision events': removed['decisions'], 'remediation actions': removed['actions'],
                                 'legacy review events': removed['legacy_reviews'], 'snapshot files': files}, by=actor[:120],
                        message='Copies and trash are kept for 30 days and the cleanup can be undone meanwhile.'))
    _write(data)


def execute_review(trigger, by='', now=None):
    import review_retention
    with lock:
        months = read().policy.review_months
        actor = by or 'data-retention'
        result = review_retention.execute(months, actor, now)
        review_retention.purge_expired(now)
        return result


def _remember(data, found, reviewed, now):
    """Persist first sightings so unclassified data becomes eligible only `months` after retention first saw it, and drop sightings of files that are gone."""
    live = {item['id'] for item in found['items']} | set(found['observed'])
    data.first_seen.update(found['observed'])
    data.first_seen.update(reviewed.get('observed', {}))
    existing = {path.stem for path in (config_dir() / 'csv-data' / 'snapshots').glob('*.json')} | {path.stem for path in (config_dir() / 'employee-directory').glob('*.json')}
    try:
        import sod_periods
        periods_now = {'period:' + item.id for item in sod_periods.read().items}
    except Exception:  # noqa: BLE001
        periods_now = {key for key in data.first_seen if key.startswith('period:')}
    data.first_seen = {key: value for key, value in data.first_seen.items() if key in existing or key in live or key in periods_now
                       or '.' in key and ((config_dir() / key).exists() or (config_dir() / 'store' / key).exists())}


def check(now=None, trigger='automatic'):
    """The daily check: measure both categories, remember, and clean up only what is approved. Returns the source outcome and the review outcome."""
    now = now or datetime.now(timezone.utc)
    with lock:
        data = read()
        if not data.policy.enabled:
            return 'disabled'
        try:
            import review_retention
            review_retention.recover(now)                              # a run interrupted by a crash is completed first
        except RuntimeError:
            logger.warning('Review retention is paused: an interrupted run could not be resolved.')
            return 'paused'
        found = plan(data.policy.months, now)
        try:
            reviewed = review_plan(data.policy.review_months, now)
        except Exception as error:  # noqa: BLE001 - unreadable review stores: review retention is skipped, source retention is independent
            logger.warning('Review retention skipped: review records could not be read (%s).', type(error).__name__)
            reviewed = dict(count=0, protected=0, reasons={}, digest='', months=data.policy.review_months, error='Review records could not be read.')
        data = read()
        data.last_check = now.isoformat()
        data.last_preview = dict(source=public_plan(found) | dict(sample=[], truncated=False), review={k: v for k, v in dict(reviewed, sample=[], protected_sample=[], truncated=False).items() if k != 'observed'})
        _remember(data, found, reviewed, now)
        _write(data)
        quiet = _moment(data.quiet_until)
        paused = bool(quiet and quiet > now)                           # no destructive cleanup for a while after a restore
        outcome = 'nothing'
        if found['count'] or reviewed['count']:
            outcome = 'awaiting_approval'
        if found['count'] and approved(data, 'source') and not paused:
            execute(trigger, now=now)
            outcome = 'cleaned'
        elif not found['count']:
            source_store.drop_missing(lambda snapshot: (config_dir() / 'csv-data' / 'snapshots' / f'{snapshot}.json').exists())
        if reviewed['count'] and approved(data, 'review') and not paused:
            execute_review(trigger, now=now)
            outcome = 'cleaned'
        try:
            import review_retention
            review_retention.purge_expired(now)
        except OSError:
            pass
        try:
            import backup_retention
            if backup_retention.check(now) == 'cleaned':
                outcome = 'cleaned'
        except Exception as error:  # noqa: BLE001 - backup retention never stops the other categories
            logger.warning('Backup retention check failed (%s).', type(error).__name__)
        return outcome


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


def approve(actor, preview_digest, now=None, category='source'):
    """Administrator approves destructive cleanup of one category for the retention period shown in the preview they saw; the first cleanup runs now."""
    if category == 'backup':
        import backup_retention
        return backup_retention.approve(actor, preview_digest, now)
    with lock:
        data = read()
        found = plan_for(category, now)
        if found['digest'] != preview_digest:
            raise ValueError('The data changed since the preview was created. Review the new preview and approve again.')
        months = months_of(data, category)
        stamp = (now or datetime.now(timezone.utc)).isoformat()
        approval = Approval(by=actor[:120], at=stamp, months=months, instance=instance())
        if category == 'source':
            data.approval = approval
        else:
            data.review_approval = approval
        label = 'source snapshots and diagnostic copies' if category == 'source' else 'completed review periods'
        _append(data, Entry(at=stamp, trigger='approval', status='changed', category=category, months=months, by=actor[:120],
                            message=f"Approved cleanup of {found['count']} item(s) ({label}) older than {months} months."))
        _write(data)
        result = execute('manual', actor, now) if category == 'source' else execute_review('manual', actor, now)
        check(now)
        return result


def set_policy(actor, enabled, months, now=None, review_months=None, backup_days=None):
    if backup_days is not None:
        import backup_retention
        backup_retention.set_policy(actor, backup_days, now)
    with lock:
        data = read()
        old = data.policy
        data.policy = Policy(enabled=enabled, months=months, review_months=review_months if review_months is not None else old.review_months)
        if (old.enabled, old.months, old.review_months) != (data.policy.enabled, data.policy.months, data.policy.review_months):
            shorter = [name for name, approval, new in (('source', data.approval, data.policy.months), ('review', data.review_approval, data.policy.review_months)) if approval and new < approval.months]
            _append(data, Entry(at=(now or datetime.now(timezone.utc)).isoformat(), trigger='policy', status='changed', months=months, by=actor[:120],
                                message=f"Retention {'enabled' if enabled else 'disabled'}: source {data.policy.months} months, review {data.policy.review_months} months."
                                        + (f" Shortening needs a new approval ({', '.join(shorter)})." if shorter else '')))
        _write(data)
        return status()


def after_restore(now=None):
    """A restore replaces the review records; nothing is removed automatically for a week and both approvals are void, so a recovered period cannot be purged
    again before an administrator has looked. Any journal carried in the archive is discarded."""
    now = now or datetime.now(timezone.utc)
    with lock:
        data = read()
        data.approval = data.review_approval = None
        data.quiet_until = (now + timedelta(days=7)).isoformat()
        _append(data, Entry(at=now.isoformat(), trigger='restore', status='changed', months=data.policy.months,
                            message='Application data was restored: approvals are void and no cleanup runs for 7 days.'))
        _write(data)
    (config_dir() / 'data-retention' / 'journal.json').unlink(missing_ok=True)


def status():
    data = read()
    def category(name):
        approval = _approval(data, name)
        return dict(months=months_of(data, name), state=state_label(data, name), last_preview=data.last_preview.get(name, {}),
                    approval=None if not approval else dict(by=approval.by, at=approval.at, months=approval.months, valid=approved(data, name)))
    import backup_retention
    saved = backup_retention.status()
    return dict(policy=dict(data.policy.model_dump(), backup_days=saved['days']), categories=dict(source=category('source'), review=category('review'), backup=saved), last_check=data.last_check, quiet_until=data.quiet_until,
                history=[entry.model_dump() for entry in reversed(data.history[-20:])],
                scope=dict(source=['Superseded role, user and SoD matrix snapshots and their SQLite copies', 'Superseded Employee Directory snapshots', 'Quarantined stores and pre-re-baseline copies'],
                           review=['Completed review periods older than the period, with their decisions, actions and exclusively owned evidence'],
                           backup=['Automatic (scheduled) backups older than the period, counted from their recorded creation time']),
                protected_note='Current source data, active and incomplete review periods, anything still referenced, the report log, backups and the newest completed period are never removed.')
