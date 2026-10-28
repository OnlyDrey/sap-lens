from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import Field, field_validator
from config_models import StrictModel
import saved_filters as store
router=APIRouter(prefix='/api/saved-filters',tags=['Saved filters'])


class Saved(StrictModel):
    name:str=Field(min_length=1,max_length=80)
    view:Literal['users','roles','release','review','comparison','sod_users','sod_roles','sod_risk_matrix','sod_activity_matrix','sod_explorer','sod_queue']
    filters:dict=Field(max_length=40)
    id:str=Field(default='',max_length=64)
    expected:str=Field(default='',max_length=64)
    rename:bool=False

    @field_validator('name')
    @classmethod
    def name_valid(cls,value):
        value=value.strip()
        if not value or any(ord(c)<32 for c in value): raise ValueError('Use a nonempty readable name.')
        return value

    @field_validator('filters')
    @classmethod
    def filters_valid(cls,value):
        import json
        if len(json.dumps(value))>16000: raise ValueError('Filter definition is too large.')
        for k,v in value.items():
            if len(k)>64 or not (isinstance(v,(str,bool,int)) or isinstance(v,list) and all(isinstance(x,str) and len(x)<=512 for x in v) and len(v)<=25): raise ValueError('Only bounded scalar filters or string lists are supported.')
            if isinstance(v,str) and len(v)>512: raise ValueError('Filter text is too long.')
        return value


@router.get('')
def listing():
    with store.lock: return {'items':store.read()}


@router.post('')
def save(request:Saved):
    allowed={
      'users':{'search','group','sort','descending','role','tcodes','transactionMode','expired','assignmentBand'},
      'roles':{'search','activeModules','transactionMode','transactionOperator','tcodes','notTcodes','sortBy'},
      'release':{'group','kind','releaseGroup','strategy','username','role','status','sort','descending','valid_from_min','valid_from_max','valid_to_min','valid_to_max','include_missing_end'},
      'review':{'search','finding','license','state','sort','descending'},
      'comparison':{'validity','kind','difference','search','area','sort','descending'}}
    for view in ('sod_users','sod_roles'):
        allowed[view]={'search','risk','criticality','risk_type','category','username','group','composite_role','single_role','tcode','account_status','sort','descending','validity','as_of','selected_roles'}
    matrix={'search','risk','criticality','risk_type','category','username','group','composite_role','single_role','tcode','role','role_suffix','activity','account_status',
            'activity_decision','assignment_decision','acceptance','validity','as_of','sort','descending','group_by','table','kind','status'}
    for view in ('sod_risk_matrix','sod_activity_matrix','sod_explorer','sod_queue'):
        allowed[view]=matrix
    if not request.rename and set(request.filters)-allowed[request.view]: raise HTTPException(422,'Unsupported filter fields; result datasets cannot be saved.')
    return store.save(request.name,request.view,request.filters,request.id,request.expected,request.rename)


class Delete(StrictModel):
    id:str=Field(min_length=1,max_length=64)
    expected:str=Field(min_length=1,max_length=64)


@router.post('/delete')
def delete(request:Delete):
    with store.lock:
        items=store.read();item=next((i for i in items if i['id']==request.id),None)
        if item is None: raise HTTPException(404,'Saved filter no longer exists.')
        if item['modified']!=request.expected: raise HTTPException(409,'Saved filter changed. Reload before deleting.')
        store.write([i for i in items if i['id']!=request.id])
    return {'status':'deleted'}
