from hashlib import sha256
from typing import Literal
from fastapi import APIRouter
from fastapi.responses import Response
from config_models import StrictModel
from pydantic import Field
from fastapi import HTTPException
import sod_reports as reports
router=APIRouter(prefix='/api/sod/reports',tags=['SoD reports'])
class Request(StrictModel):
    period_id:str=Field(pattern=r'^[a-f0-9]{32}$')
    expected_model:str|None=Field(default=None,pattern=r'^[a-f0-9]{64}$')
    options:reports.Options
@router.post('/preview')
def preview(body:Request):return reports.model(body.period_id,body.options)
@router.post('/{kind}')
def download(kind:Literal['docx','pdf'],body:Request):
    model=reports.model(body.period_id,body.options)
    if body.expected_model and body.expected_model!=model['model_checksum']:raise HTTPException(409,'Report evidence changed. Preview the current snapshot before exporting.')
    payload=reports.render(model,kind)
    return Response(payload,media_type='application/pdf' if kind=='pdf' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',headers={'Content-Disposition':f'attachment; filename="sap-lens-sod-report-{model["period"]["id"]}-{model["report_date"]}.{kind}"','Cache-Control':'no-store','X-SAP-Lens-Snapshot':model['snapshot_checksum'],'X-SAP-Lens-Report-Model':model['model_checksum'],'X-SAP-Lens-File-SHA256':sha256(payload).hexdigest()})
