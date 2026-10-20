"""Per-user application settings; no configuration is written beside the executable."""
import json
import logging
import os
import tempfile
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_PORT = 18743


def config_dir() -> Path:
    if root := os.environ.get('SAP_LENS_CONFIG_DIR'):
        return Path(root)
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / 'SAP Lens'
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'sap-lens'


class Settings(BaseSettings):
    data_csv_path: str = ''
    cors_origins: list[str] = [f'http://127.0.0.1:{APP_PORT}', f'http://localhost:{APP_PORT}']
    model_config = SettingsConfigDict(env_file=Path(__file__).parent / '.env', extra='ignore')


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    path = config_dir() / 'settings.json'
    if path.exists():
        try:
            saved = json.loads(path.read_text(encoding='utf-8'))
            settings = Settings.model_validate({**settings.model_dump(), 'data_csv_path': saved['data_csv_path']})
        except (OSError, ValueError, KeyError, TypeError):
            logging.getLogger(__name__).warning('Saved settings are unreadable; using bootstrap defaults.')
    return settings


def save_data_path(path: str) -> None:
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=directory, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump({'data_csv_path': path}, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / 'settings.json')
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    get_settings.cache_clear()
