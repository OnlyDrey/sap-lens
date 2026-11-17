"""Python v1 reference for GET /api/sod/analysis: v1 analyze, the router's enrichment and filtered() on a synthetic dataset.
Usage: python -I tools/sod_analysis_reference.py BACKEND_DIR DATA_DIR(with roles.csv users.csv sod.csv) QUERIES.json OUT.json
Each query: {name, kind, validity, as_of, ...filters}; output per name: {total, subjects, summary, coverage, items(first 25, evidence truncated as the route)}."""
import json, os, sys, tempfile
from datetime import date
os.environ['SAP_LENS_CONFIG_DIR'] = tempfile.mkdtemp()
backend, data, queries_path, out = sys.argv[1:5]
sys.path.insert(0, backend)
import cache
from config_models import UserImportProfile
from user_access import build_users
from sod_import import parse_sod
from sod_analysis import analyze
from routers.sod_analysis import filtered, _subject
from account_review import validity as account_validity

state = cache._build_catalog(path=os.path.join(data, 'roles.csv'))
state.users = build_users(os.path.join(data, 'users.csv'), UserImportProfile(id='default', name='x'), state.roles)
state.sod = parse_sod(os.path.join(data, 'sod.csv'))
state.directory = None
results = {}
defaults = dict(kind='users', validity='active', selected_roles=[], search='', risk='', criticality='', risk_type='', category='', username='', group='',
                composite_role='', single_role='', tcode='', account_status='', usernames=[], risks=[], criticalities=[], categories=[], groups=[], tcodes=[],
                sort='subject', descending=False)
for spec in json.load(open(queries_path)):
    query = {**defaults, **{k: v for k, v in spec.items() if k != 'name'}}
    query['as_of'] = date.fromisoformat(query['as_of'])
    query['selected_roles'] = sorted(set(query['selected_roles']))
    result = analyze(state, metadata={}, as_of=query['as_of'], validity=query['validity'], selected_roles=query['selected_roles'], mapping_enabled=True, directory_enabled=False, sod_enabled=True)
    definitions = {item['risk_id']: item for item in state.sod['risks']}
    for kind in ('users', 'roles'):
        enriched = []
        for finding in result[kind]:
            source = definitions[finding['risk_id']]
            if finding.get('account') is not None:
                account = finding['account']
                locks = {row.get('locked') for row in account['accounts']}
                finding = {**finding, 'account': {**account, 'sap_validity': account_validity(account['accounts'], query['as_of']),
                           'lock_status': 'Locked' if locks == {True} else 'Unlocked' if locks == {False} else 'Unknown'}}
            enriched.append({**finding, 'risk': dict(display_name='', source_text=source['source_text'], business_category='', risk_type=source['risk_type'])})
        result[kind] = enriched
    rows = filtered(result, query)
    items = [{**row, 'evidence': {side: paths[:25] for side, paths in row['evidence'].items()}, 'evidence_total': {side: len(paths) for side, paths in row['evidence'].items()}} for row in rows[:25]]
    results[spec['name']] = dict(total=len(rows), subjects=len({_subject(row) for row in rows}), summary=result['summary'],
                                 coverage={k: v for k, v in result['coverage'].items()}, items=items)
json.dump(results, open(out, 'w'), sort_keys=True, ensure_ascii=False, separators=(',', ':'), default=str)
print({k: (v['total'], v['summary']) for k, v in results.items()})
