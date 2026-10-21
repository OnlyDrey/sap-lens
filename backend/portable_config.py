"""Portable JSON packages; raw data/paths are never included, private fields opt in."""
import base64
import binascii
from typing import Literal
from pydantic import Field
from branding import logo_bytes, stage_image
from config_models import AppConfig, StrictModel


class PortableConfig(StrictModel):
    format: Literal['SAP Lens configuration'] = 'SAP Lens configuration'
    package_version: Literal[1] = 1
    settings: AppConfig
    logo_base64: str | None = Field(default=None, max_length=3_000_000)


def export_configuration(config: AppConfig, include_private: bool = False):
    defaults = AppConfig()
    exported = config.model_copy(deep=True) if include_private else defaults.model_copy(update={'theme':config.theme, 'theme_colors':config.theme_colors.model_copy(deep=True)})
    exported.data_csv_path = ''
    exported.revision = 0
    image = logo_bytes(exported.logo_id) if include_private else None
    if not image: exported.logo_id = None
    return PortableConfig(settings=exported, logo_base64=base64.b64encode(image).decode() if image else None).model_dump()


def read_portable(package: PortableConfig, local_path: str):
    config = package.settings.model_copy(deep=True)
    if config.data_csv_path: raise ValueError('Portable packages must not contain filesystem paths.')
    if package.logo_base64:
        try: data = base64.b64decode(package.logo_base64, validate=True)
        except (ValueError,binascii.Error) as exc: raise ValueError('Logo encoding is invalid.') from exc
        staged = stage_image(data)
        config.logo_id = staged['logo_id']
    elif config.logo_id:
        raise ValueError('A portable logo reference must include its validated image.')
    config.data_csv_path = local_path
    return config
