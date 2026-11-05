"""Administrator view and control of data retention: policy, preview, one-time approval, history."""
import asyncio
from typing import Literal

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
    review_months: int | None = Field(default=None, ge=data_retention.MIN_MONTHS, le=data_retention.MAX_MONTHS)


class Approval(StrictModel):
    confirm: bool
    category: Literal['source', 'review'] = 'source'
    preview_digest: str = Field(pattern=r'^[a-f0-9]{64}$')


@router.get('')
def status(request: Request):
    admin(request)
    return data_retention.status()


@router.get('/preview')
async def preview(request: Request, category: Literal['source', 'review'] = 'source'):
    """What a cleanup of one category would remove now (measurement only; the scan runs off the event loop)."""
    admin(request)
    return await asyncio.to_thread(data_retention.plan_for, category) if category == 'review' else data_retention.public_plan(await asyncio.to_thread(data_retention.plan))


@router.put('/policy')
def policy(request: Request, body: PolicyUpdate):
    admin(request)
    return data_retention.set_policy(actor('administrator'), body.enabled, body.months, review_months=body.review_months)


@router.post('/approve')
async def approve(request: Request, body: Approval):
    """Approve destructive cleanup for the previewed retention period; the first cleanup runs immediately. Later cleanups follow the daily check."""
    admin(request)
    if not body.confirm:
        raise HTTPException(422, 'Confirm that the previewed data may be removed.')
    try:
        result = await asyncio.to_thread(data_retention.approve, actor('administrator'), body.preview_digest, None, body.category)
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    return dict(result, status=data_retention.status())


class Undo(StrictModel):
    operation: str = Field(pattern=r'^[a-f0-9]{32}$')
    confirm: bool


@router.post('/review/undo')
async def undo(request: Request, body: Undo):
    """Restore the review periods of an earlier cleanup from its retained copy and trash (within 30 days)."""
    admin(request)
    if not body.confirm:
        raise HTTPException(422, 'Confirm that the removed review periods should be restored.')
    import review_retention
    try:
        return await asyncio.to_thread(review_retention.undo, body.operation)
    except (ValueError, OSError) as error:
        raise HTTPException(409, str(error)) from None
