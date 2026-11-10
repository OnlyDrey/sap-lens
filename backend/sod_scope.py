"""Resolve SoD 2.0 evidence for a review context (live data or a period snapshot) and apply shared filters.

``current`` uses live evidence; a period id uses that period's captured snapshot. Frozen periods
(approved/closed) read their decisions from the snapshot, never from the live stores.
"""
from datetime import date
import threading

from fastapi import HTTPException

import cache
from config import get_settings
from search_matching import text_matches, selected_value_matches
import assignment_lifecycle
import sod_catalogue
import sod_decisions as decisions
import sod_governance as governance
import sod_periods as periods
from routers.sod_analysis import captured, filtered

FILTER_TEXT = ('search', 'risk', 'criticality', 'risk_type', 'category', 'username', 'group', 'composite_role', 'single_role', 'tcode',
               'role', 'role_suffix', 'activity')
DECIDED = {'Approved', 'Keep', 'Accepted', 'Conditional', 'Removal required', 'Rejected'}
_cache_lock = threading.RLock()
_derived = {}


def live_query(validity='active', as_of=None):
    return dict(kind='users', validity=validity, as_of=as_of or date.today(), selected_roles=[], search='', risk='', criticality='', risk_type='',
                category='', username='', group='', composite_role='', single_role='', tcode='', account_status='', multiple_risks=False, sort='subject', descending=False)


def load(context, validity='active', as_of=None):
    """Evidence bundle for one context; never mutates evidence."""
    decisions.check_context(context)
    if context == 'current':
        query = live_query(validity, as_of)
        result = captured(query)
        versions = {name: ref['snapshot'] for name, ref in result['sources']['references'].items()}
        if get_settings().employee_snapshot_id:
            versions['employees'] = get_settings().employee_snapshot_id
        return dict(context=context, findings=result['users'], generation=result['generation'], as_of=result['as_of'], coverage=result['coverage'],
                    period=None, frozen=False, reviewable=validity == 'active', only_current=validity == 'active', versions=versions, frozen_decisions=None,
                    query=query, assignment_source=result.get('_assignment_source', {}), catalogue_names=result.get('_catalogue_names', ()), assignment_validity=validity)
    with periods.lock:
        index = periods.read()
        period = periods.find(index, context)
        if period.deleted_at:
            raise HTTPException(404, 'Review period not found.')
        saved = periods.snapshot(period)
    frozen = period.state in periods.FROZEN
    return dict(context=context, findings=saved['analysis']['users'], generation=period.snapshot, as_of=saved['evaluation_date'], coverage=saved['analysis']['coverage'],
                period=period.model_dump(mode='json'), frozen=frozen, reviewable=period.state in {'Draft', 'In review'}, only_current=True,
                versions=saved.get('source_versions', {}), frozen_decisions=saved.get('decisions') if frozen else None, query=None, legacy=saved.get('model') != 2, assignment_source=saved.get('assignment_source'), catalogue_names=saved.get('catalogue_names',()), assignment_validity=validity)


def model_for(bundle):
    key = (bundle['context'], bundle['generation'], bundle['only_current'])
    with _cache_lock:
        hit = _derived.get('entry')
        if hit and hit[0] == key:
            return hit[1]
    model = governance.derive(bundle['findings'], only_current=bundle['only_current'])
    with _cache_lock:
        _derived['entry'] = (key, model)
    return model


def review_model_for(bundle):
    """Source-only extension of the prepared conflict model, never an input to conflict detection."""
    base=model_for(bundle)
    source=bundle.get('assignment_source')
    if bundle['coverage']['status']!='available':return base
    if source is None:return base  # Historical periods without this cut retain only their original evidence.
    key=(bundle['context'],bundle['generation'],bundle.get('assignment_validity','active'))
    with _cache_lock:
        hit=_derived.get('review')
        if hit and hit[0]==key:return hit[1]
    from collections import defaultdict
    from user_access import interval_status, sap_date
    from sod_analysis import _digest
    model={user:dict(entry,assignments=dict(entry['assignments']),groups=set(entry['groups'])) for user,entry in base.items()}
    day=date.fromisoformat(bundle['as_of']) if isinstance(bundle['as_of'],str) else bundle['as_of']
    validity=bundle.get('assignment_validity','active')
    for user,record in source.items():
        for row in record['assignments']:
            status=interval_status(sap_date(row.get('valid_from')),sap_date(row.get('valid_to')),day)
            if validity!='all' and status!=validity:continue
            name=row['role_name']
            if not name:continue
            entry=model.setdefault(user,dict(user=user,findings={},activities={},assignments={},groups=set(),account=None))
            path=dict(actual_assigned_role=name,role_valid_from=row.get('valid_from'),role_valid_to=row.get('valid_to'),user_group=row.get('user_group',''))
            aid=governance.assignment_id(user,path)
            if aid not in entry['assignments']:
                entry['assignments'][aid]=dict(id=aid,user=user,role=name,valid_from=row.get('valid_from'),valid_to=row.get('valid_to'),user_group=row.get('user_group',''),
                    interval_status=status,matching_status=row.get('match_status','unknown'),catalogue_roles=set(row.get('catalogue_roles') or []),single_roles=set(),supplies=defaultdict(set),risks=set(),
                    evidence_version=_digest(['sod-assignment-evidence',1,aid,[]]))
            entry['assignments'][aid]=dict(entry['assignments'][aid],catalogue_tcodes=tuple(row.get('tcodes') or [code for codes in entry['assignments'][aid]['supplies'].values() for code in codes]))
            if row.get('user_group'):entry['groups'].add(row['user_group'])
    with _cache_lock:_derived['review']=(key,model)
    return model


def assignment_view(bundle,model,state,q):
    """Apply existing assignment predicates to the complete validated review population."""
    if bundle.get('assignment_source') is None:
        raise HTTPException(409,'This historical period lacks a full assignment snapshot. Use its retained evidence or create a new period; current imports are never substituted.')
    allowed=allowed_assignments(model,state,q)
    constrained=any(q.get(key) for key in ('risk','risks','criticality','criticalities','risk_type','category','categories','multiple_risks','acceptance','activity_decision'))
    risk_scope=visible_cells(bundle,model,state,q) if constrained else None
    users=wanted_users(q)
    result={}
    for user,entry in model.items():
        if users and user.casefold() not in users:continue
        if q.get('username') and not text_matches(user,q['username']):continue
        if risk_scope is not None and user not in risk_scope:continue
        ids=allowed[user]
        if q.get('search') and not text_matches(user,q['search']):
            ids={aid for aid in ids if text_matches(entry['assignments'][aid]['role'],q['search'])}
        if not ids:continue
        risks=set(entry['findings']) if risk_scope is None else risk_scope[user]
        result[user]=dict(entry,visible_assignments=ids,findings={key:value for key,value in entry['findings'].items() if key in risks},
                         activities={key:value for key,value in entry['activities'].items() if value['risks']&risks})
    return result


def family_map(bundle):
    from access_package import role_families
    source=bundle.get('assignment_source') or {}
    names={row['role_name'] for record in source.values() for row in record['assignments'] if row.get('role_name')}
    return role_families(names,bundle.get('catalogue_names',()))


def role_filters_match(value,q):
    wanted=many(q,'role','roles')
    families=q.get('role_families') or []
    exact=q.get('role_exact') or []
    if not wanted and not families and not exact:return True
    return bool(value in exact or wanted and role_selection_matches(value,wanted,q.get('role_match','search')) or families and q.get('_family_map',{}).get(value) in families)


def decision_data(bundle):
    """One validated store snapshot per request bundle, never shared across requests/users.

    Responses use the same revision as their decisions. Writers still validate the
    live store under its lock; a new request always reads fresh committed data.
    """
    if '_decision_data' not in bundle:
        with decisions.lock:
            bundle['_decision_data']=decisions.read()
    return bundle['_decision_data']


def latest_for(bundle):
    """kind -> key -> Event for this context (snapshot copy when frozen)."""
    if bundle['frozen_decisions'] is not None:
        events = bundle['frozen_decisions']['events']
        return {kind: {key: decisions.Event.model_validate(items[-1]) for key, items in events.get(kind, {}).items() if items} for kind in decisions.DECISIONS}
    return decisions.latest(bundle['context'], decision_data(bundle))


def states_for(bundle, model):
    """Frozen assessments retain their approval-date lifecycle; live contexts use today."""
    approved = (bundle.get('period') or {}).get('approval_date') if bundle.get('frozen') else None
    # Frozen assessments keep their captured evidence: later imports (and reappearance) never rewrite them.
    applies = None if bundle.get('frozen') else assignment_lifecycle.applicability()
    return governance.states(model, latest_for(bundle), today=date.fromisoformat(approved) if approved else None,
                             reappeared=applies.map if applies else None, reasons=applies.reasons if applies else None)


def actions_for(bundle):
    if bundle['frozen_decisions'] is not None:
        return [decisions.Action.model_validate(item) for item in bundle['frozen_decisions']['actions']]
    return decisions.actions_for(bundle['context'],decision_data(bundle))


def revision():
    with decisions.lock:
        return decisions.read().revision


def wanted_suffixes(q):
    """Case-insensitive set of requested role suffix tokens (legacy single value plus the multi-select list); empty means no filter."""
    values = [*(q.get('role_suffixes') or []), q.get('role_suffix') or '']
    return {value.strip().casefold() for value in values if value.strip()}


def wanted_users(q):
    return {value.strip().casefold() for value in (q.get('usernames') or []) if value.strip()}


def suffix_matches(role, wanted):
    """Exact token comparison on the actual assigned role; never a substring or catalogue-pattern match."""
    return not wanted or governance.role_suffix(role or '').casefold() in wanted


def many(q, single, plural):
    """Requested values of one filter: the single value plus the multi-select list (OR within, AND with the other filters)."""
    return [value for value in [q.get(single) or '', *(q.get(plural) or [])] if value]


def any_match(value, wanted):
    return not wanted or any(text_matches(value, item) for item in wanted)


def _path_matches(finding, q):
    paths = [path for side in finding['evidence'].values() for path in side]
    roles = many(q, 'role', 'roles')
    if (roles or q.get('role_families') or q.get('role_exact')) and not any(role_filters_match(path.get('actual_assigned_role',''),q) for path in paths):
        return False
    wanted = wanted_suffixes(q)
    if wanted and not any(suffix_matches(path.get('actual_assigned_role', ''), wanted) for path in paths):
        return False
    activities = many(q, 'activity', 'activities')
    if activities and not any(any_match(path['activity'], activities) for path in paths):
        return False
    return True


def assignment_filters_active(q):
    return any(q.get(name) for name in ('role', 'roles', 'role_families', 'role_exact', 'role_suffix', 'role_suffixes', 'group', 'groups', 'activity', 'activities', 'tcode', 'tcodes', 'assignment_decision')) or q.get('review_status') not in (None, '', 'all')


#: Review status filter of the assignment queue: lifecycle values each choice keeps. The default working view is 'attention'.
REVIEW_STATUS = {'attention': {'Pending', 'Investigate', 'Outdated'}, 'pending': {'Pending', 'Outdated'}, 'investigating': {'Investigate'},
                 'reviewed': {'Keep', 'Removal required'}}


def role_selection_matches(value, wanted, mode='search'):
    if not wanted:return True
    if mode=='exact':return value in wanted
    if mode=='prefix':return any(value.casefold().startswith(item.casefold()) for item in wanted)
    # Explicit wildcard mode is anchored even without '*'; search retains the
    # investigation text-search contract and is never used for group selection.
    if mode=='wildcard':return any(text_matches(value,item) if '*' in item else value.casefold()==item.casefold() for item in wanted)
    return any_match(value,wanted)


def allowed_assignments(model, state, q):
    """{user: assignment ids} passing every assignment-level filter, so lists show actual assigned roles and never siblings of a match."""
    wanted = wanted_suffixes(q)
    result = {}
    for user, entry in model.items():
        ids = set()
        for aid, assignment in entry['assignments'].items():
            if not role_filters_match(assignment['role'],q):
                continue
            if not suffix_matches(assignment['role'], wanted):
                continue
            if not selected_value_matches(assignment['user_group'], many(q, 'group', 'groups')):
                continue
            wanted_activities = many(q, 'activity', 'activities')
            if wanted_activities and not any(any_match(name, wanted_activities) for name in assignment['supplies']):
                continue
            wanted_codes = many(q, 'tcode', 'tcodes')
            if wanted_codes and not any(any_match(code,wanted_codes) for code in (assignment.get('catalogue_tcodes',()) if q.get('assignment_scope')=='all' else [code for codes in assignment['supplies'].values() for code in codes])):
                continue
            if q.get('assignment_decision') and state['assignment'][aid][0] != q['assignment_decision']:
                continue
            if q.get('review_status') in REVIEW_STATUS and state['assignment'][aid][0] not in REVIEW_STATUS[q['review_status']]:
                continue
            ids.add(aid)
        result[user] = ids
    return result


def visible_cells(bundle, model, state, q):
    """{user: {risk_id}} after path-level, text and decision filters."""
    base = filtered({'users': [row for row in bundle['findings'] if row['subject'] in model and row['risk_id'] in model[row['subject']]['findings']]},
                    dict(q, kind='users', sort='subject', descending=False))  # row order belongs to the view, not this filter
    visible = {}
    users = wanted_users(q)
    for finding in base:
        if users and finding['subject'].casefold() not in users:
            continue
        if not _path_matches(finding, q):
            continue
        entry = model[finding['subject']]
        if q.get('multiple_risks') and len(entry['findings']) < 2:
            continue
        names = [name for name, item in entry['activities'].items() if finding['risk_id'] in item['risks']]
        if q.get('acceptance') and state['acceptance'][finding['finding_id']][0] != q['acceptance']:
            continue
        if q.get('activity_decision') and not any(state['activity'][entry['activities'][name]['key']][0] == q['activity_decision'] for name in names):
            continue
        if q.get('assignment_decision') and not any(state['assignment'][aid][0] == q['assignment_decision']
                                                   for name in names for aid in entry['activities'][name]['assignments']):
            continue
        visible.setdefault(finding['subject'], set()).add(finding['risk_id'])
    return visible


def scoped(context, q):
    """bundle, full model, decision state and the filtered view for one request."""
    bundle = load(context, q.get('validity', 'active'), q.get('as_of'))
    if q.get('_review_population') and bundle.get('assignment_source') is not None:
        q=dict(q, assignment_scope='all')
    q=dict(q,_family_map=family_map(bundle) if q.get('role_families') else {})
    model = review_model_for(bundle) if q.get('assignment_scope')=='all' else model_for(bundle)
    observe(bundle, model)
    state = states_for(bundle, model)
    view = assignment_view(bundle,model,state,q) if q.get('assignment_scope')=='all' else governance.restrict(model, visible_cells(bundle, model, state, q), allowed_assignments(model, state, q) if assignment_filters_active(q) else None)
    return bundle, model, state, view


def context_info(bundle):
    period = bundle['period']
    return dict(context=bundle['context'], generation=bundle['generation'], as_of=bundle['as_of'], coverage=bundle['coverage'], frozen=bundle['frozen'],
                reviewable=bundle['reviewable'], revision=decision_data(bundle).revision, legacy=bool(bundle.get('legacy')),
                period=dict(id=period['id'], name=period['name'], state=period['state']) if period else None)


def verification_population(users=None):
    """One coherent imported-source cut, independent of conflict and validity filters.

    Completeness is within the supplied validated export scope, not certification that
    an external SAP export included the whole organization.
    """
    from user_access import normalize_username
    with sod_catalogue.lock,cache._load_lock:
        snapshot=cache.get_snapshot();settings=get_settings()
        reference=settings.data_lifecycle.sources.get('users')
        if not settings.features.sod or not settings.features.user_role_mapping or not snapshot.roles or not snapshot.sod:
            return None,set(),reference
        report=snapshot.users.report
        complete=set();ids=set()
        selected=snapshot.users.users.items() if users is None else ((name,snapshot.users.users.get(name)) for name in users)
        for name,record in selected:
            if not record:continue
            name=normalize_username(name)
            assignments=record['assignments']
            if not report.get('errors') and not report.get('invalid_catalogue_patterns') and all(a['match_status'] in {'exact','wildcard'} for a in assignments if a.get('scope','business')!='other'):
                complete.add(name)
            for assignment in assignments:
                ids.add(governance.assignment_id(name,dict(actual_assigned_role=assignment['role_name'],role_valid_from=assignment.get('valid_from'),role_valid_to=assignment.get('valid_to'),user_group=assignment.get('user_group',''))))
        return ids,complete,reference


def absence_verified(user):
    return user in verification_population({user})[1]


def activity_defined(name):
    with cache._load_lock:
        risks = cache.get_snapshot().sod.get('risks', []) if cache.get_snapshot().sod else []
    local = sod_catalogue.read()
    for risk in risks:
        entry = local.entries.get(risk['risk_id'])
        if entry and not entry.metadata.enabled or not risk.get('supported'):
            continue
        if any(item['activity'] == name for mappings in risk['activities'].values() for item in mappings):
            return True
    return False


def orphan_lifecycle(kind, event):
    """Decisions whose evidence is absent from live data: Resolved only when absence is verifiable."""
    if kind=='assignment':
        present,complete,_=verification_population({event.user})
        if present is None or event.key in present or event.user not in complete:return 'Historical'
    elif not absence_verified(event.user):
        return 'Historical'
    reference = get_settings().data_lifecycle.sources.get('sod')
    if not reference or event.source_versions.get('sod') != reference.snapshot:
        return 'Historical'
    if kind == 'activity' and not activity_defined(event.ref):
        return 'Historical'
    return 'Resolved'


def live_assignment_ids():
    """All imported assignment identities, including expired/non-conflicting records."""
    return verification_population()[0]


def make_verifier(users=None):
    """No removal is inferred from absence in the filtered SoD finding population."""
    live,complete,reference=verification_population(users)
    def verify(user,aid):
        if live is None:return 'Not assessable: current analysis is unavailable'
        if aid in live:return 'Still present in current evidence'
        return 'Not present in current evidence' if user in complete else 'Not assessable: source coverage incomplete'
    verify.source_reference=reference
    return verify


def make_decision_verifier(users=None):
    """Source-bound verification of an explicit Remove; never rewrites its event."""
    from datetime import datetime
    verify=make_verifier(users);reference=verify.source_reference
    def result(event):
        text=verify(event.user,event.key)
        value=dict(status='Not verified',reason=text,source_version=reference.snapshot if reference else None,imported_at=reference.imported_at if reference else None,decision_event_id=event.event_id)
        if event.decision!='Remove' or text!='Not present in current evidence' or reference is None:return value
        try:
            newer=datetime.fromisoformat(reference.imported_at)>datetime.fromisoformat(event.timestamp)
        except (ValueError,TypeError):return value
        if newer and reference.snapshot!=event.source_versions.get('users'):
            value.update(status='Verified',reason='Assignment absent from a newer validated User–Role snapshot with complete matching coverage for this user.')
        else:value['reason']='Awaiting a newer validated User–Role source snapshot.'
        return value
    return result


def verification_map(actions):
    tracked=[item for item in actions if item.assignment_id and item.recommended=='Remove assignment' and item.status!='Cancelled']
    verify = make_verifier({item.user for item in tracked})
    return {item.assignment_id: verify(item.user,item.assignment_id) for item in tracked}


def removal_verification(actions, verify=None):
    """(summary, ids) for tracked removals. Verified needs source evidence newer than the action that shows the assignment gone.

    A completed status is a manual claim and never verifies. The assignment must be absent from current evidence with
    complete source coverage and the User-Role source must have been imported after the action was created.
    """
    from datetime import datetime, timezone
    tracked = [item for item in actions if item.assignment_id and item.recommended == 'Remove assignment' and item.status != 'Cancelled']
    summary = dict(tracked=len(tracked), verified=0, still_present=0, awaiting_evidence=0, not_assessable=0, available=True, reason=None)
    if not tracked:
        summary.update(available=False, reason='No removal action is tracked yet.')
        return summary, set()
    verify=verify or make_verifier({item.user for item in tracked})
    reference = verify.source_reference

    def moment(text):
        try:
            value = datetime.fromisoformat(text)
        except (TypeError, ValueError):
            return None
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    imported = moment(reference.imported_at) if reference else None
    ids = set()
    for item in tracked:
        text = verify(item.user, item.assignment_id)
        if text.startswith('Not assessable'):
            summary['not_assessable'] += 1
        elif text.startswith('Still present'):
            summary['still_present'] += 1
        elif imported is not None and (moment(item.created) or imported) < imported:
            summary['verified'] += 1
            ids.add(item.id)
        else:
            summary['awaiting_evidence'] += 1
    if summary['not_assessable'] == len(tracked):
        summary.update(available=False, reason='Current evidence cannot confirm removals (analysis unavailable or source coverage incomplete).')
    return summary, ids


OBSERVE_LIMIT = 100000
_observe_lock = threading.RLock()


def observe(bundle, model):
    """Remember which findings were detected so a source refresh can report what changed.

    Keyed on source versions, not dates. The first observation has no baseline, and
    a failure here never affects the request that triggered it.
    """
    if bundle['context'] != 'current' or not bundle['only_current']:
        return None
    import json
    from config import atomic_write, config_dir
    key = governance._digest(sorted(bundle['versions'].items()))
    ids = sorted(finding['finding_id'] for entry in model.values() for finding in entry['findings'].values())
    path = config_dir() / 'sod-observations.json'
    with _observe_lock:
        try:
            state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        except (OSError, ValueError):
            state = {}
        change = state.get('change')
        if state.get('key') == key and state.get('finding_ids', []) == ids[:OBSERVE_LIMIT]:
            return change
        if state.get('key') and state['key'] != key and not state.get('truncated'):
            before, after = set(state.get('finding_ids', [])), set(ids)
            change = dict(since=state.get('observed_at'), new=len(after - before), no_longer_detected=len(before - after), previous_total=len(before), total=len(after),
                          observed_at=datetime_now())
        elif state.get('key') and state['key'] != key:
            change = dict(unavailable=True, observed_at=datetime_now())
        try:
            atomic_write(path, json.dumps(dict(key=key, observed_at=datetime_now(), finding_ids=ids[:OBSERVE_LIMIT], truncated=len(ids) > OBSERVE_LIMIT, change=change)).encode())
        except OSError:
            pass
        return change


def datetime_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
