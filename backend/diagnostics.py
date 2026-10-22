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
        'backend_status': 'loading' if loader and loader.loading else 'running',
        'data_source_configured': bool(settings.data_csv_path or settings.user_csv_path),
        'cached_roles': len(state.roles),
        'last_successful_load': state.last_loaded.isoformat() if state.last_loaded else None,
    }
    sources = []
    for key, name, path, count, report in [
        ('roles', 'Role Catalogue CSV', settings.data_csv_path, len(state.roles), state.import_report),
        ('users', 'User Access CSV', settings.user_csv_path, len(state.users.users), state.users.report),
    ]:
        loaded_path = state.loaded_sources.get(key, '')
        attempt = getattr(loader, 'source_attempts', {}).get(key, {}) if loader else {}
        source = dict(id=key, name=name, configured=bool(path), loaded=bool(loaded_path),
                      records=count, assignments=state.users.report.get('assignments', 0) if key == 'users' else report.get('transaction_assignments', 0),
                      last_successful_load=state.last_loaded.isoformat() if loaded_path and state.last_loaded else None,
                      availability=attempt.get('error') if attempt.get('path') == path and path else 'available_at_last_load' if loaded_path and loaded_path == path else 'not_checked',
                      error=attempt.get('error'), loading=bool(loader and loader.loading and path))
        if private:
            source.update(configured_path=path, loaded_path=loaded_path, attempted_path=attempt.get('path', ''))
        sources.append(source)
    result['sources'] = sources
    if private:
        result['data_source'] = settings.data_csv_path
        result['application_directory'] = str(config_dir())
    return result
