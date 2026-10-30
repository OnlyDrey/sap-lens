"""Bounded session-protected account review and spreadsheet-safe local export."""
from search_matching import search_fields
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
    items, position = review.current_rows(state, directory, saved, groups, day)
    generation = review.digest([state.last_loaded.isoformat() if state.last_loaded else None,
                                directory.digest if directory else None, groups, saved,
                                day.isoformat(), sorted(event['id'] for event in position.values())])
    return state, directory, items, generation


@router.get('')
def accounts(search: str = Query('', max_length=256), finding: str = Query('', max_length=64),
             license_group: Literal['', 'classified', 'exclude'] = '',
             review_state: Literal['', 'Needs review', 'Investigating', 'Approved for deactivation', 'No action required'] = '',
             findings: list[str] = Query([], max_length=32), license_groups: list[Literal['classified', 'exclude']] = Query([], max_length=2),
             review_states: list[Literal['Needs review', 'Investigating', 'Approved for deactivation', 'No action required']] = Query([], max_length=4),
             sort: Literal['username', 'name', 'sap_validity', 'lock_status', 'ad_status', 'review_state', 'priority'] = 'username',
             descending: bool = False, offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
    state, directory, items, generation = current()
    # Multi-value filters: OR within a filter, AND between filters. The singular parameters remain for older callers and saved links.
    wanted = [*dict.fromkeys([*findings, *([finding] if finding else [])])]
    licenses = {*license_groups, *([license_group] if license_group else [])}
    states = {*review_states, *([review_state] if review_state else [])}
    if set(wanted) - {*review.FINDINGS, 'any', 'stale', 'matched', 'reviewed', 'pending', 'position_change'}: raise HTTPException(422, 'Unknown review finding.')
    summary = dict(total=len(items), outdated=sum(r['stale'] for r in items), matched=sum(r['match_status'] == 'matched' for r in items) if directory else None,
                   missing=sum('directory_match' in r['findings'] for r in items) if directory else None,
                   mismatch=sum('ad_disabled_open' in r['findings'] for r in items),
                   requiring_review=sum(r['needs_review'] for r in items), position_changes=sum(bool(r['position_change'] and r['position_change']['open']) for r in items), unlicensed=sum(r['unlicensed'] for r in items),
                   reviewed=sum(bool(r['decision']) and r['review_state'] != 'Needs review' and not r['stale'] for r in items),
                   pending=sum(not r['decision'] or r['review_state'] == 'Needs review' or r['stale'] for r in items))
    if not state.users.report: summary = {key: None for key in summary}
    term = search.strip()
    def has(r, name):
        return (name == 'any' and r['needs_review'] or name == 'stale' and r['stale'] or name == 'matched' and r['match_status'] == 'matched'
                or name == 'reviewed' and bool(r['decision']) and r['review_state'] != 'Needs review' and not r['stale']
                or name == 'pending' and (not r['decision'] or r['review_state'] == 'Needs review' or r['stale'])
                or name == 'position_change' and bool(r['position_change'] and r['position_change']['open']) or name in r['findings'])
    # Both classifications selected (or neither) do not narrow the list.
    license_filter = licenses if len(licenses) == 1 else set()
    items = [r for r in items if (not term or search_fields(term,r['username'],r['name'],*r['groups']))
             and (not wanted or any(has(r, name) for name in wanted))
             and (not license_filter or r['unlicensed'] == ('classified' in license_filter))
             and (not states or r['review_state'] in states)]
    if sort == 'priority':
        items.sort(key=lambda r: (r['priority_order'], r['position_change']['detected_at'] if r['position_change'] else '', r['username'].casefold()), reverse=descending)
    else:
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
        review.save_decision(row['username'], dict(**request.model_dump(), evidence_schema=2, identity_version=row['identity_version'], timestamp=datetime.now(timezone.utc).isoformat()))
    return {'status': 'saved'}


@router.get('/history/{username:path}')
def history(username:str,offset:int=Query(0,ge=0),limit:int=Query(25,ge=1,le=100)):
    saved=review.decisions().get(review.digest(username.strip().upper()))
    events=list(reversed(saved.get('history',[]))) if saved else []
    return dict(items=events[offset:offset+limit],total=len(events),offset=offset,limit=limit)
