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


class RuleBody(StrictModel):
    group_id: str = Field(pattern=r'^fg_[a-f0-9]{12}$')
    department: str = Field(default='', max_length=200)
    title_contains: str = Field(default='', max_length=200)


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


@router.get('/analysis/{gid}', dependencies=[Depends(require_mapping)])
def analysis(gid: str):
    """Advisory access comparison inside one Functional Group (unique active user and role pairs)."""
    from functional_group_analysis import analyse
    data = fg.read()
    group = data['groups'].get(gid)
    if group is None:
        raise HTTPException(404, 'Functional Group not found.')
    members = [user['username'] for user in data['users'].values() if user['group_id'] == gid]
    return analyse(cache.get_snapshot(), members, group)


class BulkBody(StrictModel):
    group_id: str = Field(min_length=1, max_length=64)
    usernames: list[str] = Field(min_length=1, max_length=5000)
    data_revision: str = Field(default='', max_length=64, description='data_generation seen when the selection was made; a different publication is refused')


class BulkAssign(BulkBody):
    operation_id: str = Field(min_length=8, max_length=64)
    expected: dict[str, int] = Field(default_factory=dict, description='classification revision seen per username (0 = no record)')
    replace_existing: bool = False
    rationale: str = Field(default='', max_length=1000)
    reviewer: str = Field(default='', max_length=200)


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
    preview = fg.bulk_preview(body.group_id, known)
    return dict(**preview, missing=missing, requested=len(known) + len(missing), data_revision=cache.revision_token())


@router.post('/bulk', dependencies=[Depends(require_mapping)])
def bulk_assign(body: BulkAssign):
    who = actor(body.reviewer).strip()
    if not who:
        raise HTTPException(422, 'A reviewer is required.')
    known, missing = resolve_bulk(body)
    expected = {fg.user_key(name): revision for name, revision in body.expected.items()}
    result = fg.bulk_assign(body.group_id, known, expected, body.replace_existing, body.rationale, who, body.operation_id)
    result['rejected'] = [dict(username=name, reason='not_in_dataset', detail='Not in the active SAP user dataset.') for name in missing]
    if missing and result['status'] == 'applied':
        result['status'] = 'partial'
    result['data_revision'] = cache.revision_token()
    return result


@router.get('/rules')
def rules():
    return dict(items=fg.list_rules())


@router.post('/rules')
def add_rule(body: RuleBody):
    return fg.add_rule(body.group_id, body.department, body.title_contains)


@router.delete('/rules/{rule_id}')
def delete_rule(rule_id: str):
    fg.delete_rule(rule_id)
    return {'status': 'deleted'}


@router.get('/users/{username:path}', dependencies=[Depends(require_mapping)])
def classification(username: str):
    username = known_user(username)
    sync_organizational_changes()
    data = fg.read()
    context = directory_context(username)
    suggestion = fg.suggest(context.get('department', ''), context.get('title', ''), data) if context and context.get('match_status') == 'matched' else None
    return dict(classification=fg.public_user(data, username), history=fg.user_history(username, 0, 10), directory=context, suggestion=suggestion)


@router.put('/users/{username:path}', dependencies=[Depends(require_mapping)])
def classify(username: str, body: Classification):
    username = known_user(username)
    who = actor(body.reviewer).strip()
    if not who:
        raise HTTPException(422, 'A reviewer is required.')
    if body.group_id is None and not body.rationale.strip():
        raise HTTPException(422, 'A rationale is required to clear a Functional Group.')
    return fg.classify(username, body.group_id, body.rationale, body.expected_revision, who, body.change_id)


@router.get('/history/{username:path}', dependencies=[Depends(require_mapping)])
def history(username: str, offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
    return fg.user_history(known_user(username), offset, limit)
