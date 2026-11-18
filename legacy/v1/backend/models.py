"""Pydantic v2 data models for SAP Role Checker."""
from pydantic import BaseModel


class AssignmentSource(BaseModel):
    child_agr: str | None = None
    parent_agr: str | None = None
    effective_role: str | None = None


class RoleRelationship(AssignmentSource):
    pass


class TCode(BaseModel):
    tcode: str
    ttext: str | None = None
    assignment_sources: list[AssignmentSource] = []
    alternate_texts: list[str] = []


class SingleRole(BaseModel):
    assignment_kind: str = 'child'
    child_agr: str
    child_agr_text: str | None = None
    tcodes: list[TCode] = []
    function_key: str = 'UNCLASSIFIED'
    module_name: str = 'Unclassified'
    alternate_descriptions: list[str] = []


class RoleSummary(BaseModel):
    agr_name: str
    text: str | None = None
    function_key: str | None = None
    module_name: str | None = None
    tcode_count: int
    single_role_count: int = 0
    # Populated when the role was found via T-code search.
    # Contains the T-codes that matched the search query.
    matching_tcodes: list[str] = []
    module_ambiguous: bool = False
    source_modules: list[str] = []


class RoleDetail(RoleSummary):
    agr_name: str
    text: str | None = None
    function_key: str | None = None
    module_name: str | None = None
    tcode_count: int
    single_roles: list[SingleRole] = []
    relationships: list[RoleRelationship] = []
    alternate_descriptions: list[str] = []
    analysis: dict = {}


class ModuleInfo(BaseModel):
    function_key: str
    module_name: str
    icon: str = 'Hash'
    color: str = '#64748b'
    enabled: bool = True
    category: str = 'module'


class PairwiseOverlap(BaseModel):
    role_a: str
    role_b: str
    shared_count: int


class SingleRoleInfo(BaseModel):
    function_key: str = 'UNCLASSIFIED'
    module_name: str = 'Unclassified'
    child_agr: str
    child_agr_text: str | None = None
    tcode_count: int


class ComparisonRole(BaseModel):
    agr_name: str
    text: str | None = None
    function_key: str | None = None
    module_name: str | None = None
    tcode_count: int
    single_role_count: int = 0
    exclusive_single_roles: list[SingleRoleInfo] = []
    unique_tcodes: list[TCode] = []


class ComparisonResult(BaseModel):
    analysis: dict = {}
    roles: list[ComparisonRole]
    shared_single_roles: list[SingleRoleInfo] = []
    pairwise_single_overlaps: list[PairwiseOverlap] = []
    shared_tcodes: list[TCode] = []
    pairwise_overlaps: list[PairwiseOverlap] = []
