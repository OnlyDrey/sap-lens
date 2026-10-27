"""Current active-evidence reviews; immutable history never implies verified identity."""
import csv
from datetime import date
import io
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import Field
import cache
import sod_catalogue
from config import get_settings
from config_models import StrictModel
from csv_exports import spreadsheet_cell
from search_matching import search_fields
import sod_reviews as store
from .sod_analysis import captured, publication_guard, context_key, generation_for

router=APIRouter(prefix='/api/sod/reviews',tags=['SoD reviews'])


def current_context():
    query=dict(as_of=date.today(),validity='active',selected_roles=[])
    return query,captured(query)


def review_query(search:str=Query('',max_length=256),risk:str=Query('',max_length=512),
                 decision:str=Query('',max_length=100),lifecycle:str=Query('',max_length=64),
                 action_status:str=Query('',max_length=64),reviewer:str=Query('',max_length=120),
                 sort:Literal['subject','risk_id','decision','modified','target_date']='subject',descending:bool=False):
    return dict(search=search,risk=risk,decision=decision,lifecycle=lifecycle,action_status=action_status,reviewer=reviewer,sort=sort,descending=descending)


def selected(data,filters):
    result=[]
    for row in data['items']:
        finding=row['finding'];event=row['event'];annotation=event['annotation'] if event else {}
        if filters['search'] and not search_fields(filters['search'],finding['subject'],finding['risk_id'],annotation.get('reviewer',''),annotation.get('rationale','')):continue
        if any(filters[key] and filters[key]!=value for key,value in [('risk',finding['risk_id']),('decision',row['decision']),('lifecycle',row['lifecycle']),('action_status',annotation.get('action_status','')),('reviewer',annotation.get('reviewer',''))]):continue
        result.append(row)
    def key(row):
        event=row['event'] or {};annotation=event.get('annotation',{})
        value=row['finding'].get(filters['sort']) if filters['sort'] in {'subject','risk_id'} else row['decision'] if filters['sort']=='decision' else event.get('timestamp') if filters['sort']=='modified' else annotation.get('target_date')
        return ((value or '').casefold(),row['finding_id'])
    return sorted(result,key=key,reverse=filters['descending'])


def review_data():
    query,result=current_context()
    data=store.listing(result['users'],coverage=result['coverage'])
    # Conservative resolution: valid current sources, same matrix, retained user,
    # and every relevant assignment mapped. Missing scope never proves resolution.
    with sod_catalogue.lock,cache._load_lock:
        snapshot=cache.get_snapshot();settings=get_settings();metadata=sod_catalogue.read()
        if generation_for(context_key(snapshot,settings,metadata,query)[0])!=result['generation']:
            return query,result,data
        reference=settings.data_lifecycle.sources.get('sod')
        risks={risk['risk_id']:risk for risk in snapshot.sod.get('risks',[])}
        for row in data['items']:
            if row['presence']!='historical' or not row['event'] or not settings.features.user_role_mapping or not snapshot.roles or not snapshot.sod:continue
            finding=row['finding'];user=snapshot.users.users.get(finding['subject']);risk=risks.get(finding['risk_id'])
            local=metadata.entries.get(finding['risk_id'])
            if not user or not risk or not risk['supported'] or local and not local.metadata.enabled:continue
            if not reference or finding.get('source_versions',{}).get('sod')!=reference.snapshot:continue
            if any(a['match_status'] not in {'exact','wildcard'} for a in user['assignments'] if a.get('scope','business')!='other'):continue
            row['lifecycle']='Resolved';row['stale']=False
    data['summary']={name:sum(row['lifecycle']==name for row in data['items']) for name in ('Pending','Reviewed','Action required','Outdated','Resolved','Historical')}
    return query,result,data


@router.get('')
def listing(filters:dict=Depends(review_query),offset:int=Query(0,ge=0),limit:int=Query(25,ge=1,le=100)):
    _,result,data=review_data();rows=selected(data,filters)
    page=[]
    for row in rows[offset:offset+limit]:
        finding=row['finding']
        page.append({**row,'finding':{**finding,'evidence_total':{side:len(paths) for side,paths in finding['evidence'].items()},'evidence':{side:paths[:25] for side,paths in finding['evidence'].items()}}})
    return {**data,'items':page,'total':len(rows),'offset':offset,'limit':limit,'generation':result['generation'],'as_of':result['as_of']}


REVIEW_COLUMNS=['FINDING_ID','USERNAME','RISK','DECISION','LIFECYCLE','EVIDENCE_FRESHNESS','REVIEWER','REVIEW_DATE','JUSTIFICATION','MITIGATING_CONTROLS','ACTION_OWNER','TARGET_DATE','ACTION_STATUS','COMPLETION_NOTES','EVIDENCE_VERSION']
REVIEW_HEADER='\ufeff'+';'.join('"'+field+'"' for field in REVIEW_COLUMNS)+'\r\n'
ACTION_HEADER=REVIEW_HEADER


def export_response(filters,actions=False):
    _,_,data=review_data();rows=selected(data,filters)
    if actions:rows=[row for row in rows if row['event'] and row['event']['annotation']['action_status'] not in {'Completed','Not applicable'} and row['decision'] in {'Access removal required','Further investigation required'}]
    def stream():
        yield REVIEW_HEADER
        output=io.StringIO();writer=csv.writer(output,delimiter=';',quoting=csv.QUOTE_ALL,lineterminator='\r\n')
        for row in rows:
            event=row['event'] or {};annotation=event.get('annotation',{});finding=row['finding']
            values=[row['finding_id'],finding['subject'],finding['risk_id'],row['decision'],row['lifecycle'],'Outdated' if row['stale'] else 'Current',annotation.get('reviewer',''),event.get('timestamp',''),annotation.get('rationale',''),annotation.get('mitigating_controls',''),annotation.get('action_owner',''),annotation.get('target_date',''),annotation.get('action_status',''),annotation.get('completion_notes',''),event.get('evidence_version','')]
            output.seek(0);output.truncate(0);writer.writerow([spreadsheet_cell(value) for value in values]);yield output.getvalue()
    return StreamingResponse(stream(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="sap-lens-sod-{"actions" if actions else "reviews"}-{date.today().isoformat()}.csv"','Cache-Control':'no-store'})


@router.get('/export')
def export(filters:dict=Depends(review_query)):return export_response(filters)


@router.get('/actions/export')
def actions_export(filters:dict=Depends(review_query)):return export_response(filters,True)


class DecisionRequest(StrictModel):
    expected_revision:int=Field(ge=0)
    expected_generation:str=Field(pattern=r'^[a-f0-9]{64}$')
    evidence_version:str=Field(pattern=r'^[a-f0-9]{64}$')
    annotation:store.Annotation


@router.post('/{finding_id}')
def save(finding_id:str,body:DecisionRequest):
    query,result=current_context()
    if result['generation']!=body.expected_generation:raise HTTPException(409,'SoD evidence changed. Reload before reviewing.')
    finding=next((row for row in result['users'] if row['finding_id']==finding_id),None)
    if not finding or not finding['current_potential']:raise HTTPException(409,'Only current active-assignment findings can be reviewed here. Historical investigation is not current access evidence.')
    with store.lock,publication_guard(query,body.expected_generation):
        versions={name:ref['snapshot'] for name,ref in result['sources']['references'].items()}
        if get_settings().employee_snapshot_id:versions['employees']=get_settings().employee_snapshot_id
        return store.save({**finding,'source_versions':versions,'evaluation_as_of':result['as_of']},body.annotation,body.expected_revision,body.evidence_version)


@router.get('/{finding_id}/history')
def history(finding_id:str,offset:int=Query(0,ge=0),limit:int=Query(25,ge=1,le=100)):
    events=store.history(finding_id)
    return dict(items=events[offset:offset+limit],total=len(events),offset=offset,limit=limit,reviewer_identity=store.IDENTITY_NOTICE)


@router.get('/{finding_id}/history/{event_id}/evidence')
def historical_evidence(finding_id:str,event_id:str,side:Literal['ACTVT1','ACTVT2']='ACTVT1',offset:int=Query(0,ge=0),limit:int=Query(25,ge=1,le=100)):
    event=next((event for event in store.history(finding_id) if event['event_id']==event_id),None)
    if not event:raise HTTPException(404,'Review event is not available.')
    finding=store.finding_for_event(event);rows=finding['evidence'][side]
    return dict(items=rows[offset:offset+limit],total=len(rows),offset=offset,limit=limit,source_versions=finding.get('source_versions',{}),evaluation_as_of=finding.get('evaluation_as_of'))
