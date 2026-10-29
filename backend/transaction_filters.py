"""Bounded exact T-code filters; no role/authorization inference."""
from fastapi import HTTPException
from search_matching import text_matches


def normalized_tcodes(values):
    if len(values) > 21:
        raise HTTPException(422, 'At most 20 saved transaction filters and one draft are supported.')
    if any(len(value) > 128 for value in values):
        raise HTTPException(422, 'Transaction filters must not exceed 128 characters.')
    return tuple(dict.fromkeys(value.strip().upper() for value in values if value.strip()))


def matching_role_names(index, codes, mode='and'):
    """Combine aggregate role transaction sets, never individual CSV rows."""
    if not codes: return set()
    groups = [{role for actual in matching_codes(index,code) for role in index[actual]} for code in codes]
    return set.intersection(*groups) if mode == 'and' else set.union(*groups)


def matching_codes(index, query):
    """Expand explicit user patterns; ordinary selected T-codes stay exact."""
    return [code for code in index if text_matches(code,query)] if '*' in query else ([query] if query in index else [])


def select_role_names(index, include=(), include_mode='all', exclude=(), exclude_mode='any'):
    """Independent include and exclude transaction groups; an empty group is inactive.

    Include: ALL = holds every code, ANY = holds at least one. Exclude: ANY removes roles holding at least one of the codes,
    ALL removes only roles holding every code. A role must satisfy include and must not satisfy the exclusion. Absence is only
    concluded among roles that have at least one mapped transaction: roles without mappings are never returned by an exclusion."""
    selected = None
    if include:
        selected = matching_role_names(index, include, 'and' if include_mode == 'all' else 'or')
    if exclude:
        holding = set().union(*index.values()) if index else set()
        removed = matching_role_names(index, exclude, 'or' if exclude_mode == 'any' else 'and')
        selected = (holding if selected is None else selected & holding) - removed
    return selected if selected is not None else set()


def legacy_groups(codes, mode, exclude):
    """The earlier single list with an exclude switch expressed as the two groups: AND-exclude = exclude ALL, OR-exclude = exclude ANY."""
    if exclude:
        return (), 'all', codes, 'all' if mode == 'and' else 'any'
    return codes, 'all' if mode == 'and' else 'any', (), 'any'


def role_names_for(index, codes, mode='and', exclude=False):
    """Positive: AND = contains every code, OR = contains any. Exclude is the complement among roles that have at least one mapping,
    so AND excludes roles holding all codes together and OR excludes roles holding any; roles without mappings never match."""
    positive = matching_role_names(index, codes, mode)
    if not exclude: return positive
    holding = set().union(*index.values()) if index else set()
    return holding - positive
