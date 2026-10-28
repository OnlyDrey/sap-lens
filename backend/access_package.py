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


def propose(source, suffix, known, explicit=False):
    """-> (generated name or None, kind, message). kind: wildcard | organizational | ambiguous."""
    key = normalize_role(source)
    if '*' in key:
        if key.count('*') != 1 or not key.endswith('*') or len(key) == 1:
            return None, 'ambiguous', 'Unsupported wildcard pattern; only a trailing * is supported.'
        prefix = key[:-1]
        if prefix.endswith(':'):
            return prefix + suffix, 'wildcard', None
        partial = prefix.rpartition(':')[2]
        if partial and suffix.startswith(partial):
            return prefix[:-len(partial)] + suffix, 'wildcard', None
        return None, 'ambiguous', f"The pattern keeps the partial segment '{partial}'; the suffix must start with it."
    if ':' not in key:
        return None, 'ambiguous', 'The role name has no segment structure, so a suffix position cannot be determined.'
    stem, _, last = key.rpartition(':')
    if last in known:
        return f'{stem}:{suffix}', 'organizational', None
    if explicit:
        return f'{stem}:{suffix}', 'organizational', f"The last segment '{last}' is not a known organizational suffix; it was replaced because this role has an explicit suffix."
    return None, 'ambiguous', f"The last segment '{last}' is not a known organizational suffix. Set an explicit suffix for this role to replace it."


def preview(default_suffix, items, catalogue):
    """items: [(role, override_suffix)]; catalogue: {agr_name: description}. Deterministic and order preserving."""
    known = naming_evidence(catalogue)
    matcher = RoleMatcher(list(catalogue))
    default = normalize_suffix(default_suffix)
    rows, seen = [], {}
    for role, override in items:
        override = normalize_suffix(override)
        suffix = override or default
        row = dict(role=role, description=catalogue.get(role, ''), suffix=suffix, suffix_source='override' if override else 'default' if default else 'none',
                   name=None, status='ok', messages=[], catalogue=None)
        rows.append(row)
        if role not in catalogue:
            row.update(status='unknown_role', messages=['The role is not in the imported catalogue.'])
            continue
        if not suffix:
            row.update(status='needs_suffix', messages=['Set a package default suffix or a suffix for this role.'])
            continue
        problem = suffix_error(suffix)
        if problem:
            row.update(status='invalid', messages=[problem])
            continue
        name, _, message = propose(role, suffix, known, explicit=bool(override))
        if name is None:
            row.update(status='ambiguous', messages=[message])
            continue
        if message:
            row['messages'].append(message)
        if len(name) > MAX_ROLE_NAME or not NAME_PATTERN.match(name):
            row.update(status='invalid', messages=row['messages'] + [f'The generated name {name} is not a valid SAP role name (up to {MAX_ROLE_NAME} characters of A-Z, 0-9, _ : / . -).'])
            continue
        row['name'] = name
        match = matcher.match(name)
        row['catalogue'] = dict(status=match.status, candidates=list(match.candidates))
        if name in seen:
            row.update(status='duplicate', messages=row['messages'] + [f'Same generated name as {seen[name]}.'])
        else:
            seen[name] = role
    return rows


def csv_rows(rows):
    """Unique generated names in deterministic order: (name, description, suffix)."""
    unique = {row['name']: (row['name'], row['description'] or '', row['suffix']) for row in reversed(rows) if row['name'] and row['status'] in {'ok'}}
    return sorted(unique.values(), key=lambda item: (item[0].casefold(), item[0]))
