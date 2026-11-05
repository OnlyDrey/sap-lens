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
FORMAT = 1
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


def validate_storage(data):
    """Pure persisted contract, also used before a backup restore is activated. Returns the data or raises ValueError."""
    if not isinstance(data, dict) or data.get('format') != FORMAT:
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


def read():
    path = config_dir() / FILE
    try:
        if not path.exists():
            return empty()
        with path.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('size')
        return validate_storage(json.loads(raw))
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        raise HTTPException(409, 'Functional Group storage could not be read. The original file is retained; review local application storage before recovery.') from None


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
    result = {}
    for user in data['users'].values():
        if user['group_id']:
            result[user['group_id']] = result.get(user['group_id'], 0) + 1
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

def public_user(data, username):
    user = data['users'].get(user_key(username))
    if user is None:
        return dict(username=username, group_id=None, group=None, status='Unassigned', revision=0, confirmed_at=None, confirmed_by='', rationale='', review=None)
    group = data['groups'].get(user['group_id']) if user['group_id'] else None
    return dict(username=user['username'], group_id=user['group_id'], group=dict(id=group['id'], name=group['name'], status=group['status']) if group else None,
                status=user['status'], revision=user['revision'], confirmed_at=user.get('confirmed_at') or None, confirmed_by=user.get('confirmed_by', ''),
                rationale=user.get('rationale', ''), review=user.get('review'))


def _event(data, user, event, previous, new, actor, reason, change_id=''):
    data['history'].append(dict(
        id=uuid.uuid4().hex, event=event, user_key=user_key(user['username']), username=user['username'],
        previous_group=previous['group_id'], new_group=new['group_id'], previous_status=previous['status'], new_status=new['status'],
        actor=actor, timestamp=now(), reason=reason, change_id=change_id))
    if len(data['history']) > MAX_HISTORY:
        raise HTTPException(409, 'Functional Group history is full. Existing data is retained.')


def classify(username, group_id, rationale, expected_revision, actor, change_id=''):
    """Set, change, clear or reconfirm a user's group. `expected_revision` is the revision the reviewer saw (0 = no record):
    a stale review can never overwrite a newer classification. Group present -> Confirmed; none -> an explicit Unassigned outcome."""
    username = username.strip()
    if not username:
        raise HTTPException(422, 'A SAP user is required.')
    with lock:
        data = read()
        key = user_key(username)
        before = data['users'].get(key) or dict(username=username, group_id=None, status='Unassigned', revision=0, handled=[])
        if before['revision'] != expected_revision:
            raise HTTPException(409, 'The classification changed since it was loaded. Reload before saving.')
        if group_id is not None:
            group = data['groups'].get(group_id)
            if group is None:
                raise HTTPException(404, 'Functional Group not found.')
            if group['status'] == 'archived' and group_id != before['group_id']:
                raise HTTPException(409, 'Archived Functional Groups cannot be newly assigned. Restore the group first.')
        if before['status'] == 'Unassigned' and group_id is None and before['revision'] == 0 and not change_id:
            raise HTTPException(409, 'The user has no Functional Group to clear.')
        stamp = now()
        was = dict(group_id=before['group_id'], status=before['status'])
        after = dict(before, username=before['username'], group_id=group_id, status='Confirmed' if group_id else 'Unassigned', revision=before['revision'] + 1,
                     confirmed_at=stamp if group_id else None, confirmed_by=actor if group_id else '', rationale=rationale.strip(), updated_at=stamp, review=None)
        if before['group_id'] is None and group_id:
            event = 'assigned'
        elif group_id is None:
            event = 'removed'
        elif group_id != before['group_id']:
            event = 'changed'
        else:
            event = 'reconfirmed' if before['status'] == 'Needs review' else 'confirmed'
        after['handled'] = before.get('handled', [])
        if change_id and change_id not in after['handled']:
            after['handled'] = [*after['handled'], change_id][-MAX_HANDLED:]
        data['users'][key] = after
        _event(data, after, event, was, after, actor, rationale.strip(), change_id)
        write(data)
        return public_user(data, username)


def flag_for_review(username, change_id, reason, actor='system'):
    """Directory import hook for a Department or Job Title change. Keeps the group, sets `Needs review` once per change id.
    A completed review is not reset by re-importing the same state; only a new change id re-opens it. Returns True if changed."""
    with lock:
        data = read()
        key = user_key(username)
        user = data['users'].get(key)
        if user is None or user['group_id'] is None or change_id in user.get('handled', []) or (user.get('review') or {}).get('change_id') == change_id:
            return False
        was = dict(group_id=user['group_id'], status=user['status'])
        user.update(status='Needs review', revision=user['revision'] + 1, updated_at=now(), review=dict(change_id=change_id, reason=reason, required_since=now()))
        _event(data, user, 'review_required', was, user, actor, reason, change_id)
        write(data)
        return True


def note_manager_change(username, change_id, reason, actor='system'):
    """Manager change: an advisory history signal only. Status, group and revision are left untouched."""
    with lock:
        data = read()
        user = data['users'].get(user_key(username))
        if user is None or any(e['event'] == 'manager_changed' and e['change_id'] == change_id and e['user_key'] == user_key(username) for e in data['history'][-2000:]):
            return False
        state = dict(group_id=user['group_id'], status=user['status'])
        _event(data, user, 'manager_changed', state, user, actor, reason, change_id)
        write(data)
        return True


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
    return [dict(r, group_name=data['groups'][r['group_id']]['name'], group_status=data['groups'][r['group_id']]['status']) for r in data['rules']]


def add_rule(group_id, department='', title_contains=''):
    department, title_contains = re.sub(r'\s+', ' ', department.strip()), re.sub(r'\s+', ' ', title_contains.strip())
    if not department and not title_contains:
        raise HTTPException(422, 'A rule needs a Directory Department, a Job Title text, or both.')
    with lock:
        data = read()
        if group_id not in data['groups']:
            raise HTTPException(404, 'Functional Group not found.')
        if any(r['group_id'] == group_id and normalize_text(r.get('department', '')) == normalize_text(department)
               and normalize_text(r.get('title_contains', '')) == normalize_text(title_contains) for r in data['rules']):
            raise HTTPException(409, 'This rule already exists.')
        if len(data['rules']) >= 500:
            raise HTTPException(409, 'The maximum number of suggestion rules is reached.')
        rule = dict(id='fr_' + uuid.uuid4().hex[:12], group_id=group_id, department=department, title_contains=title_contains, created=now())
        data['rules'].append(rule)
        write(data)
        return rule


def delete_rule(rule_id):
    with lock:
        data = read()
        remaining = [r for r in data['rules'] if r['id'] != rule_id]
        if len(remaining) == len(data['rules']):
            raise HTTPException(404, 'Rule not found.')
        data['rules'] = remaining
        write(data)


def suggest(department, title, data=None):
    data = data or read()
    matches = []
    for rule in data['rules']:
        group = data['groups'][rule['group_id']]
        if group['status'] != 'active':
            continue
        reasons = []
        if rule.get('department'):
            if normalize_text(rule['department']) != normalize_text(department):
                continue
            reasons.append(f'Directory Department = {rule["department"]}')
        if rule.get('title_contains'):
            if normalize_text(rule['title_contains']) not in normalize_text(title):
                continue
            reasons.append(f'Job Title contains {rule["title_contains"]}')
        matches.append(dict(rule_id=rule['id'], group_id=group['id'], group_name=group['name'], reasons=reasons))
    groups = {m['group_id'] for m in matches}
    status = 'none' if not matches else 'suggested' if len(groups) == 1 else 'ambiguous'
    return dict(status=status, matches=sorted(matches, key=lambda m: (name_key(m['group_name']), m['rule_id'])))
