"""Scheduled refresh rules: daily time or a five-field cron expression, evaluated in a chosen time zone.

Pure functions, no dependencies. Time zones come from the platform database (``local`` and ``UTC`` always work).
Spring-forward gaps are skipped and a repeated hour runs once."""
import re
from datetime import datetime, timedelta, timezone

MIN_INTERVAL = timedelta(minutes=5)
FIELDS = (('minute', 0, 59), ('hour', 0, 23), ('day of month', 1, 31), ('month', 1, 12), ('day of week', 0, 6))
MONTHS = {name: i + 1 for i, name in enumerate('JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC'.split())}
DAYS = {name: i for i, name in enumerate('SUN MON TUE WED THU FRI SAT'.split())}
MONTH_NAMES = 'January February March April May June July August September October November December'.split()
DAY_NAMES = 'Sunday Monday Tuesday Wednesday Thursday Friday Saturday'.split()
HORIZON_DAYS = 366 * 5


def zone(name):
    """tzinfo for 'local', 'UTC' or an IANA name; ValueError when the platform has no such zone."""
    if name == 'local':
        return datetime.now().astimezone().tzinfo
    if name == 'UTC':
        return timezone.utc
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 - missing database and unknown names read the same to a user
        raise ValueError(f"Time zone '{name}' is not available on this system. Choose Local time, UTC, or an installed IANA zone such as Europe/Oslo.") from None


def _number(token, low, high, names, label, dow=False):
    token = token.upper()
    value = names[token] if token in names else int(token) if token.isdigit() else None
    if value is None:
        raise ValueError(f'Invalid {label} value {token!r}.')
    if dow and value == 7:
        value = 0
    if not low <= value <= high:
        raise ValueError(f'The {label} must be between {low} and {high}.')
    return value


def _field(text, index):
    label, low, high = FIELDS[index]
    names = MONTHS if index == 3 else DAYS if index == 4 else {}
    values = set()
    if not text:
        raise ValueError(f'The {label} field is empty.')
    for part in text.split(','):
        step = 1
        if '/' in part:
            part, _, raw = part.partition('/')
            if not raw.isdigit() or int(raw) < 1:
                raise ValueError(f'Invalid step in the {label} field.')
            step = int(raw)
        if part == '*':
            start, end = low, high
        elif '-' in part:
            first, _, last = part.partition('-')
            start, end = _number(first, low, high + (1 if index == 4 else 0), names, label, index == 4), _number(last, low, high + (1 if index == 4 else 0), names, label, index == 4)
            if start > end:
                raise ValueError(f'The range in the {label} field is reversed.')
        else:
            start = _number(part, low, high + (1 if index == 4 else 0), names, label, index == 4)
            end = high if step > 1 else start
        values.update(range(start, end + 1, step))
    return values


def parse_cron(expression):
    parts = expression.split()
    if len(parts) != 5:
        raise ValueError('A cron expression has five fields: minute hour day-of-month month day-of-week.')
    sets = [_field(part, i) for i, part in enumerate(parts)]
    return dict(minute=sets[0], hour=sets[1], dom=sets[2], month=sets[3], dow=sets[4], dom_any=parts[2] == '*', dow_any=parts[4] == '*')


def daily_cron(time):
    match = re.fullmatch(r'([01]\d|2[0-3]):([0-5]\d)', time or '')
    if not match:
        raise ValueError('Enter the daily time as HH:MM (24-hour).')
    return f'{int(match.group(2))} {int(match.group(1))} * * *'


def _day_matches(rule, day):
    dow = (day.weekday() + 1) % 7
    in_dom, in_dow = day.day in rule['dom'], dow in rule['dow']
    if rule['dom_any'] and rule['dow_any']:
        return True
    if rule['dom_any']:
        return in_dow
    if rule['dow_any']:
        return in_dom
    return in_dom or in_dow  # standard cron: either restriction may match


def next_runs(expression, tz_name, after, count=1):
    """Next ``count`` UTC run times strictly after ``after`` (aware datetime)."""
    rule, tz = parse_cron(expression), zone(tz_name)
    if tz_name == 'local':  # the platform converts per instant, so daylight saving changes are followed
        to_local = lambda moment: moment.astimezone().replace(tzinfo=None)
        to_utc = lambda naive: naive.astimezone(timezone.utc)
    else:
        to_local = lambda moment: moment.astimezone(tz).replace(tzinfo=None)
        to_utc = lambda naive: naive.replace(tzinfo=tz, fold=0).astimezone(timezone.utc)
    local = to_local(after).replace(second=0, microsecond=0)
    day, found, first = local.date(), [], True
    for _ in range(HORIZON_DAYS):
        if day.month in rule['month'] and _day_matches(rule, day):
            for hour in sorted(rule['hour']):
                for minute in sorted(rule['minute']):
                    candidate = datetime(day.year, day.month, day.day, hour, minute)
                    if first and candidate <= local:
                        continue
                    utc = to_utc(candidate)
                    if to_local(utc) != candidate or utc <= after:
                        continue  # nonexistent local time in a spring-forward gap
                    found.append(utc)
                    if len(found) == count:
                        return found
        day += timedelta(days=1)
        first = False
    return found


def check(expression, tz_name, now=None):
    """Validate: parse, time zone and minimum interval. Returns the next five runs."""
    now = now or datetime.now(timezone.utc)
    runs = next_runs(expression, tz_name, now, 6)
    if not runs:
        raise ValueError('The expression never runs within the next five years.')
    if any(b - a < MIN_INTERVAL for a, b in zip(runs, runs[1:])):
        raise ValueError('Refreshes must be at least 5 minutes apart.')
    return runs[:5]


def _list(values, names=None, offset=0):
    items = sorted(values)
    return ', '.join(names[v - offset] if names else str(v) for v in items)


def describe(expression, tz_name):
    """Readable sentence for the schedule, for example 'At 06:30 every day (Europe/Oslo)'."""
    rule = parse_cron(expression)
    parts = expression.split()
    zone_text = {'local': 'local time', 'UTC': 'UTC'}.get(tz_name, tz_name)
    minutes, hours = sorted(rule['minute']), sorted(rule['hour'])
    if len(minutes) == 1 and len(hours) == 1:
        when = f'At {hours[0]:02d}:{minutes[0]:02d}'
    elif parts[1] == '*' and parts[0].startswith('*/'):
        when = f'Every {parts[0][2:]} minutes'
    elif parts[1] == '*' and len(minutes) == 1:
        when = f'Every hour at minute {minutes[0]}'
    elif parts[1].startswith('*/') and len(minutes) == 1:
        when = f'Every {parts[1][2:]} hours at minute {minutes[0]}'
    elif len(minutes) == 1:
        when = f'At minute {minutes[0]} past hour {_list(hours)}'
    else:
        when = f'At minutes {_list(minutes)} past hour {_list(hours) if len(hours) < 24 else "every hour"}'
    scope = []
    if not rule['dom_any']:
        scope.append(f'on day {_list(rule["dom"])} of the month')
    if not rule['dow_any']:
        weekdays = sorted(rule['dow'])
        scope.append('on weekdays' if weekdays == [1, 2, 3, 4, 5] else 'on weekends' if weekdays == [0, 6] else 'on ' + _list(weekdays, DAY_NAMES))
    if parts[3] != '*':
        scope.append('in ' + _list(rule['month'], MONTH_NAMES, 1))
    return f'{when} {" ".join(scope) if scope else "every day"} ({zone_text})'
