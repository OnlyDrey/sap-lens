"""Python v1 reference for MIG-010 (GET /api/data-sources/reports/{id} and /reports/{id}/export).
Derives a before and an after CSV per source (roles, users, employees, SoD) from the synthetic fixtures, with modified, removed, added, ambiguous
and unidentified records, a spreadsheet formula, quotes and commas. Writes them to FIXTURE_DIR (as .txt) and records what v1 returns: the source
result of csv_lifecycle.diff_records over the records v1 itself parses (cache._build_catalog, build_users, parse_directory, parse_sod), then the
routers/data_sources.py `details` page and `export` CSV for a set of filters, over a report holding that result.
Usage: python -I tools/refresh_report_reference.py BACKEND_DIR FIXTURE_DIR"""
import asyncio, json, os, shutil, sys, tempfile
os.environ['SAP_LENS_CONFIG_DIR'] = tempfile.mkdtemp()
backend, fixtures = sys.argv[1:3]
sys.path.insert(0, backend)
from pathlib import Path
import cache, config
from csv_lifecycle import diff_records
from employee_directory import parse_directory, HEADERS
from sod_import import parse_sod
from user_access import build_users
import routers.data_sources as data_sources

base = Path(fixtures).resolve().parent
out = Path(fixtures).resolve()
roles = (base / 'sod' / 'analysis' / 'roles.sod.txt').read_text(encoding='utf-8').splitlines()[:401]
users = (base / 'sod' / 'analysis' / 'users.sod.txt').read_text(encoding='utf-8').splitlines()[:301]
sod = (base / 'sod' / 'with_meta.sod.txt').read_text(encoding='utf-8').splitlines()


def cells(line): return line.split(';')
def join(values): return ';'.join(values)
def setcol(line, header, column, value):
    values = cells(line); values[cells(header).index(column)] = value; return join(values)


def roles_after():
    h, rows = roles[0], roles[1:]
    after = list(rows)
    after[2] = setcol(rows[2], h, 'TEXT', '=SUM(1,2)')                   # modified, formula neutralized in the export
    after[3] = setcol(rows[3], h, 'TEXT', 'Quoted "role", with comma')  # modified
    after[4] = setcol(rows[4], h, 'FUNCTION_KEY', 'HR')                 # modified (not part of the identity)
    del after[10:12]                                                    # removed
    after.append(setcol(rows[20], h, 'TCODE', 'ZNEW1'))                 # added
    after.append(setcol(rows[20], h, 'TCODE', 'ZNEW2'))
    after[30] = setcol(rows[30], h, 'TEXT', 'Variant A')                # ambiguous: one old, two new observations of one identity
    after.append(setcol(rows[30], h, 'TEXT', 'Variant B'))
    after.append(setcol(rows[40], h, 'AGR_NAME', ' ' + cells(rows[40])[cells(h).index('AGR_NAME')].lower() + ' '))  # same identity after strip/upper
    return [h] + after


def users_after():
    h, rows = users[0], users[1:]
    after = list(rows)
    after[0] = setcol(rows[0], h, 'ROLE_VALID_TO', '20991231')
    after[1] = setcol(rows[1], h, 'LAST_NAME', '@Changed')
    del after[5:8]
    after.append(setcol(rows[9], h, 'ROLE_NAME', 'ZC:NEW:ROLE_A'))
    return [h] + after


def employee(i, dept='Finance', dn=None, sam=None):
    name = f'Person {i}'
    values = dict(Site='HQ', Name=name, SamAccountName=sam if sam is not None else f'P{i:03}', UserPrincipalName=f'p{i}@example.invalid',
                  Mail=f'person{i}@example.invalid', Department=dept, Title='Analyst', Enabled='True',
                  DistinguishedName=dn if dn is not None else f'CN={name},OU=Staff', ManagerDN='', ManagerName='', ManagerSamAccountName='',
                  ManagerMail='', ManagerDepartment='', ManagerTitle='', ManagerLookupStatus='Resolved')
    return join(values[h] for h in HEADERS)


employees_before = [join(HEADERS)] + [employee(i) for i in range(30)] + [employee(90, dn='', sam='')]
employees_after = ([join(HEADERS)] + [employee(i, dept='Sales' if i in (2, 3) else 'Finance') for i in range(30) if i != 7]
                   + [employee(31), employee(5, dn='cn=PERSON 5,ou=staff').replace('Analyst', 'Lead'), employee(91, dn='', sam='')])
employees_after = [line for line in employees_after if line != employee(5)]

sod_after = [sod[0], setcol(sod[1], sod[0], 'TTEXT', 'Créer fournisseur (new)')] + sod[2:] + [setcol(sod[1], sod[0], 'TCODE', 'T099')]

cases = {
    'roles': ('\n'.join(roles) + '\n', '\n'.join(roles_after()) + '\n'),
    'users': ('\n'.join(users) + '\n', '\n'.join(users_after()) + '\n'),
    'employees': ('\n'.join(employees_before) + '\n', '\n'.join(employees_after) + '\n'),
    'sod': ('\n'.join(sod) + '\n', '\n'.join(sod_after) + '\n'),
}
work = Path(tempfile.mkdtemp())
settings = config.get_settings()
profile = next(p for p in settings.user_import_profiles if p.id == settings.active_user_import)


def records(source, path, catalogue):
    if source == 'roles': return cache._build_catalog(str(path), settings).source_records
    if source == 'users': return build_users(str(path), profile, catalogue).source_records
    if source == 'employees': return parse_directory(path).rows
    return parse_sod(path, settings.sod_import)['records']


from csv_lifecycle import NAMES
filters = [dict(), dict(kind='modified'), dict(kind='added'), dict(kind='removed'), dict(search='variant'), dict(search='SALES'), dict(offset=1, limit=2),
           dict(source='roles'), dict(source='users', kind='modified')]
shutil.copy(base / 'sod' / 'analysis' / 'roles.sod.txt', work / 'catalogue.csv')
catalogue = cache._build_catalog(str(work / 'catalogue.csv'), settings).roles
results = {}


async def collect(iterator):
    return ''.join([chunk async for chunk in iterator])


for source, (before_text, after_text) in cases.items():
    for side, text in (('before', before_text), ('after', after_text)):
        (out / f'report_{source}_{side}.txt').write_text(text, encoding='utf-8')
        shutil.copy(out / f'report_{source}_{side}.txt', work / f'{source}_{side}.csv')
    before, after = (records(source, work / f'{source}_{side}.csv', catalogue) for side in ('before', 'after'))
    delta = diff_records(source, before, after)
    has_changes = bool(delta['added'] or delta['removed'] or delta['modified'])
    result = dict(source=source, name=NAMES[source], status='updated' if has_changes else 'unchanged', records=len(after), **delta)
    report = dict(timestamp='T', status='changed', sources=[result])
    data_sources.report = lambda identity, report=report: report
    pages = []
    for query in filters:
        arguments = dict(source='', kind='', search='', offset=0, limit=25) | query
        page = data_sources.details('ID', **arguments)
        pages.append(dict(query=query, total=page['total'], offset=page['offset'], limit=page['limit'], items=page['items'],
                          source=page['sources'][0]))
    exports = []
    for query in filters[:6]:
        arguments = dict(source='', kind='', search='') | {k: v for k, v in query.items() if k in ('source', 'kind', 'search')}
        response = data_sources.export('ID', **arguments)
        exports.append(dict(query=query, csv=asyncio.run(collect(response.body_iterator))))
    results[source] = dict(pages=pages, exports=exports)

(out / 'reports.python.json').write_text(json.dumps(results, indent=1, ensure_ascii=False, sort_keys=True) + '\n', encoding='utf-8')
print('wrote', len(results), 'sources,', sum(len(r['pages']) + len(r['exports']) for r in results.values()), 'runs')
