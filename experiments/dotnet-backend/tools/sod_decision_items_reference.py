"""Python v1 reference for what POST /api/sod/decisions/{kind} records: for every review item of the first users of the synthetic small dataset
(Fixtures/sod/analysis), the key, evidence version and evidence content address v1 derives (routers.sod_governance._locate on
sod_scope.model_for / review_model_for, with captured()'s enrichment). Usage:
python -I tools/sod_decision_items_reference.py BACKEND_DIR DATA_DIR AS_OF OUT.json"""
import hashlib, json, os, sys, tempfile
from datetime import date
os.environ['SAP_LENS_CONFIG_DIR'] = tempfile.mkdtemp()
backend, data, as_of, out = sys.argv[1:5]
sys.path.insert(0, backend)
import cache
from config_models import UserImportProfile
from user_access import build_users
from sod_import import parse_sod
from sod_analysis import analyze
from account_review import validity
import sod_scope as scope
from routers.sod_governance import _locate, DecisionItem

state = cache._build_catalog(path=os.path.join(data, 'roles.csv'))
state.users = build_users(os.path.join(data, 'users.csv'), UserImportProfile(id='default', name='x'), state.roles)
state.sod = parse_sod(os.path.join(data, 'sod.csv'))
state.directory = None
day = date.fromisoformat(as_of)
result = analyze(state, metadata={}, as_of=day, validity='active', selected_roles=[], mapping_enabled=True, directory_enabled=False, sod_enabled=True)
definitions = {item['risk_id']: item for item in state.sod['risks']}
findings = []
for finding in result['users']:   # captured(): account state and risk metadata (no local metadata here)
    if finding.get('account') is not None:
        account = finding['account']
        locks = {row.get('locked') for row in account['accounts']}
        finding = {**finding, 'account': {**account, 'sap_validity': validity(account['accounts'], day),
                                          'lock_status': 'Locked' if locks == {True} else 'Unlocked' if locks == {False} else 'Unknown'}}
    source = definitions[finding['risk_id']]
    findings.append({**finding, 'risk': dict(display_name='', source_text=source['source_text'], business_category='', risk_type=source['risk_type'])})
bundle = dict(context='current', generation='0' * 64, only_current=True, findings=findings, coverage=dict(status='available'),
              assignment_source=state.users.users, as_of=day, assignment_validity='active')
base = scope.model_for(bundle)
review = scope.review_model_for(bundle)

def address(kind, evidence):
    return hashlib.sha256(json.dumps(dict(version=1, source='sod-decision-evidence', kind=kind, evidence=evidence), ensure_ascii=False,
                                     separators=(',', ':'), sort_keys=True, default=str).encode()).hexdigest()

items = []
users = sorted(review)
for user in users[:12] + [u for u in users if u not in base][:6]:
    for kind, model in (('assignment', review), ('activity', base), ('acceptance', base), ('risk', base)):
        entry = model.get(user)
        if entry is None: continue
        refs = ([(aid, a['role']) for aid, a in entry['assignments'].items()] if kind == 'assignment'
                else [(a['key'], name) for name, a in entry['activities'].items()] if kind == 'activity'
                else [(f['finding_id'], rid) for rid, f in entry['findings'].items()])
        for key, ref in refs:
            found = _locate(model, kind, DecisionItem(key=key, user=user, ref=ref, evidence_version='0' * 64))
            _, located_key, version, evidence = found
            items.append(dict(kind=kind, user=user, ref=ref, key=located_key, evidence_version=version, address=address(kind, evidence)))
with open(out, 'w', encoding='utf-8') as stream:
    json.dump(dict(as_of=as_of, review_users=len(review), base_users=len(base), items=items), stream, indent=1, ensure_ascii=False)
