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


@router.get('/users/{username:path}', dependencies=[Depends(require_mapping)])
def classification(username: str):
    username = known_user(username)
    return dict(classification=fg.public_user(fg.read(), username), history=fg.user_history(username, 0, 10))


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
