"""Review retention: expired, completed review periods and the records they exclusively own. Separate from source retention.

What can be removed. Only a period that is *completed* (Approved, Closed or Approved / closed), whose completion timestamp is known and older than the retention
period (default 24 months), and whose records can be shown to belong to it alone. For such a period the following are removed together:
* its entry in the period index (a deletion record stays in the index: id, name, state, counts, time, reason, who/what removed it),
* its decision events, risk acceptances and remediation actions (the context `<period>` of the decisions store) and its legacy risk review events,
* the private snapshot files only it references: its frozen period snapshots, retained decision evidence and review finding snapshots.
What stays. The report log (issued reports are audit evidence; entries are small and nothing joins them to the period), every other period and the current
review context, source data (source retention ages it, by reference, once no retained period names it), configuration and backups.

Protected, never removed automatically:
* periods that are not completed (Draft, In review, Ready for approval, Rejected) and periods without a reliable completion timestamp,
* anything within the retention period, and the newest completed period (the baseline for the next comparison),
* periods with open remediation actions, with risk acceptances that have not expired, with a snapshot that fails its integrity check,
  or that serve as the comparison baseline of a report belonging to a retained period (ownership cannot be established safely),
* evidence that anything else still references: after the removal the whole data directory is scanned for identifiers and only files that nothing names any more
  are moved away, so shared evidence is preserved without a rule for each reference field.

Safe cleanup. Cross-store atomicity is *not* claimed: the period index, decisions store, review store and snapshot files are separate files. Instead the removal is a
journalled, idempotent roll-forward: the journal and a full copy of the removed JSON records are written first, the stores are rewritten by id (running it twice
changes nothing), and files are moved to a trash folder rather than deleted. An interrupted run is completed by the next one, a finished run can be undone while its
copy and trash are kept (30 days), and only then are they purged. The cleanup history is bounded."""
import json
import logging
import os
import re
import shutil
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import sod_decisions as decisions
import sod_periods as periods
import sod_reviews as reviews
from config import atomic_write, config_dir

logger = logging.getLogger('sap-lens')
KEEP_NEWEST_COMPLETED = 1
GRACE_DAYS = 30
FOLDER = 'data-retention'
HEX = re.compile(r'[a-f0-9]{64}')
OWNED_KINDS = {'sod-period', 'sod-decision-evidence', 'sod-review-finding'}
OPEN_ACTIONS = {'Open', 'In progress'}


def _root():
    return config_dir() / FOLDER


def completion(period):
    """When the period was completed, from the system-recorded transition into a completed state (the latest one: Closed follows Approved).

    The approval date field is entered by a person and can be any date, so it is not a reliable moment; a period with no recorded transition returns None and
    is protected until retention has classified it (see `plan`)."""
    stamps = []
    for event in period.history:
        if event.to_state in periods.FROZEN:
            try:
                stamps.append(datetime.fromisoformat(event.timestamp))
            except ValueError:
                continue
    stamps = [item if item.tzinfo else item.replace(tzinfo=timezone.utc) for item in stamps]
    return (max(stamps), 'recorded transition') if stamps else (None, '')


def _ids(value):
    return set(HEX.findall(json.dumps(value, default=str)))


def plan(months, now=None, seen=None):
    """Eligible and protected review periods with the reason for each. Pure measurement; `seen` maps `period:<id>` to the moment retention first classified a
    period that has no recorded completion, which is then aged from that moment (first sightings are returned in `observed`)."""
    seen = seen or {}
    observed = {}
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=months * 30.4375)
    index = periods.read()
    stored = decisions.read()
    legacy = reviews.read()
    candidates, protected = [], []
    def keep(period, reason):
        protected.append(dict(id=period.id, name=period.name, state=period.state, reason=reason))
    completed = []
    for period in index.items:
        if period.state not in periods.FROZEN:
            keep(period, 'Active or incomplete review period')
            continue
        moment, how = completion(period)
        if moment is None:
            try:
                moment, how = datetime.fromisoformat(seen['period:' + period.id]), 'first classified by retention'
            except (KeyError, ValueError):
                observed['period:' + period.id] = now.isoformat()
                keep(period, 'No reliable completion timestamp (protected until classified)')
                continue
            moment = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
        completed.append((moment, period, how))
    completed.sort(key=lambda row: row[0], reverse=True)
    newest = {row[1].id for row in completed[:KEEP_NEWEST_COMPLETED]}
    for moment, period, how in completed:
        kinds = stored.contexts.get(period.id, {})
        actions = [item for item in stored.actions.values() if item.context == period.id]
        acceptances = [event for events in kinds.get('acceptance', {}).values() for event in events if event.expires]
        if moment > cutoff:
            keep(period, 'Within the retention period')
        elif period.id in newest:
            keep(period, 'Newest completed period (comparison baseline)')
        elif any(item.status in OPEN_ACTIONS for item in actions):
            keep(period, 'Open remediation actions')
        elif any(event.expires >= now.date() for event in acceptances):
            keep(period, 'Risk acceptance has not expired')
        else:
            try:
                periods.snapshot(period)
            except Exception:  # noqa: BLE001 - HTTPException from an unreadable or mismatching snapshot
                keep(period, 'Snapshot integrity could not be verified')
                continue
            candidates.append((moment, how, period, actions))
    eligible = {row[2].id for row in candidates}
    items = []
    for moment, how, period, actions in candidates:
        dependents = [item for item in stored.reports if item.previous_period_id == period.id and item.period_id != period.id and item.period_id not in eligible
                      and any(row.id == item.period_id for row in index.items)]
        if dependents:
            keep(period, 'Baseline of a report belonging to a retained period')
            continue
        kinds = stored.contexts.get(period.id, {})
        items.append(dict(category='review periods', kind='review', id=period.id, name=period.name, state=period.state, completed=moment.isoformat(), basis=how,
                          age_days=int((now - moment).total_seconds() / 86400),
                          decisions=sum(len(events) for subjects in kinds.values() for events in subjects.values()), actions=len(actions),
                          legacy_reviews=sum(len(events) for events in legacy.contexts.get(period.id, {}).values()), snapshots=len(period.snapshots), bytes=0, path=''))
    items.sort(key=lambda row: (row['completed'], row['id']))
    reasons = {}
    for row in protected:
        reasons[row['reason']] = reasons.get(row['reason'], 0) + 1
    return dict(items=items, protected=protected, reasons=reasons, observed=observed)


# --- journalled removal -----------------------------------------------------------------------------------------------------------------

def _journal_path():
    return _root() / 'journal.json'


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_write(path, json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8'))


def _remove_from_stores(ids, record, stamp):
    """Idempotent: removes the listed periods' records from the three stores and leaves a deletion record per period. Returns the counts actually removed."""
    removed = dict(periods=0, decisions=0, actions=0, legacy_reviews=0)
    with periods.lock, reviews.lock, decisions.lock:
        index = periods.read()
        gone = [item for item in index.items if item.id in ids]
        if gone:
            for item in gone:
                counts = record.get('counts', {}).get(item.id, {})
                index.deletions = [*index.deletions, periods.Deletion(id=item.id, name=item.name, state=item.state, mode='permanent', timestamp=stamp, actor='data-retention',
                                                                      counts=counts, reason=f'Data retention: completed {record["completed"].get(item.id, "")[:10]}, older than {record["months"]} months.',
                                                                      frozen=True)][-500:]
            index.items = [item for item in index.items if item.id not in ids]
            index.revision += 1
            periods.write(index)
            removed['periods'] = len(gone)
        store = decisions.read()
        events = sum(len(events) for context in ids for subjects in store.contexts.get(context, {}).values() for events in subjects.values())
        actions = [key for key, item in store.actions.items() if item.context in ids]
        if events or actions or any(context in store.contexts for context in ids):
            for context in ids:
                store.contexts.pop(context, None)
            for key in actions:
                store.actions.pop(key)
            store.revision += 1
            decisions._write(store)
            removed['decisions'], removed['actions'] = events, len(actions)
        legacy = reviews.read()
        count = sum(len(events) for context in ids for events in legacy.contexts.get(context, {}).values())
        if any(context in legacy.contexts for context in ids):
            for context in ids:
                legacy.contexts.pop(context, None)
            legacy.revision += 1
            reviews._write(legacy)
            removed['legacy_reviews'] = count
    return removed


def _owned_files(candidate_ids, exclude):
    """Files named by the removed records that nothing else references any more and that are of an owned kind."""
    import data_retention
    snapshots, _ = data_retention._listing()
    still = data_retention.referenced([item for item in snapshots if item['id'] not in exclude])
    moved = []
    for entry in snapshots:
        if entry['id'] in candidate_ids and entry['id'] not in still:
            try:
                kind = json.loads(entry['path'].read_bytes()).get('source')
            except (OSError, ValueError):
                continue
            if kind in OWNED_KINDS:
                moved.append(entry)
    return moved


def _move_files(operation, ids, bundle_ids, stamp):
    trash = _root() / 'trash' / operation
    moved = []
    for entry in _owned_files(bundle_ids, exclude=set(bundle_ids)):
        path = entry['path']
        if path.is_symlink() or not path.is_file():
            continue
        trash.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.replace(path, trash / path.name)
        moved.append(entry['id'])
    return moved


def execute(months, actor='data-retention', now=None):
    """Re-plan, journal, remove from the stores, move exclusive files to trash. Returns counts."""
    import data_retention
    now = now or datetime.now(timezone.utc)
    recover(now)
    with periods.lock, reviews.lock, decisions.lock:
        found = plan(months, now, data_retention.read().first_seen)
        ids = [item['id'] for item in found['items']]
        if not ids:
            return dict(periods=0, decisions=0, actions=0, legacy_reviews=0, files=0, operation='')
        operation = uuid4().hex
        index = periods.read()
        stored = decisions.read()
        legacy = reviews.read()
        bundle = dict(version=1, operation=operation, at=now.isoformat(), months=months, actor=actor,
                      completed={item['id']: item['completed'] for item in found['items']},
                      counts={item['id']: dict(decisions=item['decisions'], actions=item['actions'], legacy_reviews=item['legacy_reviews'], snapshots=item['snapshots']) for item in found['items']},
                      periods=[item.model_dump(mode='json') for item in index.items if item.id in ids],
                      decisions={context: json.loads(json.dumps({kind: {key: [event.model_dump(mode='json') for event in events] for key, events in subjects.items()}
                                                                 for kind, subjects in stored.contexts.get(context, {}).items()})) for context in ids},
                      actions=[item.model_dump(mode='json') for item in stored.actions.values() if item.context in ids],
                      legacy_reviews={context: {finding: [event.model_dump(mode='json') for event in events] for finding, events in legacy.contexts.get(context, {}).items()} for context in ids})
        bundle['files'] = sorted(_ids(bundle))
        _write_json(_root() / 'removed' / f'{operation}.json', bundle)                  # the full copy exists before anything is changed
        _write_json(_journal_path(), dict(operation=operation, phase='prepared', ids=ids, at=now.isoformat(), months=months,
                                          completed=bundle['completed'], counts=bundle['counts'], files=bundle['files']))
        removed = _remove_from_stores(set(ids), bundle, now.isoformat())
        _write_json(_journal_path(), dict(json.loads(_journal_path().read_text()), phase='stores_committed'))
        moved = _move_files(operation, ids, bundle['files'], now.isoformat())
        _journal_path().unlink(missing_ok=True)
        data_retention.record_review_cleanup(removed, len(moved), months, actor, now)
        return dict(removed, files=len(moved), operation=operation)


def recover(now=None):
    """Complete an interrupted removal (roll forward): the journal names the periods; removal by id is idempotent, then the exclusive files are moved."""
    path = _journal_path()
    if not path.is_file():
        return None
    try:
        journal = json.loads(path.read_text())
        bundle = json.loads((_root() / 'removed' / f'{journal["operation"]}.json').read_text())
    except (OSError, ValueError, KeyError):
        logger.warning('An interrupted review retention run could not be read; nothing further is removed until it is resolved.')
        raise RuntimeError('Review retention journal is unreadable.') from None
    ids = set(journal['ids'])
    _remove_from_stores(ids, bundle, journal['at'])
    _move_files(journal['operation'], list(ids), bundle['files'], journal['at'])
    path.unlink(missing_ok=True)
    return journal['operation']


def undo(operation):
    """Put back what an earlier run removed, from its copy and trash. Refuses when any of the periods exists again or the copy is gone."""
    if not re.fullmatch(r'[a-f0-9]{32}', operation):
        raise ValueError('Invalid operation.')
    path = _root() / 'removed' / f'{operation}.json'
    if not path.is_file():
        raise ValueError('The copy of this cleanup is no longer retained.')
    bundle = json.loads(path.read_text())
    with periods.lock, reviews.lock, decisions.lock:
        index = periods.read()
        ids = {item['id'] for item in bundle['periods']}
        if ids & {item.id for item in index.items}:
            raise ValueError('A period of this cleanup exists again; nothing was restored.')
        index.items = [*index.items, *[periods.Period.model_validate(item) for item in bundle['periods']]]
        index.deletions = [item for item in index.deletions if not (item.id in ids and item.actor == 'data-retention')]
        index.revision += 1
        periods.write(index)
        store = decisions.read()
        for context, kinds in bundle['decisions'].items():
            if kinds:
                store.contexts[context] = {kind: {key: [decisions.Event.model_validate(event) for event in events] for key, events in subjects.items()} for kind, subjects in kinds.items() if subjects}
        for item in bundle['actions']:
            store.actions[item['id']] = decisions.Action.model_validate(item)
        store.revision += 1
        decisions._write(store)
        legacy = reviews.read()
        for context, findings in bundle['legacy_reviews'].items():
            if findings:
                legacy.contexts[context] = {finding: [reviews.ReviewEvent.model_validate(event) for event in events] for finding, events in findings.items()}
        legacy.revision += 1
        reviews._write(legacy)
        restored = 0
        trash = _root() / 'trash' / operation
        target = config_dir() / 'csv-data' / 'snapshots'
        if trash.is_dir():
            for item in trash.glob('*.json'):
                os.replace(item, target / item.name)
                restored += 1
            shutil.rmtree(trash, ignore_errors=True)
    path.unlink(missing_ok=True)
    return dict(periods=len(ids), files=restored)


def purge_expired(now=None):
    """Delete copies and trash of cleanups older than the grace period (judged by the time recorded in the copy, not by file times)."""
    now = now or datetime.now(timezone.utc)
    purged = 0
    for path in sorted((_root() / 'removed').glob('*.json')) if (_root() / 'removed').is_dir() else []:
        try:
            at = datetime.fromisoformat(json.loads(path.read_text())['at'])
        except (OSError, ValueError, KeyError):
            continue                                                  # unreadable: kept
        if now - at >= timedelta(days=GRACE_DAYS):
            shutil.rmtree(_root() / 'trash' / path.stem, ignore_errors=True)
            path.unlink(missing_ok=True)
            purged += 1
    return purged


def public(found):
    sample = [{key: value for key, value in item.items() if key not in {'path'}} for item in found['items'][:100]]
    return dict(count=len(found['items']), protected=len(found['protected']), reasons=found['reasons'], sample=sample, truncated=len(found['items']) > 100,
                protected_sample=found['protected'][:100], today=date.today().isoformat())
