"""Python v1 reference for the SoD 2.0 decision model (sod_governance.derive/states/review_coverage/effective_decision/decision_summary,
sod_decisions.lifecycle) on the synthetic small dataset in Fixtures/sod/analysis.
Usage: python -I tools/sod_governance_reference.py BACKEND_DIR DATA_DIR OUT.json

A deterministic decision scenario is built over the derived model (current, stale, removal, investigation, conditional, expired and valid
acceptance, risk review, an assignment that reappeared after its decision) and written with the expected lifecycle and derived status of every
review item, so the .NET port is compared with v1 on the same events."""
import json, os, sys, tempfile
from datetime import date
os.environ['SAP_LENS_CONFIG_DIR'] = tempfile.mkdtemp()
backend, data, out = sys.argv[1:4]
sys.path.insert(0, backend)
import cache
from config_models import UserImportProfile
from user_access import build_users
from sod_import import parse_sod
from sod_analysis import analyze
import sod_governance as governance
from sod_decisions import Event

state = cache._build_catalog(path=os.path.join(data, 'roles.csv'))
state.users = build_users(os.path.join(data, 'users.csv'), UserImportProfile(id='default', name='x'), state.roles)
state.sod = parse_sod(os.path.join(data, 'sod.csv'))
state.directory = None
TODAY = date(2026, 1, 15)
result = analyze(state, metadata={}, as_of=TODAY, validity='active', selected_roles=[], mapping_enabled=True, directory_enabled=False, sod_enabled=True)
findings = result['users']
model = governance.derive(findings, only_current=True)

def plain(entry):
    item = governance.listify({k: v for k, v in entry.items() if k not in ('findings', 'account')})
    item['finding_ids'] = sorted(f['finding_id'] for f in entry['findings'].values())
    return item

users = sorted(model)
counter = iter(range(1, 10000))
HEX = 'ab' * 32

def event(kind, key, user, ref, decision, version, stamp='2026-01-10T09:00:00+00:00', **extra):
    return Event(event_id=f'{next(counter):032x}', kind=kind, context='current', timestamp=stamp, key=key, user=user, ref=ref, decision=decision,
                 reviewer='Synthetic reviewer', justification='Synthetic justification', evidence_version=version, evidence_snapshot=HEX, **extra)

latest = dict(activity={}, assignment={}, acceptance={}, risk={})
reappeared = {}
plan = []
for index, user in enumerate(users[:24]):
    entry = model[user]
    aids = sorted(entry['assignments'])
    names = sorted(entry['activities'])
    risks = sorted(entry['findings'])
    mode = index % 8
    a = entry['assignments'][aids[0]]
    if mode == 0:    # every assignment kept: activities and risks reviewed through roles
        for aid in aids: latest['assignment'][aid] = event('assignment', aid, user, entry['assignments'][aid]['role'], 'Keep', entry['assignments'][aid]['evidence_version'])
    elif mode == 1:  # one removal (plans resolution), one stale keep
        latest['assignment'][aids[0]] = event('assignment', aids[0], user, a['role'], 'Remove', a['evidence_version'])
        if len(aids) > 1: latest['assignment'][aids[1]] = event('assignment', aids[1], user, entry['assignments'][aids[1]]['role'], 'Keep', 'cd' * 32)
    elif mode == 2:  # investigation and an explicit activity approval that disagrees with the roles
        latest['assignment'][aids[0]] = event('assignment', aids[0], user, a['role'], 'Investigate', a['evidence_version'])
        act = entry['activities'][names[0]]
        latest['activity'][act['key']] = event('activity', act['key'], user, names[0], 'Remove', act['evidence_version'])
    elif mode == 3:  # conditional activity approval and a valid acceptance
        act = entry['activities'][names[0]]
        latest['activity'][act['key']] = event('activity', act['key'], user, names[0], 'Conditional', act['evidence_version'], controls='Monthly control')
        f = entry['findings'][risks[0]]
        latest['acceptance'][f['finding_id']] = event('acceptance', f['finding_id'], user, risks[0], 'Accepted', f['evidence_version'], approver='Approver', expires=date(2027, 1, 1))
    elif mode == 4:  # expired acceptance and a rejected one
        f = entry['findings'][risks[0]]
        latest['acceptance'][f['finding_id']] = event('acceptance', f['finding_id'], user, risks[0], 'Accepted', f['evidence_version'], approver='Approver', expires=date(2025, 12, 31))
        if len(risks) > 1:
            g = entry['findings'][risks[1]]
            latest['acceptance'][g['finding_id']] = event('acceptance', g['finding_id'], user, risks[1], 'Rejected', g['evidence_version'], approver='Approver')
    elif mode == 5:  # explicit risk review approved; a keep that reappeared afterwards
        f = entry['findings'][risks[0]]
        latest['risk'][f['finding_id']] = event('risk', f['finding_id'], user, risks[0], 'Approved', f['evidence_version'])
        latest['assignment'][aids[0]] = event('assignment', aids[0], user, a['role'], 'Keep', a['evidence_version'])
        reappeared[aids[0]] = '2026-01-12T00:00:00+00:00'
    elif mode == 6:  # decision made after the reappearance stays current; pending explicit event
        latest['assignment'][aids[0]] = event('assignment', aids[0], user, a['role'], 'Keep', a['evidence_version'], stamp='2026-01-13T00:00:00+00:00')
        reappeared[aids[0]] = '2026-01-12T00:00:00+00:00'
        if len(aids) > 1: latest['assignment'][aids[1]] = event('assignment', aids[1], user, entry['assignments'][aids[1]]['role'], 'Pending', entry['assignments'][aids[1]]['evidence_version'])
    else:            # all assignments removed: Remove derived for activities, removal planned for risks
        for aid in aids: latest['assignment'][aid] = event('assignment', aid, user, entry['assignments'][aid]['role'], 'Remove', entry['assignments'][aid]['evidence_version'])
reasons = {key: 'Assignment reappeared after it was removed from the SAP import; review it again. The earlier decision stays in history.' for key in reappeared}
states = governance.states(model, latest, today=TODAY, reappeared=reappeared, reasons=reasons)

expected = {}
for user in users:
    entry = model[user]
    rows = {}
    for kind, keys in (('activity', [a['key'] for a in entry['activities'].values()]), ('assignment', list(entry['assignments'])),
                       ('acceptance', [f['finding_id'] for f in entry['findings'].values()]), ('risk', [f['finding_id'] for f in entry['findings'].values()])):
        for key in sorted(keys):
            life, ev = states[kind][key]
            row = dict(lifecycle=life, event_id=ev.event_id if ev else None)
            if kind != 'risk':
                row['coverage'] = states['coverage'][kind][key]
                row['summary'] = governance.decision_summary(entry, states, kind, key)
            else:
                row['summary'] = governance.effective_decision(entry, states, 'risk', key)
            rows[f'{kind}:{key}'] = row
    expected[user] = rows

events = [e.model_dump(mode='json') for kind in latest.values() for e in kind.values()]
with open(out, 'w', encoding='utf-8') as stream:
    json.dump(dict(today=TODAY.isoformat(), findings=findings, model={u: plain(model[u]) for u in users}, events=events, reappeared=reappeared,
                   states=expected, reappeared_reasons=states['reappeared']), stream, ensure_ascii=False, sort_keys=True)
