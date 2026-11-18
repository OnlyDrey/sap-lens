"""Python v1 reference for GET /api/access/users-selection and /api/access/exports/users on the synthetic small dataset
(Fixtures/sod/analysis roles/users). Usage: python -I tools/access_reference.py BACKEND_DIR DATA_DIR QUERIES.json OUT.json
Each query: {name, ...directory filters}; output per name: {total, usernames, count, csv_sha256 (UTF-8 of the exact export body), csv_head (first 3 lines)}."""
import asyncio, hashlib, json, os, sys, tempfile
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
cache.get_snapshot = lambda: state
access.cache.get_snapshot = lambda: state
import routers.employees as employees
employees.available = lambda snapshot: None
defaults = dict(usernames='', assignment_band='', search='', group='', role='', groups=(), roles=(), tcode='', tcodes=[], transaction_mode='and', status='',
                show_expired=False, exclude_transactions=False, exclude_tcodes=[], exclude_mode='any', missing_roles=[], missing_mode='any', functional_groups=(),
                managers=(), sort='username', descending=False)

async def body(response):
    return ''.join([chunk async for chunk in response.body_iterator])

results = {}
for spec in json.load(open(queries_path)):
    filters = {**defaults, **{k: (tuple(v) if k in ('groups', 'roles') else v) for k, v in spec.items() if k != 'name'}}
    selection = access.users_selection(filters)
    response = access.export_users(filters)
    text = asyncio.run(body(response))
    results[spec['name']] = dict(total=selection['total'], usernames=selection['usernames'], count=int(response.headers['x-sap-lens-assignment-count']),
                                 csv_sha256=hashlib.sha256(text.encode('utf-8')).hexdigest(), csv_head=text.split('\r\n')[:3])
with open(out, 'w', encoding='utf-8') as stream: json.dump(results, stream, indent=1, ensure_ascii=False)
