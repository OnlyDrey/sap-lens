"""Roles router -- list, search, filter, T-code search, detail."""
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
import cache
from models import RoleSummary, RoleDetail

router = APIRouter(prefix="/api/roles", tags=["Roles"])

# ---------------------------------------------------------------------------
# Lazy reverse T-code index
# Built on first T-code search request, then cached for the process lifetime.
# Structure: { "FB01": ["ZC:FI:...", "ZC:CO:..."], "VA01": [...], ... }
# ---------------------------------------------------------------------------
_TCODE_IDX: Optional[dict[str, list[str]]] = None


def _get_tcode_index() -> dict[str, list[str]]:
    """Return the T-code -> [agr_name] index, building it on first call."""
    global _TCODE_IDX
    if _TCODE_IDX is not None:
        return _TCODE_IDX

    idx: dict[str, list[str]] = {}
    for role in cache.get_all_roles():
        detail = cache.get_role_detail(role.agr_name)
        if detail is None:
            continue
        for sr in detail.single_roles:
            for tc in sr.tcodes:
                key = tc.tcode.upper()
                if key not in idx:
                    idx[key] = []
                if role.agr_name not in idx[key]:
                    idx[key].append(role.agr_name)

    _TCODE_IDX = idx
    total = sum(len(v) for v in idx.values())
    print(f"[cache] T-code index built: {len(idx):,} unique T-codes, {total:,} role assignments")
    return _TCODE_IDX


def _invalidate_tcode_index() -> None:
    """Call when the role cache is refreshed."""
    global _TCODE_IDX
    _TCODE_IDX = None


# ---------------------------------------------------------------------------
# GET /api/roles
# ---------------------------------------------------------------------------
@router.get("", response_model=list[RoleSummary])
def list_roles(
    function_key: Optional[str] = Query(None, description="Filter by module code, e.g. FI"),
    search: Optional[str] = Query(None, description="Search role name or description"),
    tcode: Optional[str] = Query(None, description="Find all roles containing this T-code"),
) -> list[RoleSummary]:
    """
    Return role summaries.
    - function_key : filter by SAP module (CO, FI, MM ...)
    - search       : free-text match on role name / description / AGR_NAME
    - tcode        : exact T-code lookup -- returns roles that contain this transaction
                     Matching T-codes are returned in the matching_tcodes field.
    """
    all_roles: list[RoleSummary] = cache.get_all_roles()

    # Enrich single_role_count (cache may not set it)
    for role in all_roles:
        if not role.single_role_count:
            detail = cache.get_role_detail(role.agr_name)
            if detail is not None:
                role.single_role_count = len(detail.single_roles)

    # Module filter (applied regardless of search mode)
    if function_key:
        all_roles = [r for r in all_roles if r.function_key == function_key]

    # ---- T-code search -------------------------------------------------------
    if tcode and tcode.strip():
        query = tcode.strip().upper()
        idx = _get_tcode_index()

        # Exact match first; also catch partial prefix matches (e.g. "ME3" -> ME3N, ME33K ...)
        matching_agr: set[str] = set()
        matched_keys: list[str] = []

        for key, agr_names in idx.items():
            if key == query or key.startswith(query):
                matching_agr.update(agr_names)
                matched_keys.append(key)

        result: list[RoleSummary] = []
        for r in all_roles:
            if r.agr_name not in matching_agr:
                continue
            # Collect the matching T-code strings for this role
            detail = cache.get_role_detail(r.agr_name)
            tcodes_found: list[str] = []
            if detail:
                seen: set[str] = set()
                for sr in detail.single_roles:
                    for tc in sr.tcodes:
                        k = tc.tcode.upper()
                        if tc.tcode not in seen and (k == query or k.startswith(query)):
                            tcodes_found.append(tc.tcode)
                            seen.add(tc.tcode)
            result.append(r.model_copy(update={"matching_tcodes": tcodes_found}))

        return sorted(result, key=lambda x: (x.text or x.agr_name).lower())

    # ---- Text search ---------------------------------------------------------
    if search and search.strip():
        q = search.strip().lower()
        all_roles = [
            r for r in all_roles
            if q in (r.text or "").lower()
            or q in r.agr_name.lower()
            or q in (r.module_name or "").lower()
        ]

    return all_roles


# ---------------------------------------------------------------------------
# GET /api/roles/{agr_name}
# ---------------------------------------------------------------------------
@router.get("/{agr_name}", response_model=RoleDetail)
def get_role(agr_name: str) -> RoleDetail:
    """Return full detail for a single composite role including single roles and T-codes."""
    detail = cache.get_role_detail(agr_name)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Role '{agr_name}' not found.")
    return detail