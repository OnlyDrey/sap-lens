"""SoD 2.0: matrices, access explorer, investigation workspace, review queue, decisions, what-if and remediation.

Technical conflict calculation stays in ``sod_analysis``; decisions here never change imported evidence.
"""
import csv
from datetime import date
import io
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import Field

from config_models import StrictModel
from csv_exports import spreadsheet_cell
import sod_decisions as decisions
import sod_governance as governance
import sod_reviews as legacy
import sod_scope as scope
from .sod_analysis import context_key, publication_guard

router = APIRouter(prefix='/api/sod', tags=['SoD governance'])
Lifecycle = Literal['', 'Pending', 'Approved', 'Keep', 'Accepted', 'Conditional', 'Removal required', 'Rejected', 'Outdated']
MAX_COLUMNS = 500


def scope_query(context: str = Query('current', pattern=legacy.CONTEXT_PATTERN),
                validity: Literal['active', 'expired', 'future', 'unknown', 'all'] = 'active', as_of: date | None = None,
                search: str = Query('', max_length=256), risk: str = Query('', max_length=512), criticality: str = Query('', max_length=64),
                risk_type: str = Query('', max_length=64), category: str = Query('', max_length=120), username: str = Query('', max_length=512),
                group: str = Query('', max_length=256), composite_role: str = Query('', max_length=512), single_role: str = Query('', max_length=512),
                tcode: str = Query('', max_length=256), role: str = Query('', max_length=512), role_suffix: str = Query('', max_length=128),
                activity: str = Query('', max_length=512),
                account_status: Literal['', 'locked', 'unlocked', 'ad_disabled', 'ad_enabled', 'unknown'] = '',
                activity_decision: Lifecycle = '', assignment_decision: Lifecycle = '', acceptance: Lifecycle = '',
                sort: Literal['subject', 'findings'] = 'subject', descending: bool = False):
    return locals()


def info(bundle, **extra):
    return dict(scope.context_info(bundle), **extra)


def _built(kind, q):
    bundle, _, state, view = scope.scoped(q['context'], q)
    builder = governance.risk_matrix if kind == 'risk' else governance.activity_matrix
    return bundle, builder(view, state)


def _matrix(kind, group_by, offset, limit, q):
    bundle, matrix = _built(kind, q)
    key = 'acceptance' if kind == 'risk' else 'decision'
    status_counts = {}
    for row in matrix['rows']:
        for cell in row['cells'].values():
            status_counts[cell[key]] = status_counts.get(cell[key], 0) + 1
    if group_by == 'group':
        matrix = governance.aggregate_by_group(matrix)
    rows = matrix['rows']
    if q['sort'] == 'findings':
        rows = sorted(rows, key=lambda row: (-len(row['cells']), row['user']), reverse=q['descending'])
    elif q['descending']:
        rows = list(reversed(rows))
    columns = matrix['columns'][:MAX_COLUMNS]
    keep = {column['risk_id' if kind == 'risk' else 'activity'] for column in columns}
    page = [dict(row, cells={name: cell for name, cell in row['cells'].items() if name in keep}) for row in rows[offset:offset + limit]]
    extra = {name: value for name, value in matrix.items() if name not in {'columns', 'rows'}}
    return dict(info(bundle), kind=kind, group_by=group_by, columns=columns, columns_truncated=len(matrix['columns']) > MAX_COLUMNS, rows=page,
                total_rows=len(rows), offset=offset, limit=limit, status_counts=status_counts, **extra)


@router.get('/matrix/risk')
def risk_matrix(q: dict = Depends(scope_query), group_by: Literal['user', 'group'] = 'user', offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    return _matrix('risk', group_by, offset, limit, q)


@router.get('/matrix/activity')
def activity_matrix(q: dict = Depends(scope_query), group_by: Literal['user', 'group'] = 'user', offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    return _matrix('activity', group_by, offset, limit, q)


OPTION_FIELDS = Literal['risk', 'activity', 'criticality', 'risk_type', 'category', 'group', 'username', 'role', 'role_suffix', 'tcode',
                        'composite_role', 'single_role']


def option_values(model, field):
    """Distinct values present in the imported evidence for one filter field (unfiltered by the other filters)."""
    values = set()
    for user, entry in model.items():
        if field == 'username':
            values.add(user)
        elif field == 'group':
            values.update(entry['groups'])
        elif field in {'risk', 'criticality', 'risk_type', 'category'}:
            for risk_id, finding in entry['findings'].items():
                definition = finding.get('risk') or {}
                values.add({'risk': risk_id, 'criticality': finding['criticality'], 'risk_type': definition.get('risk_type', ''),
                            'category': definition.get('business_category', '')}[field])
        elif field in {'activity', 'tcode'}:
            for activity in entry['activities'].values():
                values.update([activity['activity']] if field == 'activity' else activity['tcodes'])
        else:
            for assignment in entry['assignments'].values():
                if field == 'role':
                    values.add(assignment['role'])
                elif field == 'role_suffix':
                    name = assignment['role']
                    cut = max(name.rfind(mark) for mark in ':_-')
                    values.add(name[cut + 1:] if cut >= 0 else '')
                else:
                    values.update(assignment['catalogue_roles' if field == 'composite_role' else 'single_roles'])
    return sorted((value for value in values if value), key=lambda value: (value.casefold(), value))


@router.get('/filter-options')
def filter_options(q: dict = Depends(scope_query), field: OPTION_FIELDS = 'risk', term: str = Query('', max_length=128), limit: int = Query(50, ge=1, le=200)):
    """Searchable predefined filter values taken from the imported SoD evidence of this context."""
    bundle = scope.load(q['context'], q['validity'], q['as_of'])
    values = option_values(scope.model_for(bundle), field)
    needle = term.strip().casefold()
    if needle:
        values = [value for value in values if needle in value.casefold()]
    return dict(info(bundle), field=field, items=values[:limit], total=len(values))


HEATMAP_COLUMNS = {kind: ['SAP_USER_GROUP', 'RISK_ID' if kind == 'risk' else 'ACTIVITY', 'USERS_WITH_ITEM', 'USERS_IN_GROUP_WITH_ITEMS'] for kind in ('risk', 'activity')}


@router.get('/matrix/{kind}/group-export')
def group_heatmap_export(kind: Literal['risk', 'activity'], q: dict = Depends(scope_query)):
    """Long-format CSV of the SAP-user-group heatmap: distinct users per group and risk (or activity), honoring every filter."""
    _, matrix = _built(kind, q)
    grouped = governance.aggregate_by_group(matrix)
    rows = ((row['user'], column, cell['users'], row['users']) for row in grouped['rows'] for column, cell in row['cells'].items())
    return csv_response(HEATMAP_COLUMNS[kind], rows, f'group-{kind}-heatmap')


def _explorer(table, q):
    bundle, model, state, view = scope.scoped(q['context'], q)
    rows = governance.explorer_rows(table, view, state)
    if table == 'access_list':
        shown = {(row['user'], aid) for row in rows for aid in [row['id']]}
        rows = [row for row in rows if (row['user'], row['id']) in shown and set(row['risks']) & set(view[row['user']]['findings'])]
    if q['descending']:
        rows = list(reversed(rows))
    return bundle, rows


@router.get('/explorer/{table}')
def explorer(table: Literal['user_risk', 'user_activity', 'access_list', 'lookup'], q: dict = Depends(scope_query),
             offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    bundle, rows = _explorer(table, q)
    return dict(info(bundle), table=table, items=rows[offset:offset + limit], total=len(rows), offset=offset, limit=limit)


def csv_header(columns):
    return '\ufeff' + ';'.join('"' + column + '"' for column in columns) + '\r\n'


def csv_response(columns, rows, name):
    header = csv_header(columns)

    def stream():
        yield header
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=';', quoting=csv.QUOTE_ALL, lineterminator='\r\n')
        for values in rows:
            buffer.seek(0)
            buffer.truncate(0)
            writer.writerow([spreadsheet_cell(value) for value in values])
            yield buffer.getvalue()
    return StreamingResponse(stream(), media_type='text/csv; charset=utf-8', headers={
        'Content-Disposition': f'attachment; filename="sap-lens-sod-{name}-{date.today().isoformat()}.csv"', 'Cache-Control': 'no-store'})


def _dates(row):
    return row.get('valid_from') or '', row.get('valid_to') or ''


EXPLORER_COLUMNS = {
    'user_risk': (['USERNAME', 'RISK', 'CRITICITY', 'BUSINESS_AREA', 'USER_GROUPS', 'ACTIVITIES', 'ROLES', 'RISK_ACCEPTANCE'],
                  lambda r: [r['user'], r['risk_id'], r['criticality'], r['category'], ', '.join(r['groups']), ', '.join(r['activities']), ', '.join(r['roles']), r['acceptance']]),
    'user_activity': (['USERNAME', 'ACTIVITY', 'RISKS', 'TRANSACTIONS', 'ROLE_ASSIGNMENTS', 'DUPLICATE_COVERAGE', 'ACTIVITY_REVIEW'],
                      lambda r: [r['user'], r['activity'], ', '.join(r['risks']), ', '.join(r['tcodes']), r['roles'], 'Yes' if r['duplicate'] else 'No', r['decision']]),
    'access_list': (['USERNAME', 'ROLE', 'VALID_FROM', 'VALID_TO', 'ASSIGNMENT_STATUS', 'USER_GROUP', 'ACTIVITIES', 'RISKS', 'ASSIGNMENT_REVIEW'],
                    lambda r: [r['user'], r['role'], *_dates(r), r['interval_status'], r['user_group'], ', '.join(r['activities']), ', '.join(r['risks']), r['decision']]),
    'lookup': (['ROLE', 'USERS', 'CATALOGUE_ROLES', 'ACTIVITIES', 'RISKS'],
               lambda r: [r['role'], r['users'], ', '.join(r['catalogue_roles']), ', '.join(r['activities']), ', '.join(r['risks'])]),
}


@router.get('/explorer/{table}/export')
def explorer_export(table: Literal['user_risk', 'user_activity', 'access_list', 'lookup'], q: dict = Depends(scope_query)):
    _, rows = _explorer(table, q)
    columns, shape = EXPLORER_COLUMNS[table]
    return csv_response(columns, (shape(row) for row in rows), f'explorer-{table.replace("_", "-")}')


def _event(event):
    return event.model_dump(mode='json') if event else None


def _decision_map(entry, state):
    return {name: state['activity'][item['key']][0] for name, item in entry['activities'].items()}


@router.get('/subject')
def subject(q: dict = Depends(scope_query), user: str = Query(..., max_length=512), risk: str = Query('', max_length=512),
            activity: str = Query('', max_length=512)):
    """Shared investigation workspace: evidence path, decisions, history pointers and removal impact."""
    bundle = scope.load(q['context'], q['validity'], q['as_of'])
    model = scope.model_for(bundle)
    entry = model.get(user)
    if entry is None:
        raise HTTPException(404, 'The SAP user has no detected conflict evidence in this context.')
    state = governance.states(model, scope.latest_for(bundle))
    if risk and risk not in entry['findings']:
        raise HTTPException(404, 'The risk is not detected for this user in this context.')
    if activity and activity not in entry['activities']:
        raise HTTPException(404, 'The activity is not evidenced for this user in this context.')
    names = sorted(name for name, item in entry['activities'].items()
                   if (not risk or risk in item['risks']) and (not activity or name == activity))
    rows = []
    for name in names:
        detail = governance.activity_detail(entry, name)
        lifecycle_name, event = state['activity'][detail['key']]
        for assignment in detail['assignments']:
            a_state, a_event = state['assignment'][assignment['id']]
            assignment.update(decision=a_state, event=_event(a_event))
        rows.append(dict(detail, decision=lifecycle_name, event=_event(event)))
    finding = entry['findings'].get(risk) if risk else None
    risk_info = None
    if finding:
        acceptance_state, acceptance_event = state['acceptance'][finding['finding_id']]
        definition = finding.get('risk') or {}
        with legacy.lock:
            old = legacy.history(finding['finding_id'], q['context'])[:5] if legacy.read().contexts.get(q['context']) else []
        risk_info = dict(risk_id=risk, criticality=finding['criticality'], display_name=definition.get('display_name', ''), source_text=definition.get('source_text', ''),
                         category=definition.get('business_category', ''), risk_type=definition.get('risk_type', ''), finding_id=finding['finding_id'],
                         evidence_version=finding['evidence_version'], sides={side: sorted({path['activity'] for path in paths}) for side, paths in finding['evidence'].items()},
                         acceptance=acceptance_state, event=_event(acceptance_event), legacy_decisions=old)
    related = sorted({other for name in names for other in entry['activities'][name]['risks']} - {risk}) if names else []
    impact = None
    if finding:
        mapping = _decision_map(entry, state)
        impact = dict(options=governance.removal_options(entry, risk, mapping),
                      per_assignment={aid: governance.single_assignment_impact(entry, aid, mapping)
                                      for name in names for aid in entry['activities'][name]['assignments']})
    overview = dict(
        activities=[dict(activity=name, key=item['key'], decision=state['activity'][item['key']][0], event=_event(state['activity'][item['key']][1]),
                         evidence_version=item['evidence_version'], risks=sorted(item['risks']), tcodes=sorted(item['tcodes']),
                         roles=len(item['assignments']), duplicate_coverage=len(item['assignments']) > 1) for name, item in sorted(entry['activities'].items())],
        assignments=[dict(id=aid, role=item['role'], decision=state['assignment'][aid][0], event=_event(state['assignment'][aid][1]), evidence_version=item['evidence_version'],
                          risks=sorted(item['risks']), activities=sorted(item['supplies']), valid_from=item['valid_from'], valid_to=item['valid_to'],
                          interval_status=item['interval_status'], user_group=item['user_group'], catalogue_roles=sorted(item['catalogue_roles']))
                     for aid, item in sorted(entry['assignments'].items(), key=lambda pair: (pair[1]['role'].casefold(), pair[0]))],
        risks=[dict(risk_id=risk_id, criticality=item['criticality'], display_name=(item.get('risk') or {}).get('display_name', ''),
                    source_text=(item.get('risk') or {}).get('source_text', ''), finding_id=item['finding_id'], evidence_version=item['evidence_version'],
                    acceptance=state['acceptance'][item['finding_id']][0], event=_event(state['acceptance'][item['finding_id']][1]))
               for risk_id, item in sorted(entry['findings'].items())])
    return dict(info(bundle), user=user, groups=sorted(entry['groups']), account=entry.get('account'), risk=risk_info, activities=rows, related_risks=related, impact=impact, overview=overview)


class SimulateBody(StrictModel):
    context: str = Field(default='current', pattern=legacy.CONTEXT_PATTERN)
    user: str = Field(min_length=1, max_length=512)
    removed: list[str] = Field(default_factory=list, max_length=200)


@router.post('/simulate')
def simulate(body: SimulateBody):
    """Read-only what-if over a copy of the evidence; imported SAP data and decisions are untouched."""
    bundle = scope.load(body.context)
    model = scope.model_for(bundle)
    entry = model.get(body.user)
    if entry is None:
        raise HTTPException(404, 'The SAP user has no detected conflict evidence in this context.')
    state = governance.states(model, scope.latest_for(bundle))
    try:
        result = governance.simulate(entry, body.removed, _decision_map(entry, state))
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    return dict(info(bundle), user=body.user, **result, policy='sod-two-sided-v1',
                note='Simulation only: SAP Lens does not change SAP. A removal recommendation is not confirmed removal.')


STATUS_FILTERS = ('Pending', 'Reviewed', 'Conditional', 'Removal required', 'Rejected', 'Risk acceptance pending', 'Awaiting approval', 'Outdated', 'Resolved', 'Historical')


def _status_match(item, status, awaiting):
    life = item['lifecycle']
    return {'Pending': life == 'Pending', 'Reviewed': life in {'Approved', 'Keep', 'Accepted'}, 'Conditional': life == 'Conditional',
            'Removal required': life == 'Removal required', 'Rejected': life == 'Rejected',
            'Risk acceptance pending': item['kind'] == 'acceptance' and life == 'Pending',
            'Awaiting approval': awaiting and life in scope.DECIDED, 'Outdated': life == 'Outdated', 'Resolved': life == 'Resolved', 'Historical': life == 'Historical'}[status]


def _queue(q, kind, status):
    bundle, model, state, view = scope.scoped(q['context'], q)
    items = governance.queue_items(view, state)
    if q['context'] == 'current' and bundle['reviewable'] and not any(q[name] for name in ('search', 'risk', 'username', 'role', 'activity', 'group', 'criticality', 'category')):
        known = dict(activity={item['key'] for entry in model.values() for item in entry['activities'].values()},
                     assignment={aid for entry in model.values() for aid in entry['assignments']},
                     acceptance={finding['finding_id'] for entry in model.values() for finding in entry['findings'].values()})
        for kind_name, events in scope.latest_for(bundle).items():
            for key, event in events.items():
                if key not in known[kind_name]:
                    items.append(dict(kind=kind_name, key=key, user=event.user, ref=event.ref, risks=[event.ref] if kind_name == 'acceptance' else [],
                                      lifecycle=scope.orphan_lifecycle(kind_name, event), roles=0, event=event, evidence_version=event.evidence_version))
    awaiting = bool(bundle['period'] and bundle['period']['state'] == 'Ready for approval')
    if kind:
        items = [item for item in items if item['kind'] == kind]
    counts = {name: sum(_status_match(item, name, awaiting) for item in items) for name in STATUS_FILTERS}
    if status:
        items = [item for item in items if _status_match(item, status, awaiting)]
    order = {'activity': 0, 'assignment': 1, 'acceptance': 2}
    items.sort(key=lambda item: (item['user'].casefold(), order[item['kind']], item['ref'].casefold()))
    return bundle, items, counts


QUEUE_COLUMNS = ['CONTEXT', 'REVIEW_TYPE', 'USERNAME', 'REFERENCE', 'RISKS', 'LIFECYCLE', 'DECISION', 'REVIEWER', 'APPROVER', 'TIMESTAMP',
                 'JUSTIFICATION', 'CONTROLS', 'EXPIRES', 'EVIDENCE_VERSION']


def native_csv_header(filename):
    """Exact header contract for a native Save dialog, or None when the filename is not a SoD 2.0 export."""
    import re
    match = re.fullmatch(r'sap-lens-sod-(explorer-(user-risk|user-activity|access-list|lookup)|group-(risk|activity)-heatmap|review-queue|access-remediation)-\d{4}-\d{2}-\d{2}\.csv', filename)
    if not match:
        return None
    name = match.group(1)
    if name == 'review-queue':
        return csv_header(QUEUE_COLUMNS)
    if name == 'access-remediation':
        return csv_header(REMEDIATION_COLUMNS)
    if name.startswith('group-'):
        return csv_header(HEATMAP_COLUMNS[match.group(3)])
    return csv_header(EXPLORER_COLUMNS[match.group(2).replace('-', '_')][0])


def _public(item):
    return dict(item, event=_event(item['event']))


@router.get('/queue')
def queue(q: dict = Depends(scope_query), kind: Literal['', 'activity', 'assignment', 'acceptance'] = '',
          status: Literal['', 'Pending', 'Reviewed', 'Conditional', 'Removal required', 'Rejected', 'Risk acceptance pending', 'Awaiting approval', 'Outdated', 'Resolved', 'Historical'] = '',
          offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    bundle, items, counts = _queue(q, kind, status)
    return dict(info(bundle), items=[_public(item) for item in items[offset:offset + limit]], total=len(items), counts=counts, offset=offset, limit=limit,
                identity_notice=legacy.IDENTITY_NOTICE)


PROGRESS_FILTERS = ('', 'outstanding', 'complete', 'removal')


@router.get('/queue/users')
def queue_users(q: dict = Depends(scope_query), progress: Literal['', 'outstanding', 'complete', 'removal'] = '',
                offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    """One row per SAP user with independent progress for activity, role assignment and risk acceptance reviews."""
    bundle, items, _ = _queue(q, '', '')
    rows = {}
    for item in items:
        row = rows.setdefault(item['user'], dict(user=item['user'], activity=dict(total=0, decided=0), assignment=dict(total=0, decided=0), acceptance=dict(total=0, decided=0), removal=0, historical=0))
        if item['lifecycle'] in {'Historical', 'Resolved'}:
            row['historical'] += 1
            continue
        part = row[item['kind']]
        part['total'] += 1
        part['decided'] += item['lifecycle'] in scope.DECIDED
        row['removal'] += item['lifecycle'] == 'Removal required'
    result = []
    for row in rows.values():
        total = sum(row[kind]['total'] for kind in decisions.DECISIONS)
        decided = sum(row[kind]['decided'] for kind in decisions.DECISIONS)
        result.append(dict(row, total=total, decided=decided, outstanding=total - decided))
    result = [row for row in result if row['total']]
    counts = dict(all=len(result), outstanding=sum(row['outstanding'] > 0 for row in result), complete=sum(row['total'] > 0 and row['outstanding'] == 0 for row in result), removal=sum(row['removal'] > 0 for row in result))
    if progress == 'outstanding':
        result = [row for row in result if row['outstanding'] > 0]
    elif progress == 'complete':
        result = [row for row in result if row['total'] > 0 and row['outstanding'] == 0]
    elif progress == 'removal':
        result = [row for row in result if row['removal'] > 0]
    result.sort(key=lambda row: (-row['outstanding'], row['user'].casefold()))
    if q['descending']:
        result.reverse()
    return dict(info(bundle), items=result[offset:offset + limit], total=len(result), counts=counts, offset=offset, limit=limit)


@router.get('/queue/export')
def queue_export(q: dict = Depends(scope_query), kind: Literal['', 'activity', 'assignment', 'acceptance'] = '',
                 status: Literal['', 'Pending', 'Reviewed', 'Conditional', 'Removal required', 'Rejected', 'Risk acceptance pending', 'Awaiting approval', 'Outdated', 'Resolved', 'Historical'] = ''):
    _, items, _ = _queue(q, kind, status)

    def rows():
        for item in items:
            event = item['event']
            yield [q['context'], item['kind'], item['user'], item['ref'], ', '.join(item['risks']), item['lifecycle'], event.decision if event else '',
                   event.reviewer if event else '', event.approver if event else '', event.timestamp if event else '', event.justification if event else '',
                   event.controls if event else '', event.expires.isoformat() if event and event.expires else '', event.evidence_version if event else '']
    return csv_response(QUEUE_COLUMNS, rows(), 'review-queue')


class DecisionItem(StrictModel):
    key: str = Field(pattern=r'^[a-f0-9]{64}$')
    user: str = Field(min_length=1, max_length=512)
    ref: str = Field(min_length=1, max_length=512)
    evidence_version: str = Field(pattern=r'^[a-f0-9]{64}$')


class DecisionBody(StrictModel):
    context: str = Field(default='current', pattern=legacy.CONTEXT_PATTERN)
    expected_revision: int = Field(ge=0)
    expected_generation: str = Field(pattern=r'^[a-f0-9]{64}$')
    items: list[DecisionItem] = Field(min_length=1, max_length=decisions.MAX_BATCH)
    decision: str = Field(max_length=40)
    reviewer: str = Field(min_length=1, max_length=120)
    approver: str = Field(default='', max_length=120)
    justification: str = Field(min_length=1, max_length=4000)
    controls: str = Field(default='', max_length=8000)
    expires: date | None = None


def _locate(model, kind, item):
    entry = model.get(item.user)
    if entry is None:
        return None
    if kind == 'activity':
        found = entry['activities'].get(item.ref)
        return (found, found['key'], found['evidence_version'], governance.activity_detail(entry, item.ref)) if found else None
    if kind == 'assignment':
        found = entry['assignments'].get(item.key)
        return (found, found['id'], found['evidence_version'], governance.listify({k: v for k, v in found.items()})) if found else None
    found = entry['findings'].get(item.ref)
    return (found, found['finding_id'], found['evidence_version'], found) if found else None


@router.post('/decisions/{kind}')
def decide(kind: Literal['activity', 'assignment', 'acceptance'], body: DecisionBody):
    """Record one decision for explicitly listed items; nothing propagates to unlisted users or items."""
    if body.decision not in decisions.DECISIONS[kind]:
        raise HTTPException(422, 'Choose a decision supported by this review type.')
    bundle = scope.load(body.context)
    if not bundle['reviewable']:
        raise HTTPException(409, 'This context accepts no decisions. Frozen periods and non-current evidence are read-only.')
    if bundle['generation'] != body.expected_generation:
        raise HTTPException(409, 'SoD evidence changed. Reload before reviewing.')
    model = scope.model_for(bundle)
    items = []
    for item in body.items:
        located = _locate(model, kind, item)
        if located is None or located[1] != item.key:
            raise HTTPException(409, 'A selected item is no longer supported by current evidence. Reload before reviewing.')
        _, key, version, evidence = located
        if version != item.evidence_version:
            raise HTTPException(409, 'Evidence for a selected item changed. Reload before reviewing.')
        items.append(dict(key=key, user=item.user, ref=item.ref, evidence_version=version, evidence=evidence))
    try:
        record = lambda: decisions.record(kind, body.context, items, body.decision, body.reviewer, body.justification, body.expected_revision,
                                          approver=body.approver, controls=body.controls, expires=body.expires, source_versions=bundle['versions'])
        if body.context == 'current':
            with publication_guard(bundle['query'], body.expected_generation):
                return record()
        return record()
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@router.get('/decisions/{kind}/history')
def decision_history(kind: Literal['activity', 'assignment', 'acceptance'], key: str = Query(..., pattern=r'^[a-f0-9]{64}$'),
                     context: str = Query('current', pattern=legacy.CONTEXT_PATTERN)):
    return dict(items=decisions.history(kind, context, key), reviewer_identity=legacy.IDENTITY_NOTICE)


@router.get('/decisions/{kind}/evidence')
def decision_evidence(kind: Literal['activity', 'assignment', 'acceptance'], event_id: str = Query(..., pattern=r'^[a-f0-9]{32}$'),
                      key: str = Query(..., pattern=r'^[a-f0-9]{64}$'), context: str = Query('current', pattern=legacy.CONTEXT_PATTERN)):
    event = next((item for item in decisions.history(kind, context, key) if item['event_id'] == event_id), None)
    if event is None:
        raise HTTPException(404, 'Decision event is not available.')
    return dict(event=event, evidence=decisions.evidence_for(event))


def remediation_data(q):
    bundle, model, state, view = scope.scoped(q['context'], q)
    frozen = bundle['frozen_decisions']
    verify = (lambda user, aid: (frozen.get('verification') or {}).get(aid, 'Not assessed at approval')) if frozen is not None else scope.make_verifier()
    actions = scope.actions_for(bundle)
    rows, summary = governance.remediation_rows(view, state, actions, verify)
    return bundle, rows, summary, actions


REMEDIATION_FILTER = Literal['', 'Remove assignment', 'Investigate assignment', 'Apply compensating control', 'Maintain access', 'No action required']


@router.get('/remediation')
def remediation(q: dict = Depends(scope_query), recommended: REMEDIATION_FILTER = '', offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    bundle, rows, summary, actions = remediation_data(q)
    if recommended:
        rows = [row for row in rows if row['recommended'] == recommended]
    verify = (lambda user, aid: (bundle['frozen_decisions'].get('verification') or {}).get(aid, 'Not assessed at approval')) if bundle['frozen_decisions'] is not None else scope.make_verifier()
    tracked = [dict(item.model_dump(mode='json'), verification=verify(item.user, item.assignment_id) if item.assignment_id and item.recommended == 'Remove assignment' else 'Not verifiable from source evidence')
               for item in actions]
    return dict(info(bundle), items=rows[offset:offset + limit], total=len(rows), summary=summary, offset=offset, limit=limit, actions=tracked)


REMEDIATION_COLUMNS = ['USERNAME', 'ACTIVITY', 'RISKS', 'ROLE', 'ASSIGNMENT_ID', 'VALID_FROM', 'VALID_TO', 'ACTIVITY_REVIEW', 'ASSIGNMENT_REVIEW', 'RISK_ACCEPTANCE',
                       'RECOMMENDED_ACTION', 'JUSTIFICATION', 'OWNER', 'DUE_DATE', 'ACTION_STATUS', 'VERIFICATION']


def remediation_csv_rows(rows):
    for row in rows:
        yield [row['user'], row['activity'], ', '.join(row['risks']), row['role'], row['assignment_id'], row['valid_from'] or '', row['valid_to'] or '',
               row['activity_decision'], row['assignment_decision'], ', '.join(row['risk_acceptance']), row['recommended'],
               row['reason'] or row['controls'], row['owner'], row['due_date'] or '', row['action_status'] + (' (overdue)' if row['overdue'] else ''), row['verification']]


@router.get('/remediation/export')
def remediation_export(q: dict = Depends(scope_query), recommended: REMEDIATION_FILTER = ''):
    _, rows, _, _ = remediation_data(q)
    if recommended:
        rows = [row for row in rows if row['recommended'] == recommended]
    return csv_response(REMEDIATION_COLUMNS, remediation_csv_rows(rows), 'access-remediation')


class ActionBody(StrictModel):
    context: str = Field(default='current', pattern=legacy.CONTEXT_PATTERN)
    expected_revision: int = Field(ge=0)
    actor: str = Field(min_length=1, max_length=120)
    action_id: str = Field(default='', max_length=32)
    user: str = Field(min_length=1, max_length=512)
    activity: str = Field(default='', max_length=512)
    risk_id: str = Field(default='', max_length=512)
    assignment_id: str = Field(default='', max_length=64)
    role: str = Field(default='', max_length=512)
    recommended: Literal['Remove assignment', 'Investigate assignment', 'Maintain access', 'Apply compensating control', 'No action required']
    reason: str = Field(min_length=1, max_length=4000)
    owner: str = Field(default='', max_length=120)
    due_date: date | None = None
    status: Literal['Open', 'In progress', 'Completed', 'Cancelled'] = 'Open'
    completion_evidence: str = Field(default='', max_length=4000)


@router.post('/remediation/actions')
def save_action(body: ActionBody):
    """Track a remediation action. Completion is a manual claim; only later source evidence verifies removal."""
    bundle = scope.load(body.context)
    if bundle['frozen']:
        raise HTTPException(409, 'Frozen periods retain their remediation actions unchanged. Track follow-up in current evidence.')
    model = scope.model_for(bundle)
    entry = model.get(body.user)
    if entry is None or body.assignment_id and body.assignment_id not in entry['assignments']:
        raise HTTPException(409, 'The action refers to evidence that is not present in this context.')
    values = body.model_dump(exclude={'context', 'expected_revision', 'actor', 'action_id'})
    try:
        return decisions.save_action(body.context, values, body.actor, body.expected_revision, body.action_id)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
