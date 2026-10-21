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
        'data_source_configured': bool(settings.data_csv_path),
        'cached_roles': len(state.roles),
        'last_successful_load': state.last_loaded.isoformat() if state.last_loaded else None,
    }
    if private:
        result['data_source'] = settings.data_csv_path
        result['application_directory'] = str(config_dir())
    return result
