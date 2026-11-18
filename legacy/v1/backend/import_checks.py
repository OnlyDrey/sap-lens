"""Import anomaly detection: is a structurally valid replacement source plausible against the active revision of the same source?

Two different outcomes exist and must not be confused:
* invalid: the file is structurally unusable (no records, bad headers or dates). That is rejected by parsing and can never be confirmed.
* suspicious: a valid file that shrinks sharply or loses whole groups compared with the previous activated revision of that source.
  It is staged and reported, not activated, until an authorized user confirms it.

Only the active revision of the same source is compared (never another source, never an unactivated or held file). A first import has nothing to
compare with and is never held. The rules are pure functions of the two record lists, so they are deterministic and testable."""
from collections import Counter

# Per source: (metric label, record field, case-insensitive distinct count) and the field whose values form "organizational groups".
SPEC = {
    'roles': dict(entities=(('role catalogue entries', 'AGR_NAME'), ('transactions', 'TCODE')), groups=('FUNCTION_KEY', 'SAP module area')),
    'users': dict(entities=(('SAP users', 'USERNAME'), ('assigned roles', 'ROLE_NAME')), groups=('USER_GROUP', 'SAP user group')),
    'employees': dict(entities=(('directory accounts', 'SamAccountName'),), groups=('Department', 'department')),
    'sod': dict(entities=(('risks', 'RISK'),), groups=None),
}
GROUP_MIN_ROWS = 5   # a vanished group only matters when it held at least this many records (and at least 1% of the previous source)


def _norm(value):
    return str(value or '').strip().casefold()


def metrics(source, rows):
    spec = SPEC[source]
    result = {'records': len(rows)}
    for label, field in spec['entities']:
        result[label] = len({_norm(row.get(field)) for row in rows if _norm(row.get(field))})
    return result


def group_sizes(source, rows):
    spec = SPEC[source]
    if not spec['groups']:
        return {}
    field = spec['groups'][0]
    return dict(Counter(_norm(row.get(field)) for row in rows if _norm(row.get(field))))


def evaluate(source, before, after, checks):
    """-> dict(suspicious: bool, anomalies: [...], old: {...}, new: {...}). `checks` is the ImportChecks setting."""
    old, new = metrics(source, before), metrics(source, after)
    anomalies = []
    if checks.enabled and len(before) >= checks.min_previous_records:
        limit = checks.max_drop_percent
        for label, previous in old.items():
            current = new[label]
            if previous and current < previous * (1 - limit / 100):
                anomalies.append(dict(rule='drop', metric=label, old=previous, new=current, percent=round(100 * (previous - current) / previous, 1), threshold=limit,
                                      message=f'{label} fell from {previous:,} to {current:,} ({round(100 * (previous - current) / previous, 1)} %, limit {limit} %).'))
        spec = SPEC[source]
        if spec['groups']:
            was, now = group_sizes(source, before), group_sizes(source, after)
            floor = max(GROUP_MIN_ROWS, len(before) // 100)
            for name in sorted(group for group, size in was.items() if group not in now and size >= floor):
                anomalies.append(dict(rule='group_missing', metric=spec['groups'][1], group=name, old=was[name], new=0,
                                      message=f'All {was[name]:,} records of {spec["groups"][1]} "{name}" are missing from the new file.'))
    return dict(suspicious=bool(anomalies), anomalies=anomalies, old=old, new=new)


class ImportHeld(Exception):
    """A valid but suspicious replacement was staged and reported, not activated. It can be activated only after explicit confirmation."""

    def __init__(self, source, evaluation):
        self.source, self.evaluation = source, evaluation
        super().__init__('The new file differs sharply from the active data and needs explicit confirmation. Previous data is retained.')

    def detail(self):
        return dict(code='import_needs_confirmation', source=self.source, message=str(self), anomalies=self.evaluation['anomalies'],
                    old=self.evaluation['old'], new=self.evaluation['new'])
