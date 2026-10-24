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


class ThemePalette(StrictModel):
    primary: str = Field(default='#1a003b', pattern=r'^#[0-9a-fA-F]{6}$')
    accent: str = Field(default='#7c85d4', pattern=r'^#[0-9a-fA-F]{6}$')
    background: str = Field(default='#0d0d1a', pattern=r'^#[0-9a-fA-F]{6}$')
    surface: str = Field(default='#111827', pattern=r'^#[0-9a-fA-F]{6}$')
    text: str = Field(default='#f1f5f9', pattern=r'^#[0-9a-fA-F]{6}$')

    @model_validator(mode='after')
    def readable_text(self):
        from theme_colors import contrast
        if min(contrast(self.text, self.background), contrast(self.text, self.surface)) < 4.5:
            raise ValueError('Primary text must meet WCAG AA contrast (4.5:1) against both application and card backgrounds.')
        return self


class ThemePreset(StrictModel):
    name: str = Field(min_length=1, max_length=60)
    mode: Literal['light', 'dark']
    colors: ThemePalette


class ThemeColors(StrictModel):
    dark: ThemePalette = Field(default_factory=ThemePalette)
    light: ThemePalette = Field(default_factory=lambda: ThemePalette(primary='#182c53', accent='#515793', background='#f0f2f7', surface='#ffffff', text='#182c53'))
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


class AppConfig(StrictModel):
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
