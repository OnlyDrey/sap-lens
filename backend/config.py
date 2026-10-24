"""Versioned per-user settings with migration/recovery backups and atomic writes."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
from datetime import datetime, timezone
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from config_models import AppConfig

APP_PORT = 18743
_lock = threading.RLock()
_notice: str | None = None


class BootstrapSettings(BaseSettings):
    data_csv_path: str = ''
    cors_origins: list[str] = ['http://127.0.0.1:18743', 'http://localhost:18743']
    model_config = SettingsConfigDict(env_file=Path(__file__).parent / '.env', extra='ignore')


def config_dir() -> Path:
    from deployment import server_mode, default_server_data
    if server_mode():
        directory=Path(os.environ.get('SAP_LENS_DATA_DIR',str(default_server_data()))).expanduser()
        if not directory.is_absolute(): raise ValueError('Server data directory must be absolute.')
        return directory
    if root := os.environ.get('SAP_LENS_CONFIG_DIR'):
        directory=Path(root).expanduser()
        if not directory.is_absolute(): raise ValueError('Configuration directory override must be absolute.')
        return directory
    if os.name == 'nt':
        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x1c, None, 0, buffer) == 0:
            return Path(buffer.value) / 'SAP Lens'
        return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / 'SAP Lens'
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'sap-lens'


def atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def ensure_content_file(path: Path, data: bytes, identity: str, limit: int):
    """Reuse only verified immutable bytes; repair a corrupt target atomically."""
    if len(data) > limit or hashlib.sha256(data).hexdigest() != identity:
        raise ValueError('Invalid content-addressed payload.')
    if path.exists():
        digest, count = hashlib.sha256(), 0
        with path.open('rb') as stream:
            while block := stream.read(512 * 1024):
                count += len(block)
                if count > limit: break
                digest.update(block)
        if count <= limit and digest.hexdigest() == identity:
            return
    atomic_write(path, data)


def backup_settings(reason: str):
    source = config_dir() / 'settings.json'
    if source.exists():
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
        atomic_write(config_dir() / 'configuration-backups' / f'{reason}-{stamp}.json', source.read_bytes())


def configuration_notice():
    return _notice


@lru_cache
def get_settings() -> AppConfig:
    global _notice
    with _lock:
        _notice = None
        bootstrap = BootstrapSettings()
        defaults = AppConfig(data_csv_path=bootstrap.data_csv_path, cors_origins=bootstrap.cors_origins)
        path = config_dir() / 'settings.json'
        if not path.exists(): return defaults
        try:
            if path.stat().st_size > 1_000_000: raise ValueError('Configuration is too large.')
            saved = json.loads(path.read_text(encoding='utf-8-sig'))
            if not isinstance(saved, dict): raise ValueError('Invalid configuration.')
            if 'schema_version' not in saved:
                # v1 contained only the file path. Never discard unknown fields.
                if set(saved) - {'data_csv_path'}: raise ValueError('Unknown legacy fields.')
                migrated = AppConfig(data_csv_path=saved.get('data_csv_path', ''), cors_origins=bootstrap.cors_origins)
                backup_settings('migration-v1')
                atomic_write(path, migrated.model_dump_json(indent=2).encode())
                _notice = 'File settings migrated to schema 3; the original was backed up locally.'
                return migrated
            settings = AppConfig.model_validate(saved)
            if saved.get('schema_version') == 2:
                _notice = 'Legacy classification is inactive and preserved locally. SAP areas now use CSV evidence. Original settings remain intact until you save.'
            settings.cors_origins = bootstrap.cors_origins
            return settings
        except (OSError, ValueError, TypeError, KeyError):
            _notice = 'Saved configuration is invalid or from an unsupported version. Defaults are in use; the original has not been overwritten. Restore a backup or explicitly save/reset after review.'
            return defaults


def save_configuration(settings: AppConfig, expected_revision: int | None = None) -> AppConfig:
    # Validate a fresh copy before touching any retained file.
    validated = AppConfig.model_validate(settings.model_dump())
    with _lock:
        current = get_settings()
        if expected_revision is not None and current.revision != expected_revision:
            raise ValueError('Configuration changed. Reload Settings before saving again.')
        validated.revision = current.revision + 1
        validated.cors_origins = current.cors_origins
        payload = validated.model_dump_json(indent=2).encode()
        if len(payload) > 1_000_000: raise ValueError('Configuration exceeds its one-megabyte safety limit.')
        backup_settings('before-save')
        atomic_write(config_dir() / 'settings.json', payload)
        get_settings.cache_clear()
        return get_settings()


def save_data_path(path: str) -> None:
    current = get_settings()
    save_configuration(current.model_copy(update={'data_csv_path': path}), current.revision)
