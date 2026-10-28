"""Department and job title changes between successive validated Employee Directory snapshots.

Detected when a replacement snapshot is published and kept as private local evidence. Manager-only changes, missing values,
formatting-only differences, ambiguous identities and suspiciously incomplete imports never create a change. A change is a
review prompt, not a finding about access appropriateness."""
import hashlib
import json
import logging
import re
import threading
import unicodedata
from datetime import datetime, timedelta, timezone

from config import atomic_write, config_dir

lock = threading.RLock()
MAX_BYTES = 8 * 1024 * 1024
MAX_EVENTS = 5000
RECENT_DAYS = 90
FIELDS = (('Department', 'department'), ('Title', 'title'))
MIN_COMPLETE_SHARE = 0.5  # a replacement with fewer than half of the previous records is treated as incomplete


def normalize_text(value):
    """Case, spacing and Unicode-form differences are formatting only."""
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', value or '')).strip().casefold()


def email_key(record):
    return normalize_text(record.get('Mail', ''))


def _unique_by_mail(rows):
    seen, duplicates = {}, set()
    for record in rows:
        key = email_key(record)
        if not key:
            continue
        if key in seen:
            duplicates.add(key)
        seen[key] = record
    return {key: record for key, record in seen.items() if key not in duplicates}


def _blank_share(rows, field):
    return sum(not (record.get(field) or '').strip() for record in rows) / max(1, len(rows))


def detect(previous, current, detected_at):
    """-> (events, notices) for two Directory objects. Pure: nothing is stored."""
    if previous is None or current is None or previous.digest == current.digest:
        return [], []
    if len(current.rows) < MIN_COMPLETE_SHARE * len(previous.rows):
        return [], ['The replacement directory has far fewer records than the previous one, so no position changes were derived from it.']
    fields, notices = [], []
    for source, label in FIELDS:
        if _blank_share(current.rows, source) - _blank_share(previous.rows, source) > 0.5:
            notices.append(f'The replacement directory has mostly empty {label} values, so {label} changes were not derived from it.')
        else:
            fields.append((source, label))
    old, new, events = _unique_by_mail(previous.rows), _unique_by_mail(current.rows), []
    for key, record in new.items():
        before = old.get(key)
        if before is None:
            continue
        changed = [label for source, label in fields if (before.get(source) or '').strip() and (record.get(source) or '').strip()
                   and normalize_text(before[source]) != normalize_text(record[source])]
        if not changed:
            continue
        events.append(dict(
            id=hashlib.sha256(f'{key}|{current.digest}'.encode()).hexdigest(), key=key, email=record.get('Mail', '').strip(), name=record.get('Name', '').strip(),
            ad_username=record.get('SamAccountName', '').strip(), fields=changed,
            previous_department=before.get('Department', '').strip(), current_department=record.get('Department', '').strip(),
            previous_title=before.get('Title', '').strip(), current_title=record.get('Title', '').strip(),
            detected_at=detected_at, source_generation=current.digest, previous_generation=previous.digest))
    return sorted(events, key=lambda event: event['key']), notices


def _validate(event):
    if not isinstance(event, dict) or not re.fullmatch(r'[a-f0-9]{64}', str(event.get('id', ''))):
        raise ValueError()
    datetime.fromisoformat(event['detected_at'])
    for name in ('key', 'email', 'name', 'ad_username', 'previous_department', 'current_department', 'previous_title', 'current_title', 'source_generation', 'previous_generation'):
        if not isinstance(event[name], str) or len(event[name]) > 4096:
            raise ValueError()
    if not isinstance(event['fields'], list) or not set(event['fields']) <= {'department', 'title'}:
        raise ValueError()


def read():
    path = config_dir() / 'position-changes.json'
    try:
        if not path.exists():
            return dict(events=[], notice=None)
        with path.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        data = json.loads(raw) if len(raw) <= MAX_BYTES else None
        if not isinstance(data, dict) or data.get('format') != 1 or not isinstance(data.get('events'), list):
            raise ValueError()
        for event in data['events']:
            _validate(event)
        return dict(events=data['events'], notice=data.get('notice'))
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        logging.getLogger('sap-lens').warning('Position change records could not be read; none are shown until the next directory replacement.')
        return dict(events=[], notice='Position change records could not be read.')


def record(previous, current, now=None):
    """Store changes for a published replacement; idempotent per (identity, source generation)."""
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    events, notices = detect(previous, current, stamp)
    if previous is None or current is None or previous.digest == current.digest:
        return 0
    with lock:
        stored = read()
        known = {event['id'] for event in stored['events']}
        added = [event for event in events if event['id'] not in known]
        merged = [*stored['events'], *added]
        merged = sorted(merged, key=lambda event: (event['detected_at'], event['id']))[-MAX_EVENTS:]
        raw = json.dumps(dict(format=1, events=merged, notice=' '.join(notices) or None), ensure_ascii=False, separators=(',', ':')).encode()
        if len(raw) <= MAX_BYTES:
            atomic_write(config_dir() / 'position-changes.json', raw)
    return len(added)


def record_safely(previous, current):
    """Never blocks or fails a directory publication."""
    try:
        return record(previous, current)
    except Exception:  # noqa: BLE001 - detection is advisory evidence
        logging.getLogger('sap-lens').warning('Position changes could not be recorded; the directory import is unaffected.')
        return 0


def latest_recent(events, today=None):
    """Newest recent change per employee e-mail."""
    cutoff = datetime.combine(today or datetime.now(timezone.utc).date(), datetime.min.time(), tzinfo=timezone.utc) - timedelta(days=RECENT_DAYS)
    latest = {}
    for event in sorted(events, key=lambda event: (event['detected_at'], event['id'])):
        if datetime.fromisoformat(event['detected_at']) >= cutoff:
            latest[event['key']] = event
    return latest
