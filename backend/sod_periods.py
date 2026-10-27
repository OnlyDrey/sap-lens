"""Explicit SoD review periods and reproducible private snapshots."""
from datetime import date,datetime,timezone
import json
import threading
from typing import Literal
from uuid import uuid4
from fastapi import HTTPException
from pydantic import Field,model_validator
import cache
import sod_catalogue as catalogue
import sod_reviews as reviews
from sod_analysis import analyze
from config import atomic_write,config_dir,get_settings
from config_models import StrictModel
from csv_lifecycle import read_private,write_private

lock=threading.RLock()
MAX_BYTES=4*1024*1024
STATES=('Draft','In review','Ready for approval','Approved / closed')

class Period(StrictModel):
    id:str=Field(pattern=r'^[a-f0-9]{32}$')
    name:str=Field(min_length=1,max_length=120)
    start:date
    end:date
    evaluation_date:date
    state:Literal['Draft','In review','Ready for approval','Approved / closed']='Draft'
    snapshot:str=Field(pattern=r'^[a-f0-9]{64}$')
    snapshots:list[str]=Field(default_factory=list,max_length=100)
    created:str
    modified:str
    reviewer:str=Field(default='',max_length=120)
    approver:str=Field(default='',max_length=120)
    approval_date:date|None=None
    @model_validator(mode='after')
    def valid_dates(self):
        if self.start>self.end or not self.start<=self.evaluation_date<=self.end:raise ValueError('Evaluation date must be within the review period.')
        for value in self.snapshots:
            if len(value)!=64 or any(c not in '0123456789abcdef' for c in value):raise ValueError('Invalid snapshot history.')
        for value in (self.created,self.modified):datetime.fromisoformat(value)
        if self.state=='Approved / closed' and (not self.reviewer.strip() or not self.approver.strip() or self.approval_date is None):raise ValueError('Closed periods require recorded reviewer, approver and approval date.')
        return self

class Index(StrictModel):
    version:Literal[1]=1
    revision:int=Field(default=0,ge=0)
    items:list[Period]=Field(default_factory=list,max_length=250)
    @model_validator(mode='after')
    def unique(self):
        if len({item.id for item in self.items})!=len(self.items):raise ValueError('Duplicate period identifiers.')
        return self

def now():return datetime.now(timezone.utc).isoformat()

def read():
    path=config_dir()/'sod-periods.json'
    if not path.exists():return Index()
    try:
        with path.open('rb') as stream:raw=stream.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES:raise ValueError()
        return Index.model_validate_json(raw)
    except (OSError,ValueError,TypeError,RecursionError):raise HTTPException(409,'SoD period index is unavailable. Original data is preserved; restore a private backup.') from None

def write(index):
    try:
        validated=Index.model_validate(index.model_dump());raw=validated.model_dump_json().encode()
        if len(raw)>MAX_BYTES:raise ValueError()
        atomic_write(config_dir()/'sod-periods.json',raw)
    except (OSError,ValueError,TypeError):raise HTTPException(409,'Period changes could not be saved. Previous snapshots remain retained.') from None

def expect(index,revision):
    if index.revision!=revision:raise HTTPException(409,'Review periods changed. Reload before saving.')

def find(index,identifier):
    item=next((item for item in index.items if item.id==identifier),None)
    if not item:raise HTTPException(404,'Review period not found.')
    return item

def snapshot(period):
    try:
        saved=read_private('snapshots',period.snapshot)
        if saved.get('source')!='sod-period' or saved.get('period_id')!=period.id:raise ValueError()
        return saved
    except (OSError,ValueError,KeyError,TypeError):raise HTTPException(409,'Period snapshot is unavailable or invalid. Restore its private backup.') from None

def capture(identifier,evaluation_date):
    with reviews.lock,catalogue.lock,cache._load_lock:
        state=cache.get_snapshot();settings=get_settings();local=catalogue.read()
        config=settings.model_copy(deep=True)
        metadata={key:item.metadata.model_dump() for key,item in local.entries.items()}
        risk_items=[item for item in catalogue.catalogue(state,config,local)['items'] if item['current']]
    result=analyze(state,metadata=metadata,as_of=evaluation_date,mapping_enabled=config.features.user_role_mapping,directory_enabled=config.features.employee_directory)
    if result['coverage']['status']!='available':raise HTTPException(409,'Review periods require validated matrix, catalogue and enabled User–Role Mapping sources.')
    definitions={item['risk_id']:item for item in state.sod['risks']}
    for finding in result['users']:
        source=definitions[finding['risk_id']];local_meta=metadata.get(finding['risk_id'],{})
        finding['risk']={key:local_meta.get(key,'') for key in ('display_name','business_category')}
        finding['risk'].update(source_text=source['source_text'],risk_type=source['risk_type'])
    versions={name:ref.snapshot for name,ref in config.data_lifecycle.sources.items()}
    if config.employee_snapshot_id:versions['employees']=config.employee_snapshot_id
    for finding in result['users']:finding.update(source_versions=versions,evaluation_as_of=evaluation_date.isoformat())
    baseline=reviews.listing(result['users'],coverage=result['coverage'])
    # Only current period findings belong in its baseline, not unrelated historical reviews.
    baseline['items']=[row for row in baseline['items'] if row['presence']=='current']
    baseline['summary']={name:sum(row['lifecycle']==name for row in baseline['items']) for name in ('Pending','Reviewed','Action required','Outdated','Historical')}
    complete=[key for key,user in state.users.users.items() if all(a['match_status'] in {'exact','wildcard'} for a in user['assignments'] if a.get('scope','business')!='other')]
    return dict(version=1,source='sod-period',period_id=identifier,captured_at=now(),evaluation_date=evaluation_date.isoformat(),analysis=result,risks=risk_items,reviews=baseline,
                source_versions=versions,source_metadata={name:dict(imported_at=ref.imported_at,checked_at=ref.checked_at) for name,ref in config.data_lifecycle.sources.items()},
                source_counts=dict(users=len(state.users.users),roles=len(state.roles),matrix_records=len(state.sod['records'])),
                complete_users=complete,organization=config.organization.model_dump(),logo_id=config.logo_id,
                identity_notice=reviews.IDENTITY_NOTICE,limitation='Evaluation uses retained imported evidence at an explicit date; it does not reconstruct unexported historical SAP authorizations.')

def overlaid(period,saved):
    if period.state=='Approved / closed':return saved
    with reviews.lock:local=reviews.listing(saved['analysis']['users'],context=period.id,coverage=saved['analysis']['coverage'])
    baseline={row['finding_id']:row for row in saved['reviews']['items']}
    for row in local['items']:
        if row['event']:baseline[row['finding_id']]=row
    rows=list(baseline.values())
    summary={name:sum(row['lifecycle']==name for row in rows) for name in ('Pending','Reviewed','Action required','Outdated','Historical')}
    result={**saved,'reviews':{**local,'items':rows,'summary':summary}}
    return result

def details(identifier):
    with lock:
        index=read();period=find(index,identifier);saved=overlaid(period,snapshot(period))
        return dict(period=period.model_dump(mode='json'),revision=index.revision,review_revision=reviews.read().revision,snapshot=saved,checksum=period.snapshot)

def create(name,start,end,evaluation_date,expected_revision):
    with lock:
        index=read();expect(index,expected_revision)
        if len(index.items)>=250:raise HTTPException(409,'Review period capacity reached; preserve a private backup before recovery.')
        identifier=uuid4().hex;stamp=now()
        # Validate dates before potentially expensive capture.
        try:period=Period(id=identifier,name=name,start=start,end=end,evaluation_date=evaluation_date,snapshot='0'*64,created=stamp,modified=stamp)
        except ValueError:raise HTTPException(422,'Choose a named period with an evaluation date within its start/end range.') from None
        saved=capture(identifier,evaluation_date);period.snapshot=write_private('snapshots',saved);period.snapshots=[period.snapshot]
        index.items.append(period);index.revision+=1;write(index)
        return dict(period=period.model_dump(mode='json'),revision=index.revision)

def transition(identifier,state,expected_revision,expected_review_revision,reviewer='',approver='',approval_date=None,confirm=False):
    with lock,reviews.lock:
        index=read();expect(index,expected_revision);period=find(index,identifier)
        if period.state=='Approved / closed':raise HTTPException(409,'Approved snapshots are immutable. Create a new review period.')
        allowed={'Draft':{'In review'},'In review':{'Draft','Ready for approval'},'Ready for approval':{'In review','Approved / closed'}}
        if state not in allowed[period.state]:raise HTTPException(422,'Unsupported review-period transition.')
        if reviews.read().revision!=expected_review_revision:raise HTTPException(409,'Review decisions changed. Reload before changing period state.')
        saved=overlaid(period,snapshot(period))
        if state in {'Ready for approval','Approved / closed'} and any(row['lifecycle'] in {'Pending','Outdated'} for row in saved['reviews']['items']):raise HTTPException(409,'Complete or renew all finding decisions before approval preparation.')
        if state=='Approved / closed':
            if not confirm or not reviewer.strip() or not approver.strip() or approval_date is None:raise HTTPException(422,'Confirm closure with self-reported reviewer, approver and approval date.')
            period.reviewer=reviewer.strip();period.approver=approver.strip();period.approval_date=approval_date
            saved={**saved,'approval':dict(reviewer=period.reviewer,approver=period.approver,date=approval_date.isoformat(),identity_notice=reviews.IDENTITY_NOTICE)}
            if len(period.snapshots)>=100:raise HTTPException(409,'Period snapshot capacity reached.')
            period.snapshot=write_private('snapshots',saved);period.snapshots.append(period.snapshot)
        period.state=state;period.modified=now();index.revision+=1;write(index)
        return dict(period=period.model_dump(mode='json'),revision=index.revision)

def recapture(identifier,expected_revision,confirm):
    with lock,reviews.lock:
        index=read();expect(index,expected_revision);period=find(index,identifier)
        if period.state not in {'Draft','In review'} or not confirm:raise HTTPException(409,'Explicitly confirm recapture of an open Draft/In review period.')
        if len(period.snapshots)>=100:raise HTTPException(409,'Period snapshot capacity reached.')
        saved=capture(period.id,period.evaluation_date)
        period.snapshot=write_private('snapshots',saved);period.snapshots.append(period.snapshot);period.modified=now();index.revision+=1;write(index)
        return dict(period=period.model_dump(mode='json'),revision=index.revision)

def save_review(identifier,finding_id,annotation,expected_revision,expected_review_revision,evidence_version):
    with lock,reviews.lock:
        index=read();expect(index,expected_revision);period=find(index,identifier)
        if period.state not in {'Draft','In review'}:raise HTTPException(409,'Only Draft/In review periods accept decisions.')
        saved=snapshot(period);finding=next((row for row in saved['analysis']['users'] if row['finding_id']==finding_id),None)
        if not finding:raise HTTPException(404,'Finding not present in this period snapshot.')
        return reviews.save(finding,annotation,expected_review_revision,evidence_version,context=identifier)

def compare(left_id,right_id):
    with lock:
        index=read();left_period=find(index,left_id);right_period=find(index,right_id)
        left=overlaid(left_period,snapshot(left_period));right=overlaid(right_period,snapshot(right_period))
        a={row['finding_id']:row for row in left['analysis']['users']};b={row['finding_id']:row for row in right['analysis']['users']}
        previous=set()
        for period in index.items:
            if period.created<left_period.created and period.state=='Approved / closed' and period.modified<left_period.created:
                previous.update(row['finding_id'] for row in snapshot(period)['analysis']['users'])
        risk_a={item['risk_id']:item['definition_version'] for item in left['risks']};risk_b={item['risk_id']:item['definition_version'] for item in right['risks']}
        enabled={item['risk_id'] for item in right['risks'] if item['local']['enabled'] and item['source']['supported']}
        changes=[]
        for identifier in sorted(set(a)|set(b)):
            if identifier in a and identifier in b:status='Unchanged' if a[identifier]['evidence_version']==b[identifier]['evidence_version'] else 'Changed'
            elif identifier in b:status='Reopened' if identifier in previous else 'New'
            else:
                old=a[identifier];eligible=right['analysis']['coverage']['status']=='available' and old['subject'] in right['complete_users'] and old['risk_id'] in enabled and risk_a.get(old['risk_id'])==risk_b.get(old['risk_id'])
                status='Resolved' if eligible else 'Not observed / coverage changed'
            changes.append(dict(finding_id=identifier,status=status,before=a.get(identifier),after=b.get(identifier)))
        return dict(left=left_period.model_dump(mode='json'),right=right_period.model_dump(mode='json'),items=changes,summary={name:sum(row['status']==name for row in changes) for name in ('New','Resolved','Unchanged','Changed','Reopened','Not observed / coverage changed')},changed_risks=[risk for risk in sorted(set(risk_a)|set(risk_b)) if risk_a.get(risk)!=risk_b.get(risk)],source_coverage_changed=left['source_counts']!=right['source_counts'],review_counts=dict(before=left['reviews']['summary'],after=right['reviews']['summary']))
