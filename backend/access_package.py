"""Proposed access package: generate SAP role names from catalogue roles with an organizational suffix.

Pure derivations over the imported catalogue; nothing here changes SAP access or any stored data.
Ambiguous source identifiers are reported, never silently rewritten.
"""
from collections import defaultdict
import re

from role_matching import RoleMatcher, normalize_role, role_scope

SUFFIX_PATTERN = re.compile(r'^[A-Z0-9_-]{1,16}$')
NAME_PATTERN = re.compile(r'^[A-Z0-9_:/.-]+$')
MAX_ROLE_NAME = 30  # SAP AGR_NAME length
MIN_STEMS = 2  # a final segment is an organizational suffix when it is used under at least this many role stems


def naming_evidence(names):
    """Final segments of business roles (ZC:) used under several stems, e.g. ENP/ENK/ENS/ENO, with their counts."""
    stems = defaultdict(set)
    for name in names:
        key = normalize_role(name)
        if '*' in key or ':' not in key or role_scope(key) != 'business':
            continue
        stem, _, last = key.rpartition(':')
        if last:
            stems[last].add(stem)
    return {last: len(items) for last, items in stems.items() if len(items) >= MIN_STEMS}


def normalize_suffix(value):
    return normalize_role(value or '').strip(':')


def suffix_error(suffix):
    if not suffix:
        return None
    return None if SUFFIX_PATTERN.match(suffix) else 'Suffix may only use letters, digits, underscore and hyphen (1 to 16 characters).'


def suffix_kind(source, known):
    """How a catalogue role takes an organizational suffix: 'wildcard' (trailing pattern), 'organizational' (its final
    segment is a suffix used under several stems) or None (an exact role name without suffix variants, kept as is)."""
    key = normalize_role(source)
    if '*' in key:
        return 'wildcard'
    if ':' in key and key.rpartition(':')[2] in known:
        return 'organizational'
    return None


def propose(source, suffix, known):
    """-> (generated name or None, kind, message). kind: wildcard | organizational | exact | ambiguous."""
    key = normalize_role(source)
    kind = suffix_kind(key, known)
    if kind is None:
        return key, 'exact', None
    if kind == 'organizational':
        return f"{key.rpartition(':')[0]}:{suffix}", 'organizational', None
    if key.count('*') != 1 or not key.endswith('*') or len(key) == 1:
        return None, 'ambiguous', 'Unsupported wildcard pattern; only a trailing * is supported.'
    prefix = key[:-1]
    if prefix.endswith(':'):
        return prefix + suffix, 'wildcard', None
    partial = prefix.rpartition(':')[2]
    if partial and suffix.startswith(partial):
        return prefix[:-len(partial)] + suffix, 'wildcard', None
    return None, 'ambiguous', f"The pattern keeps the partial segment '{partial}'; the suffix must start with it."


def name_error(name):
    """SAP role name rules shared by every package source: allowed characters and length. Names ending in a colon are
    legitimate catalogue stems and are not rejected."""
    if not NAME_PATTERN.match(name):
        return 'Only A-Z, 0-9 and _ : / . - are allowed in a role name.'
    if len(name) > MAX_ROLE_NAME:
        return f'Longer than {MAX_ROLE_NAME} characters ({len(name)}).'
    return None


EXACT_NOTE = 'Exact role name: the catalogue has no suffix variants for it, so the name is kept.'
# confirmed: the exact name exists in imported explicit roles or assignments; pattern: only a catalogue pattern matches;
# attention: valid-looking or unresolved, cannot be confidently validated; invalid: violates the naming rules.
VALIDATION_LABEL = {'confirmed': 'Confirmed', 'pattern': 'Pattern match', 'attention': 'Needs attention', 'invalid': 'Invalid'}


def preview(default_suffix, items, catalogue, release_roles=None, assigned_roles=None):
    """items: [(role, override_suffix[, source])]; catalogue: {agr_name: description}. Deterministic and order preserving.

    Existence is judged separately from naming validity. Confirmed needs the exact generated name in the imported
    explicit catalogue roles (names without a wildcard) or in user assignments; a wildcard match alone is only a
    Pattern match and a name nothing supports is Needs attention. Exact roles without suffix variants keep their
    name and ignore any suffix. Release roles (from User Access) always keep their exact name. release_roles and
    assigned_roles are sets of normalized role names known to the data.
    """
    known = naming_evidence(catalogue)
    release_roles = release_roles or set()
    explicit = {normalize_role(name) for name in catalogue if '*' not in name} | {normalize_role(name) for name in (assigned_roles or ())}
    matcher = RoleMatcher(list(catalogue))
    default = normalize_suffix(default_suffix)
    rows, seen = [], {}
    exportable_states = {'confirmed', 'pattern'}

    def finish(row, name, validation, exportable=None):
        row.update(name=name, validation=validation, exportable=validation in exportable_states if exportable is None else exportable)
        if name in seen and row['exportable']:
            row.update(status='duplicate', validation='invalid', exportable=False, messages=row['messages'] + ['Same name as another role in the package.'])
        elif row['exportable']:
            seen[name] = row['role']
        return row

    for role, override, *rest in items:
        if rest and rest[0] == 'release':
            name = normalize_role(role)
            row = dict(role=role, description=catalogue.get(role, ''), suffix='', suffix_source='none', suffix_eligible=False, suffix_note=None, name=None,
                       status='ok', validation='attention', exportable=False, messages=[], catalogue=None, source='release')
            rows.append(row)
            if name not in release_roles:
                row.update(status='unknown_role', messages=['Not in the imported User Access data.'])
            elif name_error(name):
                row.update(status='invalid', validation='invalid', messages=[name_error(name)])
            else:
                row['messages'].append('Release role names are kept exactly; no suffix is applied.')
                finish(row, name, 'confirmed')
            continue
        override = normalize_suffix(override)
        kind = suffix_kind(role, known)
        eligible = kind is not None
        suffix = (override or default) if eligible else ''
        row = dict(role=role, description=catalogue.get(role, ''), suffix=suffix, suffix_source=('override' if override else 'default' if default else 'none') if eligible else 'none',
                   suffix_eligible=eligible, suffix_note=None if eligible else EXACT_NOTE, name=None, status='ok', validation='attention', exportable=False, messages=[],
                   catalogue=None, source='catalogue')
        rows.append(row)
        if role not in catalogue:
            row.update(status='unknown_role', messages=['Not in the imported catalogue; re-import or remove it.'])
            continue
        if eligible and not suffix:
            row.update(status='needs_suffix', messages=['Needs suffix: set a package default suffix or a suffix for this role.'])
            continue
        problem = suffix_error(suffix) if eligible else None
        if problem:
            row.update(status='invalid', validation='invalid', messages=[problem])
            continue
        name, _, message = propose(role, suffix, known)
        if name is None:
            row.update(status='ambiguous', messages=[message])
            continue
        problem = name_error(name)
        if problem:
            row.update(status='invalid', validation='invalid', messages=[problem])
            continue
        match = matcher.match(name)
        row['catalogue'] = dict(status=match.status, candidates=list(match.candidates))
        if name in explicit:
            finish(row, name, 'confirmed')
        elif match.status in {'exact', 'wildcard'}:
            row['messages'].append('Matches a catalogue pattern; the exact role is not in the imported data.')
            finish(row, name, 'pattern')
        else:
            row['messages'].append('Not found in imported roles, assignments or catalogue patterns. Check it in SAP before use.')
            finish(row, name, 'attention', exportable=True)
    return rows


def csv_rows(rows):
    """Unique valid generated names in deterministic order: (name, description, suffix, validation)."""
    unique = {row['name']: (row['name'], row['description'] or '', row['suffix'], VALIDATION_LABEL[row['validation']]) for row in reversed(rows) if row['name'] and row['exportable']}
    return sorted(unique.values(), key=lambda item: (item[0].casefold(), item[0]))
