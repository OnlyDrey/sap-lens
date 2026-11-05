"""Administrator view and control of data retention: policy, preview, one-time approval, history."""
import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

import data_retention
from config_models import StrictModel
from routers.backups import admin
from server_access import actor

router = APIRouter(prefix='/api/retention', tags=['Data Retention'])


class PolicyUpdate(StrictModel):
    enabled: bool
    months: int = Field(ge=data_retention.MIN_MONTHS, le=data_retention.MAX_MONTHS)


class Approval(StrictModel):
    confirm: bool
    preview_digest: str = Field(pattern=r'^[a-f0-9]{64}$')


@router.get('')
def status(request: Request):
    admin(request)
    return data_retention.status()


@router.get('/preview')
async def preview(request: Request):
    """What a cleanup would remove now (measurement only; the scan runs off the event loop)."""
    admin(request)
    return data_retention.public_plan(await asyncio.to_thread(data_retention.plan))


@router.put('/policy')
def policy(request: Request, body: PolicyUpdate):
    admin(request)
    return data_retention.set_policy(actor('administrator'), body.enabled, body.months)


@router.post('/approve')
async def approve(request: Request, body: Approval):
    """Approve destructive cleanup for the previewed retention period; the first cleanup runs immediately. Later cleanups follow the daily check."""
    admin(request)
    if not body.confirm:
        raise HTTPException(422, 'Confirm that the previewed data may be removed.')
    try:
        result = await asyncio.to_thread(data_retention.approve, actor('administrator'), body.preview_digest)
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    return dict(result, status=data_retention.status())
