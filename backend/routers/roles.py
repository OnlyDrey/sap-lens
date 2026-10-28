"""Roles router -- list, search, filter, T-code search, detail."""
from search_matching import text_matches
import csv
from datetime import date
import io
from typing import Optional, Literal
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import Field
import access_package
import cache
from config_models import StrictModel
from csv_exports import spreadsheet_cell
from models import RoleSummary, RoleDetail
from transaction_filters import normalized_tcodes, role_names_for, matching_codes

router = APIRouter(prefix="/api/roles", tags=["Roles"])

PACKAGE_COLUMNS = ['Generated SAP Role Name', 'Role Description', 'Suffix']
PACKAGE_HEADER = '\ufeff' + ';'.join('"' + column + '"' for column in PACKAGE_COLUMNS) + '\r\n'
MAX_PACKAGE_ROLES = 200


class PackageItem(StrictModel):
    role: str = Field(min_length=1, max_length=512)
    suffix: str = Field(default='', max_length=64)


class PackageBody(StrictModel):
    default_suffix: str = Field(default='', max_length=64)
    items: list[PackageItem] = Field(max_length=MAX_PACKAGE_ROLES)


def _package_rows(body):
    state = cache.get_snapshot()
    catalogue = {role.agr_name: role.text or '' for role in state.summaries}
    return access_package.preview(body.default_suffix, [(item.role, item.suffix) for item in body.items], catalogue), catalogue


@router.get("/naming")
def naming():
    """Organizational suffixes found in the imported role names (final segments used under several stems)."""
    state = cache.get_snapshot()
    names = [role.agr_name for role in state.summaries] + [a['role_name'] for a in getattr(state.users, 'assignments', [])]
    evidence = access_package.naming_evidence(names)
    return dict(suffixes=[dict(value=value, roles=count) for value, count in sorted(evidence.items(), key=lambda item: (-item[1], item[0]))], evidence_roles=len(names))


@router.post("/package/preview")
def package_preview(body: PackageBody):
    """Proposed role names for the cart. Never changes SAP access or stored data."""
    rows, _ = _package_rows(body)
    return dict(items=rows, exportable=len(access_package.csv_rows(rows)), max_roles=MAX_PACKAGE_ROLES)


@router.post("/package/export")
def package_export(body: PackageBody):
    rows, _ = _package_rows(body)
    lines = access_package.csv_rows(rows)
    if not lines:
        raise HTTPException(422, 'No valid generated role names to export.')
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=';', quoting=csv.QUOTE_ALL, lineterminator='\r\n')
    writer.writerow(PACKAGE_COLUMNS)
    for line in lines:
        writer.writerow([spreadsheet_cell(value) for value in line])
    return Response('\ufeff' + buffer.getvalue(), media_type='text/csv; charset=utf-8', headers={
        'Content-Disposition': f'attachment; filename="sap-lens-access-package-{date.today().isoformat()}.csv"', 'Cache-Control': 'no-store'})

@router.get("", response_model=list[RoleSummary])
def list_roles(
    function_key: Optional[str] = Query(None, description="Filter by module code, e.g. FI"),
    function_keys: list[str] = Query(default=[], max_length=100),
    transaction_mode: Literal['and', 'or'] = 'and',
    search: Optional[str] = Query(None, description="Search role name or description"),
    tcodes: list[str] = Query(default=[], max_length=21),
    exclude_matching: bool = Query(False, description="Reverse the transaction filter: AND = not all together, OR = none of them; roles without mappings never match"),
    tcode: Optional[str] = Query(None, description="Find all roles containing this T-code"),
) -> list[RoleSummary]:
    """
    Return role summaries.
    - function_key : filter by SAP module (CO, FI, MM ...)
    - search       : free-text match on role name / description / AGR_NAME
    - tcode        : exact T-code lookup -- returns roles that contain this transaction
                     Matching T-codes are returned in the matching_tcodes field.
    """
    state = cache.get_snapshot()
    all_roles: list[RoleSummary] = state.summaries

    # Module filter (applied regardless of search mode)
    if any(len(key) > 256 for key in function_keys):
        raise HTTPException(422, 'SAP area identifiers must not exceed 256 characters.')
    if function_keys:
        all_roles = [r for r in all_roles if r.function_key in function_keys]
    if function_key:
        all_roles = [r for r in all_roles if r.function_key == function_key]

    exact_codes = normalized_tcodes(tcodes)
    if exact_codes:
        index = state.tcode_index
        names = role_names_for(index, exact_codes, transaction_mode, exclude_matching)
        shown = (lambda r: []) if exclude_matching else (lambda r: sorted({actual for code in exact_codes for actual in matching_codes(index,code) if r.agr_name in index[actual]}))
        all_roles = [r.model_copy(update={"matching_tcodes": shown(r)}) for r in all_roles if r.agr_name in names]
        if search and search.strip():
            query = search.strip().lower()
            all_roles = [r for r in all_roles if text_matches(r.agr_name, query) or text_matches(r.text, query)]
        return all_roles

    # ---- T-code search -------------------------------------------------------
    if tcode and tcode.strip():
        query = tcode.strip().upper()
        idx = state.tcode_index

        # Exact match first; also catch partial prefix matches (e.g. "ME3" -> ME3N, ME33K ...)
        matching_agr: set[str] = set()

        for key, agr_names in idx.items():
            if (text_matches(key,query) if '*' in query else key.startswith(query)):
                matching_agr.update(agr_names)

        result: list[RoleSummary] = []
        for r in all_roles:
            if r.agr_name not in matching_agr:
                continue
            # Collect the matching T-code strings for this role
            detail = state.roles.get(r.agr_name)
            tcodes_found: list[str] = []
            if detail:
                seen: set[str] = set()
                for sr in detail.single_roles:
                    for tc in sr.tcodes:
                        k = tc.tcode.upper()
                        if tc.tcode not in seen and (text_matches(k,query) if '*' in query else k.startswith(query)):
                            tcodes_found.append(tc.tcode)
                            seen.add(tc.tcode)
            result.append(r.model_copy(update={"matching_tcodes": tcodes_found}))

        return sorted(result, key=lambda x: (x.text or x.agr_name).lower())

    # ---- Text search ---------------------------------------------------------
    if search and search.strip():
        q = search.strip().lower()
        all_roles = [
            r for r in all_roles
            if text_matches(r.text, q) or text_matches(r.agr_name, q)
        ]

    return all_roles


# ---------------------------------------------------------------------------
# GET /api/roles/{agr_name}
# ---------------------------------------------------------------------------
@router.get("/{agr_name:path}", response_model=RoleDetail)
def get_role(agr_name: str) -> RoleDetail:
    """Return full detail for a single composite role including single roles and T-codes."""
    detail = cache.get_role_detail(agr_name)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Role '{agr_name}' not found.")
    return detail