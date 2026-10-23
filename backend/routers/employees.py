"""Session-protected directory APIs; optional failures never change SAP source data."""
from collections import Counter
from fastapi import APIRouter, HTTPException, Query
from pydantic import Field
import cache
from config import get_settings, save_configuration
from config_models import StrictModel
from daemon_tasks import daemon_call
from employee_directory import parse_directory, store
from user_access import normalize_username

router = APIRouter(prefix='/api/employees', tags=['Employee Directory'])


class ImportRequest(StrictModel):
    path: str = Field(min_length=1, max_length=4096)
    digest: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    revision: int = Field(ge=0)


def directory_status(private=False):
    settings = get_settings()
    directory = store.get(settings.employee_csv_path) if settings.features.employee_directory else store.directory
    enabled = settings.features.employee_directory
    status = ('disabled' if not enabled else 'not_configured' if not settings.employee_csv_path else
              'error' if store.error or store.import_error else 'healthy' if directory else 'warning')
    report = directory.report() if directory and settings.employee_csv_path else {}
    coverage = Counter()
    if enabled and directory:
        for user in cache.get_snapshot().users.users.values():
            coverage[directory.match(user['emails'])['status']] += 1
    if status == 'healthy' and (report.get('duplicate_emails') or report.get('missing_emails') or
                                any(report.get('managers', {}).get(k) for k in ['ambiguous', 'unresolved', 'self_reference'])):
        status = 'warning'
    if not private: report.pop('file_name', None)
    return dict(enabled=enabled, configured=bool(settings.employee_csv_path), loaded=bool(directory and settings.employee_csv_path),
                status=status, error=(store.error or store.import_error) if enabled else None, report=report, coverage=dict(coverage),
                user_mapping_available=bool(cache.get_snapshot().users.report), action='Settings → Data Sources → Employee Directory')


def available():
    settings = get_settings()
    if not settings.features.employee_directory: return None
    return store.get(settings.employee_csv_path)


@router.get('/status')
def status():
    return directory_status(private=True)


async def parsed(request):
    try: return await daemon_call(parse_directory, request.path)
    except (ValueError, OSError) as exc:
        store.import_error = 'Employee Directory validation failed on the last attempt. Previous valid data is retained.'
        message = str(exc) if isinstance(exc, ValueError) else 'Cannot read Employee Directory CSV. Check the absolute path and file permissions.'
        raise HTTPException(400, message) from None


@router.post('/preview')
async def preview(request: ImportRequest):
    directory = await parsed(request)
    return dict(**directory.report(), digest=directory.digest, samples=[directory.view(r) for r in directory.rows[:5]])


@router.post('/import')
async def import_directory(request: ImportRequest):
    directory = await parsed(request)
    if not request.digest or directory.digest != request.digest:
        raise HTTPException(409, 'The CSV changed or has not been previewed. Preview it again before confirmation.')
    with store.lock:
        settings = get_settings().model_copy(deep=True)
        if settings.revision != request.revision:
            raise HTTPException(409, 'Settings changed. Reload before importing.')
        settings.employee_csv_path = request.path
        try: save_configuration(settings, request.revision)
        except (ValueError, OSError): raise HTTPException(409, 'Import could not be saved. Previous directory retained.') from None
        store.generation += 1
        store.directory, store.path, store.attempted_path, store.error = directory, request.path, request.path, None
        store.import_error = None
    return directory_status(private=True)


@router.post('/clear')
def clear(request: ImportRequest):
    with store.lock:
        settings = get_settings().model_copy(deep=True)
        if settings.revision != request.revision: raise HTTPException(409, 'Settings changed. Reload before clearing.')
        settings.employee_csv_path = ''
        try: save_configuration(settings, request.revision)
        except (ValueError, OSError): raise HTTPException(409, 'Directory could not be cleared. Previous data retained.') from None
        store.clear()
    return dict(status='cleared')


@router.get('/match/{username:path}')
def match_user(username: str):
    directory = available()
    if directory is None: return dict(status='directory_unavailable', employee=None)
    user = cache.get_snapshot().users.users.get(normalize_username(username))
    if user is None: raise HTTPException(404, 'SAP user not found.')
    return dict(**directory.match(user['emails']), generation=directory.digest)


@router.get('')
def employees(search: str = Query('', max_length=256), offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
    directory = available()
    if directory is None: return dict(items=[], total=0, offset=offset, limit=limit)
    term = search.strip().casefold()
    fields = ['Name', 'Mail', 'Department', 'Title', 'Site', 'ManagerName', 'ManagerMail']
    records = [r for r in directory.rows if not term or any(term in r[key].casefold() for key in fields)]
    records.sort(key=lambda r: (r['Name'].casefold(), r['Mail'].casefold(), int(r['id'])))
    return dict(items=[directory.view(r) for r in records[offset:offset + limit]], total=len(records), offset=offset, limit=limit, generation=directory.digest)


@router.get('/record/{employee_id}')
def employee(employee_id: int, generation: str = Query(..., pattern=r'^[a-f0-9]{64}$')):
    directory = available()
    if directory is None: raise HTTPException(404, 'Employee Directory unavailable.')
    if directory.digest != generation: raise HTTPException(409, 'Directory changed. Search again.')
    if employee_id < 0 or employee_id >= len(directory.rows): raise HTTPException(404, 'Employee not found.')
    return directory.view(directory.rows[employee_id])
