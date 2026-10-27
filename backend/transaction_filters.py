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
