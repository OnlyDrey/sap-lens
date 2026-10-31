"""Versioned, organization-neutral configuration contracts."""
from typing import Literal, ClassVar
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = 3
from lucide_catalog import ICONS


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', validate_default=True)

    @field_validator('id', check_fields=False)
    @classmethod
    def safe_identifier(cls,value):
        if value.casefold() in {'__proto__','prototype','constructor'}:
            raise ValueError('Choose an identifier that is not a reserved object key.')
        return value


class Organization(StrictModel):
    name: str = Field(default='Example Inc.', min_length=0, max_length=120)
    platform: Literal['SAP S/4HANA', 'SAP ECC', 'Other / Custom'] = 'SAP S/4HANA'
    custom_platform: str = Field(default='', max_length=80)
    system_id: str = Field(default='DEMO', max_length=20)
    client: str = Field(default='100', max_length=10)
    description: str = Field(default='Example System', max_length=200)
    footer: str = Field(default='', max_length=240)


class ModuleOverride(StrictModel):
    display_name: str | None = Field(default=None, max_length=100)
    icon: str | None = None
    color: str | None = Field(default=None, pattern=r'^#[0-9a-fA-F]{6}$')
    enabled: bool = True

    @field_validator('icon')
    @classmethod
    def safe_icon(cls, value):
        if value is not None and value not in ICONS:
            raise ValueError('Choose a supported icon.')
        return value


FIELDS = ['FUNCTION_KEY', 'AGR_NAME', 'TEXT', 'CHILD_AGR', 'CHILD_AGR_TEXT',
          'PARENT_AGR', 'Effective_Role', 'TCODE', 'TTEXT']


USER_FIELDS = ['USERNAME', 'ROLE_NAME', 'USER_GROUP', 'FIRST_NAME', 'LAST_NAME', 'EMAIL',
               'USER_VALID_FROM', 'USER_VALID_TO', 'ROLE_VALID_FROM', 'ROLE_VALID_TO', 'USER_LOCKED', 'USER_TYPE']


class ImportProfile(StrictModel):
    fields: ClassVar[list[str]] = FIELDS
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,40}$')
    name: str = Field(min_length=1, max_length=100)
    version: int = Field(default=1, ge=1)
    mapping: dict[str, str] = Field(default_factory=dict, max_length=12)
    delimiter: Literal['auto', ',', ';', '\t', '|'] = 'auto'
    encoding: Literal['auto', 'utf-8-sig', 'utf-16', 'cp1252'] = 'auto'

    @field_validator('mapping')
    @classmethod
    def valid_mapping(cls, value):
        if any(key not in cls.fields or not source.strip() or len(source) > 120 for key, source in value.items()):
            raise ValueError('Column mappings must use supported canonical fields and nonempty source headers.')
        if len(set(value.values())) != len(value):
            raise ValueError('Each source column can map to only one field.')
        return value


class UserImportProfile(ImportProfile):
    fields: ClassVar[list[str]] = USER_FIELDS


SOD_FIELDS = ['RISK', 'CRITICITY', 'TYPE', 'TEXT', 'ACTVT1', 'ACTVT2', 'ACTIVITY_SLOT', 'ACTIVITY', 'TCODE', 'TTEXT']


class SodImportProfile(ImportProfile):
    """Format and optional header mapping of the SoD matrix CSV. The documented columns are fixed; a mapping only says which source header carries each one."""
    fields: ClassVar[list[str]] = SOD_FIELDS


class ThemePalette(StrictModel):
    primary: str = Field(default='#1a003b', pattern=r'^#[0-9a-fA-F]{6}$')
    accent: str = Field(default='#7c85d4', pattern=r'^#[0-9a-fA-F]{6}$')
    secondary: str = Field(default='#2a3156', pattern=r'^#[0-9a-fA-F]{6}$')
    background: str = Field(default='#0d0d1a', pattern=r'^#[0-9a-fA-F]{6}$')
    surface: str = Field(default='#111827', pattern=r'^#[0-9a-fA-F]{6}$')
    text: str = Field(default='#f1f5f9', pattern=r'^#[0-9a-fA-F]{6}$')

    @model_validator(mode='before')
    @classmethod
    def legacy_secondary(cls, value):
        # Palettes saved before Secondary Color existed get a readable tint instead of failing to load.
        if isinstance(value, dict) and 'secondary' not in value:
            from theme_colors import derive_secondary
            value = {**value, 'secondary': derive_secondary(value)}
        return value

    @model_validator(mode='after')
    def readable_text(self):
        from theme_colors import contrast
        if min(contrast(self.text, self.background), contrast(self.text, self.surface)) < 4.5:
            raise ValueError('Primary text must meet WCAG AA contrast (4.5:1) against both application and card backgrounds.')
        if contrast(self.text, self.secondary) < 4.5:
            raise ValueError('Primary text must meet WCAG AA contrast (4.5:1) against the secondary color used by secondary buttons and selected controls.')
        return self


class ThemePreset(StrictModel):
    name: str = Field(min_length=1, max_length=60)
    mode: Literal['light', 'dark']
    colors: ThemePalette


class ThemeColors(StrictModel):
    dark: ThemePalette = Field(default_factory=ThemePalette)
    light: ThemePalette = Field(default_factory=lambda: ThemePalette(primary='#182c53', accent='#515793', secondary='#e1e5f2', background='#f0f2f7', surface='#ffffff', text='#182c53'))
    custom_presets: list[ThemePreset] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def unique_names(self):
        names = [preset.name.strip().casefold() for preset in self.custom_presets]
        if any(not name for name in names) or len(names) != len(set(names)):
            raise ValueError('Custom theme names must be nonempty and unique.')
        return self


class FeatureSettings(StrictModel):
    user_role_mapping: bool = True
    employee_directory: bool = False
    sod: bool = False


class SourceModes(StrictModel):
    roles: Literal['static', 'dynamic'] = 'dynamic'
    users: Literal['static', 'dynamic'] = 'dynamic'
    employees: Literal['static', 'dynamic'] = 'static'
    sod: Literal['static', 'dynamic'] = 'static'


class SourceSnapshot(StrictModel):
    snapshot: str = Field(pattern=r'^[a-f0-9]{64}$')
    path: str = Field(max_length=4096)
    imported_at: str = Field(max_length=40)
    checked_at: str = Field(max_length=40)


class RefreshMetadata(StrictModel):
    timestamp: str = Field(max_length=40)
    operation: Literal['startup', 'import', 'refresh']
    status: Literal['changed', 'unchanged', 'partial', 'failed']
    checked: int = Field(ge=0, le=4)
    updated: int = Field(ge=0, le=4)
    unchanged: int = Field(ge=0, le=4)
    failed: int = Field(ge=0, le=4)
    skipped: int = Field(ge=0, le=4)


class DataLifecycle(StrictModel):
    sod_history: list[SourceSnapshot] = Field(default_factory=list, max_length=1000)
    history_metadata: dict[str, RefreshMetadata] = Field(default_factory=dict, max_length=5)
    last_successful_refresh: str | None = Field(default=None, max_length=40)
    last_failed_refresh: str | None = Field(default=None, max_length=40)
    sources: dict[Literal['roles', 'users', 'sod'], SourceSnapshot] = Field(default_factory=dict, max_length=3)
    history: list[str] = Field(default_factory=list, max_length=5)

    @field_validator('history')
    @classmethod
    def safe_reports(cls, values):
        import re
        if any(not re.fullmatch(r'[a-f0-9]{64}', v) for v in values):
            raise ValueError('Invalid refresh report reference.')
        return values

    @field_validator('history_metadata')
    @classmethod
    def safe_summary_keys(cls, values):
        cls.safe_reports(list(values))
        return values


class DesktopPreferences(StrictModel):
    close_to_tray: bool = False
    run_at_signin: bool = False
    start_minimized: bool = False

    @model_validator(mode='after')
    def usable_background_mode(self):
        if self.start_minimized and not self.close_to_tray:
            raise ValueError('Start minimized requires tray mode.')
        return self


class RefreshSchedule(StrictModel):
    """Scheduled background refresh; the daily time or the cron expression applies depending on the mode."""
    enabled: bool = False
    mode: Literal['daily', 'cron'] = 'daily'
    time: str = Field(default='06:00', max_length=5)
    cron: str = Field(default='0 6 * * *', max_length=100)
    timezone: str = Field(default='local', max_length=64, pattern=r'^(local|UTC|[A-Za-z0-9_+\-]{1,32}(/[A-Za-z0-9_+\-]{1,32}){0,2})$')

    @property
    def expression(self):
        import cron_schedule as schedule
        return schedule.daily_cron(self.time) if self.mode == 'daily' else self.cron.strip()

    @model_validator(mode='after')
    def readable_schedule(self):
        import cron_schedule as schedule
        schedule.parse_cron(self.expression)
        return self


class AppConfig(StrictModel):
    desktop: DesktopPreferences = Field(default_factory=DesktopPreferences)
    refresh_schedule: RefreshSchedule = Field(default_factory=RefreshSchedule)
    source_modes: SourceModes = Field(default_factory=SourceModes)
    data_lifecycle: DataLifecycle = Field(default_factory=DataLifecycle)
    unlicensed_user_groups: list[str] = Field(default_factory=lambda: ['UNLICENSED'], max_length=100)

    @field_validator('unlicensed_user_groups')
    @classmethod
    def review_groups(cls, values):
        values = [v.strip() for v in values]
        if any(not v or len(v) > 120 for v in values) or len({v.casefold() for v in values}) != len(values):
            raise ValueError('Unlicensed user groups must be nonempty, unique and at most 120 characters.')
        return values

    employee_snapshot_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    employee_csv_path: str = Field(default='', max_length=4096)
    sod_csv_path: str = Field(default='', max_length=4096)
    sod_import: SodImportProfile = Field(default_factory=lambda: SodImportProfile(id='default', name='Standard SoD matrix'))
    features: FeatureSettings = Field(default_factory=FeatureSettings)
    schema_version: Literal[3] = 3
    user_csv_path: str = Field(default='', max_length=4096)
    user_import_profiles: list[UserImportProfile] = Field(default_factory=lambda: [UserImportProfile(id='default', name='Standard SAP user CSV')], min_length=1, max_length=20)
    active_user_import: str = 'default'
    legacy_classification: dict | None = None
    revision: int = Field(default=0, ge=0)
    data_csv_path: str = Field(default='', max_length=4096)
    organization: Organization = Field(default_factory=Organization)
    theme: Literal['system', 'dark', 'light'] = 'dark'
    theme_colors: ThemeColors = Field(default_factory=ThemeColors)
    logo_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    module_overrides: dict[str, ModuleOverride] = Field(default_factory=dict, max_length=100)
    import_profiles: list[ImportProfile] = Field(default_factory=lambda: [ImportProfile(id='default', name='Standard SAP CSV')], min_length=1, max_length=20)
    active_import: str = 'default'
    cors_origins: list[str] = Field(default_factory=lambda: ['http://127.0.0.1:18743', 'http://localhost:18743'], exclude=True)

    @model_validator(mode='before')
    @classmethod
    def compatibility(cls, value):
        if not isinstance(value, dict): return value
        value = dict(value)
        if value.get('schema_version', 3) == 2: value['schema_version'] = 3
        # SoD becomes a manual feature. Installations that already use a SoD source keep working; a source never enables it later.
        features = value.get('features')
        if not isinstance(features, dict) or 'sod' not in features:
            lifecycle = value.get('data_lifecycle')
            sources = lifecycle.get('sources', {}) if isinstance(lifecycle, dict) else getattr(lifecycle, 'sources', {})
            existing = bool(value.get('sod_csv_path') or 'sod' in (sources or {}))
            if isinstance(features, dict) or features is None:
                value['features'] = {**(features or {}), 'sod': existing}
        archived = {key: value.pop(key) for key in ('classification_profiles', 'active_classification') if key in value}
        if archived: value['legacy_classification'] = archived
        # Deleting an active custom preset safely restores the source's built-in default.
        for field, active, kind, label in [('import_profiles','active_import',ImportProfile,'Standard SAP CSV'),
                                         ('user_import_profiles','active_user_import',UserImportProfile,'Standard SAP user CSV')]:
            entries = list(value.get(field, []))
            if entries and not any((p.get('id') if isinstance(p,dict) else p.id) == 'default' for p in entries):
                entries.insert(0, kind(id='default',name=label))
                value[field] = entries
            if entries and value.get(active, 'default') not in {(p.get('id') if isinstance(p,dict) else p.id) for p in entries}:
                value[active] = 'default'
        return value

    @model_validator(mode='after')
    def active_profiles_exist(self):
        for entries, active in [(self.import_profiles, self.active_import), (self.user_import_profiles, self.active_user_import)]:
            if len({p.id for p in entries}) != len(entries) or active not in {p.id for p in entries}:
                raise ValueError('Import preset identifiers must be unique and the active preset must exist.')
        return self
