"""Coverage of validated snapshots, not a second import validator or risk engine."""
from datetime import date
from threading import RLock
from fastapi import APIRouter, Query
import cache
from config import get_settings
from user_access import interval_status, sap_date
from .employees import directory_status

router=APIRouter(prefix='/api/data-health',tags=['Data Health'])
_lock=RLock()
_key=None
_value=None


def calculations(state):
    findings={k:[] for k in ('unmapped','ambiguous','unknown_dates','expired','future','unparsed_release','no_transactions','missing_description','unknown_module','unknown_type','conflicting_identity')}
    assignments=[a for a in state.users.assignments if a['scope']!='other']
    for a in assignments:
        evidence=dict(identifier=a['role_name'],username=a['username'],source='users',destination='user')
        if a['match_status']=='unmapped': findings['unmapped'].append(evidence)
        elif a['match_status']=='ambiguous': findings['ambiguous'].append(evidence)
        status=interval_status(sap_date(a['valid_from']),sap_date(a['valid_to']))
        if status in {'expired','future'}: findings[status].append(evidence)
        if not a['valid_from'] or not a['valid_to']: findings['unknown_dates'].append(evidence)
        if a['scope']=='release' and not a['release']['parsed']: findings['unparsed_release'].append(evidence)
    for role in state.roles.values():
        row=dict(identifier=role.agr_name,source='roles',destination='role')
        if not role.tcode_count: findings['no_transactions'].append(row)
        if not role.text: findings['missing_description'].append(row)
        if not role.function_key or role.function_key=='UNCLASSIFIED': findings['unknown_module'].append(row)
    for u in state.users.users.values():
        row=dict(identifier=u['username'],username=u['username'],source='users',destination='user')
        if any(a['user_type'].upper() not in {'A','B','C','S','L'} for a in u['accounts']): findings['unknown_type'].append(row)
        if len({n for n in u['names'] if any(n)})>1 or len(u['emails'])>1 or len(u['accounts'])>1: findings['conflicting_identity'].append(row)
    return findings


LABELS={
 'unmapped':('Assigned roles absent from catalogue','warning','No exact or unambiguous wildcard mapping; absence does not prove invalid access.'),
 'ambiguous':('Ambiguous catalogue matches','warning','Multiple equally specific catalogue patterns; no transaction access is inferred.'),
 'unknown_dates':('Assignments with missing dates','warning','Missing bounds do not establish current access.'),
 'expired':('Expired assignment records','information','Historical records; not inherently a security or data-quality problem.'),
 'future':('Future assignment records','information','Scheduled assignments; not evidence of current access.'),
 'unparsed_release':('Unparsed release-role names','information','Naming does not match the confirmed PR/PO parser; records are retained.'),
 'no_transactions':('Catalogue roles without T-code mappings','information','The export may omit mappings; this does not prove no authorization.'),
 'missing_description':('Catalogue roles without descriptions','information','Optional description missing.'),
 'unknown_module':('Unclassified catalogue roles','information','No reliable SAP module from the imported catalogue.'),
 'unknown_type':('Unknown or missing SAP user type','warning','Technical values are retained; classification cannot be assumed.'),
 'conflicting_identity':('Users with multiple identity/account observations','information','Different names, emails or account intervals may be legitimate source evidence; inspect before interpreting as a conflict.')}


@router.get('')
def overview(finding:str=Query('',max_length=64),offset:int=Query(0,ge=0),limit:int=Query(25,ge=1,le=100)):
    global _key,_value
    state=cache.get_snapshot();settings=get_settings();mapping=settings.features.user_role_mapping
    key=(id(state),state.last_loaded,date.today(),mapping)
    with _lock:
        if key!=_key:
            _value=calculations(state);_key=key
        data=_value
    directory=directory_status(snapshot=state)
    catalogue=bool(state.import_report);users=mapping and bool(state.users.report)
    findings=[]
    for code,(title,severity,explanation) in LABELS.items():
        usable=catalogue if code in {'no_transactions','missing_description','unknown_module'} else users and (catalogue if code in {'unmapped','ambiguous'} else True)
        findings.append(dict(id=code,title=title,severity=severity,count=len(data[code]) if usable else None,explanation=explanation))
    eligible=[a for a in state.users.assignments if a['scope']!='other'] if users else []
    matched=sum(a['match_status'] in {'exact','wildcard'} for a in eligible)
    def ratio(label,n,d,available): return dict(label=label,numerator=n if available else None,denominator=d if available else None,percent=round(100*n/d,1) if available and d else None)
    coverage=[ratio('Business/release assignment records mapped to catalogue',matched,len(eligible),users and catalogue),
              ratio('Catalogue roles with transaction mappings',sum(bool(r.tcode_count) for r in state.roles.values()),len(state.roles),catalogue),
              ratio('SAP identities matched to Employee Directory',directory['coverage'].get('matched',0),directory['coverage_total'],bool(directory['coverage_total']))]
    selected=next((f for f in findings if f['id']==finding),None)
    rows=data.get(finding,[]) if selected and selected['count'] is not None else []
    return dict(sources=[dict(id='roles',name='Role Catalogue',enabled=True,configured=bool(settings.data_csv_path),available=catalogue,records=len(state.roles) if catalogue else None,snapshot='Memory; startup reloads configured CSV',last_successful=state.last_loaded.isoformat() if catalogue and state.last_loaded else None),
                         dict(id='users',name='User–Role Mapping',enabled=mapping,configured=bool(settings.user_csv_path),available=bool(state.users.report),records=len(state.users.users) if state.users.report else None,snapshot='Memory; startup reloads configured CSV',last_successful=state.last_loaded.isoformat() if state.users.report and state.last_loaded else None),
                         dict(id='employees',name='Employee Directory',enabled=directory['enabled'],configured=directory['configured'],available=directory['loaded'],records=directory['report'].get('records'),snapshot='Durable local snapshot' if directory['persisted'] else 'No durable snapshot',last_successful=directory['report'].get('imported_at'))],
                coverage=coverage,findings=findings,items=rows[offset:offset+limit],total=len(rows),offset=offset,limit=limit,
                directory_coverage_reason=directory['coverage_reason'],
                data_revision=state.last_loaded.isoformat() if state.last_loaded else None,
                import_totals={name:{key:report.get(key) for key in ('parsed_rows','unique_records','duplicate_rows')} for name,report in [('roles',state.import_report),('users',state.users.report)]},
                validation_note='Only validated published snapshots are counted. Invalid headers, missing usernames, invalid dates and reversed intervals reject the replacement atomically. Identical duplicate rows are deduplicated at import; import totals below count raw rows, not duplicate role definitions.')
