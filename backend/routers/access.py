"""Authenticated local investigation APIs. Dates describe assignments, not effective authorization."""

from collections import defaultdict
from datetime import date
from typing import Literal
from fastapi import APIRouter, HTTPException, Query
import cache
from role_matching import normalize_role
from user_access import (
    assignment_view,
    interval_status,
    relevant,
    sap_date,
    normalize_username,
)

router = APIRouter(prefix="/api/access", tags=["User access"])
Status = Literal["", "active", "expired", "future", "unknown"]


def page(items, offset, limit):
    return dict(
        items=items[offset : offset + limit],
        total=len(items),
        offset=offset,
        limit=limit,
    )


def record_navigation(items, anchor, key, normalize):
    """Bounded identity-only navigation over the exact filtered list ordering."""
    wanted = normalize(anchor)
    index = next((i for i, item in enumerate(items) if normalize(item[key]) == wanted), None)
    return dict(
        index=index,
        total=len(items),
        previous=items[index - 1][key] if index is not None and index > 0 else None,
        next=items[index + 1][key] if index is not None and index + 1 < len(items) else None,
    )


def source_info(state):
    return dict(
        loaded=bool(state.users.report),
        catalogue_loaded=bool(state.roles),
        report={
            key: value
            for key, value in state.users.report.items()
            if key not in {"samples", "file_name"}
        },
        as_of=date.today().isoformat(),
    )


def matching_entries(state, role="", tcode=""):
    if tcode:
        unique = {}
        for name in state.tcode_index.get(tcode.strip().upper(), []):
            for a in state.role_index.get(name, []):
                unique[a["id"]] = a
        return unique.values()
    if role:
        # Preserve all exact assignment evidence as well as resolved catalogue links.
        key = normalize_role(role)
        return [
            a
            for a in state.assignments
            if normalize_role(a["role_name"]) == key
            or any(normalize_role(name) == key for name in a["catalogue_roles"])
            and a["match_status"] in {"exact", "wildcard"}
        ]
    return state.assignments


def user_summary(user, entries):
    names = next((n for n in user["names"] if any(n)), ("", ""))
    statuses = sorted(
        {
            interval_status(sap_date(a["valid_from"]), sap_date(a["valid_to"]))
            for a in user["accounts"]
        }
    )
    locks = {a["locked"] for a in user["accounts"]}
    return dict(
        username=user["username"],
        user_key=normalize_username(user["username"]),
        groups=user["groups"],
        first_name=names[0],
        last_name=names[1],
        email=next(iter(user["emails"]), ""),
        account_status="/".join(statuses),
        lock_status=(
            "Locked"
            if locks == {True}
            else "Unlocked" if locks == {False} else "Mixed / unknown"
        ),
        relevant_roles=len(
            {normalize_role(a["role_name"]) for a in entries if a["scope"] != "other"}
        ),
    )


@router.get("/users")
def users(
    anchor: str = Query("", max_length=512),
    search: str = Query("", max_length=256),
    group: str = Query("", max_length=512),
    role: str = Query("", max_length=512),
    tcode: str = Query("", max_length=128),
    status: Status = "",
    show_expired: bool = False,
    sort: Literal[
        "username",
        "group",
        "first_name",
        "last_name",
        "email",
        "account_status",
        "relevant_roles",
    ] = "username",
    descending: bool = False,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    snapshot = cache.get_snapshot()
    state = snapshot.users
    candidates = matching_entries(state, role, tcode)
    evidence = defaultdict(list)
    for a in candidates:
        if (
            a["scope"] != "other"
            and relevant(a, status, show_expired)
            and (not group or group == a["user_group"])
        ):
            evidence[a["user_key"]].append(a)
    result = []
    term = search.casefold().strip()
    for key, user in state.users.items():
        if group and group not in user["groups"]:
            continue
        if (role or tcode or status) and key not in evidence:
            continue
        text = " ".join(
            [
                user["username"],
                *user["groups"],
                *user["emails"],
                *(part for n in user["names"] for part in n),
            ]
        )
        if term and term not in text.casefold():
            continue
        result.append(user_summary(user, evidence[key]))
    result.sort(
        key=lambda u: (
            (u["groups"][0] if u["groups"] else "") if sort == "group" else u[sort],
            u["user_key"],
        ),
        reverse=descending,
    )
    if anchor:
        return dict(**page(result, offset, limit), navigation=record_navigation(result, anchor, "username", normalize_username))
    return dict(
        **page(result, offset, limit),
        **source_info(snapshot),
        groups=state.groups,
        groups_total=state.group_count
    )


@router.get("/users/{username:path}")
def user_detail(
    username: str,
    show_expired: bool = False,
    status: Status = "",
    scope: Literal["business", "release", "other", ""] = "",
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    account_offset: int = Query(0, ge=0),
    name_offset: int = Query(0, ge=0),
    email_offset: int = Query(0, ge=0),
):
    state = cache.get_snapshot().users
    user = state.users.get(normalize_username(username))
    if user is None:
        raise HTTPException(404, "User not found in the current local export.")
    entries = [
        a
        for a in user["assignments"]
        if relevant(a, status, show_expired) and (not scope or a["scope"] == scope)
    ]
    rows = sorted(
        entries,
        key=lambda a: (normalize_role(a["role_name"]), a["valid_from"] or "", a["id"]),
    )
    paged = page(rows, offset, limit)
    paged["items"] = [assignment_view(a) for a in paged["items"]]
    return dict(
        **paged,
        **user_summary(user, entries),
        names=user["names"][name_offset : name_offset + 100],
        names_total=len(user["names"]),
        emails=user["emails"][email_offset : email_offset + 100],
        emails_total=len(user["emails"]),
        accounts=[
            dict(
                a,
                status=interval_status(
                    sap_date(a["valid_from"]), sap_date(a["valid_to"])
                ),
            )
            for a in user["accounts"][account_offset : account_offset + 50]
        ],
        account_total=len(user["accounts"]),
        account_offset=account_offset,
        retained_assignments=len(user["assignments"]),
        as_of=date.today().isoformat()
    )


@router.get("/releases")
def releases(
    anchor: str = Query("", max_length=512),
    group: str = Query("", max_length=512),
    document_type: Literal["", "PR", "PO", "Unparsed"] = "",
    release_group: str = Query("", max_length=100),
    strategy: str = Query("", max_length=100),
    username: str = Query("", max_length=512),
    role: str = Query("", max_length=512),
    status: Literal["active", "expired", "future", "unknown", "all"] = "active",
    matrix_offset: int = Query(0, ge=0),
    group_by_user_group: bool = False,
    sort: Literal[
        "role_name",
        "document_type",
        "release_group",
        "release_strategy",
        "assigned_users",
    ] = "role_name",
    descending: bool = False,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    snapshot = cache.get_snapshot()
    state = snapshot.users
    buckets = defaultdict(list)
    cells = defaultdict(dict)
    for a in state.assignments:
        if a["scope"] != "release":
            continue
        r = a["release"]
        if group and a["user_group"] != group:
            continue
        if document_type and (r["document_type"] or "Unparsed") != document_type:
            continue
        if release_group and r["release_group"] != release_group:
            continue
        if strategy and r["release_strategy"] != strategy:
            continue
        if username and username.casefold() not in a["username"].casefold():
            continue
        if role and role.casefold() not in a["role_name"].casefold():
            continue
        if not relevant(a, "" if status == "all" else status, True):
            continue
        buckets[normalize_role(a["role_name"])].append(a)
        if r["parsed"]:
            key = (
                a["user_group"] if group_by_user_group else "",
                r["document_type"],
                r["release_group"],
                r["release_strategy"],
            )
            cells[key][a["user_key"]] = True
    rows = []
    for _, assignments in buckets.items():
        sample = assignments[0]
        rows.append(
            dict(
                role_name=sample["role_name"],
                **sample["release"],
                assigned_users=len({a["user_key"] for a in assignments}),
                assignment_count=len(assignments),
                statuses=sorted(
                    {
                        interval_status(
                            sap_date(a["valid_from"]), sap_date(a["valid_to"])
                        )
                        for a in assignments
                    }
                ),
                valid_from=min(
                    (a["valid_from"] for a in assignments if a["valid_from"]),
                    default=None,
                ),
                valid_to=max(
                    (a["valid_to"] for a in assignments if a["valid_to"]), default=None
                ),
                missing_dates=any(
                    not a["valid_from"] or not a["valid_to"] for a in assignments
                )
            )
        )
    rows.sort(
        key=lambda r: (
            r.get(sort) or (0 if sort == "assigned_users" else ""),
            r["role_name"],
        ),
        reverse=descending,
    )
    if anchor:
        return dict(**page(rows, offset, limit), navigation=record_navigation(rows, anchor, "role_name", normalize_role))
    matrix = [
        dict(
            user_group=g,
            document_type=d,
            release_group=r,
            release_strategy=s,
            user_count=len(users),
        )
        for (g, d, r, s), users in sorted(cells.items())
    ]
    return dict(
        **page(rows, offset, limit),
        matrix=matrix[matrix_offset : matrix_offset + 200],
        matrix_total=len(matrix),
        matrix_offset=matrix_offset,
        **source_info(snapshot),
        groups=state.groups,
        groups_total=state.group_count
    )


@router.get("/release-assignments")
def release_assignments(
    role: str = Query("", max_length=512),
    group: str = Query("", max_length=512),
    ungrouped: bool = False,
    username: str = Query("", max_length=512),
    role_search: str = Query("", max_length=512),
    document_type: Literal["", "PR", "PO"] = "",
    release_group: str = Query("", max_length=100),
    strategy: str = Query("", max_length=100),
    status: Literal["active", "expired", "future", "unknown", "all"] = "active",
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    entries = []
    for a in cache.get_snapshot().users.assignments:
        if a["scope"] != "release":
            continue
        r = a["release"]
        if username and username.casefold() not in a["username"].casefold():
            continue
        if role_search and role_search.casefold() not in a["role_name"].casefold():
            continue
        if role and normalize_role(a["role_name"]) != normalize_role(role):
            continue
        if group and a["user_group"] != group or ungrouped and a["user_group"]:
            continue
        if document_type and r["document_type"] != document_type:
            continue
        if release_group and r["release_group"] != release_group:
            continue
        if strategy and r["release_strategy"] != strategy:
            continue
        if relevant(a, "" if status == "all" else status, True):
            entries.append(a)
    entries.sort(
        key=lambda a: (a["user_key"], a["role_name"], a["valid_from"] or "", a["id"])
    )
    paged = page(entries, offset, limit)
    paged["items"] = [assignment_view(a) for a in paged["items"]]
    return dict(**paged, distinct_users=len({a["user_key"] for a in entries}))
