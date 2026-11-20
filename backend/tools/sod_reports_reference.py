"""Python v1 reference for the SoD report models (sod_reports.model, remediation_model) on an approved review period of the synthetic dataset.
v1 captures a period, records activity, acceptance and assignment decisions and one remediation action in it, approves it (freezing the decisions)
and builds report models for several option sets. Output: the period, its frozen snapshot, the snapshot checksum and the expected models.
Usage: python -I tools/sod_reports_reference.py BACKEND_DIR DATA_DIR(roles.csv users.csv sod.csv) OUT.json"""
import json, os, sys, tempfile
from datetime import date
os.environ['SAP_LENS_CONFIG_DIR'] = tempfile.mkdtemp()
backend, data, out = sys.argv[1:4]
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
import routers.sod_analysis as analysis_router, sod_scope, sod_periods as periods, sod_decisions as decisions, sod_governance as governance, sod_reports as reports
for module in (analysis_router, sod_scope, periods, reports):
    if hasattr(module, 'get_settings'): module.get_settings = lambda: settings

created = periods.create('Synthetic Q2', date(2026, 1, 1), date(2026, 12, 31), date(2026, 6, 1), 0)
pid = created['period']['id']
bundle = sod_scope.load(pid)
model = sod_scope.review_model_for(bundle)
st = sod_scope.states_for(bundle, model)
items = governance.queue_items(model, st)
revision = decisions.read().revision
def record(kind, chosen, decision, **extra):
    global revision
    for start in range(0, len(chosen), 100):
        chunk = []
        for item in chosen[start:start + 100]:
            entry = model[item['user']]
            if kind == 'activity': evidence = governance.activity_detail(entry, item['ref'])
            elif kind == 'assignment': evidence = governance.listify(dict(entry['assignments'][item['key']]))
            else: evidence = entry['findings'][item['ref']]
            chunk.append(dict(key=item['key'], user=item['user'], ref=item['ref'], evidence_version=item['evidence_version'], evidence=evidence))
        revision = decisions.record(kind, pid, chunk, decision, 'Synthetic reviewer', 'Synthetic justification', revision, source_versions=bundle['versions'], **extra)['revision']
activities = [i for i in items if i['kind'] == 'activity']
acceptances = [i for i in items if i['kind'] == 'acceptance']
assignments = [i for i in items if i['kind'] == 'assignment']
record('activity', activities[::2], 'Approved')
record('activity', activities[1::4], 'Conditional', controls='Monthly control')
record('activity', activities[3::4], 'Remove')
record('acceptance', acceptances[::3], 'Accepted', approver='Approver', expires=date(2099, 12, 31))
record('acceptance', acceptances[1::3], 'Rejected', approver='Approver')
record('acceptance', acceptances[2::3], 'Accepted', approver='Approver', controls='Dual control', expires=date(2099, 12, 31))
record('assignment', assignments[:6], 'Remove')
record('assignment', assignments[6:12], 'Keep')
record('assignment', assignments[12:15], 'Investigate')
first = assignments[0]
revision = decisions.save_action(pid, dict(user=first['user'], assignment_id=first['key'], role=first['ref'], recommended='Remove assignment', reason='Synthetic removal', owner='Owner',
                                           due_date=date(2026, 7, 1), status='Open', completion_evidence='', activity='', risk_id=''), 'Synthetic reviewer', revision)['revision']
index = periods.read()
for target, extra in (('In review', {}), ('Ready for approval', {}), ('Approved', dict(reviewer='Synthetic reviewer', approver='Synthetic approver', approval_date=date(2026, 6, 30), confirm=True))):
    index = periods.read()
    periods.transition(pid, target, index.revision, decisions.read().revision, actor='Synthetic reviewer', **extra)
details = periods.details(pid)
OPTIONS = dict(
    full=dict(report_date=date(2026, 7, 15), prepared_by='Preparer', status='Approved', management_comments='Reviewed in committee.'),
    draft_without_appendices=dict(report_date=date(2026, 7, 15), include_appendices=False, title='Quarterly SoD', document_version='2.1'),
    sections=dict(report_date=date(2026, 6, 15), sections=['executive', 'outstanding', 'remediation', 'conclusion'], status='Reviewed', reviewer_role='Controller'),
)
models = {name: reports.model(pid, reports.Options(**value)) for name, value in OPTIONS.items()}
remediation = {name: reports.remediation_model(pid, reports.RemediationOptions(**value)) for name, value in dict(
    all=dict(report_date=date(2026, 7, 15), prepared_by='Preparer'), removals=dict(report_date=date(2026, 7, 15), recommended=['Remove assignment', 'Investigate assignment'])).items()}
period = details['period']
saved = periods.snapshot(periods.find(periods.read(), pid))
result = dict(period=period, saved=saved, checksum=details['checksum'], options={k: {kk: (vv.isoformat() if isinstance(vv, date) else vv) for kk, vv in v.items()} for k, v in OPTIONS.items()},
              models=models, remediation_options=dict(all=dict(report_date='2026-07-15', prepared_by='Preparer'), removals=dict(report_date='2026-07-15', recommended=['Remove assignment', 'Investigate assignment'])),
              remediation=remediation)
with open(out, 'w', encoding='utf-8') as stream:
    json.dump(json.loads(json.dumps(result, default=str)), stream, ensure_ascii=False, sort_keys=True)
