"""Bounded exact T-code filters; no role/authorization inference."""
from fastapi import HTTPException


def normalized_tcodes(values):
    if len(values) > 21:
        raise HTTPException(422, 'At most 20 saved transaction filters and one draft are supported.')
    if any(len(value) > 128 for value in values):
        raise HTTPException(422, 'Transaction filters must not exceed 128 characters.')
    return tuple(dict.fromkeys(value.strip().upper() for value in values if value.strip()))
