from datetime import date
from fastapi import APIRouter,Query
from pydantic import Field
from config_models import StrictModel
import sod_periods as store
from sod_reviews import Annotation
router=APIRouter(prefix='/api/sod/periods',tags=['SoD periods'])
class Create(StrictModel):
    name:str=Field(min_length=1,max_length=120)
    start:date
    end:date
    evaluation_date:date
    expected_revision:int=Field(ge=0)
class Transition(StrictModel):
    state:str=Field(max_length=40)
    expected_revision:int=Field(ge=0)
    expected_review_revision:int=Field(ge=0)
    reviewer:str=Field(default='',max_length=120)
    approver:str=Field(default='',max_length=120)
    approval_date:date|None=None
    confirm:bool=False
    actor:str=Field(default='',max_length=120)
    reason:str=Field(default='',max_length=2000)
class Delete(StrictModel):
    expected_revision:int=Field(ge=0)
    confirm_name:str=Field(max_length=120)
    confirm_impact:bool=False
    actor:str=Field(default='',max_length=120)
class Recapture(StrictModel):
    expected_revision:int=Field(ge=0)
    confirm:bool=False
class Review(StrictModel):
    expected_revision:int=Field(ge=0)
    expected_review_revision:int=Field(ge=0)
    evidence_version:str=Field(pattern=r'^[a-f0-9]{64}$')
    annotation:Annotation
@router.get('')
def listing(include_archived:bool=False):
    with store.lock:
        index=store.read();return dict(revision=index.revision,items=[item.model_dump(mode='json') for item in index.items if include_archived or not item.deleted_at],deletions=[item.model_dump(mode='json') for item in index.deletions[-50:]])
@router.post('')
def create(body:Create):return store.create(**body.model_dump())
@router.get('/compare')
def compare(left:str=Query(...,pattern=r'^[a-f0-9]{32}$'),right:str=Query(...,pattern=r'^[a-f0-9]{32}$')):
    data=store.compare(left,right)
    return {**data,'items':[{**row,'before':{key:row['before'][key] for key in ('subject','risk_id','evidence_version')} if row['before'] else None,'after':{key:row['after'][key] for key in ('subject','risk_id','evidence_version')} if row['after'] else None} for row in data['items']]}
@router.get('/{identifier}')
def details(identifier:str,offset:int=Query(0,ge=0),limit:int=Query(25,ge=1,le=100)):
    data=store.details(identifier);saved={key:value for key,value in data['snapshot'].items() if key!='decisions'};users=saved['analysis']['users'];rows=saved['reviews']['items']
    return {**data,'snapshot':{**saved,'analysis':{**saved['analysis'],'users':users[offset:offset+limit],'roles':[]},'reviews':{**saved['reviews'],'items':rows[offset:offset+limit]}},'total':len(users),'offset':offset,'limit':limit}
@router.post('/{identifier}/transition')
def transition(identifier:str,body:Transition):return store.transition(identifier,**body.model_dump())
@router.post('/{identifier}/recapture')
def recapture(identifier:str,body:Recapture):return store.recapture(identifier,**body.model_dump())
@router.post('/{identifier}/reviews/{finding_id}')
def review(identifier:str,finding_id:str,body:Review):return store.save_review(identifier,finding_id,**body.model_dump())

@router.get('/{identifier}/deletion-impact')
def deletion_impact(identifier:str):return store.deletion_impact(identifier)
@router.post('/{identifier}/delete')
def delete(identifier:str,body:Delete):return store.delete(identifier,**body.model_dump())
