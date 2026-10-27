"""SoD catalogue endpoints; the shared application boundary protects all routes."""
from typing import Literal
from fastapi import APIRouter, Query,Depends
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
        return ((not search.strip() or search_fields(search.strip(), item['risk_id'], source['source_text'], local['display_name'], local['business_category'], local['explanation_en'], local['explanation_no']))
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
        selected = item['risk_id'] if sort == 'risk_id' else item['source']['criticality'] if sort == 'criticality' else item['modified'] if sort == 'modified' else item['local'][sort]
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
            values=[row['risk_id'],local['display_name'],source['source_text'],source['criticality'],source['risk_type'],'Yes' if row['current'] else 'No','Yes' if local['enabled'] else 'No',row['description_review_status'],local['business_category']]
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
    return dict(counts=counts,criticality=dict(Counter(row['criticality'] for row in analysis['users'])),source=catalogue['source'],coverage=analysis['coverage'])

@router.post('/catalogue/bulk')
def bulk(request: CatalogueBulk):
    return store.bulk(request.enabled, request.expected_revision, request.confirm)


@router.post('/catalogue/{risk_id:path}')
def edit(risk_id: str, request: CatalogueEdit):
    return store.save(risk_id, request.metadata, request.expected_revision, request.definition_version)
