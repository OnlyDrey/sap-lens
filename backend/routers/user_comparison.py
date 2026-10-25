"""Two-user role-derived coverage. Never infers effective SAP authorization."""
from datetime import date
from threading import RLock
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
import cache
from role_matching import normalize_role
from user_access import normalize_username, assignment_view, interval_status, sap_date
from .access import require_mapping, user_summary, page

_lock=RLock()
_cached_key=None
_cached_value=None

router = APIRouter(prefix='/api/user-comparison', dependencies=[Depends(require_mapping)])


def _compare(snapshot, left, right, validity='active'):
    users = snapshot.users.users
    keys = [normalize_username(left), normalize_username(right)]
    if keys[0] == keys[1]: raise HTTPException(422, 'Choose two different SAP users.')
    if any(k not in users for k in keys): raise HTTPException(404, 'A selected SAP user is not in the current export.')
    roles, codes = {}, {}
    today=date.today()
    for side, key in zip(('a', 'b'), keys):
        for a in users[key]['assignments']:
            if a['scope'] == 'other': continue
            status = interval_status(sap_date(a['valid_from']), sap_date(a['valid_to']),today)
            if validity != 'all' and status != validity: continue
            name = normalize_role(a['role_name'])
            item = roles.setdefault(name, dict(identifier=name, a=[], b=[], areas=[], description=''))
            # Retain every distinct interval and source group; do not flatten to membership.
            evidence = {k:v for k,v in assignment_view(a).items() if k not in {'tcodes','release','user_valid_from','user_valid_to','user_locked','user_type'}}
            item[side].append(evidence)
            for role in a['catalogue_roles'] if a['match_status'] in {'exact', 'wildcard'} else []:
                detail = snapshot.roles.get(role)
                if detail:
                    if detail.module_name and detail.module_name not in item['areas']: item['areas'].append(detail.module_name)
                    if not item['description']: item['description'] = detail.text or ''
            for code in a['tcodes'] if a['match_status'] in {'exact', 'wildcard'} else []:
                entry = codes.setdefault(code, dict(identifier=code, a=set(), b=set(), areas=[]))
                entry[side].add(name)
                entry['areas'] = sorted(set(entry['areas']) | set(item['areas']))
    for row in codes.values():
        for side in ('a','b'): row[side]=sorted(row[side])
    for collection in (roles, codes):
        for entry in collection.values(): entry['difference'] = 'shared' if entry['a'] and entry['b'] else 'a' if entry['a'] else 'b'
    return dict(users=[{**user_summary(users[k], users[k]['assignments']), 'identity_ambiguous':len({n for n in users[k]['names'] if any(n)})>1 or len(users[k]['emails'])>1} for k in keys], roles=roles, transactions=codes)


def compare(snapshot,left,right,validity='active'):
    global _cached_key,_cached_value
    key=(id(snapshot),snapshot.last_loaded,date.today(),normalize_username(left),normalize_username(right),validity)
    with _lock:
        if key != _cached_key:
            value=_compare(snapshot,left,right,validity)
            _cached_key,_cached_value=key,value
        return _cached_value


@router.get('/evidence')
def evidence(user_a:str=Query(...,min_length=1,max_length=512),user_b:str=Query(...,min_length=1,max_length=512),
             identifier:str=Query(...,min_length=1,max_length=512),side:Literal['a','b']='a',
             validity:Literal['active','expired','future','unknown','all']='active',kind:Literal['roles','transactions']='roles',
             offset:int=Query(0,ge=0),limit:int=Query(25,ge=1,le=100)):
    snapshot=cache.get_snapshot()
    result=compare(snapshot,user_a,user_b,validity)
    row=result[kind].get(normalize_role(identifier) if kind=='roles' else identifier)
    items=row[side] if row else []
    return dict(**page(items,offset,limit),data_revision=snapshot.last_loaded.isoformat() if snapshot.last_loaded else None,as_of=date.today().isoformat())


@router.get('')
def comparison(user_a: str = Query(..., min_length=1, max_length=512), user_b: str = Query(..., min_length=1, max_length=512),
               validity: Literal['active','expired','future','unknown','all'] = 'active',
               kind: Literal['roles','transactions'] = 'roles', difference: Literal['','shared','a','b'] = '',
               search: str = Query('', max_length=256), area: str = Query('', max_length=256),
               sort: Literal['identifier','difference','a','b'] = 'identifier', descending: bool = False,
               offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
    snapshot = cache.get_snapshot()
    result = compare(snapshot, user_a, user_b, validity)
    rows = list(result[kind].values())
    summaries = {name: {d: sum(r['difference']==d for r in result[name].values()) for d in ('shared','a','b')} for name in ('roles','transactions')}
    areas = sorted({a for r in result['roles'].values() for a in r['areas']})
    term = search.strip().casefold()
    rows = [r for r in rows if (not difference or r['difference']==difference) and (not area or area in r['areas']) and (not term or term in (r['identifier']+' '+r.get('description','')).casefold())]
    rows.sort(key=lambda r:(len(r[sort]) if sort in {'a','b'} else r[sort], r['identifier']), reverse=descending)
    bounded=[{**r, 'a':r['a'][:25], 'b':r['b'][:25], 'a_total':len(r['a']), 'b_total':len(r['b'])} for r in rows[offset:offset+limit]]
    return dict(items=bounded,total=len(rows),offset=offset,limit=limit, users=result['users'], summary=summaries, areas=areas,
                catalogue_available=bool(snapshot.roles), as_of=date.today().isoformat(),
                data_revision=snapshot.last_loaded.isoformat() if snapshot.last_loaded else None)
