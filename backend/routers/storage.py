"""Administrator view of the SQLite source store and the retained pre-migration backup."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

import assignment_lifecycle
import storage_migration
from config_models import StrictModel
from routers.backups import admin
from server_access import actor

router = APIRouter(prefix='/api/storage', tags=['Storage'])


class Confirmation(StrictModel):
    migration_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    confirm: bool


@router.get('/status')
def status(request: Request):
    admin(request)
    _, state, detail = assignment_lifecycle.load()
    return dict(storage_migration.status(), review_continuity=dict(state=state, detail=detail))


@router.post('/migration/confirm')
def confirm(request: Request, body: Confirmation):
    """Releases the pre-migration backup. Explicit and administrator-only; nothing removes the archive by age."""
    admin(request)
    if not body.confirm:
        raise HTTPException(422, 'Confirm that the upgraded installation works to release the pre-migration backup.')
    try:
        return storage_migration.confirm(body.migration_id, actor('administrator'))
    except storage_migration.NotReady as error:
        raise HTTPException(409, str(error)) from None


@router.post('/migration/delete-backup')
def delete_backup(request: Request, body: Confirmation):
    """Deletes the pre-migration backup of an already confirmed migration. Explicit and administrator-only."""
    admin(request)
    if not body.confirm:
        raise HTTPException(422, 'Confirm that the pre-migration backup may be deleted.')
    try:
        return storage_migration.delete_backup(body.migration_id, actor('administrator'))
    except storage_migration.NotReady as error:
        raise HTTPException(409, str(error)) from None


class Rebaseline(StrictModel):
    confirm: bool


@router.post('/lifecycle/rebaseline')
def rebaseline(request: Request, body: Rebaseline):
    """Administrator acknowledges the current imported data as the continuity baseline after the lifecycle memory was damaged, lost or rolled back.

    Earlier assignment decisions then apply again; their history is untouched. Anyone relying on the decisions should first check the data."""
    admin(request)
    if not body.confirm:
        raise HTTPException(422, 'Confirm that the current imported data may serve as the continuity baseline.')
    assignment_lifecycle.rebaseline(actor('administrator'))
    _, state, detail = assignment_lifecycle.load()
    return dict(review_continuity=dict(state=state, detail=detail))
