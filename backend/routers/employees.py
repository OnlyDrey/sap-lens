"""Session-protected directory APIs; optional failures never change SAP source data."""
from collections import Counter
from typing import Literal
import threading
import time
from fastapi import APIRouter, HTTPException, Query
from pydantic import Field
import cache
from config import get_settings, save_configuration
from config_models import StrictModel
from daemon_tasks import daemon_call
from employee_directory import parse_directory, store, persist_directory, discard_snapshot, sap_email_owners, match_sap_identity
from user_access import normalize_username

router = APIRouter(prefix='/api/employees', tags=['Employee Directory'])


class ImportRequest(StrictModel):
    path: str = Field(min_length=1, max_length=4096)
    digest: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    revision: int = Field(ge=0)
    mode: Literal['static', 'dynamic'] | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=25, ge=1, le=100)
    search: str = Field(default='', max_length=256)
    filter: Literal['', 'missing_email', 'duplicate_email', 'missing_identifier', 'duplicate_identifier', 'missing_manager', 'ambiguous_manager', 'matched', 'unmatched'] = ''
    sort: Literal['name', 'email', 'department', 'manager'] = 'name'
    descending: bool = False


_previews = {}
_preview_lock = threading.Lock()
_coverage_lock = threading.Lock()
_coverage_key = None
_coverage_value = None


def directory_status(private=False, snapshot=None):
    global _coverage_key, _coverage_value
    settings = get_settings()
    snapshot = snapshot or cache.get_snapshot()
    directory = snapshot.directory if snapshot.directory_bound else store.get(settings.employee_csv_path, settings.employee_snapshot_id) if settings.employee_snapshot_id or settings.features.employee_directory else store.directory
    enabled = settings.features.employee_directory
    status = ('disabled' if not enabled else 'not_configured' if not (settings.employee_csv_path or settings.employee_snapshot_id) else
              'error' if store.error or store.import_error else 'healthy' if directory else 'warning')
    report = directory.report() if directory and (settings.employee_csv_path or settings.employee_snapshot_id) else {}
    coverage = Counter()
    user_mapping_enabled = settings.features.user_role_mapping
    user_mapping_available = user_mapping_enabled and bool(snapshot.users.report)
    if enabled and directory and user_mapping_available:
        key = (id(snapshot), snapshot.last_loaded, directory.digest)
        with _coverage_lock:
            if key != _coverage_key:
                owners = sap_email_owners(snapshot.users.users.values())
                value = Counter(match_sap_identity(directory, user, owners)['status'] for user in snapshot.users.users.values())
                _coverage_key, _coverage_value = key, value
            coverage.update(_coverage_value)
    if status == 'healthy' and (report.get('duplicate_emails') or report.get('missing_emails') or report.get('missing_identifiers') or any(report.get('duplicate_identifiers',{}).values()) or
                                any(report.get('managers', {}).get(k) for k in ['ambiguous', 'unresolved', 'self_reference'])):
        status = 'warning'
    if not private: report.pop('file_name', None)
    return dict(enabled=enabled, configured=bool(settings.employee_csv_path), loaded=bool(directory and (settings.employee_csv_path or settings.employee_snapshot_id)),
                status=status, error=(store.error or store.import_error) if enabled else None, report=report, coverage=dict(coverage),
                persisted=bool(settings.employee_snapshot_id and directory),
                operational_status='disabled' if not enabled else 'data_unavailable' if not directory else 'dependency_unavailable' if not user_mapping_available else 'ready',
                digest=directory.digest if private and directory else None,
                storage='persisted_snapshot' if settings.employee_snapshot_id else 'legacy_path_only' if settings.employee_csv_path else 'none',
                coverage_reason=('Enable Employee Directory in Feature Settings.' if not enabled else 'Import directory records first.' if not directory else 'Enable User–Role Mapping in Feature Settings to evaluate SAP email matches.' if not user_mapping_enabled else 'Load the User Access CSV to evaluate SAP email matches.' if not user_mapping_available else 'The User Access CSV contains no SAP users.' if not coverage else ''),
                coverage_total=sum(coverage.values()),
                dependency_satisfied=user_mapping_available, user_mapping_enabled=user_mapping_enabled,
                mapping_data_available=bool(snapshot.users.report), user_mapping_available=user_mapping_available,
                directory_operational=bool(enabled and directory),
                enrichment=dict(enabled=bool(enabled and user_mapping_enabled),
                                available=bool(directory and snapshot.users.report),
                                operational=bool(enabled and directory and user_mapping_available),
                                dependencies=['user_role_mapping', 'employee_directory']),
                action='Settings → Data Sources → Employee Directory')


def available(snapshot=None):
    settings = get_settings()
    if not settings.features.employee_directory: return None
    snapshot = snapshot or cache.get_snapshot()
    if snapshot.directory_bound: return snapshot.directory
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
    key = (request.path, request.digest, request.revision)
    with _preview_lock:
        cached = _previews.get(key) if request.digest else None
    directory = cached[1] if cached and time.monotonic() - cached[0] < 600 else await parsed(request)
    if request.digest and directory.digest != request.digest:
        raise HTTPException(409, 'Preview source changed. Validate the CSV again.')
    with _preview_lock:
        if len(_previews) >= 2:
            _previews.pop(next(iter(_previews)))
        _previews[(request.path, directory.digest, request.revision)] = (time.monotonic(), directory)
    settings = get_settings()
    snapshot = cache.get_snapshot()
    previous = snapshot.directory if snapshot.directory_bound else store.get(settings.employee_csv_path, settings.employee_snapshot_id)
    from employee_preview import preview_page
    return await daemon_call(preview_page, directory, previous, snapshot, settings, request)


@router.post('/import')
async def import_directory(request: ImportRequest):
    directory = await parsed(request)
    if not request.digest or directory.digest != request.digest:
        raise HTTPException(409, 'The CSV changed or has not been previewed. Preview it again before confirmation.')
    with cache._load_lock, store.lock:
        settings = get_settings().model_copy(deep=True)
        if settings.revision != request.revision:
            raise HTTPException(409, 'Settings changed. Reload before importing.')
        previous_id = settings.employee_snapshot_id
        staged_id = None
        try:
            staged_id = persist_directory(directory)
            settings.employee_csv_path = request.path
            settings.employee_snapshot_id = staged_id
            if request.mode is not None: settings.source_modes.employees = request.mode
            from deployment import validate_server_sources
            validate_server_sources(settings)
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
        published = cache.with_directory(cache.get_snapshot(), directory, request.path, staged_id)
        # Directory-only publication leaves SAP assignment revision unchanged.
        cache._cache = published
    result = directory_status(private=True)
    if previous_id and previous_id != staged_id:
        try: discard_snapshot(previous_id)
        except OSError: result['cleanup_warning'] = 'Imported successfully; an older private snapshot could not be removed. Review local application storage.'
    return result


@router.post('/clear')
def clear(request: ImportRequest):
    with cache._load_lock, store.lock:
        settings = get_settings().model_copy(deep=True)
        if settings.revision != request.revision: raise HTTPException(409, 'Settings changed. Reload before clearing.')
        previous_id = settings.employee_snapshot_id
        settings.employee_csv_path = ''
        settings.employee_snapshot_id = None
        try: save_configuration(settings, request.revision)
        except (ValueError, OSError): raise HTTPException(409, 'Directory could not be cleared. Previous data retained.') from None
        store.clear()
        published = cache.with_directory(cache.get_snapshot(), None, '', None)
        cache._cache = published
    warning = None
    try: discard_snapshot(previous_id)
    except OSError: warning = 'Source cleared, but the private snapshot could not be removed. Review local application storage.'
    return dict(status='cleared', cleanup_warning=warning)


@router.get('/match/{username:path}')
def match_user(username: str):
    snapshot = cache.get_snapshot()
    directory = available(snapshot)
    if directory is None: return dict(status='directory_unavailable', employee=None)
    if not get_settings().features.user_role_mapping or not snapshot.users.report:
        return dict(status='mapping_unavailable', employee=None)
    user = snapshot.users.users.get(normalize_username(username))
    if user is None: raise HTTPException(404, 'SAP user not found.')
    result = match_sap_identity(directory, user, sap_email_owners(snapshot.users.users.values()))
    employee = result.get('employee')
    manager_sap = dict(status='missing_email', username=None)
    if employee:
        from employee_directory import normalized as normalize_email
        email = normalize_email(employee['manager']['email'])
        if email:
            matches = [u['username'] for u in snapshot.users.users.values()
                       if email in {normalize_email(e) for e in u['emails']}]
            manager_sap = dict(status='matched' if len(matches) == 1 else 'ambiguous' if matches else 'unmatched',
                               username=matches[0] if len(matches) == 1 else None)
    if manager_sap.get('username'):
        manager = snapshot.users.users[normalize_username(manager_sap['username'])]
        names = [' '.join(n).strip() for n in manager['names'] if any(n)]
        if len(names) == 1: manager_sap['display_name'] = names[0]
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


class PersistRequest(StrictModel):
    revision: int = Field(ge=0)
    digest: str = Field(pattern=r'^[a-f0-9]{64}$')


@router.post('/persist')
def persist_current(request: PersistRequest):
    """Recover already validated legacy records without rereading a missing CSV."""
    with cache._load_lock, store.lock:
        settings = get_settings().model_copy(deep=True)
        directory = store.directory
        if settings.revision != request.revision or not directory or directory.digest != request.digest or store.path != settings.employee_csv_path:
            raise HTTPException(409, 'Directory or settings changed. Review Data Sources before saving records.')
        staged = None
        try:
            staged = persist_directory(directory)
            settings.employee_snapshot_id = staged
            save_configuration(settings, request.revision)
        except (OSError, ValueError):
            if staged and staged != get_settings().employee_snapshot_id:
                try: discard_snapshot(staged)
                except OSError: pass
            raise HTTPException(409, 'Durable storage could not be saved. Validated in-memory records are retained; check local storage permissions.') from None
        store.attempted_path = ('snapshot', staged)
        store.error = None
        cache._cache = cache.with_directory(cache.get_snapshot(), directory, settings.employee_csv_path, staged)
    return directory_status(private=True)
