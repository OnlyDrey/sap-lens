"""Python v1 reference for the Release Roles routes of routers/access.py on the synthetic small dataset (Fixtures/sod/analysis roles/users).
Usage: python -I tools/release_reference.py BACKEND_DIR DATA_DIR QUERIES.json OUT.json
Each query: {name, route, ...query parameters}; JSON routes give the response without as_of/data_revision, CSV routes {csv_sha256, csv_head, count}."""
import asyncio, hashlib, json, os, sys, tempfile
from datetime import date
os.environ['SAP_LENS_CONFIG_DIR'] = tempfile.mkdtemp()
backend, data, queries_path, out = sys.argv[1:5]
sys.path.insert(0, backend)
import cache
from config_models import UserImportProfile
from user_access import build_users
import routers.access as access

state = cache._build_catalog(path=os.path.join(data, 'roles.csv'))
state.users = build_users(os.path.join(data, 'users.csv'), UserImportProfile(id='default', name='x'), state.roles)
state.directory = None
access.cache.get_snapshot = lambda: state
DATES = ('valid_from_min', 'valid_from_max', 'valid_to_min', 'valid_to_max', 'open_ended', 'include_missing_end')
def dates(spec):
    value = dict(valid_from_min=None, valid_from_max=None, valid_to_min=None, valid_to_max=None, open_ended='', include_missing_end=True)
    for key in DATES:
        if key in spec: value[key] = date.fromisoformat(spec[key]) if key.startswith('valid') else spec[key]
    return value
FILTERS = dict(group='', user_groups=[], document_type='', release_group='', release_areas=[], release_groups=[], strategy='', strategies=[], username='', role='',
               status='active', sort='role_name', descending=False)
OPTIONS = dict(search='', selected='', group='', user_groups=[], document_type='', release_group='', release_areas=[], release_groups=[], strategy='', strategies=[],
               status='active', limit=50)
ASSIGNMENTS = dict(role='', group='', user_groups=[], ungrouped=False, username='', role_search='', document_type='', release_group='', strategy='', strategies=[],
                   status='active', offset=0, limit=50)
RELEASES = dict(anchor='', matrix_offset=0, group_by_user_group=False, matrix_complete=False, list_complete=False, offset=0, limit=50)

async def body(response):
    return ''.join([chunk async for chunk in response.body_iterator])

def strip(result):
    return {k: v for k, v in result.items() if k not in ('as_of', 'data_revision')}

results = {}
for spec in json.load(open(queries_path)):
    route, params = spec['route'], {k: v for k, v in spec.items() if k not in ('name', 'route') and k not in DATES}
    if route in ('release-roles', 'releases', 'exports/release-roles', 'exports/releases'):
        filters = dict(FILTERS, dates=dates(spec), **{k: v for k, v in params.items() if k in FILTERS})
        if route == 'release-roles': result = strip(access.release_role_list(filters))
        elif route == 'releases': result = strip(access.releases(filters, **{**RELEASES, **{k: v for k, v in params.items() if k in RELEASES}}))
        else:
            response = (access.export_release_role_list if route == 'exports/release-roles' else access.export_releases)(filters)
            text = asyncio.run(body(response))
            result = dict(csv_sha256=hashlib.sha256(text.encode('utf-8')).hexdigest(), csv_head=text.split('\r\n')[:3],
                          count=int(response.headers.get('x-sap-lens-assignment-count') or response.headers['x-sap-lens-role-count']))
    elif route == 'release-options':
        result = access.release_options(params['field'], dates(spec), **{**OPTIONS, **{k: v for k, v in params.items() if k != 'field'}})
    else:
        result = access.release_assignments(dates(spec), **{**ASSIGNMENTS, **params})
    results[spec['name']] = result
with open(out, 'w', encoding='utf-8') as stream: json.dump(results, stream, indent=1, ensure_ascii=False, default=str)
