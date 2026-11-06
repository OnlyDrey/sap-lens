"""Functional Group catalogue and per-user classification. Local annotations only: no SAP access is ever changed."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field

import cache
import functional_groups as fg
from config_models import StrictModel
from server_access import actor
from .access import require_mapping

router = APIRouter(prefix='/api/functional-groups', tags=['Functional Groups'])


class GroupBody(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default='', max_length=500)


class GroupPatch(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)


class Classification(StrictModel):
    group_id: str | None = Field(default=None, pattern=r'^fg_[a-f0-9]{12}$')
    rationale: str = Field(default='', max_length=2000)
    reviewer: str = Field(default='', max_length=120)
    expected_revision: int = Field(ge=0)
    change_id: str = Field(default='', max_length=64)


class Membership(StrictModel):
    username: str = Field(min_length=1, max_length=200)
    group_id: str = Field(pattern=r'^fg_[a-f0-9]{12}$')
    rationale: str = Field(default='', max_length=2000)
    reviewer: str = Field(default='', max_length=120)
    expected_revision: int = Field(ge=0)
    change_id: str = Field(default='', max_length=64)


class RuleBody(StrictModel):
    group_id: str = Field(pattern=r'^fg_[a-f0-9]{12}$')
    department: str = Field(default='', max_length=200)
    title_contains: str = Field(default='', max_length=200)
    department_mode: str = Field(default='contains', pattern=r'^(contains|equals)$')


def directory_context(username):
    """Imported Directory Department, Job Title and Manager for the SAP user, only when the match is unambiguous."""
    from employee_directory import match_sap_identity, sap_email_owners
    from .employees import available
    state = cache.get_snapshot()
    directory = available(state)
    user = next((u for u in state.users.users.values() if u['username'].strip().upper() == username.strip().upper()), None)
    if not directory or user is None:
        return None
    match = match_sap_identity(directory, user, sap_email_owners(state.users.users.values()))
    employee = match['employee']
    if match['status'] != 'matched' or not employee:
        return dict(match_status=match['status'])
    return dict(match_status='matched', department=employee['department'], title=employee['title'], site=employee['site'],
                manager=employee['manager']['name'], manager_email=employee['manager']['email'])


def sync_organizational_changes():
    """Apply stored Directory change events to classified users. Never fails a read: the import itself is unaffected."""
    import logging
    from employee_directory import match_sap_identity, normalized, sap_email_owners
    from position_changes import read as read_changes, read_manager_events
    from .employees import available
    try:
        if not fg.read()['users']:
            return 0
        state = cache.get_snapshot()
        directory = available(state)
        changes, managers = read_changes(), read_manager_events()
        if not directory or not (changes['events'] or managers):
            return 0
        owners = sap_email_owners(state.users.users.values())
        classified = {user['username'].strip().upper() for user in fg.read()['users'].values()}
        emails = {}
        for user in state.users.users.values():
            if user['username'].strip().upper() in classified:
                match = match_sap_identity(directory, user, owners)
                if match['status'] == 'matched' and match['employee']['email']:
                    emails[user['username'].strip().upper()] = normalized(match['employee']['email'])
        return fg.apply_organizational_changes(emails, changes['events'], managers)
    except Exception:  # noqa: BLE001 - advisory synchronisation must not break reads
        logging.getLogger('sap-lens').warning('Functional Group review synchronisation failed; classifications are unchanged.')
        return 0


def known_user(username):
    users = cache.get_snapshot().users.users
    for user in users.values():
        if user['username'].strip().upper() == username.strip().upper():
            return user['username']
    raise HTTPException(404, 'SAP user not found.')


@router.get('')
def groups(include_archived: bool = True):
    return dict(items=fg.list_groups(include_archived), statuses=fg.STATUSES)


@router.post('')
def create(body: GroupBody):
    return fg.create_group(body.name, body.description)


@router.patch('/{gid}')
def update(gid: str, body: GroupPatch):
    return fg.update_group(gid, body.name, body.description)


@router.post('/{gid}/archive')
def archive(gid: str):
    return fg.set_group_status(gid, 'archived')


@router.post('/{gid}/restore')
def restore(gid: str):
    return fg.set_group_status(gid, 'active')


@router.get('/options', dependencies=[Depends(require_mapping)])
def options():
    """Functional Group and Manager choices (with SAP user counts) for filters in User Access and SoD."""
    import organization
    from .employees import available
    state = cache.get_snapshot()
    return organization.options(state, available(state))


@router.get('/{gid}/members', dependencies=[Depends(require_mapping)])
def members(gid: str, search: str = Query('', max_length=200), status: str = Query('', max_length=20), offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    """Current members of one group with Directory context where the SAP user is uniquely linked to a Directory employee. Nothing is invented: a member
    without a SAP record or Directory link shows only what is stored. Includes every membership status so reviews stay visible."""
    import organization
    from employee_directory import identity_matcher
    from .employees import available
    data = fg.read()
    group = data['groups'].get(gid)
    if group is None:
        raise HTTPException(404, 'Functional Group not found.')
    state = cache.get_snapshot()
    directory = available(state)
    matcher = identity_matcher(state.users, directory) if directory else None
    people = {u['username'].strip().upper(): u for u in organization.users_of(state)}
    needle, rows = search.strip().casefold(), []
    for user in data['users'].values():
        member = user['memberships'].get(gid)
        if member is None:
            continue
        sap = people.get(user['username'].strip().upper())
        employee, identity = None, 'not_in_import'
        if sap is not None:
            identity = 'unmatched'
            match = matcher(sap) if matcher else None
            if match and match['status'] == 'matched' and match['employee']:
                employee, identity = match['employee'], 'matched'
        names = [' '.join(part for part in n if part).strip() for n in (sap or {}).get('names', []) if isinstance(n, (list, tuple))]
        row = dict(username=user['username'], full_name=(employee or {}).get('name') or next((n for n in names if n), ''), department=(employee or {}).get('department', ''),
                   title=(employee or {}).get('title', ''), identity=identity, status=member['status'], confirmed_at=member.get('confirmed_at') or None,
                   confirmed_by=member.get('confirmed_by', ''), revision=user['revision'], review=member.get('review'),
                   other_groups=sorted(data['groups'][g]['name'] for g in user['memberships'] if g != gid))
        if status and row['status'] != status:
            continue
        if needle and needle not in ' '.join([row['username'], row['full_name'], row['department'], row['title']]).casefold():
            continue
        rows.append(row)
    rows.sort(key=lambda r: r['username'].casefold())
    return dict(group=dict(id=gid, name=group['name'], status=group['status']), total=len(rows), items=rows[offset:offset + limit], offset=offset, limit=limit)


@router.get('/analysis/{gid}', dependencies=[Depends(require_mapping)])
def analysis(gid: str):
    """Advisory access comparison inside one Functional Group (unique active user and role pairs)."""
    from functional_group_analysis import analyse
    data = fg.read()
    group = data['groups'].get(gid)
    if group is None:
        raise HTTPException(404, 'Functional Group not found.')
    members = [user['username'] for user in data['users'].values() if gid in user['memberships']]
    return analyse(cache.get_snapshot(), members, group)


class BulkBody(StrictModel):
    group_ids: list[str] = Field(default_factory=list, max_length=50, description='Functional Groups to ADD to every user (existing memberships are kept)')
    group_id: str = Field(default='', max_length=64, description='Legacy single-group alias of group_ids')
    usernames: list[str] = Field(min_length=1, max_length=5000)
    data_revision: str = Field(default='', max_length=64, description='data_generation seen when the selection was made; a different publication is refused')


class BulkAssign(BulkBody):
    operation_id: str = Field(min_length=8, max_length=64)
    expected: dict[str, int] = Field(default_factory=dict, description='classification revision seen per username (0 = no record)')
    replace_existing: bool = Field(default=False, description='Not supported: assignment only adds memberships. Kept so older clients get a clear error.')
    rationale: str = Field(default='', max_length=1000)
    reviewer: str = Field(default='', max_length=200)


def target_groups(body):
    ids = list(dict.fromkeys([*body.group_ids, *([body.group_id] if body.group_id else [])]))
    if not ids:
        raise HTTPException(422, 'Select at least one Functional Group.')
    return ids


def resolve_bulk(body):
    """Validate the dataset and resolve names against it. Returns (known canonical names, missing names)."""
    if body.data_revision:
        current = cache.revision_token().split('.')
        seen = body.data_revision.split('.')
        if seen[:2] != current[:2]:
            raise HTTPException(409, detail=dict(code='stale_dataset', message='The user data changed after this selection was made. Select the users again.'))
    users = cache.get_snapshot().users.users
    known, missing, seen_keys = [], [], set()
    for name in body.usernames:
        from user_access import normalize_username
        key = normalize_username(name)
        if key in seen_keys or not key:
            continue
        seen_keys.add(key)
        (known if key in users else missing).append(users[key]['username'] if key in users else name.strip())
    return known, missing


@router.post('/bulk/preview', dependencies=[Depends(require_mapping)])
def bulk_preview(body: BulkBody):
    known, missing = resolve_bulk(body)
    preview = fg.bulk_preview(target_groups(body), known)
    return dict(**preview, missing=missing, requested=len(known) + len(missing), data_revision=cache.revision_token())


@router.post('/bulk', dependencies=[Depends(require_mapping)])
def bulk_assign(body: BulkAssign):
    who = actor(body.reviewer).strip()
    if not who:
        raise HTTPException(422, 'A reviewer is required.')
    if body.replace_existing:
        raise HTTPException(422, 'Replacing memberships is not supported: assignment adds groups. Remove a membership on the user instead.')
    groups = target_groups(body)
    known, missing = resolve_bulk(body)
    expected = {fg.user_key(name): revision for name, revision in body.expected.items()}
    result = fg.bulk_assign(groups, known, expected, body.rationale, who, body.operation_id)
    result['rejected'] = [dict(username=name, reason='not_in_dataset', detail='Not in the active SAP user dataset.') for name in missing]
    if missing and result['status'] == 'applied':
        result['status'] = 'partial'
    result['data_revision'] = cache.revision_token()
    return result


def rule_audience():
    """Directory identities that can receive a SAP-linked assignment: SAP users whose e-mail matches exactly one Directory employee, with the imported
    Department and Job Title. Ambiguous, duplicate, unmatched and missing identities are excluded and counted separately. Returns (eligible, not_linked)."""
    import organization
    from employee_directory import identity_matcher
    from position_changes import normalize_text
    from .employees import available
    state = cache.get_snapshot()
    directory = available(state)
    if not directory:
        return [], [], False
    matcher = identity_matcher(state.users, directory)
    linked, eligible = set(), []
    for user in organization.users_of(state):
        match = matcher(user)
        if match['status'] != 'matched' or not match['employee']:
            continue
        employee = match['employee']
        linked.add(employee['id'])
        names = [' '.join(part for part in name if part).strip() for name in user.get('names', []) if isinstance(name, (list, tuple))]
        eligible.append(dict(username=user['username'], full_name=employee['name'] or next((n for n in names if n), ''), department=employee['department'], title=employee['title'],
                             dn=normalize_text(employee['department']), tn=normalize_text(employee['title'])))
    not_linked = [dict(full_name=r['Name'], department=r['Department'], title=r['Title'], dn=normalize_text(r['Department']), tn=normalize_text(r['Title']))
                  for r in directory.rows if r['id'] not in linked]
    return eligible, not_linked, True


def _applies(rule, row):
    from position_changes import normalize_text
    wanted_department, wanted_title = normalize_text(rule.get('department', '')), normalize_text(rule.get('title_contains', ''))
    if wanted_department:
        if not row['dn'] or (wanted_department != row['dn'] if (rule.get('department_mode') or 'equals') == 'equals' else wanted_department not in row['dn']):
            return False
    if wanted_title and wanted_title not in row['tn']:
        return False
    return bool(wanted_department or wanted_title)


@router.get('/rules')
def rules(counts: bool = False):
    items = fg.list_rules()
    if counts:
        eligible, not_linked, available_directory = rule_audience()
        for rule in items:
            rule['match_count'] = sum(1 for row in eligible if _applies(rule, row)) if available_directory else None
            rule['not_linked_count'] = sum(1 for row in not_linked if _applies(rule, row)) if available_directory else None
    return dict(items=items)


@router.post('/rules')
def add_rule(body: RuleBody):
    return fg.add_rule(body.group_id, body.department, body.title_contains, body.department_mode)


@router.put('/rules/{rule_id}')
def update_rule(rule_id: str, body: RuleBody):
    return fg.update_rule(rule_id, body.group_id, body.department, body.title_contains, body.department_mode)


@router.delete('/rules/{rule_id}')
def delete_rule(rule_id: str):
    fg.delete_rule(rule_id)
    return {'status': 'deleted'}


def _rule_or_404(rule_id):
    rule = next((r for r in fg.list_rules() if r['id'] == rule_id), None)
    if rule is None:
        raise HTTPException(404, 'Rule not found.')
    return rule


def _rule_rows(rule, search, only_new, data):
    eligible, not_linked, available_directory = rule_audience()
    if not available_directory:
        raise HTTPException(409, 'The Employee Directory is not available. Import it in Data Sources to preview matching users.')
    classes = {user['username'].strip().upper(): fg.public_user(data, user['username']) for user in data['users'].values()}
    needle = search.strip().casefold()
    rows = []
    for row in eligible:
        if not _applies(rule, row):
            continue
        record = classes.get(row['username'].strip().upper())
        groups = [m['group'] for m in record['memberships']] if record else []
        member = any(g['id'] == rule['group_id'] for g in groups)
        if only_new and member:
            continue
        if needle and needle not in ' '.join([row['username'], row['full_name'], row['department'], row['title']]).casefold():
            continue
        rows.append(dict(username=row['username'], full_name=row['full_name'], department=row['department'], title=row['title'], groups=groups, already_member=member))
    rows.sort(key=lambda r: r['username'].casefold())
    return rows, [r for r in not_linked if _applies(rule, r)]


@router.get('/rules/{rule_id}/matches', dependencies=[Depends(require_mapping)])
def rule_matches(rule_id: str, search: str = Query('', max_length=200), only_new: bool = False, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    """Users a suggestion rule applies to: SAP users uniquely linked to a Directory employee. Directory employees that match but have no unique SAP link are
    counted and sampled, never offered for assignment. Read-only: nothing is assigned."""
    rule = _rule_or_404(rule_id)
    rows, unlinked = _rule_rows(rule, search, only_new, fg.read())
    return dict(rule=rule, total=len(rows), items=rows[offset:offset + limit], offset=offset, limit=limit, not_linked_total=len(unlinked),
                not_linked=[dict(full_name=r['full_name'], department=r['department'], title=r['title'], reason='No unique SAP user is linked to this Directory identity') for r in unlinked[:25]],
                data_revision=cache.revision_token())


@router.get('/rules/{rule_id}/matches/selection', dependencies=[Depends(require_mapping)])
def rule_match_selection(rule_id: str, search: str = Query('', max_length=200), only_new: bool = False):
    """Every username of the (filtered) match list, for Select all across pages. Capped like the User Directory selection."""
    rows, _ = _rule_rows(_rule_or_404(rule_id), search, only_new, fg.read())
    cap = 5000
    return dict(total=len(rows), usernames=[r['username'] for r in rows[:cap]], truncated=len(rows) > cap, limit=cap, data_revision=cache.revision_token())


@router.get('/users/{username:path}', dependencies=[Depends(require_mapping)])
def classification(username: str):
    username = known_user(username)
    sync_organizational_changes()
    data = fg.read()
    context = directory_context(username)
    current = fg.public_user(data, username)
    suggestion = fg.suggest(context.get('department', ''), context.get('title', ''), data, current['group_ids']) if context and context.get('match_status') == 'matched' else None
    return dict(classification=current, history=fg.user_history(username, 0, 10), directory=context, suggestion=suggestion)


@router.put('/users/{username:path}', dependencies=[Depends(require_mapping)])
def classify(username: str, body: Classification):
    username = known_user(username)
    who = actor(body.reviewer).strip()
    if not who:
        raise HTTPException(422, 'A reviewer is required.')
    if body.group_id is None and not body.rationale.strip():
        raise HTTPException(422, 'A rationale is required to clear a Functional Group.')
    return fg.classify(username, body.group_id, body.rationale, body.expected_revision, who, body.change_id)


@router.post('/memberships', dependencies=[Depends(require_mapping)])
def add_membership(body: Membership):
    """Add a Functional Group to one user (or reconfirm a membership that needs review). Other memberships are never touched; repeating it is a no-op."""
    username = known_user(body.username)
    who = actor(body.reviewer).strip()
    if not who:
        raise HTTPException(422, 'A reviewer is required.')
    classification, outcome = fg.add_membership(username, body.group_id, body.rationale, body.expected_revision, who, body.change_id)
    return dict(classification=classification, outcome=outcome)


@router.post('/memberships/remove', dependencies=[Depends(require_mapping)])
def remove_membership(body: Membership):
    """Remove one membership with a rationale; the user's other memberships and the history are kept."""
    username = known_user(body.username)
    who = actor(body.reviewer).strip()
    if not who:
        raise HTTPException(422, 'A reviewer is required.')
    if not body.rationale.strip():
        raise HTTPException(422, 'A rationale is required to remove a Functional Group.')
    return dict(classification=fg.remove_membership(username, body.group_id, body.rationale, body.expected_revision, who, body.change_id))


@router.get('/history/{username:path}', dependencies=[Depends(require_mapping)])
def history(username: str, offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
    return fg.user_history(known_user(username), offset, limit)
