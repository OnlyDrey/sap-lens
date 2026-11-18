"""Administrator-only private archive boundary; all replacement happens at restart."""
from tarfile import TarError
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import Field, SecretStr
from config_models import StrictModel
import application_backups as backups
from backup_schedule import Schedule
from maintenance import MaintenanceError, private_file
from backup_crypto import BackupCryptoError

router=APIRouter(prefix='/api/backups',tags=['Backups'])


def admin(request):
    server=request.app.state.deployment
    if server:
        principal=getattr(request.state,'server_principal',None)
        if server.auth not in {'users','sessions'} or not principal or principal[1]!='administrator':
            raise HTTPException(403,'Application backups require an authenticated administrator account. Other deployments can use stopped host maintenance.')
    return server


def operation(action):
    try: return action()
    except BackupCryptoError as error:
        raise HTTPException(409,str(error)) from None
    except (MaintenanceError,OSError,ValueError,KeyError,TypeError,TarError):
        raise HTTPException(409,'Backup operation could not be completed. Check the archive, compatibility, storage and pending operation. Existing data is preserved.') from None


@router.get('')
def status(request:Request):
    admin(request)
    result=operation(backups.read)
    result.pop('crypto_plan',None)
    from backup_crypto import key_status
    from config import config_dir
    return {**result,'key_provider':key_status(config_dir())}


class CreateBackup(StrictModel):
    passphrase:SecretStr=Field(default='',max_length=1024)


@router.post('/create')
def create(request:Request,body:CreateBackup=CreateBackup()):
    admin(request)
    return operation(lambda:backups.request_backup(passphrase=body.passphrase.get_secret_value()))


class VerifyKey(StrictModel):
    recovery_key:SecretStr=Field(max_length=96)


@router.post('/key/verify')
def verify_key(request:Request,body:VerifyKey):
    admin(request)
    from backup_crypto import verify_escrow
    from config import config_dir
    return operation(lambda:verify_escrow(body.recovery_key.get_secret_value(),config_dir()))


@router.post('/cancel')
def cancel(request:Request):
    admin(request)
    return operation(backups.cancel)


class BackupScheduleBody(StrictModel):
    revision:int=Field(ge=0)
    schedule:Schedule


@router.get('/schedule')
def schedule_status(request:Request):
    admin(request)
    from backup_schedule import status
    return operation(status)


@router.post('/schedule')
def schedule_save(request:Request,body:BackupScheduleBody):
    admin(request)
    from backup_schedule import save
    return operation(lambda:save(body.schedule,body.revision))


@router.get('/history')
def backup_history(request:Request):
    admin(request)
    from backup_schedule import history
    return operation(history)


class DeleteBackup(StrictModel):
    confirm:bool=False


@router.post('/{identity}/delete')
def delete_backup(request:Request,identity:str,body:DeleteBackup):
    admin(request)
    from backup_schedule import remove
    return operation(lambda:remove(identity,body.confirm))


@router.post('/upload')
async def upload(request:Request):
    server=admin(request)
    if request.headers.get('content-type','').split(';')[0] not in {'application/gzip','application/octet-stream'}: raise HTTPException(415,'Select an encrypted .slbak backup or acknowledge a legacy .tar.gz import.')
    import base64
    encoded=request.headers.get('x-sap-lens-backup-secret','')
    if len(encoded)>8192:raise HTTPException(422,'Backup secret exceeds its supported length.')
    try:secret=base64.b64decode(encoded,validate=True).decode('utf-8') if encoded else ''
    except (ValueError,UnicodeError):raise HTTPException(422,'Invalid backup secret encoding.') from None
    if len(secret.encode('utf-8'))>4096:raise HTTPException(422,'Backup secret exceeds its supported length.')
    try:
        with backups.uploaded() as (identity,path):
            count=0
            with path.open('xb') as stream:
                private_file(path)
                async for block in request.stream():
                    count+=len(block)
                    if count>backups.MAX_UPLOAD: raise HTTPException(413,'Settings uploads support up to 256 MiB compressed; use stopped host maintenance for larger backups.')
                    stream.write(block)
            if count==0: raise HTTPException(422,'The archive is empty.')
            from starlette.concurrency import run_in_threadpool
            return await run_in_threadpool(backups.register_upload,identity,server=server,secret=secret,allow_legacy=request.headers.get('x-sap-lens-allow-legacy')=='1')
    except HTTPException: raise
    except BackupCryptoError as error:raise HTTPException(422,str(error)) from None
    except Exception:
        raise HTTPException(422,'Archive validation failed. No active data was changed. Use a compatible application-data backup.') from None


@router.post('/uploads/{identity}/cancel')
def discard_upload(request:Request,identity:str):
    admin(request)
    return operation(lambda:backups.discard_upload(identity))


class Confirm(StrictModel):
    id:str=Field(pattern=r'^[a-f0-9]{32}$')
    sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    confirm:bool=False
    confirm_accounts:bool=False


@router.post('/restore')
def restore(request:Request,body:Confirm):
    admin(request)
    return operation(lambda:backups.confirm_restore(body.id,body.sha256,body.confirm,confirm_accounts=body.confirm_accounts))


@router.get('/{identity}/download')
def download(request:Request,identity:str,kind:str='backup'):
    admin(request)
    path=operation(lambda:backups.download(identity,kind))
    suffix='.slbak' if path.name.endswith('.slbak') else '.tar.gz'
    return FileResponse(path,media_type='application/octet-stream' if suffix=='.slbak' else 'application/gzip',filename=f'SAP-Lens-{kind}-{identity}{suffix}',headers={'Cache-Control':'no-store'})
