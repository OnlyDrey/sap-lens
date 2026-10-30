"""Captured-generation potential SoD investigation and local evidence CSV export."""
import csv
from contextlib import contextmanager
from datetime import date
import hashlib
import io
import json
from threading import RLock
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
import cache
from config import get_settings
from csv_exports import spreadsheet_cell
from search_matching import search_fields, text_matches
from sod_analysis import analyze
import sod_catalogue as store
from user_access import sap_date

router = APIRouter(prefix='/api/sod/analysis', tags=['SoD analysis'])
_cache_lock = RLock()
_cached_key = _cached_snapshot = _cached_value = None


def analysis_query(kind: Literal['users', 'roles'] = 'users',
                   validity: Literal['active', 'expired', 'future', 'unknown', 'all'] = 'active',
                   as_of: date | None = None,
                   selected_roles: list[str] = Query(default=[], max_length=25),
                   search: str = Query('', max_length=256), risk: str = Query('', max_length=512),
                   criticality: str = Query('', max_length=64), risk_type: str = Query('', max_length=64),
                   category: str = Query('', max_length=120), username: str = Query('', max_length=512),
                   group: str = Query('', max_length=256), composite_role: str = Query('', max_length=512),
                   single_role: str = Query('', max_length=512), tcode: str = Query('', max_length=256),
                   account_status: Literal['', 'locked', 'unlocked', 'ad_disabled', 'ad_enabled', 'unknown'] = '',
                   usernames: list[str] = Query(default=[], max_length=100), risks: list[str] = Query(default=[], max_length=100),
                   criticalities: list[str] = Query(default=[], max_length=50), categories: list[str] = Query(default=[], max_length=50),
                   groups: list[str] = Query(default=[], max_length=100), tcodes: list[str] = Query(default=[], max_length=100),
                   sort: Literal['subject', 'risk_id', 'criticality', 'evidence_count'] = 'subject',
                   descending: bool = False):
    if any(not name or len(name) > 512 for name in selected_roles):
        raise HTTPException(422, 'Choose at most 25 existing catalogue role identifiers.')
    return dict(kind=kind, validity=validity, as_of=as_of or date.today(), selected_roles=sorted(set(selected_roles)),
                search=search, risk=risk, criticality=criticality, risk_type=risk_type, category=category,
                username=username, group=group, composite_role=composite_role, single_role=single_role,
                tcode=tcode, account_status=account_status, usernames=list(usernames), risks=list(risks), criticalities=list(criticalities),
                categories=list(categories), groups=list(groups), tcodes=list(tcodes), sort=sort, descending=descending)


def context_key(snapshot, settings, saved, query):
    references = {name: dict(snapshot=ref.snapshot, imported_at=ref.imported_at, checked_at=ref.checked_at)
                  for name, ref in settings.data_lifecycle.sources.items()}
    key = (id(snapshot), saved.revision, query['as_of'], query['validity'], tuple(query['selected_roles']),
           settings.features.user_role_mapping, settings.features.employee_directory, settings.features.sod,
           json.dumps(references, sort_keys=True))
    return key, references


def generation_for(key):
    return hashlib.sha256(json.dumps(key, default=str, sort_keys=True).encode()).hexdigest()


@contextmanager
def publication_guard(query, expected):
    """Hold publication stable only while committing a justified annotation."""
    with store.lock, cache._load_lock:
        key, _ = context_key(cache.get_snapshot(), get_settings(), store.read(), query)
        if generation_for(key) != expected:
            raise HTTPException(409, 'SoD source evidence changed. Reload before saving.')
        yield


def captured(query):
    """Capture locks in catalogue-write order; expensive analysis runs after release."""
    global _cached_key, _cached_snapshot, _cached_value
    with store.lock, cache._load_lock:
        snapshot = cache.get_snapshot()
        settings = get_settings()
        saved = store.read()
        metadata = {key: item.metadata.model_dump() for key, item in saved.entries.items()}
        key, source_refs = context_key(snapshot, settings, saved, query)
    with _cache_lock:
        if key == _cached_key and _cached_snapshot is snapshot:
            return _cached_value
    try:
        result = analyze(snapshot, metadata=metadata, as_of=query['as_of'], validity=query['validity'],
                         selected_roles=query['selected_roles'], mapping_enabled=key[5], directory_enabled=key[6], sod_enabled=key[7])
    except ValueError:
        raise HTTPException(422, 'A selected role or analysis option is unavailable in the current dataset.') from None
    definitions = {item['risk_id']: item for item in snapshot.sod.get('risks', [])}
    enriched = {}
    for kind in ('users', 'roles'):
        enriched[kind] = []
        for finding in result[kind]:
            source = definitions[finding['risk_id']]
            local = metadata.get(finding['risk_id'], {})
            if finding.get('account') is not None:
                from account_review import validity
                account = finding['account']
                locks = {row.get('locked') for row in account['accounts']}
                finding = {**finding, 'account': {**account,
                    'sap_validity': validity(account['accounts'], query['as_of']),
                    'lock_status': 'Locked' if locks == {True} else 'Unlocked' if locks == {False} else 'Unknown'}}
            enriched[kind].append({**finding, 'risk': dict(display_name=local.get('display_name', ''),
                source_text=source['source_text'], business_category=local.get('business_category', ''), risk_type=source['risk_type'])})
    generation = generation_for(key)
    value = {**result, **enriched, 'generation': generation,
             'sources': {**result['sources'], 'references': source_refs}}
    with _cache_lock:
        _cached_key, _cached_snapshot, _cached_value = key, snapshot, value
    return value


def _subject(row):
    return ' + '.join(row['subject']) if isinstance(row['subject'], list) else row['subject']


def _account_matches(row, selected):
    account = row.get('account')
    if not account:
        return False
    locks = {record.get('locked') for record in account.get('accounts', [])}
    if selected == 'locked': return locks == {True}
    if selected == 'unlocked': return locks == {False}
    if selected == 'ad_disabled': return account['ad_status'] == 'Disabled'
    if selected == 'ad_enabled': return account['ad_status'] == 'Enabled'
    return account['ad_status'] == 'Unknown' or locks not in ({True}, {False})


def _many(query, single, plural):
    """Requested values of one filter: the single value plus the multi-select list (OR within, AND with the other filters)."""
    return [value for value in [query.get(single) or '', *(query.get(plural) or [])] if value]


def filtered(result, query):
    items = []
    for row in result[query['kind']]:
        definition = row['risk']
        paths = [path for side in row['evidence'].values() for path in side]
        if query['search'].strip() and not search_fields(query['search'].strip(), _subject(row), row['risk_id'],
                definition['display_name'], definition['source_text'], *(path['tcode'] for path in paths),
                *(path['matched_catalogue_pattern'] for path in paths), *(path.get('actual_assigned_role', '') for path in paths)):
            continue
        if any(wanted and value not in wanted for wanted,value in [(_many(query,'risk','risks'),row['risk_id']),
                (_many(query,'criticality','criticalities'),row['criticality']),(_many(query,'category','categories'),definition['business_category'])]) \
                or query['risk_type'] and definition['risk_type'] != query['risk_type']:
            continue
        if query['username'] and (row['kind'] != 'user' or not text_matches(row['subject'], query['username'])):
            continue
        users = {name.casefold() for name in query.get('usernames') or []}
        if users and (row['kind'] != 'user' or row['subject'].casefold() not in users):
            continue
        fields = [('group','groups','user_group'),('tcode','tcodes','tcode')]
        if any(wanted and not any(text_matches(path.get(field, ''), item) for path in paths for item in wanted) for wanted,field in [(_many(query,single,plural),field) for single,plural,field in fields]):
            continue
        if any(query[key] and not any(text_matches(path.get(field, ''), query[key]) for path in paths) for key,field in [('composite_role','matched_catalogue_pattern'),('single_role','single_role')]):
            continue
        if query['account_status'] and not _account_matches(row, query['account_status']):
            continue
        items.append(row)
    def value(row):
        selected = sum(len(items) for items in row['evidence'].values()) if query['sort'] == 'evidence_count' else _subject(row) if query['sort'] == 'subject' else row[query['sort']]
        return (selected.casefold() if isinstance(selected, str) else selected, row['finding_id'])
    return sorted(items, key=value, reverse=query['descending'])


@router.get('')
def findings(response: Response, query: dict = Depends(analysis_query), offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
    response.headers['Cache-Control'] = 'no-store'
    result = captured(query)
    rows = filtered(result, query)
    items = [{**row, 'evidence': {side: paths[:25] for side, paths in row['evidence'].items()},
              'evidence_total': {side: len(paths) for side, paths in row['evidence'].items()}}
             for row in rows[offset:offset+limit]]
    return dict(items=items, total=len(rows), offset=offset, limit=limit, generation=result['generation'],
                summary=dict(unfiltered=result['summary'], filtered=dict(findings=len(rows), subjects=len({_subject(row) for row in rows}))),
                coverage=result['coverage'], methodology=result['methodology'], as_of=result['as_of'], sources=result['sources'])


@router.get('/evidence')
def evidence(response: Response, finding_id: str = Query(..., pattern=r'^[a-f0-9]{64}$'),
             expected_generation: str = Query(..., pattern=r'^[a-f0-9]{64}$'),
             side: Literal['ACTVT1','ACTVT2'] = 'ACTVT1', query: dict = Depends(analysis_query),
             offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
    response.headers['Cache-Control'] = 'no-store'
    result = captured(query)
    if result['generation'] != expected_generation:
        raise HTTPException(409, 'SoD evidence changed. Reload findings before inspecting further evidence.')
    row = next((row for row in result[query['kind']] if row['finding_id'] == finding_id), None)
    if row is None:
        raise HTTPException(404, 'The finding is unavailable in this analysis context.')
    paths = row['evidence'][side]
    return dict(items=paths[offset:offset+limit], total=len(paths), offset=offset, limit=limit,
                finding_id=finding_id, side=side, generation=result['generation'], as_of=result['as_of'])


EXPORT_COLUMNS = ['FINDING_ID','KIND','SUBJECT','RISK','CRITICITY','TYPE','ACTIVITY_SLOT','ACTIVITY','TCODE',
           'MATRIX_TRANSACTION','ROLE_NAME','CATALOGUE_ROLE','SINGLE_ROLE','ROLE_VALID_FROM','ROLE_VALID_TO',
           'ASSIGNMENT_STATUS','USER_GROUP','MATCHING_STATUS','EVIDENCE_VERSION','AS_OF','EVALUATION_POLICY',
           'SOD_SOURCE_VERSION','ROLE_SOURCE_VERSION','USER_SOURCE_VERSION']


EXPORT_HEADER = '\ufeff' + ';'.join('\"'+name+'\"' for name in EXPORT_COLUMNS) + '\r\n'
COLUMNS = EXPORT_COLUMNS


@router.get('/export')
def export(query: dict = Depends(analysis_query), expected_generation: str | None = Query(None, pattern=r'^[a-f0-9]{64}$')):
    result = captured(query)
    if expected_generation and result['generation'] != expected_generation:
        raise HTTPException(409, 'SoD evidence changed. Reload findings before exporting.')
    rows = filtered(result, query)
    def local_date(value):
        day = sap_date(value)
        return f'{day.day:02}.{day.month:02}.{day.year:04}' if day else ''
    def stream():
        yield EXPORT_HEADER
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=';', quoting=csv.QUOTE_ALL, lineterminator='\r\n')
        def line(values):
            buffer.seek(0); buffer.truncate(0)
            writer.writerow([spreadsheet_cell(value) for value in values])
            return buffer.getvalue()
        for row in rows:
            for side, paths in row['evidence'].items():
                for path in paths:
                    yield line([row['finding_id'],row['kind'],_subject(row),row['risk_id'],row['criticality'],row['risk']['risk_type'],
                        side,path['activity'],path['tcode'],path['matrix_transaction'],path.get('actual_assigned_role',''),
                        path['matched_catalogue_pattern'],path['single_role'],local_date(path.get('role_valid_from')),
                        local_date(path.get('role_valid_to')),path.get('interval_status','Not applicable'),path.get('user_group',''),
                        path.get('matching_status','Catalogue mapping'),row['evidence_version'],result['as_of'],row['evaluation_policy'],
                        *(result['sources']['references'].get(source, {}).get('snapshot', '') for source in ('sod','roles','users'))])
    return StreamingResponse(stream(), media_type='text/csv; charset=utf-8', headers={
        'Content-Disposition': f'attachment; filename="sap-lens-sod-{query["kind"]}-findings-{result["as_of"]}.csv"',
        'Cache-Control':'no-store', 'X-SAP-Lens-Data-Generation':result['generation'], 'X-SAP-Lens-As-Of':result['as_of'], 'X-SAP-Lens-Finding-Count':str(len(rows))})
