"""Minimal lifecycle memory for decided assignments: was it verifiably absent from the imported data, and did it come back?

Review decisions are immutable events keyed by the assignment identity (user, role, validity, group). Without lifecycle memory an assignment
that disappears from SAP and later reappears with the same identity would silently make its old decision current again, and a re-used
username would inherit the previous person's approval. This store records only what is needed to prevent that:

* only assignments that have at least one decision event are tracked (bounded by the decision store, no general SAP/AD history);
* an assignment is *absent* after a validated users revision that does not contain it while the user is either fully mapped (verified
  absence) or not in the source at all (the identity is gone); users that are present but only partly mapped are *ambiguous*: nothing changes;
* when an absent assignment is found again, `reappeared_at` is set. The old decision then reads **Outdated** (reason: reappeared) until a new
  decision event is recorded after that moment. Decision events, evidence and frozen review periods are never modified; the status is derived.

Identity continuity: the only identifiers the imports provide beyond the username are the SAP e-mail address and the first/last name of the users
file (the Employee Directory is matched through that same e-mail, so it adds no independent evidence; addresses shared by several SAP users are ignored,
as in the directory matching). Salted-free SHA-256 tokens of them are kept per tracked assignment. When both the recorded and the current user carry
evidence and share none of it, the person behind the username is treated as different: the earlier decision reads Outdated (reason: identity changed).
Missing evidence on either side proves nothing and changes nothing.

Fail safe: if this memory cannot be trusted (file damaged or failing its checksum, missing although it was established before, or older than the
newest state this installation knew, e.g. after restoring an old backup), every assignment decision reads Outdated (reason: continuity cannot be
confirmed) until an administrator re-baselines. Imports and the rest of the application are unaffected. Decision events are never modified.

The file is a validated JSON store (included in backups) and is updated only from committed source revisions (`observe`, idempotent per
users+catalogue revision)."""
import hashlib
import json
import logging
import re
import shutil
import threading
from datetime import datetime, timezone
from typing import Literal

from pydantic import Field

import cache
import sod_decisions
from config import atomic_write, config_dir, get_settings
from config_models import StrictModel

logger = logging.getLogger('sap-lens')
HEX64 = r'^[a-f0-9]{64}$'
MAX_ITEMS = 500_000
MAX_BYTES = 128 * 1024 * 1024
lock = threading.RLock()
FAR_FUTURE = '9999-12-31T00:00:00+00:00'
REAPPEARED = 'Assignment reappeared after it was removed from the SAP import; review it again. The earlier decision stays in history.'
IDENTITY = 'SAP user identity evidence (e-mail and name) changed since this assignment was reviewed; review it again. The earlier decision stays in history.'
UNAVAILABLE = 'Review continuity data is unavailable or cannot be trusted, so the earlier decision cannot be confirmed for the same identity; review it again or re-baseline in Data Health. The earlier decision stays in history.'
TEXTS = dict(reappeared=REAPPEARED, identity=IDENTITY)


class Item(StrictModel):
    state: Literal['present', 'absent']
    absent_since: str = Field(default='', max_length=40)
    absent_source: str = Field(default='', max_length=140)
    reappeared_at: str = Field(default='', max_length=40)
    reappeared_source: str = Field(default='', max_length=140)
    reason: Literal['', 'reappeared', 'identity'] = ''
    identity: list[str] = Field(default_factory=list, max_length=12)


class Storage(StrictModel):
    version: Literal[1] = 1
    revision: int = Field(default=0, ge=0)
    observed_source: str = Field(default='', max_length=140)
    baseline: dict[str, str] = Field(default_factory=dict, max_length=4)
    digest: str = Field(default='', max_length=64)
    items: dict[str, Item] = Field(default_factory=dict, max_length=MAX_ITEMS)

    def sealed(self):
        body = self.model_dump(exclude={'digest'}, mode='json')
        return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _path():
    return config_dir() / 'assignment-lifecycle.json'


class _Everything(dict):
    """Mapping that answers every key: used when no decision can be confirmed."""

    def get(self, key, default=None):
        return FAR_FUTURE

    def __contains__(self, key):
        return True

    def __bool__(self):
        return True   # an empty dict subclass is falsy; this one answers for every key


class _Always(dict):
    def get(self, key, default=None):
        return UNAVAILABLE

    def __bool__(self):
        return True


_cache = {}
_established = {}   # process cache of the store's record of the newest lifecycle revision this installation has written


def _scope():
    """Process caches belong to one data directory (tests and tools switch directories)."""
    here = str(config_dir())
    if _established.get('dir') != here:
        _established.clear()
        _cache.clear()
        _established['dir'] = here


def _meta():
    """Newest revision ever written here, from the (backup-excluded) SQLite store; None if unknown. A restored older file reads as stale against it."""
    _scope()
    if 'value' not in _established:
        try:
            import store_db
            connection = store_db.connect(create=False)
            try:
                row = connection.execute("SELECT value FROM meta WHERE key='lifecycle_revision'").fetchone()
                _established['value'] = int(row[0]) if row else None
            finally:
                connection.close()
        except Exception:  # noqa: BLE001 - no store: continuity then rests on the file alone
            _established['value'] = None
    return _established['value']


def _record_meta(revision):
    _scope()
    try:
        import store_db
        with store_db.transaction() as connection:
            connection.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('lifecycle_revision', ?)", (str(revision),))
        _established['value'] = revision
    except Exception:  # noqa: BLE001
        _established.pop('value', None)


def load():
    """(Storage, state, detail): state is 'ok', 'corrupt', 'missing' or 'stale'. Anything but 'ok' means continuity cannot be trusted."""
    _scope()
    path = _path()
    try:
        stat = path.stat()
        key = (stat.st_mtime_ns, stat.st_size, _established.get('value', '?'))
    except OSError:
        key = None
    if key is not None and _cache.get('key') == key:
        return _cache['value']
    if key is None:
        meta = _meta()
        value = (Storage(), 'missing', 'The lifecycle file is missing although this installation had written one before.') if meta is not None else (Storage(), 'ok', '')
    else:
        try:
            raw = path.read_bytes()
            if len(raw) > MAX_BYTES:
                raise ValueError()
            data = Storage.model_validate_json(raw)
            if any(not re.fullmatch(HEX64, name) for name in data.items) or data.digest and data.digest != data.sealed():
                raise ValueError()
            meta = _meta()
            if meta is not None and data.revision < meta:
                value = (data, 'stale', f'The lifecycle file (revision {data.revision}) is older than the newest known state (revision {meta}), for example after restoring an old backup.')
            else:
                value = (data, 'ok', '')
        except (OSError, ValueError, TypeError, RecursionError):
            value = (Storage(), 'corrupt', 'The lifecycle file is unreadable or failed its integrity check.')
    _cache.clear()
    _cache.update(key=(key[0], key[1], _established.get('value', '?')) if key else None, value=value)
    if key is None:
        _cache['key'] = None
    return value


def read():
    return load()[0]


def fingerprint():
    """Changes whenever applicability() can change: the stored file's identity and the newest revision this installation recorded."""
    _scope()
    try:
        stat = _path().stat()
        stored = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
    except OSError:
        stored = None
    return (_established.get('dir'), stored, _meta())


def _write(data):
    data = data.model_copy(update=dict(digest=''))
    data = data.model_copy(update=dict(digest=data.sealed()))
    atomic_write(_path(), Storage.model_validate(data.model_dump()).model_dump_json().encode('utf-8'))
    _record_meta(data.revision)
    _cache.clear()


class Applicability:
    """What the review views need: when each assignment decision stops applying and why. Cheap enough for every request."""

    def __init__(self, map_, reasons, state, detail):
        self.map, self.reasons, self.state, self.detail = map_, reasons, state, detail


def applicability():
    data, state, detail = load()
    if state != 'ok':
        return Applicability(_Everything(), _Always(), state, detail)
    return Applicability({key: item.reappeared_at for key, item in data.items.items() if item.reappeared_at},
                         {key: TEXTS[item.reason or 'reappeared'] for key, item in data.items.items() if item.reappeared_at}, 'ok', '')


def reappeared():
    return applicability().map


def problems():
    """For Data Health: (integrity problem or '', decided assignments affected by it, assignments awaiting a new review because they came back / changed identity)."""
    data, state, detail = load()
    events = decided_events()
    if state != 'ok':
        return dict(state=state, detail=detail, affected=[dict(key=key, user=event.user, role=event.ref) for key, event in events.items()], pending=[])
    pending = [dict(key=key, user=events[key].user, role=events[key].ref, reason=item.reason or 'reappeared') for key, item in data.items.items()
               if item.reappeared_at and key in events and events[key].timestamp < item.reappeared_at]
    return dict(state='ok', detail='', affected=[], pending=pending)


def decided_events():
    result = {}
    for kinds in sod_decisions.read().contexts.values():
        for key, events in kinds.get('assignment', {}).items():
            if events and (key not in result or events[-1].timestamp > result[key].timestamp):
                result[key] = events[-1]
    return result


def tokens(record, shared):
    """Hashed identity evidence of one SAP user from the users file: unshared e-mail addresses and complete names."""
    digest = lambda text: hashlib.sha256(text.encode()).hexdigest()[:20]  # noqa: E731
    found = {digest('mail:' + email.strip().casefold()) for email in record.get('emails', ()) if email.strip() and email.strip().casefold() not in shared}
    found |= {digest('name:' + first.strip().casefold() + ' ' + last.strip().casefold()) for first, last in record.get('names', ()) if first.strip() and last.strip()}
    return sorted(found)[:12]


def rebaseline(actor='administrator'):
    """Administrator acknowledges the current data as the continuity baseline: decisions apply again from now on, a damaged file is kept aside."""
    with lock:
        path = _path()
        if path.exists():
            try:
                shutil.copy2(path, path.with_name(path.name + '.before-rebaseline-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')))
            except OSError:
                pass
        old = load()[0]
        meta = _meta() or 0
        _write(Storage(revision=max(old.revision, meta) + 1, baseline=dict(by=actor[:120], at=datetime.now(timezone.utc).isoformat())))
        return observe()


def decided():
    """assignment key -> normalized username for every assignment that has at least one decision event in any review context."""
    from user_access import normalize_username
    return {key: normalize_username(event.user) for key, event in decided_events().items()}


def observe():
    """Compare the decided assignments with the active users revision. Returns 'current', 'unassessable', 'blocked' or the number of changed items."""
    from employee_directory import sap_email_owners
    from sod_scope import verification_population
    settings = get_settings()
    users_state = cache.get_snapshot().users
    ids, complete, reference = verification_population()
    users_reference = settings.data_lifecycle.sources.get('users')
    roles_reference = settings.data_lifecycle.sources.get('roles')
    if ids is None or not reference or not users_reference or not users_state.users:
        return 'unassessable'      # SoD or user mapping unavailable: absence cannot be established, nothing changes
    marker = f'{users_reference.snapshot}:{roles_reference.snapshot if roles_reference else ""}'
    present_users = set(users_state.users)
    with lock:
        data, state, _ = load()
        if state != 'ok':
            return 'blocked'       # untrusted memory is never repaired silently; an administrator re-baselines
        if data.observed_source == marker:
            return 'current'
        if cache.get_snapshot().users is not users_state:
            return 'unassessable'  # a newer dataset was published while this ran; the next load observes it
        shared = {email for email, count in sap_email_owners(users_state.users.values()).items() if count > 1}
        stamp = datetime.now(timezone.utc).isoformat()
        changed = 0
        for key, user in decided().items():
            item = data.items.get(key)
            if key in ids:
                current = tokens(users_state.users.get(user, {}), shared)
                if item and item.state == 'absent':
                    data.items[key] = item.model_copy(update=dict(state='present', reappeared_at=stamp, reappeared_source=marker, reason='reappeared', identity=current or item.identity))
                    changed += 1
                elif item and item.identity and current and not set(item.identity) & set(current):
                    # Same username, same assignment, but nothing of the recorded person's evidence remains: probably someone else.
                    data.items[key] = item.model_copy(update=dict(reappeared_at=stamp, reappeared_source=marker, reason='identity', identity=current))
                    changed += 1
                elif not item or (current and current != item.identity):
                    data.items[key] = (item or Item(state='present')).model_copy(update=dict(identity=current or (item.identity if item else [])))
            elif user in complete or user not in present_users:
                # Verified absence of the assignment, or the identity itself is gone from the source (a later user of the same name is not the same person).
                if not item or item.state != 'absent':
                    data.items[key] = (item or Item(state='present')).model_copy(update=dict(state='absent', absent_since=stamp, absent_source=marker))
                    changed += 1
            # present but only partly mapped (ambiguous): neither absent nor present, no change
        data.observed_source = marker
        data.revision += 1 if changed or data.revision == 0 else 0
        _write(data)
        return changed
