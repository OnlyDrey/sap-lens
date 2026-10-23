"""Shared inclusive assignment-date predicates; account validity is independent."""
from datetime import date
from typing import Literal
from fastapi import HTTPException


def assignment_dates(valid_from_min: date | None = None, valid_from_max: date | None = None,
                     valid_to_min: date | None = None, valid_to_max: date | None = None,
                     open_ended: Literal['', 'only', 'exclude'] = '', include_missing_end: bool = True):
    if (valid_from_min and valid_from_max and valid_from_min > valid_from_max or
            valid_to_min and valid_to_max and valid_to_min > valid_to_max):
        raise HTTPException(422, 'Earliest assignment dates must not follow their latest dates.')
    return dict(valid_from_min=valid_from_min, valid_from_max=valid_from_max,
                valid_to_min=valid_to_min, valid_to_max=valid_to_max, open_ended=open_ended, include_missing_end=include_missing_end)


def within_dates(assignment, filters):
    for field in ['valid_from', 'valid_to']:
        lower, upper = filters[field + '_min'], filters[field + '_max']
        value = date.fromisoformat(assignment[field]) if assignment[field] else None
        if field == 'valid_to' and value is None:
            if filters['include_missing_end']: continue
            return False
        if (lower or upper) and (value is None or lower and value < lower or upper and value > upper):
            return False
    end = assignment['valid_to']
    if filters['open_ended'] == 'only' and end != '9999-12-31': return False
    if filters['open_ended'] == 'exclude' and end == '9999-12-31': return False
    return True
