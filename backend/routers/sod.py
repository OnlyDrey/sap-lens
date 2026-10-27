"""SoD catalogue endpoints; the shared application boundary protects all routes."""
from typing import Literal
from fastapi import APIRouter, Query
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


@router.get('/catalogue')
def catalogue(search: str = Query('', max_length=256),
              enabled: Literal['', 'enabled', 'disabled'] = '',
              current: Literal['', 'current', 'historical'] = '',
              status: Literal['', 'new', 'changed', 'needs_review', 'reviewed', 'unsupported'] = '',
              criticality: str = Query('', max_length=64),
              type: str = Query('', max_length=64),
              category: str = Query('', max_length=120),
              sort: Literal['risk_id', 'display_name', 'criticality', 'business_category', 'modified'] = 'risk_id',
              descending: bool = False,
              offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
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
    return {**result, 'items': items[offset:offset + limit], 'total': len(items), 'offset': offset, 'limit': limit}


@router.post('/catalogue/bulk')
def bulk(request: CatalogueBulk):
    return store.bulk(request.enabled, request.expected_revision, request.confirm)


@router.post('/catalogue/{risk_id:path}')
def edit(risk_id: str, request: CatalogueEdit):
    return store.save(risk_id, request.metadata, request.expected_revision, request.definition_version)
