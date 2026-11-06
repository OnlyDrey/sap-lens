"""Functional Groups: the business function a person performs, maintained locally by reviewers.

One JSON store (`functional-groups.json`, format 1) holds the global catalogue, one classification per canonical SAP user,
an append-only history and the advisory suggestion rules. It is deliberately independent of Directory Department, Job Title and
SAP User Group: Directory imports never write here, they can only flag an existing classification as `Needs review`
(see `flag_for_review`). Nothing in this module changes SAP access."""
import json
import re
import threading
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException

from account_review import digest as _digest
from config import atomic_write, config_dir
from position_changes import normalize_text

lock = threading.RLock()
FORMAT = 2  # 2: many-to-many memberships. 1 (one group per user) is still accepted everywhere and migrated on read.
LEGACY_FORMAT = 1
FILE = 'functional-groups.json'
MAX_BYTES = 20 * 1024 * 1024
MAX_GROUPS = 500
MAX_HISTORY = 50000
MAX_HANDLED = 200  # remembered organizational change ids per user (idempotency window)
STATUSES = ('Unassigned', 'Confirmed', 'Needs review')
GROUP_STATES = ('active', 'archived')
EVENTS = ('assigned', 'changed', 'confirmed', 'removed', 'review_required', 'reconfirmed', 'manager_changed')
GROUP_ID = re.compile(r'^fg_[a-f0-9]{12}$')
HEX64 = re.compile(r'^[a-f0-9]{64}$')


def now():
    return datetime.now(timezone.utc).isoformat()


def user_key(username):
    """Same canonical identity as Account Review decisions: the upper-cased SAP user name."""
    return _digest(username.strip().upper())


def name_key(name):
    return normalize_text(name)


def empty():
    return dict(format=FORMAT, groups={}, users={}, history=[], rules=[])


def _validate_v1(data):
    """Legacy (format 1) persisted contract: one group per user."""
    if not isinstance(data, dict) or data.get('format') != LEGACY_FORMAT:
        raise ValueError('format')
    groups, users, history, rules = data.get('groups'), data.get('users'), data.get('history'), data.get('rules', [])
    if not isinstance(groups, dict) or not isinstance(users, dict) or not isinstance(history, list) or not isinstance(rules, list):
        raise ValueError('shape')
    if len(groups) > MAX_GROUPS or len(history) > MAX_HISTORY:
        raise ValueError('size')
    names = set()
    for gid, group in groups.items():
        if not GROUP_ID.fullmatch(gid) or not isinstance(group, dict) or group.get('id') != gid:
            raise ValueError('group id')
        name = group.get('name')
        if not isinstance(name, str) or not name.strip() or len(name) > 80 or group.get('status') not in GROUP_STATES:
            raise ValueError('group')
        if not isinstance(group.get('description', ''), str) or len(group.get('description', '')) > 500:
            raise ValueError('description')
        if name_key(name) in names:
            raise ValueError('duplicate group name')
        names.add(name_key(name))
        datetime.fromisoformat(group['created'])
        datetime.fromisoformat(group['modified'])
    for key, user in users.items():
        if not HEX64.fullmatch(key) or not isinstance(user, dict) or user.get('status') not in STATUSES:
            raise ValueError('user')
        if not isinstance(user.get('username'), str) or user_key(user['username']) != key:
            raise ValueError('user identity')
        gid = user.get('group_id')
        if gid is not None and gid not in groups:
            raise ValueError('missing group reference')
        # Status and group must agree: Unassigned has no group, the other two require one.
        if (user['status'] == 'Unassigned') != (gid is None):
            raise ValueError('status contradicts group')
        if not isinstance(user.get('revision'), int) or user['revision'] < 1:
            raise ValueError('revision')
        for field in ('confirmed_by', 'rationale'):
            if not isinstance(user.get(field, ''), str) or len(user.get(field, '')) > 2000:
                raise ValueError(field)
        for field in ('confirmed_at', 'updated_at'):
            if user.get(field):
                datetime.fromisoformat(user[field])
        review = user.get('review')
        if review is not None and (user['status'] != 'Needs review' or not isinstance(review, dict) or not isinstance(review.get('change_id'), str)):
            raise ValueError('review')
        if user['status'] == 'Needs review' and review is None:
            raise ValueError('review')
        if not isinstance(user.get('handled', []), list) or len(user.get('handled', [])) > MAX_HANDLED:
            raise ValueError('handled')
    seen = set()
    for event in history:
        if not isinstance(event, dict) or event.get('event') not in EVENTS or event.get('id') in seen or not HEX64.fullmatch(event.get('user_key', '')):
            raise ValueError('history')
        seen.add(event['id'])
        datetime.fromisoformat(event['timestamp'])
        for side in ('previous_group', 'new_group'):
            if event.get(side) is not None and event[side] not in groups:
                raise ValueError('history group reference')
        for field in ('previous_status', 'new_status'):
            if event.get(field) not in STATUSES:
                raise ValueError('history status')
        if not isinstance(event.get('actor'), str) or not isinstance(event.get('reason', ''), str) or len(event.get('reason', '')) > 2000:
            raise ValueError('history actor')
    for rule in rules:
        if not isinstance(rule, dict) or rule.get('group_id') not in groups:
            raise ValueError('rule group reference')
    return data



MEMBERSHIP_STATUSES = ('Confirmed', 'Needs review')


def migrate_v1(data):
    """Format 1 (one group per user) -> format 2. Pure and lossless: every assignment becomes one membership that keeps its status, confirmation
    metadata and review; user revisions, handled change ids and the complete history are carried over unchanged."""
    users = {}
    for key, user in data['users'].items():
        memberships = {}
        if user.get('group_id'):
            memberships[user['group_id']] = dict(status=user['status'], confirmed_at=user.get('confirmed_at') or None, confirmed_by=user.get('confirmed_by', ''),
                                                 rationale=user.get('rationale', ''), review=user.get('review'), updated_at=user.get('updated_at') or user.get('confirmed_at'))
        users[key] = dict(username=user['username'], revision=user['revision'], updated_at=user.get('updated_at'), handled=user.get('handled', []), memberships=memberships)
    # Compatibility: before format 2, Directory Department matched by equality. Existing rules keep that meaning explicitly (`department_mode: equals`), so
    # moving to substring matching never silently broadens a historical rule; new rules default to `contains` and an administrator may convert a rule.
    rules = [dict(rule, department_mode=rule.get('department_mode') or 'equals') for rule in data.get('rules', [])]
    return dict(data, format=FORMAT, users=users, rules=rules)


def _validate_v2(data):
    groups, users, history, rules = data.get('groups'), data.get('users'), data.get('history'), data.get('rules', [])
    if not isinstance(groups, dict) or not isinstance(users, dict) or not isinstance(history, list) or not isinstance(rules, list):
        raise ValueError('shape')
    # Catalogue, history and rules share the legacy rules; users are validated below. Reuse by validating a user-less legacy view.
    probe = dict(data, format=LEGACY_FORMAT, users={})
    _validate_v1(probe)
    for rule in rules:
        if rule.get('department_mode') not in (None, 'contains', 'equals') or not (rule.get('department') or rule.get('title_contains')):
            raise ValueError('rule')
    for key, user in users.items():
        if not HEX64.fullmatch(key) or not isinstance(user, dict) or not isinstance(user.get('username'), str) or user_key(user['username']) != key:
            raise ValueError('user identity')
        if not isinstance(user.get('revision'), int) or user['revision'] < 1:
            raise ValueError('revision')
        if user.get('updated_at'):
            datetime.fromisoformat(user['updated_at'])
        if not isinstance(user.get('handled', []), list) or len(user.get('handled', [])) > MAX_HANDLED:
            raise ValueError('handled')
        memberships = user.get('memberships')
        if not isinstance(memberships, dict) or len(memberships) > MAX_GROUPS:
            raise ValueError('memberships')
        for gid, member in memberships.items():
            if gid not in groups or not isinstance(member, dict) or member.get('status') not in MEMBERSHIP_STATUSES:
                raise ValueError('membership')
            for field in ('confirmed_by', 'rationale'):
                if not isinstance(member.get(field, ''), str) or len(member.get(field, '')) > 2000:
                    raise ValueError(field)
            for field in ('confirmed_at', 'updated_at'):
                if member.get(field):
                    datetime.fromisoformat(member[field])
            review = member.get('review')
            if (member['status'] == 'Needs review') != (review is not None) or (review is not None and (not isinstance(review, dict) or not isinstance(review.get('change_id'), str))):
                raise ValueError('review')
    return data


def validate_storage(data):
    """Pure persisted contract, also used before a backup restore is activated. Accepts format 2 and legacy format 1 (returned migrated, so a restored
    old backup is usable at once). Returns the data or raises ValueError."""
    if isinstance(data, dict) and data.get('format') == LEGACY_FORMAT:
        return migrate_v1(_validate_v1(data))
    if not isinstance(data, dict) or data.get('format') != FORMAT:
        raise ValueError('format')
    return _validate_v2(data)


def read():
    path = config_dir() / FILE
    try:
        if not path.exists():
            return empty()
        with path.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('size')
        parsed = json.loads(raw)
        result = validate_storage(parsed)
        if isinstance(parsed, dict) and parsed.get('format') == LEGACY_FORMAT:
            _keep_legacy_copy(path, raw)
        return result
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        raise HTTPException(409, 'Functional Group storage could not be read. The original file is retained; review local application storage before recovery.') from None


def _keep_legacy_copy(path, raw):
    """The format 1 file is preserved once, next to the store, before the first format 2 write replaces it. Best effort: failing here never blocks reading."""
    copy = path.with_name(path.name + '.format1.bak')
    try:
        if not copy.exists():
            atomic_write(copy, raw)
    except OSError:
        pass


def write(data):
    raw = json.dumps(validate_storage(data), ensure_ascii=False, separators=(',', ':')).encode()
    if len(raw) > MAX_BYTES:
        raise HTTPException(409, 'Functional Group storage is full. Existing data is retained.')
    try:
        atomic_write(config_dir() / FILE, raw)
    except OSError:
        raise HTTPException(409, 'Functional Group data could not be saved. Previous data is retained.') from None


# --- catalogue ---------------------------------------------------------------------------------------------------------

def _clean_name(name):
    name = re.sub(r'\s+', ' ', (name or '').strip())
    if not name or len(name) > 80 or any(ord(c) < 32 for c in name):
        raise HTTPException(422, 'Use a Functional Group name of 1 to 80 readable characters.')
    return name


def _ensure_unique(data, name, ignore=None):
    if any(g['id'] != ignore and name_key(g['name']) == name_key(name) for g in data['groups'].values()):
        raise HTTPException(409, f'A Functional Group named "{name}" already exists.')


def counts(data):
    """Unique users per group (a user is counted once in every group they belong to)."""
    result = {}
    for user in data['users'].values():
        for gid in user['memberships']:
            result[gid] = result.get(gid, 0) + 1
    return result


def list_groups(include_archived=True):
    data = read()
    assigned = counts(data)
    items = [dict(g, user_count=assigned.get(g['id'], 0)) for g in data['groups'].values() if include_archived or g['status'] == 'active']
    return sorted(items, key=lambda g: (g['status'] != 'active', name_key(g['name']), g['id']))


def create_group(name, description=''):
    name = _clean_name(name)
    with lock:
        data = read()
        if len(data['groups']) >= MAX_GROUPS:
            raise HTTPException(409, 'The maximum number of Functional Groups is reached.')
        _ensure_unique(data, name)
        stamp = now()
        gid = 'fg_' + uuid.uuid4().hex[:12]
        data['groups'][gid] = dict(id=gid, name=name, description=description.strip()[:500], status='active', created=stamp, modified=stamp)
        write(data)
        return data['groups'][gid]


def update_group(gid, name=None, description=None):
    with lock:
        data = read()
        group = data['groups'].get(gid)
        if group is None:
            raise HTTPException(404, 'Functional Group not found.')
        if name is not None:
            name = _clean_name(name)
            _ensure_unique(data, name, ignore=gid)
            group['name'] = name
        if description is not None:
            group['description'] = description.strip()[:500]
        group['modified'] = now()
        write(data)
        return group


def set_group_status(gid, status):
    """Archive or restore. Groups are never deleted: users and history keep referring to them."""
    with lock:
        data = read()
        group = data['groups'].get(gid)
        if group is None:
            raise HTTPException(404, 'Functional Group not found.')
        if group['status'] != status:
            group['status'] = status
            group['modified'] = now()
            write(data)
        return group


# --- classification ----------------------------------------------------------------------------------------------------

def _aggregate(memberships):
    """User-level status: Unassigned without memberships, Needs review when any membership needs it, otherwise Confirmed."""
    if not memberships:
        return 'Unassigned'
    return 'Needs review' if any(m['status'] == 'Needs review' for m in memberships.values()) else 'Confirmed'


def _public_membership(data, gid, member):
    group = data['groups'][gid]
    return dict(group_id=gid, group=dict(id=gid, name=group['name'], status=group['status']), status=member['status'], confirmed_at=member.get('confirmed_at') or None,
                confirmed_by=member.get('confirmed_by', ''), rationale=member.get('rationale', ''), review=member.get('review'))


def public_user(data, username):
    """One user's classification. `memberships` is the list of groups (by name); `group_id`/`group` and the top-level confirmation fields are kept for
    older consumers and are set only when the user has exactly one membership."""
    user = data['users'].get(user_key(username))
    if user is None:
        return dict(username=username, group_id=None, group=None, group_ids=[], memberships=[], status='Unassigned', revision=0, confirmed_at=None, confirmed_by='', rationale='', review=None)
    members = sorted((_public_membership(data, gid, m) for gid, m in user['memberships'].items()), key=lambda m: (name_key(m['group']['name']), m['group_id']))
    sole = members[0] if len(members) == 1 else None
    return dict(username=user['username'], group_id=sole['group_id'] if sole else None, group=sole['group'] if sole else None, group_ids=[m['group_id'] for m in members],
                memberships=members, status=_aggregate(user['memberships']), revision=user['revision'], confirmed_at=sole['confirmed_at'] if sole else None,
                confirmed_by=sole['confirmed_by'] if sole else '', rationale=sole['rationale'] if sole else '', review=sole['review'] if sole else None)


def classification_map(data=None):
    """{UPPER SAP USER NAME: public classification} for every user with a record; users without a record are Unassigned by default."""
    data = data or read()
    return {user['username'].strip().upper(): public_user(data, user['username']) for user in data['users'].values()}


def _event(data, user, event, group_before, group_after, status_before, status_after, actor, reason, change_id=''):
    data['history'].append(dict(
        id=uuid.uuid4().hex, event=event, user_key=user_key(user['username']), username=user['username'],
        previous_group=group_before, new_group=group_after, previous_status=status_before, new_status=status_after,
        actor=actor, timestamp=now(), reason=reason, change_id=change_id))
    if len(data['history']) > MAX_HISTORY:
        raise HTTPException(409, 'Functional Group history is full. Existing data is retained.')


def _record(data, username, expected_revision):
    """The user's record (a fresh one, revision 0, when none exists) after the optimistic revision check."""
    username = username.strip()
    if not username:
        raise HTTPException(422, 'A SAP user is required.')
    user = data['users'].get(user_key(username)) or dict(username=username, revision=0, updated_at=None, handled=[], memberships={})
    if user['revision'] != expected_revision:
        raise HTTPException(409, 'The classification changed since it was loaded. Reload before saving.')
    return user


def _commit(data, user, change_id=''):
    user['revision'] += 1
    user['updated_at'] = now()
    if change_id and change_id not in user.get('handled', []):
        user['handled'] = [*user.get('handled', []), change_id][-MAX_HANDLED:]
    data['users'][user_key(user['username'])] = user


def _add(data, user, group_id, rationale, actor, change_id=''):
    """Add or reconfirm one membership inside a loaded store. Returns 'added', 'reconfirmed' or 'unchanged' (already a Confirmed member: idempotent)."""
    group = data['groups'].get(group_id)
    if group is None:
        raise HTTPException(404, 'Functional Group not found.')
    existing = user['memberships'].get(group_id)
    if existing is not None and existing['status'] == 'Confirmed':
        return 'unchanged'
    if group['status'] == 'archived' and existing is None:
        raise HTTPException(409, 'Archived Functional Groups cannot be newly assigned. Restore the group first.')
    stamp = now()
    before = existing['status'] if existing else 'Unassigned'
    user['memberships'][group_id] = dict(status='Confirmed', confirmed_at=stamp, confirmed_by=actor, rationale=rationale.strip(), review=None, updated_at=stamp)
    _event(data, user, 'reconfirmed' if existing else 'assigned', group_id if existing else None, group_id, before, 'Confirmed', actor, rationale.strip(), change_id)
    return 'reconfirmed' if existing else 'added'


def _remove(data, user, group_id, rationale, actor, change_id=''):
    existing = user['memberships'].get(group_id)
    if existing is None:
        raise HTTPException(409, 'The user is not a member of this Functional Group.')
    del user['memberships'][group_id]
    _event(data, user, 'removed', group_id, None, existing['status'], 'Unassigned', actor, rationale.strip(), change_id)


def add_membership(username, group_id, rationale, expected_revision, actor, change_id=''):
    """Add a group to the user (or reconfirm an existing membership that needs review), keeping every other membership."""
    with lock:
        data = read()
        user = _record(data, username, expected_revision)
        outcome = _add(data, user, group_id, rationale, actor, change_id)
        if outcome != 'unchanged':
            _commit(data, user, change_id)
            write(data)
        return public_user(data, username.strip()), outcome


def remove_membership(username, group_id, rationale, expected_revision, actor, change_id=''):
    """Remove one membership; the user's other memberships, their confirmations and the history are untouched."""
    with lock:
        data = read()
        user = _record(data, username, expected_revision)
        _remove(data, user, group_id, rationale, actor, change_id)
        _commit(data, user, change_id)
        write(data)
        return public_user(data, username.strip())


def classify(username, group_id, rationale, expected_revision, actor, change_id=''):
    """Legacy single-group operation, kept for older clients: `group_id=None` removes every membership; a group makes it the only membership
    (other memberships are removed, each with its own history event). New code uses add_membership/remove_membership."""
    with lock:
        data = read()
        user = _record(data, username, expected_revision)
        if group_id is None and not user['memberships'] and user['revision'] == 0 and not change_id:
            raise HTTPException(409, 'The user has no Functional Group to clear.')
        if group_id is not None and group_id not in data['groups']:
            raise HTTPException(404, 'Functional Group not found.')
        others = [g for g in user['memberships'] if g != group_id]
        for gid in others:
            _remove(data, user, gid, rationale, actor, change_id)
        if group_id is not None:
            _add(data, user, group_id, rationale, actor, change_id)
        elif not others and change_id:
            # "Keep unassigned" for an organizational change: an explicit, auditable outcome even though nothing was held.
            _event(data, user, 'removed', None, None, 'Unassigned', 'Unassigned', actor, rationale.strip(), change_id)
        _commit(data, user, change_id)
        write(data)
        return public_user(data, username.strip())


def bulk_preview(group_ids, usernames):
    """Per user, which of the target groups would be added and which are already held (idempotent no-ops). Nothing changes."""
    data = read()
    groups = []
    for gid in group_ids:
        group = data['groups'].get(gid)
        if group is None:
            raise HTTPException(404, 'Functional Group not found.')
        groups.append(dict(id=group['id'], name=group['name'], status=group['status']))
    rows = []
    for name in usernames:
        current = public_user(data, name)
        held = set(current['group_ids'])
        rows.append(dict(username=current['username'] if current['revision'] else name, revision=current['revision'], group_ids=current['group_ids'],
                         group_names=[m['group']['name'] for m in current['memberships']], additions=[g for g in group_ids if g not in held],
                         existing=[g for g in group_ids if g in held]))
    return dict(groups=groups, items=rows, counts=dict(users=len(rows), additions=sum(len(r['additions']) for r in rows), existing=sum(len(r['existing']) for r in rows),
                                                      unassigned=sum(1 for r in rows if not r['group_ids'])))


def bulk_assign(group_ids, usernames, expected, rationale, actor, operation_id):
    """Add the selected Functional Groups to many users in ONE store write. Existing memberships are never removed and already-held groups are no-ops.

    Request-level problems (unknown or archived group, an operation id that was already applied) change nothing. Per-user outcomes are explicit:
    applied (added and/or reconfirmed groups), unchanged (every group already held) and conflicts (the record changed since `expected`)."""
    if not operation_id:
        raise HTTPException(422, 'An operation identifier is required.')
    group_ids = list(dict.fromkeys(group_ids))
    if not group_ids:
        raise HTTPException(422, 'Select at least one Functional Group.')
    with lock:
        data = read()
        if any(item.get('change_id') == operation_id for item in data['history']):
            raise HTTPException(409, 'This operation was already applied.')
        for gid in group_ids:
            group = data['groups'].get(gid)
            if group is None:
                raise HTTPException(404, 'Functional Group not found.')
            if group['status'] == 'archived':
                raise HTTPException(409, 'Archived Functional Groups cannot be newly assigned. Restore the group first.')
        applied, unchanged, conflicts, seen = [], [], [], set()
        for name in usernames:
            key = user_key(name)
            if key in seen:
                continue
            seen.add(key)
            existing = data['users'].get(key)
            revision = existing['revision'] if existing else 0
            if revision != expected.get(key, revision) or (key not in expected and revision):
                conflicts.append(dict(username=name, reason='changed', detail='The classification changed since it was loaded.'))
                continue
            user = existing or dict(username=name.strip(), revision=0, updated_at=None, handled=[], memberships={})
            outcomes = {gid: _add(data, user, gid, rationale, actor, operation_id) for gid in group_ids}
            added = [g for g, o in outcomes.items() if o == 'added']
            reconfirmed = [g for g, o in outcomes.items() if o == 'reconfirmed']
            if added or reconfirmed:
                _commit(data, user, operation_id)
                applied.append(dict(username=name, added=added, reconfirmed=reconfirmed, unchanged=[g for g, o in outcomes.items() if o == 'unchanged']))
            else:
                unchanged.append(dict(username=name, group_ids=group_ids))
        if applied:
            write(data)
        return dict(operation_id=operation_id, group_ids=group_ids, group_names=[data['groups'][g]['name'] for g in group_ids], applied=applied, unchanged=unchanged,
                    conflicts=conflicts, status='applied' if not conflicts else 'partial' if applied or unchanged else 'rejected')


def _flag(data, user, change_id, reason, actor):
    """Department or Job Title change: every Confirmed membership becomes `Needs review` (reconfirmed or removed on its own). Idempotent per change id."""
    if not user['memberships'] or change_id in user.get('handled', []) or any((m.get('review') or {}).get('change_id') == change_id for m in user['memberships'].values()):
        return False
    stamp, changed = now(), False
    for gid, member in user['memberships'].items():
        if member['status'] != 'Confirmed':
            continue
        member.update(status='Needs review', updated_at=stamp, review=dict(change_id=change_id, reason=reason, required_since=stamp))
        _event(data, user, 'review_required', gid, gid, 'Confirmed', 'Needs review', actor, reason, change_id)
        changed = True
    if changed:
        user['revision'] += 1
        user['updated_at'] = stamp
    return changed


def _note_manager(data, user, change_id, reason, actor, seen):
    key = (user_key(user['username']), change_id)
    if key in seen:
        return False
    status = _aggregate(user['memberships'])
    _event(data, user, 'manager_changed', None, None, status, status, actor, reason, change_id)
    seen.add(key)
    return True


def _seen_manager_notes(data):
    return {(e['user_key'], e['change_id']) for e in data['history'] if e['event'] == 'manager_changed'}


def flag_for_review(username, change_id, reason, actor='system'):
    """Department or Job Title change. Keeps the memberships, sets `Needs review` once per change id. A completed review is not reset by
    re-importing the same state; only a new change id re-opens it. Returns True if changed."""
    with lock:
        data = read()
        user = data['users'].get(user_key(username))
        if user is None or not _flag(data, user, change_id, reason, actor):
            return False
        write(data)
        return True


def note_manager_change(username, change_id, reason, actor='system'):
    """Manager change: an advisory history signal only. Memberships, statuses and revision are left untouched."""
    with lock:
        data = read()
        user = data['users'].get(user_key(username))
        if user is None or not _note_manager(data, user, change_id, reason, actor, _seen_manager_notes(data)):
            return False
        write(data)
        return True


def _change_text(label, before, after):
    return f'{label} changed from {before or "empty"} to {after or "empty"}'


def _last_confirmation(user):
    stamps = [m.get('confirmed_at') for m in user['memberships'].values() if m.get('confirmed_at')]
    return max(stamps) if stamps else (user.get('updated_at') or '')


def apply_organizational_changes(email_by_username, position_events, manager_events):
    """Apply stored Directory change events to classified users. `email_by_username` maps SAP user name -> normalized Directory e-mail for
    reliably matched users only. Department or Job Title changes detected after the last confirmation flag every membership `Needs review`; Manager
    changes only add a history signal. Idempotent per event id, so repeating an import or this call changes nothing. Returns changes made."""
    with lock:
        data = read()
        if not data['users']:
            return 0
        by_email = {}
        for event in position_events:
            by_email.setdefault(event['key'], []).append(event)
        managers = {}
        for event in manager_events:
            managers.setdefault(event['key'], []).append(event)
        seen, changed = _seen_manager_notes(data), 0
        for user in data['users'].values():
            email = email_by_username.get(user['username'].strip().upper())
            if not email:
                continue
            since = _last_confirmation(user)
            for event in sorted(by_email.get(email, []), key=lambda e: (e['detected_at'], e['id'])):
                if event['detected_at'] <= since:
                    continue
                parts = []
                if 'department' in event['fields']:
                    parts.append(_change_text('Directory Department', event['previous_department'], event['current_department']))
                if 'title' in event['fields']:
                    parts.append(_change_text('Job Title', event['previous_title'], event['current_title']))
                changed += _flag(data, user, event['id'], '; '.join(parts), 'system')
            for event in sorted(managers.get(email, []), key=lambda e: (e['detected_at'], e['id'])):
                if event['detected_at'] > since:
                    changed += _note_manager(data, user, event['id'], _change_text('Manager', event['previous_manager'], event['current_manager']), 'system', seen)
        if changed:
            write(data)
        return changed


def user_history(username, offset=0, limit=25):
    key = user_key(username)
    events = [dict(e) for e in reversed(read()['history']) if e['user_key'] == key]
    return dict(items=events[offset:offset + limit], total=len(events), offset=offset, limit=limit)


# --- advisory suggestion rules -----------------------------------------------------------------------------------------
# A rule matches when every condition it states holds: Directory Department equals (normalized) and/or Job Title contains
# (normalized). Rules are advisory; nothing is ever assigned from them. All matching rules are shown. A single suggestion is made
# only when every matching rule on an active group names the same group; otherwise the ambiguity is reported.

def list_rules():
    data = read()
    return [dict(r, department_mode=r.get('department_mode') or 'equals', group_name=data['groups'][r['group_id']]['name'], group_status=data['groups'][r['group_id']]['status'])
            for r in data['rules']]


def _clean_rule(department, title_contains):
    department, title_contains = re.sub(r'\s+', ' ', (department or '').strip()), re.sub(r'\s+', ' ', (title_contains or '').strip())
    if not department and not title_contains:
        raise HTTPException(422, 'A rule needs a Directory Department text, a Job Title text, or both.')
    return department, title_contains


def _same_rule(a, b):
    return (a['group_id'] == b['group_id'] and normalize_text(a.get('department', '')) == normalize_text(b.get('department', ''))
            and normalize_text(a.get('title_contains', '')) == normalize_text(b.get('title_contains', ''))
            and (a.get('department_mode') or 'equals') == (b.get('department_mode') or 'equals'))


def add_rule(group_id, department='', title_contains='', department_mode='contains'):
    department, title_contains = _clean_rule(department, title_contains)
    if department_mode not in ('contains', 'equals'):
        raise HTTPException(422, 'Department matching is "contains" or "equals".')
    with lock:
        data = read()
        if group_id not in data['groups']:
            raise HTTPException(404, 'Functional Group not found.')
        rule = dict(id='fr_' + uuid.uuid4().hex[:12], group_id=group_id, department=department, title_contains=title_contains, department_mode=department_mode, created=now())
        if any(_same_rule(r, rule) for r in data['rules']):
            raise HTTPException(409, 'This rule already exists.')
        if len(data['rules']) >= 500:
            raise HTTPException(409, 'The maximum number of suggestion rules is reached.')
        data['rules'].append(rule)
        write(data)
        return rule


def update_rule(rule_id, group_id, department='', title_contains='', department_mode='contains'):
    department, title_contains = _clean_rule(department, title_contains)
    if department_mode not in ('contains', 'equals'):
        raise HTTPException(422, 'Department matching is "contains" or "equals".')
    with lock:
        data = read()
        if group_id not in data['groups']:
            raise HTTPException(404, 'Functional Group not found.')
        current = next((r for r in data['rules'] if r['id'] == rule_id), None)
        if current is None:
            raise HTTPException(404, 'Rule not found.')
        candidate = dict(current, group_id=group_id, department=department, title_contains=title_contains, department_mode=department_mode)
        if any(r['id'] != rule_id and _same_rule(r, candidate) for r in data['rules']):
            raise HTTPException(409, 'This rule already exists.')
        current.update(group_id=group_id, department=department, title_contains=title_contains, department_mode=department_mode, modified=now())
        write(data)
        return current


def delete_rule(rule_id):
    with lock:
        data = read()
        remaining = [r for r in data['rules'] if r['id'] != rule_id]
        if len(remaining) == len(data['rules']):
            raise HTTPException(404, 'Rule not found.')
        data['rules'] = remaining
        write(data)


def rule_matches(rule, department, title):
    """Whether a rule applies to Directory attributes. Conditions are ANDed; Department is a case-insensitive substring ("contains"; legacy rules keep
    equality) and Job Title a substring. A condition the rule states never matches an empty Directory attribute. Returns the reasons, or None."""
    reasons = []
    wanted_department, wanted_title = normalize_text(rule.get('department', '')), normalize_text(rule.get('title_contains', ''))
    if not wanted_department and not wanted_title:
        return None
    if wanted_department:
        actual = normalize_text(department or '')
        if not actual:
            return None
        if (rule.get('department_mode') or 'equals') == 'equals':
            if actual != wanted_department:
                return None
            reasons.append(f'Directory Department = {rule["department"]}')
        else:
            if wanted_department not in actual:
                return None
            reasons.append(f'Directory Department contains {rule["department"]}')
    if wanted_title:
        if wanted_title not in normalize_text(title or ''):
            return None
        reasons.append(f'Job Title contains {rule["title_contains"]}')
    return reasons


def suggest(department, title, data=None, held=()):
    """Advisory suggestions: every matching rule on an active group, consolidated per group (several rules naming one group give one entry with all its
    reasons). Nothing is ever assigned from them; `already_member` marks groups the user already belongs to. A user may belong to several groups, so
    several suggested groups are normal and never an error."""
    data = data or read()
    matches = []
    for rule in data['rules']:
        group = data['groups'][rule['group_id']]
        if group['status'] != 'active':
            continue
        reasons = rule_matches(rule, department, title)
        if reasons is None:
            continue
        matches.append(dict(rule_id=rule['id'], group_id=group['id'], group_name=group['name'], reasons=reasons))
    held = set(held)
    consolidated = {}
    for match in matches:
        entry = consolidated.setdefault(match['group_id'], dict(group_id=match['group_id'], group_name=match['group_name'], rule_ids=[], reasons=[], already_member=match['group_id'] in held))
        entry['rule_ids'].append(match['rule_id'])
        entry['reasons'] += [reason for reason in match['reasons'] if reason not in entry['reasons']]
    groups = sorted(consolidated.values(), key=lambda e: (name_key(e['group_name']), e['group_id']))
    return dict(status='suggested' if groups else 'none', matches=sorted(matches, key=lambda m: (name_key(m['group_name']), m['rule_id'])), groups=groups)
