"""Administrator view of the SQLite source store and the retained pre-migration backup."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

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
    return storage_migration.status()


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
