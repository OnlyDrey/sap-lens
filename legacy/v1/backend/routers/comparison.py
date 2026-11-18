"""Comparison router â€” single-role-level and T-code-level multi-role comparison."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from cache import get_snapshot
from models import (
    ComparisonResult, ComparisonRole, SingleRoleInfo,
    PairwiseOverlap, TCode
)

router = APIRouter(prefix="/api/compare", tags=["Comparison"])


class CompareRequest(BaseModel):
    roles: list[str] = Field(min_length=2, max_length=5)


@router.post("", response_model=ComparisonResult)
def compare_roles(request: CompareRequest) -> ComparisonResult:
    """
    Compare 2-5 composite SAP roles at two levels:

    1. Single role level (structural) â€” which single roles (building blocks)
       are shared vs exclusive across the selected composites.

    2. T-code level (detailed) â€” which T-codes are shared vs exclusive.

    Both levels include pairwise overlap counts and an all-roles intersection.
    """
    if len(request.roles) < 2:
        raise HTTPException(status_code=400, detail="At least 2 roles required.")
    if len(set(request.roles)) != len(request.roles):
        raise HTTPException(status_code=400, detail="Duplicate role names are not allowed.")

    state = get_snapshot()
    role_details = []
    for name in request.roles:
        detail = state.roles.get(name)
        if detail is None:
            raise HTTPException(status_code=404, detail=f"Role '{name}' not found.")
        role_details.append(detail)

    # â”€â”€ Build per-role sets â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    # Single role sets
    sr_sets: list[set[str]] = []
    sr_lookups: list[dict[str, SingleRoleInfo]] = []
    for detail in role_details:
        sr_set: set[str] = set()
        sr_lookup: dict[str, SingleRoleInfo] = {}
        for sr in detail.single_roles:
            sr_set.add(sr.child_agr)
            sr_lookup[sr.child_agr] = SingleRoleInfo(
                function_key=sr.function_key, module_name=sr.module_name,
                child_agr=sr.child_agr,
                child_agr_text=sr.child_agr_text,
                tcode_count=len(sr.tcodes),
            )
        sr_sets.append(sr_set)
        sr_lookups.append(sr_lookup)

    # T-code sets
    tc_sets: list[set[str]] = []
    tc_lookups: list[dict[str, TCode]] = []
    for detail in role_details:
        lookup: dict[str, TCode] = {}
        for sr in detail.single_roles:
            for tc in sr.tcodes:
                if tc.tcode not in lookup:
                    lookup[tc.tcode] = tc
        tc_sets.append(set(lookup.keys()))
        tc_lookups.append(lookup)

    # â”€â”€ Single role level â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    shared_sr_strs = set.intersection(*sr_sets) if sr_sets else set()
    shared_single_roles: list[SingleRoleInfo] = sorted(
        [sr_lookups[0][s] for s in shared_sr_strs],
        key=lambda x: x.child_agr
    )

    pairwise_single: list[PairwiseOverlap] = []
    for i in range(len(role_details)):
        for j in range(i + 1, len(role_details)):
            pairwise_single.append(PairwiseOverlap(
                role_a=role_details[i].agr_name,
                role_b=role_details[j].agr_name,
                shared_count=len(sr_sets[i] & sr_sets[j]),
            ))

    # â”€â”€ T-code level â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    shared_tc_strs = set.intersection(*tc_sets) if tc_sets else set()
    shared_tcodes: list[TCode] = sorted(
        [tc_lookups[0][t] for t in shared_tc_strs],
        key=lambda tc: tc.tcode
    )

    pairwise_tc: list[PairwiseOverlap] = []
    for i in range(len(role_details)):
        for j in range(i + 1, len(role_details)):
            pairwise_tc.append(PairwiseOverlap(
                role_a=role_details[i].agr_name,
                role_b=role_details[j].agr_name,
                shared_count=len(tc_sets[i] & tc_sets[j]),
            ))

    # â”€â”€ Per-role results â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    comparison_roles: list[ComparisonRole] = []
    for i, detail in enumerate(role_details):

        # Exclusive single roles (not in any other selected composite)
        other_sr_union = set.union(*[sr_sets[j] for j in range(len(sr_sets)) if j != i])
        exc_sr_strs = sr_sets[i] - other_sr_union
        exclusive_single_roles: list[SingleRoleInfo] = sorted(
            [sr_lookups[i][s] for s in exc_sr_strs],
            key=lambda x: x.child_agr
        )

        # Exclusive T-codes
        other_tc_union = set.union(*[tc_sets[j] for j in range(len(tc_sets)) if j != i])
        exc_tc_strs = tc_sets[i] - other_tc_union
        unique_tcodes: list[TCode] = sorted(
            [tc_lookups[i][t] for t in exc_tc_strs],
            key=lambda tc: tc.tcode
        )

        comparison_roles.append(ComparisonRole(
            agr_name=detail.agr_name,
            text=detail.text,
            function_key=detail.function_key,
            module_name=detail.module_name,
            tcode_count=detail.tcode_count,
            single_role_count=len(sr_sets[i]),
            exclusive_single_roles=exclusive_single_roles,
            unique_tcodes=unique_tcodes,
        ))

    return ComparisonResult(
        analysis=state.analysis,
        roles=comparison_roles,
        shared_single_roles=shared_single_roles,
        pairwise_single_overlaps=pairwise_single,
        shared_tcodes=shared_tcodes,
        pairwise_overlaps=pairwise_tc,
    )