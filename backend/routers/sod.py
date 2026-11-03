"""SoD catalogue endpoints; the shared application boundary protects all routes."""
from typing import Literal
from fastapi import APIRouter, Query,Depends, Request, HTTPException
import csv
import io
import json
from datetime import date
from fastapi.responses import StreamingResponse
from csv_exports import spreadsheet_cell
from pydantic import Field
from config_models import StrictModel
from search_matching import search_fields
import sod_catalogue as store
import cache

router = APIRouter(prefix='/api/sod', tags=['SoD'])


class CatalogueEdit(StrictModel):
    expected_revision: int = Field(ge=0)
    definition_version: str = Field(pattern=r'^[a-f0-9]{64}$')
    metadata: store.LocalMetadata


class CatalogueBulk(StrictModel):
    expected_revision: int = Field(ge=0)
    enabled: bool
    confirm: bool = False


def catalogue_query(search: str = Query('', max_length=256),
              enabled: Literal['', 'enabled', 'disabled'] = '',
              current: Literal['', 'current', 'historical'] = '',
              status: Literal['', 'new', 'changed', 'needs_review', 'reviewed', 'unsupported'] = '',
              criticality: str = Query('', max_length=64),
              type: str = Query('', max_length=64),
              category: str = Query('', max_length=120),
              sort: Literal['risk_id', 'display_name', 'criticality', 'business_category', 'modified'] = 'risk_id',
              descending: bool = False,
):
    return locals()

def catalogue_data(search='',enabled='',current='',status='',criticality='',type='',category='',sort='risk_id',descending=False):
    with store.lock, cache._load_lock:
        result = store.catalogue()
    def matches(item):
        local, source = item['local'], item['source']
        return ((not search.strip() or search_fields(search.strip(), item['risk_id'], source['source_text'], item['display_name'], local['business_category'], local['explanation_en'], local['explanation_no']))
                and (not enabled or local['enabled'] == (enabled == 'enabled'))
                and (not current or item['current'] == (current == 'current'))
                and (not criticality or source['criticality'] == criticality)
                and (not type or source['risk_type'] == type)
                and (not category or local['business_category'] == category)
                and (not status or status == 'new' and item['new']
                     or status == 'changed' and item['source_changed']
                     or status == 'needs_review' and item['description_review_status'] != 'Reviewed'
                     or status == 'reviewed' and item['description_review_status'] == 'Reviewed'
                     or status == 'unsupported' and not source['supported']))
    items = [item for item in result['items'] if matches(item)]
    def value(item):
        selected = item['risk_id'] if sort == 'risk_id' else item['source']['criticality'] if sort == 'criticality' else item['modified'] if sort == 'modified' else item['display_name'] if sort=='display_name' else item['local'][sort]
        return ((selected or '').casefold(), item['risk_id'])
    items.sort(key=value, reverse=descending)
    return {**result,'items':items}

@router.get('/catalogue')
def catalogue(filters:dict=Depends(catalogue_query),offset:int=Query(0,ge=0),limit:int=Query(25,ge=1,le=100)):
    result=catalogue_data(**filters)
    return {**result,'items':result['items'][offset:offset+limit],'total':len(result['items']),'offset':offset,'limit':limit}


CATALOGUE_COLUMNS=['RISK_ID','DISPLAY_NAME','SOURCE_DESCRIPTION','CRITICITY','TYPE','CURRENT','ENABLED','DESCRIPTION_REVIEW_STATUS','BUSINESS_CATEGORY','EXPLANATION_EN','EXPLANATION_NO','CONSEQUENCE_EN','CONSEQUENCE_NO','MITIGATING_CONTROLS_EN','MITIGATING_CONTROLS_NO','REVIEW_GUIDANCE_EN','REVIEW_GUIDANCE_NO','NOTES','ACTIVITY_1','ACTIVITY_2','ACTIVITY_1_TCODES','ACTIVITY_2_TCODES','DEFINITION_VERSION','MODIFIED']
CATALOGUE_HEADER='\ufeff'+';'.join('"'+field+'"' for field in CATALOGUE_COLUMNS)+'\r\n'

@router.get('/catalogue/export')
def catalogue_export(filters:dict=Depends(catalogue_query)):
    result=catalogue_data(**filters)
    def stream():
        yield CATALOGUE_HEADER
        buffer=io.StringIO();writer=csv.writer(buffer,delimiter=';',quoting=csv.QUOTE_ALL,lineterminator='\r\n')
        for row in result['items']:
            source,local=row['source'],row['local']
            values=[row['risk_id'],row['display_name'],source['source_text'],source['criticality'],source['risk_type'],'Yes' if row['current'] else 'No','Yes' if local['enabled'] else 'No',row['description_review_status'],local['business_category']]
            values.extend(local[key] for key in ('explanation_en','explanation_no','consequence_en','consequence_no','mitigating_controls_en','mitigating_controls_no','review_guidance_en','review_guidance_no','notes'))
            values.extend([source['activity1'],source['activity2'],json.dumps(source['activities']['ACTVT1'],ensure_ascii=False),json.dumps(source['activities']['ACTVT2'],ensure_ascii=False),row['definition_version'],row['modified'] or ''])
            buffer.seek(0);buffer.truncate(0);writer.writerow([spreadsheet_cell(value) for value in values]);yield buffer.getvalue()
    return StreamingResponse(stream(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="sap-lens-sod-catalogue-{date.today().isoformat()}.csv"','Cache-Control':'no-store'})

@router.get('/overview')
def overview():
    from collections import Counter
    from .sod_reviews import review_data
    _,analysis,reviews=review_data()
    with store.lock,cache._load_lock:catalogue=store.catalogue()
    available=analysis['coverage']['status']=='available'
    counts=dict(defined=catalogue['summary']['current'],enabled=catalogue['summary']['enabled'],new=catalogue['summary']['new'],needs_description_review=catalogue['summary']['needs_description_review'],user_findings=analysis['summary']['user_findings'] if available else None,role_findings=analysis['summary']['role_findings'] if analysis['coverage']['roles_available'] else None,reviewed=reviews['summary'].get('Reviewed',0),pending=reviews['summary'].get('Pending',0) if available else None,outdated=reviews['summary'].get('Outdated',0))
    return dict(counts=counts,criticality=dict(Counter(row['criticality'] for row in analysis['users'])),source=catalogue['source'],coverage=analysis['coverage'],governance=governance_overview())

class ActivityEdit(StrictModel):
    expected_revision: int = Field(ge=0)
    metadata: store.ActivityMetadata


@router.get('/catalogue-activities')
def activities(search: str = Query('', max_length=256), current: Literal['', 'current', 'historical'] = '',
               sort: Literal['activity', 'display_name', 'business_category', 'risks'] = 'activity', descending: bool = False,
               offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
    with store.lock, cache._load_lock:
        result = store.activity_catalogue()
        source_version=cache.get_snapshot().sod.get('content_hash')
    needle = search.strip()
    items = [item for item in result['items']
             if (not current or item['current'] == (current == 'current'))
             and (not needle or search_fields(needle, item['activity'], item['display_name'], item['local']['business_category'],
                                              item['local']['explanation_en'], *item['risks'], *item['tcodes']))]
    key = {'activity': lambda item: item['activity'].casefold(), 'risks': lambda item: (len(item['risks']), item['activity'].casefold()),
           'display_name': lambda item: (item['display_name'].casefold(), item['activity'].casefold()),
           'business_category': lambda item: (item['local']['business_category'].casefold(), item['activity'].casefold())}[sort]
    items.sort(key=key, reverse=descending)
    return dict(items=items[offset:offset + limit], total=len(items), offset=offset, limit=limit, revision=result['revision'],source_version=source_version)


@router.post('/catalogue-activities/{activity:path}')
def edit_activity(activity: str, request: ActivityEdit):
    return store.save_activity(activity, request.metadata, request.expected_revision)


@router.get('/appearance')
def appearance():
    with store.lock:
        return store.appearance()


@router.get('/metadata')
def metadata():
    """Resolved risk and activity descriptions (imported first, local fallback, origin identified) for pills and detail popovers."""
    import sod_metadata
    with store.lock:
        return sod_metadata.lookup()


@router.post('/catalogue/bulk')
def bulk(request: CatalogueBulk):
    return store.bulk(request.enabled, request.expected_revision, request.confirm)


@router.post('/catalogue/{risk_id:path}')
def edit(risk_id: str, request: CatalogueEdit):
    return store.save(risk_id, request.metadata, request.expected_revision, request.definition_version)


def governance_overview():
    """Actionable SoD 2.0 summary for the primary Overview; counts distinguish users, findings, activities and assignments."""
    import sod_governance as governance
    import sod_periods as periods
    import sod_scope as scope
    bundle=scope.load('current')
    if bundle['coverage']['status']!='available':return dict(available=False,reason=bundle['coverage'].get('reason'),missing=bundle['coverage'].get('missing',[]))
    model=scope.model_for(bundle);change=scope.observe(bundle,model);state=scope.states_for(bundle,model)
    def tally(kind):
        result={}
        for life,_ in state[kind].values():result[life]=result.get(life,0)+1
        return result
    actions=scope.actions_for(bundle);today=date.today()
    open_actions=[item for item in actions if item.status in {'Open','In progress'}]
    rows,summary=governance.remediation_rows(model,state,actions,scope.make_verifier(),today=today)
    with periods.lock:index=periods.read()
    progress=[]
    for period in sorted(index.items,key=lambda item:item.modified,reverse=True):
        if period.deleted_at or period.state in periods.FROZEN:continue
        assessment=periods.progress(period)
        if assessment is None:continue
        progress.append(dict(id=period.id,name=period.name,state=period.state,**assessment))
        if len(progress)>=5:break
    frozen=[item for item in index.items if not item.deleted_at and item.state in periods.FROZEN and item.approval_date]
    latest=max(frozen,key=lambda item:(item.approval_date,item.modified),default=None)
    latest_approval=dict(id=latest.id,name=latest.name,state=latest.state,approval_date=latest.approval_date.isoformat(),approver=latest.approver) if latest else None
    return dict(available=True,latest_approval=latest_approval,users_with_conflicts=len(model),user_risk_findings=sum(len(entry['findings']) for entry in model.values()),
                activities=tally('activity'),assignments=tally('assignment'),acceptance=tally('acceptance'),
                review_coverage={kind:dict(total=len(values),reviewed=sum(value['reviewed'] for value in values.values())) for kind,values in state['coverage'].items()},
                assignments_marked_remove=sum(1 for life,_ in state['assignment'].values() if life=='Removal required'),concentration=governance.conflict_concentration(model),
                remediation=dict(open_actions=len(open_actions),overdue=sum(1 for item in open_actions if item.due_date and item.due_date<today),
                                 removal_without_action=len({(row['user'],row['assignment_id']) for row in rows if row['recommended']=='Remove assignment' and not row['action']}),
                                 verification=scope.removal_verification(actions)[0]),
                periods=progress,change=change,as_of=bundle['as_of'])


class ReferenceUpload(StrictModel):
    expected_revision: int = Field(ge=0)
    workbook_base64: str = Field(max_length=2800000)


@router.get('/reference')
def reference_library():
    import sod_reference
    return sod_reference.status()


@router.put('/reference')
def replace_reference(request: ReferenceUpload):
    import base64
    import binascii
    import sod_reference
    from fastapi import HTTPException
    try:
        raw = base64.b64decode(request.workbook_base64, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(422, 'Workbook must be valid base64.') from None
    return sod_reference.status(sod_reference.install(raw, request.expected_revision))


@router.post('/reference/upload')
async def upload_reference(request: Request):
    from fastapi import HTTPException
    from starlette.datastructures import UploadFile
    from starlette.concurrency import run_in_threadpool
    import sod_reference
    async with request.form(max_files=1, max_fields=1, max_part_size=128) as form:
        if set(form) != {'file', 'revision'} or any(len(form.getlist(key)) != 1 for key in form):
            raise HTTPException(422, 'Choose one reference workbook and its current revision.')
        file = form['file']
        if not isinstance(file, UploadFile):
            raise HTTPException(422, 'Choose an XLSX reference workbook.')
        name = file.filename or ''
        if not name.lower().endswith('.xlsx') or len(name.encode('utf-8')) > 200 or '..' in name or any(c in name for c in '/\\\x00<>:"|?*') or any(ord(c) < 32 for c in name):
            raise HTTPException(422, 'Choose an XLSX filename without path components.')
        if not file.size or file.size > sod_reference.MAX_BYTES:
            raise HTTPException(413 if file.size else 422, 'Choose a non-empty reference workbook up to 2 MB.')
        try:
            revision = int(form['revision'])
        except (TypeError, ValueError):
            raise HTTPException(422, 'Choose the current reference revision.') from None
        library = await run_in_threadpool(sod_reference.install, await file.read(sod_reference.MAX_BYTES + 1), revision)
        return sod_reference.status(library)


class ReferenceReset(StrictModel):
    expected_revision: int = Field(ge=0)


@router.post('/reference/reset')
def reset_reference(request: ReferenceReset):
    import sod_reference
    return sod_reference.status(sod_reference.reset(request.expected_revision))


@router.get('/reference/template')
def reference_template():
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    from sod_reference import default_path
    path=default_path().with_name('sod-reference-template.xlsx')
    if not path.is_file():raise HTTPException(503,'Reference template is unavailable; repair the application package.')
    return FileResponse(path,filename='sap-lens-sod-reference-template.xlsx',media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Cache-Control':'no-store'})


@router.get('/catalogue/{risk_id}')
def risk_detail(risk_id:str):
    with store.lock,cache._load_lock:
        result=store.catalogue()
    item=next((row for row in result['items'] if row['risk_id']==risk_id),None)
    if item is None:raise HTTPException(404,'Risk is not available in the retained source definitions.')
    return dict(item=item,revision=result['revision'])


@router.get('/catalogue-activities/{activity:path}')
def activity_detail(activity:str):
    with store.lock,cache._load_lock:
        result=store.activity_catalogue()
    item=next((row for row in result['items'] if row['activity']==activity),None)
    if item is None:raise HTTPException(404,'Activity is not available in the retained source definitions.')
    return dict(item=item,revision=result['revision'])
