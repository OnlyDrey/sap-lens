"""Allowlisted diagnostics; exported reports exclude local identity and paths."""
from datetime import datetime, timezone
from platform import system, python_version
import cache
from config import config_dir, get_settings
from version import VERSION


def diagnostics_snapshot(loader=None, private=False):
    state = cache.get_snapshot()
    settings = get_settings()
    result = {
        'application': 'SAP Lens', 'version': VERSION,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'platform': system(), 'python_version': python_version(),
        'configuration_schema': settings.schema_version,
        'configuration_revision': settings.revision,
        'last_failed_load': getattr(loader, 'last_failed_load', None),
        'storage_available': config_dir().is_dir(),
        'backend_status': 'loading' if loader and loader.loading else 'running',
        'data_source_configured': bool(settings.data_csv_path or settings.user_csv_path),
        'cached_roles': len(state.roles),
        'last_successful_load': state.last_loaded.isoformat() if state.last_loaded else None,
        'last_successful_refresh': settings.data_lifecycle.last_successful_refresh,
    }
    from deployment import server_mode
    result['deployment_mode'] = 'server' if server_mode() else 'desktop'
    result['last_failed_load'] = result['last_failed_load'] or settings.data_lifecycle.last_failed_refresh
    sources = []
    for key, name, path, count, report in [
        ('roles', 'Role Catalogue CSV', settings.data_csv_path, len(state.roles), state.import_report),
        ('users', 'User Access CSV', settings.user_csv_path, len(state.users.users), state.users.report),
        ('sod', 'SoD Matrix CSV', settings.sod_csv_path, len(state.sod.get('records', [])), state.sod.get('report', {})),
    ]:
        loaded_path = state.loaded_sources.get(key, '')
        attempt = getattr(loader, 'source_attempts', {}).get(key, {}) if loader else {}
        source = dict(enabled=settings.features.user_role_mapping if key == 'users' else True, id=key, name=name, configured=bool(path), loaded=bool(loaded_path),
                      records=count, assignments=state.users.report.get('assignments', 0) if key == 'users' else report.get('transaction_assignments', 0),
                      last_successful_load=state.last_loaded.isoformat() if loaded_path and state.last_loaded else None,
                      availability=attempt.get('error') if attempt.get('path') == path and path else 'available_at_last_load' if loaded_path and loaded_path == path else 'not_checked',
                      error=attempt.get('error'), loading=bool(loader and loader.loading and path))
        reference = settings.data_lifecycle.sources.get(key)
        from csv_lifecycle import private_path
        try: snapshot_available = bool(reference and reference.path == path and private_path('snapshots',reference.snapshot).is_file() and attempt.get('error') != 'snapshot')
        except OSError: snapshot_available = False
        source.update(mode=getattr(settings.source_modes,key), snapshot_available=snapshot_available,
                      last_checked=reference.checked_at if reference else None)
        if reference and reference.path == path:
            source['last_successful_load'] = reference.imported_at
        if private:
            source.update(configured_path=path, loaded_path=loaded_path, attempted_path=attempt.get('path', ''))
        sources.append(source)
    from routers.employees import directory_status
    result['employee_directory'] = directory_status(private=private)
    directory = result['employee_directory']
    attempt = getattr(loader, 'source_attempts', {}).get('employees', {}) if loader else {}
    employee_source = dict(id='employees', name='Employee Directory CSV', enabled=directory['enabled'],
                          mode=settings.source_modes.employees, configured=directory['configured'], loaded=directory['loaded'],
                          records=directory['report'].get('records',0), assignments=0,
                          snapshot_available=directory['persisted'], last_successful_load=directory['report'].get('imported_at'),
                          availability=attempt.get('error') or ('available_at_last_load' if directory['loaded'] else 'not_checked'),
                          error=attempt.get('error') if directory['enabled'] else None,
                          loading=bool(loader and loader.loading and settings.employee_csv_path),
                          dependency=directory['operational_status'])
    reference=settings.data_lifecycle.sources.get('employees')
    employee_source['last_checked']=reference.checked_at if reference and reference.path==settings.employee_csv_path else None
    if private:
        employee_source.update(configured_path=settings.employee_csv_path, loaded_path=store_path(directory, settings), attempted_path=attempt.get('path',''))
    sources.append(employee_source)
    result['sources'] = sources
    from csv_lifecycle import history
    result['refresh_history'] = history()
    if not private:
        result['refresh_history'] = [{k:v for k,v in item.items() if k != 'id'} for item in result['refresh_history']]
    if private:
        result['data_source'] = settings.data_csv_path
        result['application_directory'] = str(config_dir())
    return result


def store_path(directory, settings):
    return settings.employee_csv_path if directory['loaded'] else ''
