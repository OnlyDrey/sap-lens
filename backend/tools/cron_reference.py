"""Python v1 reference for MIG-008 (cron_schedule.py and POST /api/refresh-schedule/preview).
Records, for fixed instants, the next runs of daily and cron expressions in UTC and IANA zones (including the spring-forward gap and the repeated
autumn hour), readable descriptions, parse and validation errors, and the preview route's answer for a set of drafts (its clock fixed).
Usage: python -I tools/cron_reference.py BACKEND_DIR OUT_JSON"""
import json, os, sys, tempfile
from datetime import datetime, timezone
os.environ['SAP_LENS_CONFIG_DIR'] = tempfile.mkdtemp()
backend, target = sys.argv[1:3]
sys.path.insert(0, backend)
import cron_schedule as schedule
import routers.refresh_schedule as routes

expressions = ['0 6 * * *', '30 6 * * 1-5', '*/15 * * * *', '0 */4 * * *', '15 * * * *', '0 2 * * *', '30 2 * * *', '0 1,13 * * *', '5,35 8-17 * * MON-FRI',
               '0 0 1 * *', '0 7 1,15 * *', '0 7 * * 0,6', '0 7 * * 7', '0 7 13 * 5', '0 9 * JAN,JUL *', '0 9 29 2 *', '10-50/20 9 * * *', '0 12 * * SUN-SAT', '*/30 9-11 * * *']
zones = ['UTC', 'Europe/Oslo', 'America/New_York', 'Asia/Kolkata', 'Australia/Lord_Howe']
instants = ['2026-03-28T23:59:00+00:00', '2026-03-29T00:30:00+00:00', '2026-10-24T23:00:00+00:00', '2026-11-01T04:30:00+00:00', '2026-11-16T06:00:00+00:00',
            '2027-02-27T12:34:56.789000+00:00', '2026-04-04T14:00:00+00:00']
runs = []
for expression in expressions:
    for zone in zones:
        for instant in instants:
            after = datetime.fromisoformat(instant)
            runs.append(dict(expression=expression, zone=zone, after=instant, next=[r.isoformat() for r in schedule.next_runs(expression, zone, after, 4)]))
describe = [dict(expression=e, zone=z, text=schedule.describe(e, z)) for e in expressions for z in ('local', 'UTC', 'Europe/Oslo')]
errors = []
for expression in ['0 6 * *', '60 6 * * *', '0 24 * * *', '0 6 0 * *', '0 6 * 13 *', '0 6 * * 8', '0 6 * * FOO', '*/0 * * * *', '5-1 * * * *', ',0 6 * * *',
                   '0 6 * * MON-', 'a 6 * * *', '0 6 * JAN-FEB/2 *', '0 6 * * 1/2', '0 6 32 * *']:
    try: schedule.parse_cron(expression); errors.append(dict(expression=expression, error=None))
    except ValueError as error: errors.append(dict(expression=expression, error=str(error)))
now = datetime(2026, 11, 16, 8, 0, 0, 123456, tzinfo=timezone.utc)
checks = []
for expression, zone in [('*/2 * * * *', 'UTC'), ('*/5 * * * *', 'UTC'), ('0 0 31 2 *', 'UTC'), ('0 6 * * *', 'Mars/Olympus'), ('0 6 * * *', 'Europe/Oslo')]:
    try: checks.append(dict(expression=expression, zone=zone, runs=[r.isoformat() for r in schedule.check(expression, zone, now)], error=None))
    except ValueError as error: checks.append(dict(expression=expression, zone=zone, runs=None, error=str(error)))
daily = []
for time in ['06:00', '6:00', '23:59', '24:00', '07:60', '', '0630']:
    try: daily.append(dict(time=time, cron=schedule.daily_cron(time)))
    except ValueError as error: daily.append(dict(time=time, error=str(error)))


class Fixed(datetime):
    @classmethod
    def now(cls, tz=None): return now


routes.datetime = Fixed
preview = routes.refresh_schedule_router(None, None).routes[-1].endpoint
drafts = [dict(mode='daily', time='06:30', timezone='Europe/Oslo'), dict(mode='daily', time='25:00', timezone='UTC'), dict(mode='cron', cron='*/2 * * * *', timezone='UTC'),
          dict(mode='cron', cron='0 6 * *', timezone='UTC'), dict(mode='cron', cron='0 */4 * * *', timezone='America/New_York', enabled=True),
          dict(mode='weekly', time='06:00'), dict(mode='daily', time='06:00:00'), dict(mode='daily', timezone='Europe/Oslo/x/y'), dict(mode='daily', timezone='Nowhere/Zone'),
          dict(mode='daily', extra=1), dict(mode='cron', cron='0 0 31 2 *', timezone='UTC'), dict(), dict(enabled='maybe')]
previews = [dict(draft=draft, result=preview(draft)) for draft in drafts]
with open(target, 'w', encoding='utf-8') as handle:
    json.dump(dict(runs=runs, describe=describe, errors=errors, checks=checks, daily=daily, previews=previews, now=now.isoformat()), handle, indent=0, sort_keys=True)
    handle.write('\n')
print(len(runs), 'next-run cases,', len(describe), 'descriptions,', len(errors), 'parse cases,', len(previews), 'previews')
