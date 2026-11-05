"""Minimal lifecycle memory for decided assignments: was it verifiably absent from the imported data, and did it come back?

Review decisions are immutable events keyed by the assignment identity (user, role, validity, group). Without lifecycle memory an assignment
that disappears from SAP and later reappears with the same identity would silently make its old decision current again, and a re-used
username would inherit the previous person's approval. This store records only what is needed to prevent that:

* only assignments that have at least one decision event are tracked (bounded by the decision store, no general SAP/AD history);
* an assignment is *absent* after a validated users revision that does not contain it while the user is either fully mapped (verified
  absence) or not in the source at all (the identity is gone); users that are present but only partly mapped are *ambiguous*: nothing changes;
* when an absent assignment is found again, `reappeared_at` is set. The old decision then reads **Outdated** (reason: reappeared) until a new
  decision event is recorded after that moment. Decision events, evidence and frozen review periods are never modified; the status is derived.

The file is a validated JSON store (included in backups) and is updated only from committed source revisions (`observe`, idempotent per
users+catalogue revision)."""
import logging
import re
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
REASON = 'Assignment reappeared after it was removed from the SAP import; review it again. The earlier decision is kept in history.'


class Item(StrictModel):
    state: Literal['present', 'absent']
    absent_since: str = Field(default='', max_length=40)
    absent_source: str = Field(default='', max_length=140)
    reappeared_at: str = Field(default='', max_length=40)
    reappeared_source: str = Field(default='', max_length=140)


class Storage(StrictModel):
    version: Literal[1] = 1
    revision: int = Field(default=0, ge=0)
    observed_source: str = Field(default='', max_length=140)
    items: dict[str, Item] = Field(default_factory=dict, max_length=MAX_ITEMS)


def _path():
    return config_dir() / 'assignment-lifecycle.json'


def read():
    path = _path()
    if not path.exists():
        return Storage()
    try:
        raw = path.read_bytes()
        if len(raw) > MAX_BYTES:
            raise ValueError()
        value = Storage.model_validate_json(raw)
        if any(not re.fullmatch(HEX64, key) for key in value.items):
            raise ValueError()
        return value
    except (OSError, ValueError, TypeError, RecursionError):
        # Unreadable lifecycle memory must not hide decisions or stop the application; without it nothing is marked reappeared.
        logger.warning('Assignment lifecycle metadata is unreadable; reappearance cannot be assessed until it is restored from a backup.')
        return Storage()


def _write(data):
    atomic_write(_path(), Storage.model_validate(data.model_dump()).model_dump_json().encode('utf-8'))


def reappeared():
    """assignment key -> when it reappeared (only items whose decisions predate that moment matter; the caller compares timestamps)."""
    return {key: item.reappeared_at for key, item in read().items.items() if item.reappeared_at}


def decided():
    """assignment key -> normalized username for every assignment that has at least one decision event in any review context."""
    from user_access import normalize_username
    result = {}
    for kinds in sod_decisions.read().contexts.values():
        for key, events in kinds.get('assignment', {}).items():
            if events:
                result[key] = normalize_username(events[-1].user)
    return result


def observe():
    """Compare the decided assignments with the active users revision. Returns 'current', 'unassessable' or the number of changed items."""
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
        data = read()
        if data.observed_source == marker:
            return 'current'
        if cache.get_snapshot().users is not users_state:
            return 'unassessable'  # a newer dataset was published while this ran; the next load observes it
        stamp = datetime.now(timezone.utc).isoformat()
        changed = 0
        for key, user in decided().items():
            item = data.items.get(key)
            if key in ids:
                if item and item.state == 'absent':
                    data.items[key] = item.model_copy(update=dict(state='present', reappeared_at=stamp, reappeared_source=marker))
                    changed += 1
            elif user in complete or user not in present_users:
                # Verified absence of the assignment, or the identity itself is gone from the source (a later user of the same name is not the same person).
                if not item or item.state != 'absent':
                    data.items[key] = Item(state='absent', absent_since=stamp, absent_source=marker, reappeared_at=item.reappeared_at if item else '',
                                           reappeared_source=item.reappeared_source if item else '')
                    changed += 1
            # present but only partly mapped (ambiguous): neither absent nor present, no change
        data.observed_source = marker
        if changed or data.revision == 0:
            data.revision += 1
        _write(data)
        return changed
