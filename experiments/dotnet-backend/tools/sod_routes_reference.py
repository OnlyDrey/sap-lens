"""Python v1 reference for the SoD 2.0 read routes (routers/sod_governance.py: context, matrices, filter options, explorer tables, selection, queue,
queue users, remediation) on the synthetic small dataset (Fixtures/sod/analysis), live context, no decisions recorded.
Usage: python -I tools/sod_routes_reference.py BACKEND_DIR DATA_DIR(roles.csv users.csv sod.csv) QUERIES.json OUT.json
Each query: {name, route, ...query parameters}; output per name: the route's JSON with generation and revision removed."""
import inspect, json, os, sys, tempfile
from datetime import date
os.environ['SAP_LENS_CONFIG_DIR'] = tempfile.mkdtemp()
backend, data, queries_path, out = sys.argv[1:5]
sys.path.insert(0, backend)
import cache, config
from config_models import UserImportProfile
from user_access import build_users
from sod_import import parse_sod
state = cache._build_catalog(path=os.path.join(data, 'roles.csv'))
state.users = build_users(os.path.join(data, 'users.csv'), UserImportProfile(id='default', name='x'), state.roles)
state.sod = parse_sod(os.path.join(data, 'sod.csv'))
state.directory = None
cache.get_snapshot = lambda: state
settings = config.get_settings().model_copy(deep=True)
settings.features.sod = True
settings.features.user_role_mapping = True
config.get_settings = lambda: settings
import routers.sod_analysis as analysis_router
import sod_scope
analysis_router.get_settings = sod_scope.get_settings = lambda: settings
import routers.sod_governance as g

def defaults(function):
    result = {}
    for name, parameter in inspect.signature(function).parameters.items():
        value = parameter.default
        result[name] = getattr(value, 'default', value)
    return result

SCOPE = defaults(g.scope_query)
ROUTES = dict(matrix_risk=g.risk_matrix, matrix_activity=g.activity_matrix, explorer=g.explorer, queue=g.queue, queue_users=g.queue_users,
              remediation=g.remediation, filter_options=g.filter_options, selection=g.assignment_selection)
results = {}
for spec in json.load(open(queries_path)):
    params = {k: v for k, v in spec.items() if k not in ('name', 'route')}
    route = spec['route']
    if route == 'context':
        result = g.context_summary('current')
    else:
        function = ROUTES[route]
        own = {k: v for k, v in defaults(function).items() if k != 'q'}
        scope = {**SCOPE, **{k: v for k, v in params.items() if k in SCOPE}}
        scope['as_of'] = date.fromisoformat(scope['as_of']) if scope.get('as_of') else None
        q = g.scope_query(**scope)
        extra = {k: v for k, v in {**own, **params}.items() if k in own}
        result = function(q=q, **extra)
    result = json.loads(json.dumps(result, default=str))
    for key in ('generation', 'revision'):
        result.pop(key, None)
    results[spec['name']] = result
with open(out, 'w', encoding='utf-8') as stream:
    json.dump(results, stream, ensure_ascii=False, sort_keys=True)
