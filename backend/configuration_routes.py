"""Application configuration, branding and staged analysis previews."""
import base64
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import Field

import cache
from config import get_settings, save_configuration, configuration_notice, config_dir
from config_models import AppConfig, StrictModel, ClassificationProfile, ImportProfile, ICONS
from classification import Classifier, classification_preview
from module_registry import REGISTRY, resolve_module, registry_list
from branding import image_from_path, logo_bytes
from daemon_tasks import daemon_call
from csv_import import CsvImport
from portable_config import PortableConfig, export_configuration, read_portable


def validate_configuration(config,current=None):
    if any(key not in REGISTRY for key in config.module_overrides):
        raise ValueError('Module overrides must use a stable registry identifier.')
    for profile in config.classification_profiles:
        Classifier(profile)
        if any(d.module_id and d.module_id not in REGISTRY for d in profile.domains):
            raise ValueError('Domain module mappings must use a stable registry identifier.')
    if config.logo_id and logo_bytes(config.logo_id) is None and (current is None or config.logo_id!=current.logo_id):
        raise ValueError('The selected logo is missing or invalid. Choose another image or restore the default.')


class ImportPreview(StrictModel):
    data_csv_path: str = Field(min_length=1,max_length=4096)
    profile: ImportProfile | None = None


class ClassificationPreview(StrictModel):
    profile: ClassificationProfile
    test_role: str | None = Field(default=None,max_length=512)


class LogoSelection(StrictModel):
    path: str = Field(min_length=1,max_length=4096)


class ThemeSelection(StrictModel):
    theme: str


def configuration_router(loader):
    router = APIRouter(prefix='/api',tags=['Configuration'])

    async def apply(config, expected):
        try:
            current = get_settings()
            validate_configuration(config,current)
            if config.revision != current.revision or expected != current.revision:
                raise HTTPException(409,'Settings changed. Reload before applying your edits.')
            analysis_fields = ['data_csv_path','import_profiles','active_import','classification_profiles','active_classification','module_overrides']
            changed = any(getattr(config,k) != getattr(current,k) for k in analysis_fields)
            # Profile versions increase automatically on content changes.
            for field in ['import_profiles','classification_profiles']:
                old = {p.id:p for p in getattr(current,field)}
                for p in getattr(config,field):
                    if p.id in old and p.model_dump(exclude={'version'}) != old[p.id].model_dump(exclude={'version'}):
                        p.version = max(p.version,old[p.id].version+1)
            if changed and config.data_csv_path:
                await loader.load(config.data_csv_path, configuration=config.model_copy(update={'revision':expected+1}), commit=lambda:save_configuration(config,expected))
            else:
                if changed and not config.data_csv_path: loader.cancel()
                save_configuration(config,expected)
                if changed: cache.clear_cache()
                if not config.data_csv_path: loader.error = 'Choose a SAP role CSV in Settings.'
            return read_config()
        except HTTPException: raise
        except (OSError,ValueError):
            raise HTTPException(400,'Configuration could not be applied. Validate profiles, file access, logo and current revision; previous settings remain intact.')

    @router.get('/diagnostics')
    def diagnostics():
        from diagnostics import diagnostics_snapshot
        return diagnostics_snapshot(loader, private=True)

    @router.get('/diagnostics/export')
    def diagnostics_export():
        from diagnostics import diagnostics_snapshot
        return diagnostics_snapshot(loader)

    @router.get('/configuration')
    def read_config():
        return {'settings':get_settings().model_dump(), 'notice':configuration_notice(),
                'loading':loader.loading, 'error':loader.error, 'analysis':cache.get_snapshot().analysis}

    @router.post('/configuration')
    async def write_config(config: AppConfig):
        return await apply(config,config.revision)

    @router.post('/configuration/theme')
    async def theme(request: ThemeSelection):
        if configuration_notice() and 'invalid' in configuration_notice():
            raise HTTPException(409,'Review configuration recovery in Settings before saving preferences.')
        if request.theme not in {'system','dark','light'}: raise HTTPException(400,'Choose a supported theme.')
        current = get_settings().model_copy(deep=True)
        current.theme = request.theme
        return await apply(current,current.revision)

    @router.post('/data/cancel')
    async def cancel_data():
        loader.cancel()
        return {'status':'canceled'}

    @router.post('/configuration/export')
    def export(include_private: bool = False):
        return export_configuration(get_settings(),include_private)

    @router.post('/configuration/import')
    async def import_config(package: PortableConfig):
        try: candidate = read_portable(package,get_settings().data_csv_path)
        except (OSError,ValueError): raise HTTPException(400,'Invalid configuration package or logo; nothing was applied.')
        candidate.revision = get_settings().revision
        return await apply(candidate,candidate.revision)

    @router.post('/configuration/reset')
    async def reset():
        current = get_settings()
        return await apply(AppConfig(revision=current.revision),current.revision)

    @router.get('/registry/modules')
    def registry():
        return {'modules':registry_list(get_settings().module_overrides),'icons':ICONS,
                'sources':['https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE','https://help.sap.com/docs/SAP_ERP'],
                'reference_note':'Stable SAP area terminology; products/components/submodules are distinguished. Live source retrieval must be verified separately when network access permits.'}

    @router.post('/classification/preview')
    async def preview_classification(request: ClassificationPreview):
        state = cache.get_snapshot()
        if len(state.roles)>100_000: raise HTTPException(400,'Preview is limited to 100,000 composite roles.')
        records = [dict(agr_name=r.agr_name,source_module=(r.source_modules or [None])[0],text=r.text) for r in state.roles.values()]
        current = {r.agr_name:dict(module_id=r.function_key,domain_id=r.domain_id) for r in state.roles.values()}
        try: return await daemon_call(classification_preview,request.profile,records,current,request.test_role)
        except ValueError: raise HTTPException(400,'Invalid or overly expensive classification rules. Check expressions and simplify them.')

    @router.post('/import/headers')
    async def import_headers(request: ImportPreview):
        profile = request.profile or next(p for p in get_settings().import_profiles if p.id == get_settings().active_import)
        try: return await daemon_call(CsvImport(Path(request.data_csv_path),profile).inspect_header)
        except HTTPException: raise
        except Exception: raise HTTPException(400,'Could not inspect the CSV header. Check path, encoding and delimiter.')

    @router.post('/import/preview')
    async def preview_import(request: ImportPreview):
        config = get_settings().model_copy(deep=True)
        if request.profile:
            config.import_profiles = [request.profile]; config.active_import = request.profile.id
        try: return (await daemon_call(cache.build_cache,request.data_csv_path,config)).import_report
        except HTTPException: raise
        except Exception:
            # All CSV/encoding/parser failures are user-facing validation failures.
            raise HTTPException(400,'Import preview failed. Check the absolute path, encoding, delimiter, mappings and required AGR_NAME column.') from None

    @router.post('/branding/preview')
    async def preview_logo(request: LogoSelection):
        try: return await daemon_call(image_from_path,request.path)
        except (OSError,ValueError): raise HTTPException(400,'Choose a valid PNG, JPEG or WebP up to 2 MB and 4096 pixels per side. SVG is not supported.')

    @router.get('/branding/logo')
    def logo():
        data = logo_bytes(get_settings().logo_id)
        if not data: raise HTTPException(404,'No valid custom logo; use the SAP Lens default.')
        return {'data_url':'data:image/png;base64,'+base64.b64encode(data).decode()}

    return router
