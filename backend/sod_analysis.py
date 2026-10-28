"""Deterministic potential SoD evidence from imported role/transaction mappings.

No result establishes effective SAP authorization or simultaneous historical use.
"""
import hashlib
import json
from datetime import date

from employee_directory import match_sap_identity, sap_email_owners
from sod_import import EVALUATION_POLICY
from user_access import interval_status, normalize_username, sap_date


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), default=str)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _unique(items):
    return [value for _, value in sorted({_canonical(item): item for item in items}.items())]


def _paths(role, catalogue):
    for single in role.single_roles:
        for code in single.tcodes:
            sources = [source.model_dump() for source in code.assignment_sources]
            yield dict(matched_catalogue_pattern=catalogue, single_role=single.child_agr,
                       assignment_kind=single.assignment_kind, tcode=code.tcode,
                       source_provenance=_unique(sources))


def analyze(snapshot, metadata=None, as_of=None, validity='active', selected_roles=None,
            mapping_enabled=True, directory_enabled=False, sod_enabled=True):
    """Analyze one captured snapshot, with stable per-subject/risk finding identity.

    users/roles contain findings, each with ACTVT1/ACTVT2 evidence arrays.
    Role findings have no assignment validity; selected role combinations are
    explicit only. Sources carry revision references, never fingerprint inputs.
    """
    if validity not in {'active', 'expired', 'future', 'unknown', 'all'}:
        raise ValueError('Unsupported assignment validity filter.')
    day = date.fromisoformat(as_of) if isinstance(as_of, str) else as_of or date.today()
    metadata = metadata or {}
    source = (snapshot.sod or {}) if sod_enabled else {}
    risks = {}
    index = {}
    for risk in source.get('risks', []):
        local = metadata.get(risk['risk_id'], {})
        local = local.get('local', local)
        if not local.get('enabled', True) or not risk.get('supported') or risk.get('evaluation_policy') != EVALUATION_POLICY:
            continue
        risks[risk['risk_id']] = risk
        for slot, mappings in risk['activities'].items():
            for mapping in mappings:
                index.setdefault(mapping['tcode'].upper(), []).append((risk['risk_id'], slot, mapping['activity'], mapping['tcode']))
    catalogue_paths = {name: list(_paths(role, name)) for name, role in snapshot.roles.items()}

    def group(paths):
        grouped = {}
        for path in paths:
            for risk_id, slot, activity, matrix_transaction in index.get(path['tcode'].upper(), []):
                sides = grouped.setdefault(risk_id, {'ACTVT1': [], 'ACTVT2': []})
                sides[slot].append(dict(path, activity_slot=slot, activity=activity, matrix_transaction=matrix_transaction))
        return {risk_id: {slot: _unique(items) for slot, items in sides.items()}
                for risk_id, sides in grouped.items() if all(sides.values())}

    def findings(subject, kind, paths, account=None):
        result = []
        for risk_id, evidence in sorted(group(paths).items()):
            current = kind == 'user' and all(any(item['interval_status'] == 'active' for item in evidence[slot]) for slot in evidence)
            result.append(dict(finding_id=_digest([1, kind, subject, risk_id, EVALUATION_POLICY]),
                               subject=subject, kind=kind, risk_id=risk_id, criticality=risks[risk_id]['criticality'],
                               evaluation_policy=EVALUATION_POLICY, evidence=evidence,
                               current_potential=current, account=account,
                               evidence_version=_digest([risks[risk_id], evidence, account])))
        return result

    role_results = []
    for name, paths in sorted(catalogue_paths.items()):
        role_results.extend(findings(name, 'role', paths))
    if selected_roles is not None and (not isinstance(selected_roles, (list, tuple)) or len(selected_roles) > 25
                                       or any(not isinstance(name, str) for name in selected_roles)):
        raise ValueError('Select at most 25 existing catalogue roles.')
    selected = sorted(set(selected_roles or []))
    if any(name not in catalogue_paths for name in selected):
        raise ValueError('A selected catalogue role is unavailable in the current dataset.')
    if len(selected) > 1:
        role_results.extend(findings(selected, 'role_combination',
                                     [path for name in selected for path in catalogue_paths.get(name, [])]))
    users_available = bool(mapping_enabled and snapshot.users.users and snapshot.roles and source)
    user_results = []
    matched_assignments = eligible_assignments = 0
    directory = snapshot.directory if directory_enabled else None
    owners = sap_email_owners(snapshot.users.users.values()) if directory else {}
    if users_available:
        for key, user in sorted(snapshot.users.users.items()):
            paths = []
            for assignment in user['assignments']:
                status = interval_status(sap_date(assignment.get('valid_from')), sap_date(assignment.get('valid_to')), day)
                if validity != 'all' and status != validity:
                    continue
                eligible_assignments += 1
                if assignment['match_status'] not in {'exact', 'wildcard'}:
                    continue
                assignment_paths = [path for name in assignment['catalogue_roles'] for path in catalogue_paths.get(name, [])]
                if assignment_paths:
                    matched_assignments += 1
                for path in assignment_paths:
                    paths.append(dict(path, actual_assigned_role=assignment['role_name'],
                                      matching_status=assignment['match_status'],
                                      role_valid_from=assignment.get('valid_from'), role_valid_to=assignment.get('valid_to'),
                                      interval_status=status, user_group=assignment.get('user_group', '')))
            match = match_sap_identity(directory, user, owners) if directory else {'status': 'directory_unavailable' if directory_enabled else 'directory_disabled', 'employee': None}
            employee = match['employee']
            account = dict(accounts=_unique(user.get('accounts', [])), directory_match=match['status'],
                           ad_status=employee.get('account_status', 'Unknown') if employee else 'Unknown')
            user_results.extend(findings(normalize_username(key), 'user', paths, account))
    reason = None if users_available else ('sod_disabled' if not sod_enabled else 'mapping_disabled' if not mapping_enabled else 'required_source_unavailable')
    return dict(users=user_results, roles=role_results,
                summary=dict(user_findings=len(user_results), role_findings=len(role_results),
                             users_with_findings=len({item['subject'] for item in user_results}),
                             current_potential_findings=sum(item['current_potential'] for item in user_results)),
                coverage=dict(status='available' if users_available else 'unavailable', reason=reason,
                              eligible_assignment_records=eligible_assignments, mapped_assignment_records=matched_assignments,
                              unmapped_assignment_records=eligible_assignments - matched_assignments,
                              roles_available=bool(snapshot.roles),
                              supported_risks=len(risks)),
                methodology=dict(policy=EVALUATION_POLICY, validity=validity,
                                 evidence='Potential transaction-derived SoD; not effective SAP authorization.',
                                 historical='All-validity findings do not prove concurrent historical access.',
                                 role_validity='Catalogue role coverage has no assignment validity.'),
                as_of=day.isoformat(), sources=dict(sod_content_hash=source.get('content_hash'),
                                                   sap_revision=snapshot.last_loaded.isoformat() if snapshot.last_loaded else None))
