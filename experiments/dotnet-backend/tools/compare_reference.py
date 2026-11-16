"""Python v1 reference for POST /api/compare on the synthetic small dataset (Fixtures/sod/analysis roles).
Usage: python -I tools/compare_reference.py BACKEND_DIR DATA_DIR QUERIES.json OUT.json  (each query: {name, roles}); output per name: the response."""
import json, os, sys, tempfile
os.environ['SAP_LENS_CONFIG_DIR'] = tempfile.mkdtemp()
backend, data, queries_path, out = sys.argv[1:5]
sys.path.insert(0, backend)
import cache
import routers.comparison as comparison

state = cache._build_catalog(path=os.path.join(data, 'roles.csv'))
comparison.get_snapshot = lambda: state
results = {}
for spec in json.load(open(queries_path)):
    result = comparison.compare_roles(comparison.CompareRequest(roles=spec['roles'])).model_dump(mode='json')
    result.pop('analysis')
    results[spec['name']] = result
with open(out, 'w', encoding='utf-8') as stream: json.dump(results, stream, indent=1, ensure_ascii=False)
