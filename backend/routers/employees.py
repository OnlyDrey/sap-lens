"""Session-protected directory APIs; optional failures never change SAP source data."""
from collections import Counter
from fastapi import APIRouter, HTTPException, Query
from pydantic import Field
import cache
from config import get_settings, save_configuration
from config_models import StrictModel
from daemon_tasks import daemon_call
from employee_directory import parse_directory, store, persist_directory, discard_snapshot
from user_access import normalize_username

router = APIRouter(prefix='/api/employees', tags=['Employee Directory'])


class ImportRequest(StrictModel):
    path: str = Field(min_length=1, max_length=4096)
    digest: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    revision: int = Field(ge=0)


def directory_status(private=False, snapshot=None):
    settings = get_settings()
    snapshot = snapshot or cache.get_snapshot()
    directory = store.get(settings.employee_csv_path, settings.employee_snapshot_id) if settings.employee_snapshot_id or settings.features.employee_directory else store.directory
    enabled = settings.features.employee_directory
    status = ('disabled' if not enabled else 'not_configured' if not (settings.employee_csv_path or settings.employee_snapshot_id) else
              'error' if store.error or store.import_error else 'healthy' if directory else 'warning')
    report = directory.report() if directory and (settings.employee_csv_path or settings.employee_snapshot_id) else {}
    coverage = Counter()
    user_mapping_enabled = settings.features.user_role_mapping
    user_mapping_available = user_mapping_enabled and bool(snapshot.users.report)
    if enabled and directory and user_mapping_available:
        for user in snapshot.users.users.values():
            coverage[directory.match(user['emails'])['status']] += 1
    if status == 'healthy' and (report.get('duplicate_emails') or report.get('missing_emails') or
                                any(report.get('managers', {}).get(k) for k in ['ambiguous', 'unresolved', 'self_reference'])):
        status = 'warning'
    if not private: report.pop('file_name', None)
    return dict(enabled=enabled, configured=bool(settings.employee_csv_path), loaded=bool(directory and (settings.employee_csv_path or settings.employee_snapshot_id)),
                status=status, error=(store.error or store.import_error) if enabled else None, report=report, coverage=dict(coverage),
                persisted=bool(settings.employee_snapshot_id and directory),
                operational_status='disabled' if not enabled else 'data_unavailable' if not directory else 'dependency_unavailable' if not user_mapping_available else 'ready',
                storage='persisted_snapshot' if settings.employee_snapshot_id else 'legacy_path_only' if settings.employee_csv_path else 'none',
                coverage_reason=('Enable Employee Directory in Feature Settings.' if not enabled else 'Import directory records first.' if not directory else 'Enable User–Role Mapping in Feature Settings to evaluate SAP email matches.' if not user_mapping_enabled else 'Load the User Access CSV to evaluate SAP email matches.' if not user_mapping_available else 'The User Access CSV contains no SAP users.' if not coverage else ''),
                coverage_total=sum(coverage.values()),
                dependency_satisfied=user_mapping_available, user_mapping_enabled=user_mapping_enabled,
                mapping_data_available=bool(snapshot.users.report), user_mapping_available=user_mapping_available, action='Settings → Data Sources → Employee Directory')


def available():
    settings = get_settings()
    if not settings.features.employee_directory: return None
    return store.get(settings.employee_csv_path, settings.employee_snapshot_id)


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
        previous_id = settings.employee_snapshot_id
        staged_id = None
        try:
            staged_id = persist_directory(directory)
            settings.employee_csv_path = request.path
            settings.employee_snapshot_id = staged_id
            save_configuration(settings, request.revision)
        except (ValueError, OSError):
            if staged_id and staged_id != previous_id:
                try: discard_snapshot(staged_id)
                except OSError:
                    raise HTTPException(409, 'Import could not be saved. Previous directory retained; a staged private snapshot needs cleanup in local application storage.') from None
            raise HTTPException(409, 'Import could not be saved. Previous directory retained.') from None
        store.generation += 1
        store.directory, store.path, store.attempted_path, store.error = directory, request.path, ('snapshot', staged_id), None
        store.import_error = None
    result = directory_status(private=True)
    if previous_id and previous_id != staged_id:
        try: discard_snapshot(previous_id)
        except OSError: result['cleanup_warning'] = 'Imported successfully; an older private snapshot could not be removed. Review local application storage.'
    return result


@router.post('/clear')
def clear(request: ImportRequest):
    with store.lock:
        settings = get_settings().model_copy(deep=True)
        if settings.revision != request.revision: raise HTTPException(409, 'Settings changed. Reload before clearing.')
        previous_id = settings.employee_snapshot_id
        settings.employee_csv_path = ''
        settings.employee_snapshot_id = None
        try: save_configuration(settings, request.revision)
        except (ValueError, OSError): raise HTTPException(409, 'Directory could not be cleared. Previous data retained.') from None
        store.clear()
    warning = None
    try: discard_snapshot(previous_id)
    except OSError: warning = 'Source cleared, but the private snapshot could not be removed. Review local application storage.'
    return dict(status='cleared', cleanup_warning=warning)


@router.get('/match/{username:path}')
def match_user(username: str):
    directory = available()
    if directory is None: return dict(status='directory_unavailable', employee=None)
    if not get_settings().features.user_role_mapping or not cache.get_snapshot().users.report:
        return dict(status='mapping_unavailable', employee=None)
    user = cache.get_snapshot().users.users.get(normalize_username(username))
    if user is None: raise HTTPException(404, 'SAP user not found.')
    result = directory.match(user['emails'])
    employee = result.get('employee')
    manager_sap = dict(status='missing_email', username=None)
    if employee:
        from employee_directory import normalized as normalize_email
        email = normalize_email(employee['manager']['email'])
        if email:
            matches = [u['username'] for u in cache.get_snapshot().users.users.values()
                       if email in {normalize_email(e) for e in u['emails']}]
            manager_sap = dict(status='matched' if len(matches) == 1 else 'ambiguous' if matches else 'unmatched',
                               username=matches[0] if len(matches) == 1 else None)
    return dict(**result, manager_sap=manager_sap, generation=directory.digest)


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
