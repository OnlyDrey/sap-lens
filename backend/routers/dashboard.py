"""Aggregate validated local snapshots; missing/disabled sources are never zero-filled."""
from collections import Counter
from fastapi import APIRouter
import cache
from config import get_settings
from role_matching import normalize_role
from user_access import interval_status, sap_date
from .employees import directory_status

router = APIRouter(prefix='/api/dashboard', tags=['Overview'])


@router.get('')
def overview():
    state, settings = cache.get_snapshot(), get_settings()
    catalogue = bool(state.import_report)
    mapping = settings.features.user_role_mapping and bool(state.users.report)
    directory = directory_status()
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
    add('email_matches','Directory email matches',coverage.get('matched',0) if directory['coverage_total'] else None,'employees',f"Exact matches of {directory['coverage_total']} SAP identities; open directory data quality.",directory['coverage_reason'])
    add('unresolved','Missing or ambiguous directory matches',sum(v for k,v in coverage.items() if k!='matched') if directory['coverage_total'] else None,'employees','Includes missing SAP email, unmatched and ambiguous evidence; open data quality.',directory['coverage_reason'])
    return dict(metrics=metrics,as_of=directory['report'].get('imported_at'),notice='Current local snapshots only; no historical trends or effective-authorization claims.')
