"""Authenticated local investigation APIs. Dates describe assignments, not effective authorization."""
from search_matching import text_matches, search_fields

from collections import defaultdict
from csv_exports import assignment_response
from datetime import date
from typing import Literal
from fastapi import APIRouter, HTTPException, Query, Depends
from assignment_filters import assignment_dates, within_dates
import cache
from role_matching import normalize_role
from transaction_filters import normalized_tcodes, matching_role_names, matching_codes
from user_access import (
    assignment_view, current_role_count,
    interval_status,
    relevant,
    sap_date,
    normalize_username,
    parse_release_role,
)

def require_mapping():
    from config import get_settings
    if not get_settings().features.user_role_mapping:
        raise HTTPException(409, 'User–Role Mapping is disabled. Enable it in Settings → Features; imported data is retained.')


router = APIRouter(prefix="/api/access", tags=["User access"], dependencies=[Depends(require_mapping)])
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


def source_info(state, today=None):
    return dict(
        loaded=bool(state.users.report),
        catalogue_loaded=bool(state.roles),
        report={
            key: value
            for key, value in state.users.report.items()
            if key not in {"samples", "file_name"}
        },
        as_of=(today or date.today()).isoformat(),
        data_revision=state.last_loaded.isoformat() if state.last_loaded else "empty",
    )


def matching_entries(state, role="", tcode=""):
    if tcode:
        unique = {}
        for name in {name for code in matching_codes(state.tcode_index,tcode.strip().upper()) for name in state.tcode_index[code]}:
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


def directory_filters(
    search: str = Query("", max_length=256),
    group: str = Query("", max_length=512),
    role: str = Query("", max_length=512),
    tcode: str = Query("", max_length=128),
    tcodes: list[str] = Query(default=[], max_length=21),
    transaction_mode: Literal["and", "or"] = "and",
    assignment_band: Literal["", "0", "1–5", "6–20", "21+"] = "",
    status: Status = "",
    show_expired: bool = False,
    exclude_transactions: bool = Query(False, description="Reverse the transaction filter across the user's eligible role assignments"),
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
):
    return dict(assignment_band=assignment_band,search=search,group=group,role=role,tcode=tcode,tcodes=tcodes,transaction_mode=transaction_mode,status=status,show_expired=show_expired,exclude_transactions=exclude_transactions,sort=sort,descending=descending)


def directory_selection(snapshot, *, search,group,role,tcode,tcodes,transaction_mode,status,show_expired,sort,descending,today=None,assignment_band="",exclude_transactions=False):
    state = snapshot.users
    wanted_codes = normalized_tcodes([tcode] + tcodes if tcode else tcodes)
    candidates = matching_entries(state, role)
    evidence = defaultdict(list)
    for a in candidates:
        if (
            a["scope"] != "other"
            and relevant(a, status, show_expired, today)
            and (not group or group == a["user_group"])
        ):
            evidence[a["user_key"]].append(a)
    if wanted_codes and snapshot.roles:
        code_ids = {code: {a['id'] for actual in matching_codes(state.tcode_index,code) for name in state.tcode_index[actual] for a in state.role_index.get(name, [])} for code in wanted_codes}
        for key, entries in list(evidence.items()):
            matches = {code for code, ids in code_ids.items() if any(a['id'] in ids for a in entries)}
            positive = len(matches) == len(wanted_codes) if transaction_mode == 'and' else bool(matches)
            if exclude_transactions:
                # Absence is only concluded from eligible assignments that are all mapped to catalogue roles; unmapped roles may hold any transaction.
                if positive or not entries or any(a['match_status'] not in {'exact', 'wildcard'} for a in entries):
                    del evidence[key]
            elif not positive:
                del evidence[key]
            else:
                evidence[key] = [a for a in entries if any(a['id'] in ids for ids in code_ids.values())]
    elif wanted_codes and exclude_transactions:
        evidence.clear()  # without a catalogue no transaction evidence exists, so absence cannot be concluded
    result = []
    term = search.strip()
    for key, user in state.users.items():
        if assignment_band:
            count=current_role_count(user,today)
            band='0' if count==0 else '1–5' if count<=5 else '6–20' if count<=20 else '21+'
            if band!=assignment_band:continue
        if group and group not in user["groups"]:
            continue
        if (role or (wanted_codes and (snapshot.roles or exclude_transactions)) or status) and key not in evidence:
            continue
        if term and not search_fields(term, user["username"], *user["groups"], *user["emails"], *(" ".join(n) for n in user["names"])):
            continue
        result.append(user_summary(user, evidence[key]))
    result.sort(
        key=lambda u: (
            (u["groups"][0] if u["groups"] else "") if sort == "group" else u[sort],
            u["user_key"],
        ),
        reverse=descending,
    )
    return result,evidence


def audit_assignments(snapshot, key, filters, today):
    """Every imported assignment of a matching user, except expired ones unless expired assignments are shown or filtered explicitly."""
    include_expired = filters['show_expired'] or filters['status'] == 'expired'
    return [a for a in snapshot.users.users[key]['assignments'] if include_expired or interval_status(sap_date(a['valid_from']), sap_date(a['valid_to']), today) != 'expired']


@router.get('/users')
def users(filters:dict=Depends(directory_filters),anchor:str=Query('',max_length=512),offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100)):
    snapshot=cache.get_snapshot();today=date.today()
    result,evidence=directory_selection(snapshot,**filters,today=today)
    if anchor:return dict(**page(result,offset,limit),navigation=record_navigation(result,anchor,'username',normalize_username))
    return dict(**page(result,offset,limit),**source_info(snapshot,today),groups=snapshot.users.groups,groups_total=snapshot.users.group_count,
                export_assignments=sum(len(audit_assignments(snapshot,u['user_key'],filters,today)) for u in result))


@router.get('/exports/users')
def export_users(filters:dict=Depends(directory_filters)):
    snapshot=cache.get_snapshot();today=date.today()
    if not snapshot.users.report:raise HTTPException(409,'No validated User Access dataset is loaded.')
    result,evidence=directory_selection(snapshot,**filters,today=today)
    identities={u['user_key']:u for u in result}
    matching={key:{a['id'] for a in values} for key,values in evidence.items()}
    included={key:audit_assignments(snapshot,key,filters,today) for key in identities}
    count=sum(len(values) for values in included.values())
    entries=((a,a['id'] in matching.get(key,())) for key in identities for a in included[key])
    return assignment_response(snapshot,entries,identities,count,'user-directory',today)


@router.get("/users/{username:path}")
def user_detail(
    username: str,
    dates: dict = Depends(assignment_dates),
    show_expired: bool = False,
    status: Status = "",
    tcode: str = Query("", max_length=128),
    tcodes: list[str] = Query(default=[], max_length=21),
    transaction_mode: Literal["and", "or"] = "and",
    scope: Literal["business", "release", "other", "all", ""] = "",
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    account_offset: int = Query(0, ge=0),
    name_offset: int = Query(0, ge=0),
    email_offset: int = Query(0, ge=0),
):
    snapshot = cache.get_snapshot()
    state = snapshot.users
    user = state.users.get(normalize_username(username))
    if user is None:
        raise HTTPException(404, "User not found in the current local export.")
    entries = [
        a
        for a in user["assignments"]
        if within_dates(a, dates) and relevant(a, status, show_expired) and (not scope or (a["scope"] in {"business", "release"} if scope == "all" else a["scope"] == scope))
    ]
    unmapped = sum(a["match_status"] not in {"exact", "wildcard"} or not a["tcodes"] for a in entries)
    wanted_codes = normalized_tcodes([tcode] + tcodes if tcode else tcodes)
    if wanted_codes:
        matched_names = matching_role_names(state.tcode_index, wanted_codes, transaction_mode)
        entries = [a for a in entries if a["match_status"] in {"exact", "wildcard"} and matched_names.intersection(a["catalogue_roles"])]
    rows = sorted(
        entries,
        key=lambda a: (normalize_role(a["role_name"]), a["valid_from"] or "", a["id"]),
    )
    paged = page(rows, offset, limit)
    paged["items"] = [assignment_view(a) for a in paged["items"]]
    for item in paged["items"]:
        matches = item["catalogue_roles"]
        role = snapshot.roles.get(matches[0]) if len(matches) == 1 and item["match_status"] in {"exact", "wildcard"} else None
        item["role_description"] = role.text if role else ""
        item["transaction_roles"] = sorted({sr.child_agr for name in matches
            for sr in (snapshot.roles[name].single_roles if name in snapshot.roles else [])
            if wanted_codes and any(tc.tcode.upper() in matching_codes(state.tcode_index,pattern) for tc in sr.tcodes for pattern in wanted_codes)}) if item["match_status"] in {"exact", "wildcard"} else []
    return dict(
        mapping_available=bool(snapshot.roles),
        unmapped_assignments=unmapped,
        data_revision=snapshot.last_loaded.isoformat() if snapshot.last_loaded else "empty",
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


@router.get("/release-options")
def release_options(
    field: Literal["group", "document_type", "release_group", "strategy", "username", "role"],
    dates: dict = Depends(assignment_dates),
    search: str = Query("", max_length=512),
    selected: str = Query("", max_length=512),
    group: str = Query("", max_length=100),
    document_type: str = Query("", max_length=20),
    release_group: str = Query("", max_length=100),
    strategy: str = Query("", max_length=100),
    status: Literal["active", "expired", "future", "unknown", "all"] = "active",
    limit: int = Query(50, ge=1, le=100),
):
    """Hierarchical facets. A child never restricts its own or an ancestor's options.

    Group -> document type -> release group -> strategy -> username / role.
    Username and role are sibling substring filters, not mutual dependencies.
    Values are bounded in transit; all matching records contribute, not one page.
    """
    rank = {"group": 0, "document_type": 1, "release_group": 2, "strategy": 3, "username": 4, "role": 4}[field]
    values = set()
    for a in cache.get_snapshot().users.assignments:
        if a["scope"] != "release" or not within_dates(a, dates) or not relevant(a, "" if status == "all" else status, True):
            continue
        release = a["release"]
        kind = release["document_type"] or "Unparsed"
        if rank > 0 and group and a["user_group"] != group: continue
        if rank > 1 and document_type and kind != document_type: continue
        if rank > 2 and release_group and release["release_group"] != release_group: continue
        if rank > 3 and strategy and release["release_strategy"] != strategy: continue
        value = {"group": a["user_group"], "document_type": kind,
                 "release_group": release["release_group"], "strategy": release["release_strategy"],
                 "username": a["username"], "role": a["role_name"]}[field]
        if value: values.add(value)
    matches = sorted((v for v in values if text_matches(v,search)), key=lambda v: (v.casefold(), v))
    # Username/role use the same literal search as their assignment filters.
    available = not selected or (any(text_matches(v,selected) for v in values)
                                if field in {"username", "role"} else selected in values)
    return dict(items=matches[:limit], total=len(matches), has_more=len(matches) > limit,
                selected_available=available)


def release_filters(dates:dict=Depends(assignment_dates),
    group: str = Query("", max_length=512),
    document_type: Literal["", "PR", "PO", "Unparsed"] = "",
    release_group: str = Query("", max_length=100),
    strategy: str = Query("", max_length=100),
    username: str = Query("", max_length=512),
    role: str = Query("", max_length=512),
    status: Literal["active", "expired", "future", "unknown", "all"] = "active",
    sort: Literal[
        "role_name",
        "document_type",
        "release_group",
        "release_strategy",
        "assigned_users",
    ] = "role_name",
    descending: bool = False,
):
    return dict(dates=dates,group=group,document_type=document_type,release_group=release_group,strategy=strategy,username=username,role=role,status=status,sort=sort,descending=descending)


def filtered_release_assignments(snapshot, *, dates,group,document_type,release_group,strategy,username,role,status,sort,descending,today=None):
    for a in snapshot.users.assignments:
        if a["scope"] != "release" or not within_dates(a, dates):
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
        if username and not text_matches(a["username"],username):
            continue
        if role and not text_matches(a["role_name"],role):
            continue
        if not relevant(a, "" if status == "all" else status, True, today):
            continue
        yield a


@router.get('/exports/releases')
def export_releases(filters:dict=Depends(release_filters)):
    snapshot=cache.get_snapshot();today=date.today()
    if not snapshot.users.report:raise HTTPException(409,'No validated User Access dataset is loaded.')
    entries=list(filtered_release_assignments(snapshot,**filters,today=today))
    # Same assignment set in Table/Matrix; grouping never alters export scope.
    entries.sort(key=lambda a:(normalize_role(a['role_name']),a['user_key'],a['valid_from'] or '',a['valid_to'] or '',a['id']),reverse=filters['descending'])
    identities={key:user_summary(snapshot.users.users[key],[]) for key in {a['user_key'] for a in entries}}
    return assignment_response(snapshot,((a,True) for a in entries),identities,len(entries),'release-roles',today)


@router.get('/releases')
def releases(filters:dict=Depends(release_filters),anchor:str=Query('',max_length=512),matrix_offset:int=Query(0,ge=0),group_by_user_group:bool=False,matrix_complete:bool=False,list_complete:bool=False,offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100)):
    snapshot = cache.get_snapshot()
    state = snapshot.users
    today=date.today()
    sort,descending=filters["sort"],filters["descending"]
    buckets = defaultdict(list)
    cells = defaultdict(dict)
    for a in filtered_release_assignments(snapshot,**filters,today=today):
        r=a['release']
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
        **page(rows, 0 if list_complete else offset, max(1,len(rows)) if list_complete else limit),
        matrix=matrix if matrix_complete else matrix[matrix_offset : matrix_offset + 200],
        matrix_total=len(matrix),
        matrix_offset=matrix_offset,
        **source_info(snapshot,today),
        export_assignments=sum(len(values) for values in buckets.values()),
        groups=state.groups,
        groups_total=state.group_count
    )


@router.get("/release-assignments")
def release_assignments(
    dates: dict = Depends(assignment_dates),
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
        if a["scope"] != "release" or not within_dates(a, dates):
            continue
        r = a["release"]
        if username and not text_matches(a["username"],username):
            continue
        if role_search and not text_matches(a["role_name"],role_search):
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
    return dict(**paged, distinct_users=len({a["user_key"] for a in entries}), role_info=parse_release_role(role) if role else None)
