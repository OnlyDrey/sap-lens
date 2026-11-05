"""Advisory comparison of SAP role assignments inside one Functional Group.

Transparent and deterministic. Unique (user, role) pairs from currently active assignments only; duplicated activity, risk or interval rows never
count twice. Role frequency = members holding the role / eligible members. A group is never judged by a score and nothing here grants,
removes or approves access: the output only suggests where to look."""
from role_matching import normalize_role
from user_access import interval_status, sap_date

COMMON_AT = 0.6      # a role held by at least 60% of eligible members is "common"
UNCOMMON_AT = 0.25   # a role held by at most 25% of eligible members is "uncommon"
MIN_MEMBERS = 3      # fewer eligible members are listed but not compared


def active_roles(user, today=None):
    """Unique normalized role names with at least one active interval, mapped to the displayed role name."""
    roles = {}
    for assignment in user.get('assignments', []):
        if interval_status(sap_date(assignment['valid_from']), sap_date(assignment['valid_to']), today) == 'active':
            roles.setdefault(normalize_role(assignment['role_name']), assignment['role_name'])
    return roles


def analyse(state, members, group, today=None):
    """`members`: usernames classified in the group. Members without a SAP user record are reported, not compared."""
    by_name = {(u.get('username') or key).strip().upper(): u for key, u in state.users.users.items()}
    eligible = {}
    for name in sorted(members, key=str.casefold):
        user = by_name.get(name.strip().upper())
        if user is not None:
            eligible[user.get('username') or name] = active_roles(user, today)
    missing = sorted(name for name in members if name.strip().upper() not in by_name)
    limitations = []
    if missing:
        limitations.append(f'{len(missing)} classified member(s) are not in the SAP user import and were not compared.')
    if len(eligible) < MIN_MEMBERS:
        limitations.append(f'Only {len(eligible)} comparable member(s): at least {MIN_MEMBERS} are needed before common and uncommon roles mean anything.')
    total = len(eligible)
    holders, labels = {}, {}
    for username, roles in eligible.items():
        for role, label in roles.items():
            holders.setdefault(role, []).append(username)
            labels.setdefault(role, label)
    comparable = total >= MIN_MEMBERS
    rows = []
    for role in sorted(holders, key=lambda r: (-len(holders[r]), labels[r].casefold())):
        frequency = len(holders[role]) / total
        kind = 'not compared' if not comparable else 'common' if frequency >= COMMON_AT else 'uncommon' if frequency <= UNCOMMON_AT else 'shared'
        rows.append(dict(role=labels[role], users=len(holders[role]), eligible=total, frequency=round(frequency, 4), kind=kind))
    kinds = {normalize_role(r['role']): r['kind'] for r in rows}
    users = []
    for username, roles in eligible.items():
        extra = sorted((labels[r] for r in roles if comparable and kinds[r] == 'uncommon'), key=str.casefold)
        lacking = sorted((labels[r] for r in holders if comparable and kinds[r] == 'common' and r not in roles), key=str.casefold)
        users.append(dict(username=username, roles=len(roles), additional_roles=extra, missing_common_roles=lacking))
    users.sort(key=lambda u: (-(len(u['additional_roles']) + len(u['missing_common_roles'])), u['username'].casefold()))
    return dict(group=dict(id=group['id'], name=group['name'], status=group['status']), members=len(members), eligible=total, not_in_import=missing,
                distinct_roles=len(rows), common_roles=sum(r['kind'] == 'common' for r in rows), deviations=sum(bool(u['additional_roles'] or u['missing_common_roles']) for u in users),
                roles=rows, users=users, limitations=limitations, comparable=comparable,
                method=dict(common_at=COMMON_AT, uncommon_at=UNCOMMON_AT, min_members=MIN_MEMBERS,
                            note='Advisory only. Roles are unique active user and role pairs; a deviation is a prompt to investigate, not a finding.'))
