"""Aggregate validated local snapshots; missing/disabled sources are never zero-filled."""
from collections import Counter
from fastapi import APIRouter, HTTPException
from datetime import date
import cache
from config import get_settings
from role_matching import normalize_role
from user_access import interval_status, sap_date, current_role_count
from .employees import directory_status

router = APIRouter(prefix='/api/dashboard', tags=['Overview'])


@router.get('')
def overview():
    state, settings = cache.get_snapshot(), get_settings()
    catalogue = bool(state.import_report)
    mapping = settings.features.user_role_mapping and bool(state.users.report)
    directory = directory_status(snapshot=state)
    metrics = []
    def add(key, label, value, destination, context, reason='Source not loaded'):
        metrics.append(dict(id=key, label=label, value=value, destination=destination,
                            context=context, unavailable_reason=reason if value is None else None))
    add('roles','Catalogue roles',len(state.roles) if catalogue else None,'roles','Open the complete role catalogue.')
    add('areas','Enabled SAP areas',sum(m.enabled for m in state.modules) if catalogue else None,'roles','Open Role Lookup and its SAP area filters.')
    add('mappings','Role/T-code mappings',sum(r.tcode_count for r in state.summaries) if catalogue else None,'roles','Distinct role/code pairs; open Role Lookup.')
    reason='User–Role Mapping disabled' if not settings.features.user_role_mapping else 'User Access CSV not loaded'
    add('users','SAP users',len(state.users.users) if mapping else None,'users','Open all SAP users.',reason)
    add('assignments','Role assignment records',len(state.users.assignments) if mapping else None,'users','All imported intervals, including technical roles; open all users.',reason)
    add('assigned_users','Users with assignments',len({a['user_key'] for a in state.users.assignments}) if mapping else None,'users','Any imported assignment; open all users, including users without assignments.',reason)
    add('releases','Release roles',len({normalize_role(a['role_name']) for a in state.users.assignments if a['scope']=='release'}) if mapping else None,'releases','Distinct release roles across all validity states; opens the currently-valid release view.',reason)
    counts=Counter(interval_status(sap_date(a['valid_from']),sap_date(a['valid_to'])) for a in state.users.assignments) if mapping else {}
    for status in ['expired','future']:
        add(status,status.title()+' assignment records',counts.get(status,0) if mapping else None,'users','Snapshot validity, not account state. Opens all users; select assignment status in User Details.',reason)
    enabled=directory['enabled']
    add('employees','Employee Directory records',directory['report'].get('records') if enabled and directory['loaded'] else None,'employees','Open directory import and data quality.','Employee Directory disabled' if not enabled else 'Import directory records first')
    coverage=directory['coverage']
    add('email_matches','Matched SAP identities',coverage.get('matched',0) if directory['coverage_total'] else None,'review',f"Exact matches of {directory['coverage_total']} SAP identities; open directory data quality.",directory['coverage_reason'])
    add('unresolved','Missing or ambiguous directory matches',sum(v for k,v in coverage.items() if k!='matched') if directory['coverage_total'] else None,'review','Includes missing SAP email, unmatched and ambiguous evidence; open data quality.',directory['coverage_reason'])
    if mapping:
        from account_review import current_rows, decisions
        from .employees import available
        try:
            review_rows, _ = current_rows(state, available(state), decisions(), settings.unlicensed_user_groups, date.today())
        except HTTPException:
            add('account_review', 'Accounts requiring review', None, 'review', 'Open Account Review for recovery.', 'Review annotations unavailable; other source metrics remain available.')
            for key,label in [('reviewed','Reviewed accounts'),('pending','Pending reviews'),('outdated','Outdated reviews')]: add(key,label,None,'review','Open Account Review for recovery.','Review annotations unavailable.')
        else:
            add('account_review', 'Accounts requiring review', sum(r['needs_review'] for r in review_rows), 'review', 'Review supported account evidence and stale annotations, not effective authorization or license savings.')
            reviewed=sum(bool(r['decision']) and r['review_state']!='Needs review' and not r['stale'] for r in review_rows)
            for key,label,value in [('reviewed','Reviewed accounts',reviewed),('pending','Pending reviews',len(review_rows)-reviewed),('outdated','Outdated reviews',sum(r['stale'] for r in review_rows))]:
                add(key,label,value,'review','All currently imported SAP accounts form the review population; outdated reviews are included in pending.')
            add('position_changes','Users requiring review — Position changes',sum(bool(r['position_change'] and r['position_change']['open']) for r in review_rows) if directory['loaded'] and enabled else None,'review','Department or job title changed between Employee Directory imports and not yet reviewed. Separate from SoD conflicts and other account findings; opens Account Review.','Employee Directory not loaded')
            add('ad_disabled_open','AD disabled / SAP valid and unlocked',sum('ad_disabled_open' in r['findings'] for r in review_rows) if directory['loaded'] and enabled else None,'review','Reliably matched AD and SAP account evidence.',directory['coverage_reason'])
    else:
        add('account_review', 'Accounts requiring review', None, 'review', 'Open Account Review.', reason)
        for key,label in [('reviewed','Reviewed accounts'),('pending','Pending reviews'),('outdated','Outdated reviews')]: add(key,label,None,'review','Open Account Review.',reason)
    role_distribution=Counter((r.function_key or 'UNCLASSIFIED') for r in state.summaries) if catalogue else None
    assignment_distribution=Counter() if mapping else None
    if mapping:
        for user in state.users.users.values():
            count=current_role_count(user)
            assignment_distribution['0' if count==0 else '1–5' if count<=5 else '6–20' if count<=20 else '21+']+=1
    paths={'roles':settings.data_csv_path,'users':settings.user_csv_path,'employees':settings.employee_csv_path}
    def freshness(key):
        reference=settings.data_lifecycle.sources.get(key)
        return dict(last_import=reference.imported_at if reference and reference.path==paths[key] else directory['report'].get('imported_at') if key=='employees' else None,
                    last_checked=reference.checked_at if reference and reference.path==paths[key] else None)
    return dict(metrics=metrics,review_population=len(state.users.users) if mapping else None,role_distribution=dict(role_distribution) if role_distribution is not None else None,assignment_distribution=dict(assignment_distribution) if assignment_distribution is not None else None,last_successful_refresh=settings.data_lifecycle.last_successful_refresh,
                source_warning='A source needs attention. Review Health & Diagnostics.' if directory['error'] else None,coverage_total=directory['coverage_total'],
                sources=[dict(id='roles',name='Role Catalogue',enabled=True,configured=bool(settings.data_csv_path),available=catalogue,**freshness('roles')),
                         dict(id='users',name='User–Role Mapping',enabled=settings.features.user_role_mapping,configured=bool(settings.user_csv_path),available=bool(state.users.report),**freshness('users')),
                         dict(id='employees',name='Employee Directory',enabled=enabled,configured=directory['configured'],available=directory['loaded'],**freshness('employees'))],as_of=directory['report'].get('imported_at'),notice='Current local snapshots only; no historical trends or effective-authorization claims.')
