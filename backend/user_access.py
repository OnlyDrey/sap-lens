"""Local user export parsing and evidence-preserving access investigation."""

from dataclasses import dataclass, field
from datetime import date
import re
from pathlib import Path

from analysis_errors import AnalysisValidationError
from config_models import USER_FIELDS
from csv_import import CsvImport
from role_matching import RoleMatcher, normalize_role, role_scope


def normalize_username(value):
    # SAP username identity is case-insensitive; never merge distinct interior text.
    return value.strip().upper()


MAX_USERS = 100_000


class UserCsvImport(CsvImport):
    fields = USER_FIELDS
    required = "USERNAME"
    identifier_fields = ["USERNAME", "ROLE_NAME", "USER_GROUP"]


def sap_date(value):
    if not value or value in {"00000000", "0000-00-00"}:
        return None
    try:
        if re.fullmatch(r"\d{8}", value):
            return date(int(value[:4]), int(value[4:6]), int(value[6:]))
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return date.fromisoformat(value)
    except ValueError:
        pass
    raise AnalysisValidationError(
        "Invalid SAP date. Use YYYY-MM-DD or YYYYMMDD; no data was applied."
    )


def interval_status(start, end, today=None):
    today = today or date.today()
    if end and end < today:
        return "expired"
    if start and start > today:
        return "future"
    if start is None or end is None:
        return "unknown"
    return "active"


def parse_release_role(value):
    # MM, PR/PO_REL_ST and group/strategy positions are confirmed. No meaning is
    # assigned to the surrounding opaque scope/suffix tokens (e.g. M and ALL).
    name = normalize_role(value)
    match = re.fullmatch(
        r"ZO:MM:([A-Z0-9_-]+):(PR|PO)_REL_ST_([A-Z0-9]+)_([A-Z0-9]+):([A-Z0-9_-]+)",
        name,
    )
    if not match:
        return dict(
            parsed=False, document_type=None, release_group=None, release_strategy=None
        )
    scope, kind, group, strategy, suffix = match.groups()
    return dict(
        parsed=True,
        document_type=kind,
        release_group=group,
        release_strategy=strategy,
        opaque_scope=scope,
        opaque_suffix=suffix,
    )


@dataclass
class UserState:
    users: dict = field(default_factory=dict)
    assignments: list = field(default_factory=list)
    report: dict = field(default_factory=dict)
    role_index: dict = field(default_factory=dict)
    tcode_index: dict = field(default_factory=dict)
    groups: list = field(default_factory=list)
    group_count: int = 0


def build_users(path, profile, catalogue):
    parser = UserCsvImport(Path(path).expanduser(), profile)
    state = UserState()
    matcher = RoleMatcher(catalogue)
    matched = {}
    unique_assignments = set()
    for row in parser.records():
        key = normalize_username(row["USERNAME"])
        if key not in state.users and len(state.users) >= MAX_USERS:
            raise AnalysisValidationError(
                "User CSV exceeds the 100,000-user safety limit; no data was applied."
            )
        user = state.users.setdefault(
            key,
            dict(
                username=row["USERNAME"],
                names=set(),
                emails=set(),
                groups=set(),
                accounts=set(),
                assignments=[],
            ),
        )
        user["names"].add((row["FIRST_NAME"], row["LAST_NAME"]))
        if row["EMAIL"]:
            user["emails"].add(row["EMAIL"])
        user["groups"].add(row["USER_GROUP"])
        start, end = sap_date(row["USER_VALID_FROM"]), sap_date(row["USER_VALID_TO"])
        role_start, role_end = sap_date(row["ROLE_VALID_FROM"]), sap_date(
            row["ROLE_VALID_TO"]
        )
        if (start and end and start > end) or (
            role_start and role_end and role_start > role_end
        ):
            raise AnalysisValidationError(
                "A validity interval ends before it starts; no data was applied."
            )
        lock = row["USER_LOCKED"].strip().upper()
        # SU01 UFLAG is a bitmask: any nonzero integer indicates a lock.
        locked = (
            None
            if not lock
            else (
                False
                if lock in {"0", "FALSE", "NO", "N", "UNLOCKED"}
                else (
                    True
                    if lock in {"X", "TRUE", "YES", "Y", "LOCKED"}
                    or (lock.isdigit() and int(lock) != 0)
                    else None
                )
            )
        )
        user["accounts"].add(
            (
                start.isoformat() if start else None,
                end.isoformat() if end else None,
                locked,
                row["USER_TYPE"],
                row["USER_GROUP"],
            )
        )
        if not row["ROLE_NAME"]:
            continue  # Explicit supported directory-only record.
        # Assignment identity preserves group, role spelling and all validity intervals.
        identity = (
            key,
            row["ROLE_NAME"],
            row["USER_GROUP"],
            start,
            end,
            role_start,
            role_end,
            locked,
            row["USER_TYPE"],
        )
        if identity in unique_assignments:
            continue
        unique_assignments.add(identity)
        role = row["ROLE_NAME"]
        if "*" in role:
            raise AnalysisValidationError(
                "User exports require exact assigned role names, not catalogue wildcard patterns."
            )
        normalized = normalize_role(role)
        if normalized not in matched:
            match = matcher.match(role)
            codes = (
                sorted(
                    {
                        tc.tcode
                        for name in match.candidates
                        for sr in catalogue[name].single_roles
                        for tc in sr.tcodes
                    }
                )
                if match.status in {"exact", "wildcard"}
                else []
            )
            matched[normalized] = (match, codes)
        match, codes = matched[normalized]
        entry = dict(
            id=len(state.assignments),
            username=user["username"],
            user_key=key,
            role_name=role,
            user_group=row["USER_GROUP"],
            scope=role_scope(role),
            valid_from=role_start.isoformat() if role_start else None,
            valid_to=role_end.isoformat() if role_end else None,
            user_valid_from=start.isoformat() if start else None,
            user_valid_to=end.isoformat() if end else None,
            user_locked=locked,
            user_type=row["USER_TYPE"],
            match_status=match.status,
            catalogue_roles=list(match.candidates),
            tcodes=codes,
            release=parse_release_role(role) if role_scope(role) == "release" else None,
        )
        state.assignments.append(entry)
        user["assignments"].append(entry)
        if match.status in {"exact", "wildcard"}:
            for name in match.candidates:
                state.role_index.setdefault(name, []).append(entry)
    for name, entries in state.role_index.items():
        for code in {
            tc.tcode.upper() for sr in catalogue[name].single_roles for tc in sr.tcodes
        }:
            state.tcode_index.setdefault(code, []).append(name)
    for user in state.users.values():
        user["names"] = sorted(user["names"])
        user["emails"] = sorted(user["emails"])
        user["groups"] = sorted(user["groups"])
        user["accounts"] = [
            dict(valid_from=a, valid_to=b, locked=c, user_type=d, user_group=e)
            for a, b, c, d, e in sorted(user["accounts"], key=repr)
        ]
    all_groups = {
        group for user in state.users.values() for group in user["groups"] if group
    }
    state.group_count = len(all_groups)
    import heapq

    state.groups = heapq.nsmallest(1000, all_groups)
    state.report = parser.report()
    # Preview stays local and authenticated, but needs no personal-data sample payload.
    state.report["samples"] = []
    state.report.update(
        unique_users=len(state.users),
        assignments=len(state.assignments),
        relevant_assignments=sum(a["scope"] != "other" for a in state.assignments),
        directory_only_users=sum(not u["assignments"] for u in state.users.values()),
        invalid_catalogue_patterns=len(matcher.invalid_patterns),
    )
    return state


def assignment_view(entry):
    return dict(
        entry,
        tcodes=entry["tcodes"][:100],
        tcode_count=len(entry["tcodes"]),
        status=interval_status(
            sap_date(entry["valid_from"]), sap_date(entry["valid_to"])
        ),
        account_status=interval_status(
            sap_date(entry["user_valid_from"]), sap_date(entry["user_valid_to"])
        ),
    )


def relevant(entry, status="", show_expired=False):
    current = interval_status(
        sap_date(entry["valid_from"]), sap_date(entry["valid_to"])
    )
    return current == status if status else show_expired or current != "expired"
