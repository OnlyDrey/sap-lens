"""Pydantic v2 data models for SAP Role Checker."""
from pydantic import BaseModel


class TCode(BaseModel):
    tcode: str
    ttext: str | None = None


class SingleRole(BaseModel):
    child_agr: str
    child_agr_text: str | None = None
    tcodes: list[TCode] = []


class SingleRoleInfo(BaseModel):
    child_agr: str
    child_agr_text: str | None = None
    tcode_count: int


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


class RoleDetail(BaseModel):
    agr_name: str
    text: str | None = None
    function_key: str | None = None
    module_name: str | None = None
    tcode_count: int
    single_roles: list[SingleRole] = []


class ModuleInfo(BaseModel):
    function_key: str
    module_name: str


class PairwiseOverlap(BaseModel):
    role_a: str
    role_b: str
    shared_count: int


class SingleRoleInfo(BaseModel):
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
    roles: list[ComparisonRole]
    shared_single_roles: list[SingleRoleInfo] = []
    pairwise_single_overlaps: list[PairwiseOverlap] = []
    shared_tcodes: list[TCode] = []
    pairwise_overlaps: list[PairwiseOverlap] = []