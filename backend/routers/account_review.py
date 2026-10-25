"""Bounded session-protected account review and spreadsheet-safe local export."""
from datetime import date, datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
import cache
import account_review as review
from config import get_settings
from config_models import StrictModel
from .access import require_mapping
from .employees import available

router = APIRouter(prefix='/api/account-review', tags=['Account Review'], dependencies=[Depends(require_mapping)])


class Decision(StrictModel):
    state: Literal['Needs review', 'Investigating', 'Approved for deactivation', 'No action required']
    reviewer: str = Field(min_length=1, max_length=120)
    rationale: str = Field(min_length=1, max_length=2000)
    evidence_version: str = Field(pattern=r'^[a-f0-9]{64}$')


def current():
    state = cache.get_snapshot()
    directory = available(state)
    saved = review.decisions()
    groups = get_settings().unlicensed_user_groups
    day = date.today()
    items = review.cached_rows(state, directory, saved, groups, day)
    generation = review.digest([state.last_loaded.isoformat() if state.last_loaded else None,
                                directory.digest if directory else None, groups, saved,
                                day.isoformat()])
    return state, directory, items, generation


@router.get('')
def accounts(search: str = Query('', max_length=256), finding: str = Query('', max_length=64),
             license_group: Literal['', 'classified', 'exclude'] = '',
             review_state: Literal['', 'Needs review', 'Investigating', 'Approved for deactivation', 'No action required'] = '',
             sort: Literal['username', 'name', 'sap_validity', 'lock_status', 'ad_status', 'review_state'] = 'username',
             descending: bool = False, offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
    state, directory, items, generation = current()
    if finding and finding not in {*review.FINDINGS, 'any', 'stale', 'matched'}: raise HTTPException(422, 'Unknown review finding.')
    summary = dict(total=len(items), outdated=sum(r['stale'] for r in items), matched=sum(r['match_status'] == 'matched' for r in items) if directory else None,
                   missing=sum('directory_match' in r['findings'] for r in items) if directory else None,
                   mismatch=sum('ad_disabled_open' in r['findings'] for r in items),
                   requiring_review=sum(r['needs_review'] for r in items), unlicensed=sum(r['unlicensed'] for r in items),
                   reviewed=sum(bool(r['decision']) and r['review_state'] != 'Needs review' and not r['stale'] for r in items))
    if not state.users.report: summary = {key: None for key in summary}
    term = search.strip().casefold()
    items = [r for r in items if (not term or term in ' '.join([r['username'], r['name'], *r['groups']]).casefold())
             and (not finding or finding == 'any' and r['needs_review'] or finding == 'stale' and r['stale'] or finding == 'matched' and r['match_status'] == 'matched' or finding in r['findings'])
             and (not license_group or r['unlicensed'] == (license_group == 'classified'))
             and (not review_state or r['review_state'] == review_state)]
    items.sort(key=lambda r: (r[sort].casefold(), r['username'].casefold()), reverse=descending)
    return dict(items=items[offset:offset+limit], total=len(items), offset=offset, limit=limit,
                loaded=bool(state.users.report), directory_available=bool(directory), summary=summary,
                data_revision=generation, finding_labels=review.FINDINGS, review_states=review.STATES)


@router.post('/decision/{username:path}')
def decision(username: str, request: Decision):
    if not request.reviewer.strip() or not request.rationale.strip(): raise HTTPException(422, 'Reviewer and rationale are required.')
    with review.lock:
        _, _, items, _ = current()
        row = next((r for r in items if r['username'].strip().upper() == username.strip().upper()), None)
        if row is None: raise HTTPException(404, 'SAP user not found.')
        if row['evidence_version'] != request.evidence_version: raise HTTPException(409, 'Identity evidence changed. Refresh the review before saving.')
        review.save_decision(row['username'], dict(**request.model_dump(), timestamp=datetime.now(timezone.utc).isoformat()))
    return {'status': 'saved'}
