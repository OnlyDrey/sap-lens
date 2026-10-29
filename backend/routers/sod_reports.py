from hashlib import sha256
from typing import Literal
from fastapi import APIRouter
from fastapi.responses import Response
from config_models import StrictModel
from pydantic import Field
from fastapi import HTTPException
import sod_reports as reports
import sod_decisions as decisions
import report_branding
from .sod_governance import csv_response,REMEDIATION_COLUMNS,remediation_csv_rows
router=APIRouter(prefix='/api/sod/reports',tags=['SoD reports'])
class Request(StrictModel):
    period_id:str=Field(pattern=r'^[a-f0-9]{32}$')
    expected_model:str|None=Field(default=None,pattern=r'^[a-f0-9]{64}$')
    options:reports.Options
class BrandingImage(StrictModel):
    image_base64:str=Field(min_length=1,max_length=1_500_000)
    filename:str=Field(default='',max_length=200)
@router.get('/branding')
def branding():return report_branding.describe()
@router.put('/branding')
def branding_upload(body:BrandingImage):
    try:return report_branding.store(body.image_base64,body.filename)
    except ValueError as error:raise HTTPException(422,str(error)) from None
@router.delete('/branding')
def branding_remove():
    try:return report_branding.remove()
    except ValueError as error:raise HTTPException(409,str(error)) from None
@router.post('/preview')
def preview(body:Request):return reports.model(body.period_id,body.options)
@router.post('/{kind}')
def download(kind:Literal['docx','pdf'],body:Request):
    model=reports.model(body.period_id,body.options)
    if body.expected_model and body.expected_model!=model['model_checksum']:raise HTTPException(409,'Report evidence changed. Preview the current snapshot before exporting.')
    payload=reports.render(model,kind)
    decisions.log_report(body.period_id,kind,model['title'],model['status'],model['document_version'],model['model_checksum'],body.options.previous_period_id,model['prepared_by'])
    return Response(payload,media_type='application/pdf' if kind=='pdf' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',headers={'Content-Disposition':f'attachment; filename="sap-lens-sod-report-{model["period"]["id"]}-{model["report_date"]}.{kind}"','Cache-Control':'no-store','X-SAP-Lens-Snapshot':model['snapshot_checksum'],'X-SAP-Lens-Report-Model':model['model_checksum'],'X-SAP-Lens-File-SHA256':sha256(payload).hexdigest()})

class RemediationRequest(StrictModel):
    context:str=Field(default='current',pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')
    expected_model:str|None=Field(default=None,pattern=r'^[a-f0-9]{64}$')
    options:reports.RemediationOptions=Field(default_factory=reports.RemediationOptions)
@router.post('/remediation/preview')
def remediation_preview(body:RemediationRequest):
    model=reports.remediation_model(body.context,body.options);return {key:value for key,value in model.items() if key!='rows'}|dict(row_count=len(model['rows']))
@router.post('/remediation/{kind}')
def remediation_download(kind:Literal['csv','docx','pdf'],body:RemediationRequest):
    """Operational remediation export; CSV, DOCX and PDF share one model and never claim completed removal."""
    model=reports.remediation_model(body.context,body.options)
    if body.expected_model and body.expected_model!=model['model_checksum']:raise HTTPException(409,'Remediation evidence changed. Preview again before exporting.')
    if body.context!='current':decisions.log_report(body.context,'remediation-'+kind,model['title'],model['status'],model['document_version'],model['model_checksum'],None,model['prepared_by'])
    if kind=='csv':
        response=csv_response(REMEDIATION_COLUMNS,remediation_csv_rows(model['rows']),'access-remediation')
        response.headers['X-SAP-Lens-Model']=model['model_checksum'];return response
    payload=reports.render(model,kind)
    return Response(payload,media_type='application/pdf' if kind=='pdf' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',headers={'Content-Disposition':f'attachment; filename="sap-lens-access-remediation-{body.context}-{model["report_date"]}.{kind}"','Cache-Control':'no-store','X-SAP-Lens-Model':model['model_checksum']})
