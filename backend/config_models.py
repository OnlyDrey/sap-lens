"""Versioned, organization-neutral configuration contracts."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = 2
ICONS = ['DollarSign', 'BarChart2', 'Package', 'Wrench', 'Users', 'TrendingUp', 'Cog',
         'FolderKanban', 'CheckCircle', 'Server', 'Warehouse', 'Layers', 'Shield', 'Database',
         'Truck', 'Building2', 'Globe', 'Code', 'FileText', 'Leaf', 'Hash']


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', validate_default=True)

    @field_validator('id', check_fields=False)
    @classmethod
    def safe_identifier(cls,value):
        if value.casefold() in {'__proto__','prototype','constructor'}:
            raise ValueError('Choose an identifier that is not a reserved object key.')
        return value


class Organization(StrictModel):
    name: str = Field(default='Example Inc.', min_length=1, max_length=120)
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


class Domain(StrictModel):
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,40}$')
    label: str = Field(min_length=1, max_length=100)
    module_id: str | None = Field(default=None, max_length=30)


class Rule(StrictModel):
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,40}$')
    kind: Literal['prefix', 'exact', 'contains', 'regex'] = 'prefix'
    pattern: str = Field(min_length=1, max_length=256)
    domain_id: str
    priority: int = Field(default=100, ge=0, le=10000)
    case_sensitive: bool = False


class ClassificationProfile(StrictModel):
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,40}$')
    name: str = Field(min_length=1, max_length=100)
    version: int = Field(default=1, ge=1)
    mode: Literal['legacy', 'generic', 'custom'] = 'generic'
    domains: list[Domain] = Field(default_factory=list, max_length=100)
    rules: list[Rule] = Field(default_factory=list, max_length=64)
    overrides: dict[str, str] = Field(default_factory=dict, max_length=2000)
    fallback_domain: str | None = None

    @model_validator(mode='after')
    def consistent(self):
        domain_ids = {d.id for d in self.domains}
        if len(domain_ids) != len(self.domains) or len({r.id for r in self.rules}) != len(self.rules):
            raise ValueError('Domain and rule identifiers must be unique.')
        targets = [r.domain_id for r in self.rules] + list(self.overrides.values())
        if self.fallback_domain: targets.append(self.fallback_domain)
        if any(target not in domain_ids for target in targets):
            raise ValueError('A rule or override references an unknown domain.')
        if any(len(role) > 512 for role in self.overrides):
            raise ValueError('Role override names are too long.')
        if self.mode != 'custom' and (self.domains or self.rules or self.overrides or self.fallback_domain):
            raise ValueError('Custom rules require a Custom profile.')
        return self


FIELDS = ['FUNCTION_KEY', 'AGR_NAME', 'TEXT', 'CHILD_AGR', 'CHILD_AGR_TEXT',
          'PARENT_AGR', 'Effective_Role', 'TCODE', 'TTEXT']


class ImportProfile(StrictModel):
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,40}$')
    name: str = Field(min_length=1, max_length=100)
    version: int = Field(default=1, ge=1)
    mapping: dict[str, str] = Field(default_factory=dict, max_length=9)
    delimiter: Literal['auto', ',', ';', '\t', '|'] = 'auto'
    encoding: Literal['auto', 'utf-8-sig', 'utf-16', 'cp1252'] = 'auto'

    @field_validator('mapping')
    @classmethod
    def valid_mapping(cls, value):
        if any(key not in FIELDS or not source.strip() or len(source) > 120 for key, source in value.items()):
            raise ValueError('Column mappings must use supported canonical fields and nonempty source headers.')
        if len(set(value.values())) != len(value):
            raise ValueError('Each source column can map to only one field.')
        return value


class AppConfig(StrictModel):
    schema_version: Literal[2] = 2
    revision: int = Field(default=0, ge=0)
    data_csv_path: str = Field(default='', max_length=4096)
    organization: Organization = Field(default_factory=Organization)
    theme: Literal['system', 'dark', 'light'] = 'system'
    logo_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    module_overrides: dict[str, ModuleOverride] = Field(default_factory=dict, max_length=100)
    classification_profiles: list[ClassificationProfile] = Field(default_factory=lambda: [
        ClassificationProfile(id='legacy', name='Current / Legacy', mode='legacy'),
        ClassificationProfile(id='generic', name='Generic SAP', mode='generic'),
        ClassificationProfile(id='custom', name='Custom', mode='custom'),
    ], min_length=1, max_length=20)
    active_classification: str = 'legacy'
    import_profiles: list[ImportProfile] = Field(default_factory=lambda: [ImportProfile(id='default', name='Standard SAP CSV')], min_length=1, max_length=20)
    active_import: str = 'default'
    cors_origins: list[str] = Field(default_factory=lambda: ['http://127.0.0.1:18743', 'http://localhost:18743'], exclude=True)

    @model_validator(mode='after')
    def active_profiles_exist(self):
        for entries, active in [(self.classification_profiles, self.active_classification), (self.import_profiles, self.active_import)]:
            if len({p.id for p in entries}) != len(entries) or active not in {p.id for p in entries}:
                raise ValueError('Profile identifiers must be unique and the active profile must exist.')
        return self
