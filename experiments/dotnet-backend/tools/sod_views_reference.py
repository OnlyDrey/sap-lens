"""Python v1 reference for the SoD 2.0 views (sod_governance.restrict, risk_matrix, activity_matrix, aggregate_by_group, place_in_groups,
explorer_rows, queue_items, conflict_concentration, remediation_rows) on the decision scenario of tools/sod_governance_reference.py.
Usage: python -I tools/sod_views_reference.py BACKEND_DIR DATA_DIR GOVERNANCE_EXPECTED.json OUT.json
(GOVERNANCE_EXPECTED.json is the output of sod_governance_reference.py; this script runs that scenario again and writes the views.)"""
import json, os, runpy, sys
from datetime import date
backend, data, governance_out, out = sys.argv[1:5]
scenario = runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sod_governance_reference.py'), run_name='scenario')
import sod_governance as governance
import sod_decisions as decisions

model, states, latest, TODAY = scenario['model'], scenario['states'], scenario['latest'], scenario['TODAY']


def plain(value):
    if isinstance(value, decisions.Event): return value.event_id
    if isinstance(value, decisions.Action): return value.id
    if isinstance(value, dict): return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset)): return sorted(plain(v) for v in value)
    if isinstance(value, (list, tuple)): return [plain(v) for v in value]
    if isinstance(value, date): return value.isoformat()
    return value


users = sorted(model)
# A filtered view: every second user keeps only their first risk; every third user keeps only their first assignment in lists.
visible = {u: {sorted(model[u]['findings'])[0]} if i % 2 else set(model[u]['findings']) for i, u in enumerate(users)}
allowed = {u: ({sorted(model[u]['assignments'])[0]} if i % 3 == 0 else set(model[u]['assignments'])) for i, u in enumerate(users)}
view = governance.restrict(model, visible, allowed)

stamp = '2026-01-11T08:00:00+00:00'
actions = []
for n, user in enumerate(users[:16]):
    entry = model[user]
    aid = sorted(entry['assignments'])[0]
    recommended = 'Remove assignment' if n % 2 == 0 else 'Investigate assignment'
    actions.append(decisions.Action(id=f'{n + 1:032x}', context='current', user=user, assignment_id=aid, role=entry['assignments'][aid]['role'], recommended=recommended,
                                    reason='Synthetic', owner='Owner' if n % 3 else '', due_date=date(2026, 1, 1) if n % 4 == 0 else date(2026, 6, 1),
                                    status=['Open', 'In progress', 'Completed', 'Cancelled'][n % 4], completion_evidence='Done' if n % 4 == 2 else '',
                                    created=stamp, modified=f'2026-01-11T08:00:{n:02d}+00:00', created_by='Synthetic'))
verify = lambda user, aid: 'Still present in current evidence' if (user + aid) < 'U' else 'Not present in current evidence'

result = dict(
    users=users, visible=plain(visible), allowed=plain(allowed), actions=[a.model_dump(mode='json') for a in actions],
    restricted={u: plain(governance.listify({k: v for k, v in e.items() if k not in ('findings', 'account')}) | dict(finding_ids=sorted(f['finding_id'] for f in e['findings'].values()),
                                                                                                                     visible_assignments=sorted(e['visible_assignments'] or [])))
                for u, e in view.items()},
    risk_matrix=plain(governance.risk_matrix(model, states)), activity_matrix=plain(governance.activity_matrix(model, states)),
    risk_matrix_view=plain(governance.risk_matrix(view, states)), activity_matrix_view=plain(governance.activity_matrix(view, states)),
    risk_groups=plain(governance.aggregate_by_group(governance.risk_matrix(model, states))),
    activity_groups=plain(governance.aggregate_by_group(governance.activity_matrix(view, states))),
    placed=plain(governance.place_in_groups(governance.risk_matrix(model, states)['rows'], ['GRP_PRC'], False)),
    placed_reverse=plain(governance.place_in_groups(governance.activity_matrix(view, states)['rows'], [], True)),
    explorer={table: plain(governance.explorer_rows(table, view, states)) for table in ('user_risk', 'user_activity', 'access_list', 'lookup')},
    explorer_full={table: plain(governance.explorer_rows(table, model, states)) for table in ('access_list', 'lookup')},
    queue=plain(governance.queue_items(view, states)), queue_full=plain(governance.queue_items(model, states)),
    concentration=plain(governance.conflict_concentration(model)),
    remediation=plain(governance.remediation_rows(model, states, actions, verify, today=TODAY)),
    remediation_pending=plain(governance.remediation_rows(view, states, actions, verify, today=TODAY, include_pending=True)),
)
with open(out, 'w', encoding='utf-8') as stream:
    json.dump(result, stream, ensure_ascii=False, sort_keys=True)
