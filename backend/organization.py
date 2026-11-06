"""User-level organizational context shared by User Access, Account Review and SoD filters: Functional Group and direct Manager.

Both come from stored or imported evidence only: the classification store and the Employee Directory match that already refuses missing,
duplicate and ambiguous identities. Manager is the imported reporting link (manager mail), never inferred from Department. Unmatched users
have manager key `none`; users without a classification are `unassigned`."""
import functional_groups as fg
from employee_directory import identity_matcher, normalized

NO_USER = '\u0000'  # sentinel that matches no SAP user: an empty selection result must still filter everything out


def users_of(state):
    """SAP users with the identity fields the matchers need, tolerating partial records (the key is the canonical user name)."""
    return [dict(user, username=user.get('username') or key, emails=user.get('emails', [])) for key, user in state.users.users.items()]


def manager_key_for(employee):
    manager = (employee or {}).get('manager') or {}
    return normalized(manager.get('email', '')) or 'none'


def manager_map(state, directory):
    """{UPPER SAP USER: manager key} for every user (`none` when unmatched or the manager is unknown)."""
    if not directory:
        return {}
    matcher = identity_matcher(state.users, directory)
    result = {}
    for user in users_of(state):
        match = matcher(user)
        result[user['username'].strip().upper()] = manager_key_for(match['employee']) if match['status'] == 'matched' else 'none'
    return result


def group_keys(classifications, username):
    """Filter keys of one user: the id of every Functional Group they belong to, or 'unassigned' when they belong to none."""
    return (classifications.get(username.strip().upper()) or {}).get('group_ids') or ['unassigned']


def selection(state, directory, functional_groups=(), managers=()):
    """Predicate on a SAP user dict, or None when no organizational filter is active. OR within a filter, AND between them."""
    if not functional_groups and not managers:
        return None
    wanted_groups, wanted_managers = set(functional_groups), {normalized(value) for value in managers}
    classes = fg.classification_map() if wanted_groups else {}
    matcher = identity_matcher(state.users, directory) if wanted_managers and directory else None

    def keep(user):
        if wanted_groups and not wanted_groups.intersection(group_keys(classes, user['username'])):
            return False
        if wanted_managers:
            key = 'none'
            if directory:
                match = matcher(user)
                key = manager_key_for(match['employee']) if match['status'] == 'matched' else 'none'
            if key not in wanted_managers:
                return False
        return True
    return keep


def expand_usernames(state, directory, usernames, functional_groups=(), managers=(), universe=()):
    """SoD filters select users by name: translate the organizational selection into the existing `usernames` list.

    `universe` are the SoD subjects of the evaluated context. A subject without a User Access record has no Directory match (manager `none`) and
    counts as Unassigned unless it is classified, so the SoD matrix can be filtered even when its users are not in the SAP user import."""
    keep = selection(state, directory, functional_groups, managers)
    if keep is None:
        return list(usernames)
    people = users_of(state)
    known = {user['username'].strip().upper() for user in people}
    extra = [dict(username=name, emails=[], names=[], groups=[]) for name in universe if name.strip().upper() not in known]
    allowed = [user['username'] for user in [*people, *extra] if keep(user)]
    if usernames:
        existing = {name.strip().casefold() for name in usernames}
        allowed = [name for name in allowed if name.strip().casefold() in existing]
    return allowed or [NO_USER]


def options(state, directory):
    """Group and manager choices with the number of SAP users, for filters outside Account Review."""
    classes = fg.classification_map()
    groups = {g['id']: g for g in fg.list_groups()}
    counts, managers = {}, {}
    for user in users_of(state):
        for key in group_keys(classes, user['username']):
            counts[key] = counts.get(key, 0) + 1
    labels = {}
    if directory:
        matcher = identity_matcher(state.users, directory)
        for user in users_of(state):
            match = matcher(user)
            key = manager_key_for(match['employee']) if match['status'] == 'matched' else 'none'
            managers[key] = managers.get(key, 0) + 1
            if key != 'none':
                manager = match['employee']['manager']
                labels[key] = manager['name'] or manager['email']
    group_options = [dict(value='unassigned', label='Unassigned', count=counts.get('unassigned', 0))]
    group_options += [dict(value=g['id'], label=g['name'] + (' (archived)' if g['status'] == 'archived' else ''), count=counts.get(g['id'], 0))
                      for g in groups.values() if g['status'] == 'active' or counts.get(g['id'])]
    manager_options = sorted((dict(value=key, label=labels.get(key, 'No manager'), count=count) for key, count in managers.items()),
                             key=lambda o: (o['value'] == 'none', o['label'].casefold(), o['value']))
    return dict(functional_groups=group_options, managers=manager_options)


def annotate(page):
    """Add the SAP Lens-maintained Functional Group and classification status to the rows of one result page (never the whole dataset)."""
    classes = fg.classification_map()
    for item in page.get('items', []):
        record = classes.get(item['username'].strip().upper())
        item['functional_group'] = record['group'] if record else None  # only when the user has exactly one membership (compatibility)
        item['functional_groups'] = [m['group'] for m in record['memberships']] if record else []
        item['classification_status'] = record['status'] if record else 'Unassigned'
    return page
