"""Python v1 reference for the SoD decision store (sod_decisions.record/history/evidence_for): a scripted operation sequence with the outcome of each
call (status, revision, previous decisions, evidence content addresses) and the resulting histories. Event ids and timestamps are random/clock
values in v1 and are not compared. Usage: python -I tools/sod_decisions_reference.py BACKEND_DIR OUT.json"""
import json, os, sys, tempfile
from datetime import date
os.environ['SAP_LENS_CONFIG_DIR'] = tempfile.mkdtemp()
backend, out = sys.argv[1:3]
sys.path.insert(0, backend)
from fastapi import HTTPException
import sod_decisions as decisions

K = lambda n: f'{n:064x}'
def item(n, evidence=None, user='USER01', ref=None):
    return dict(key=K(n), user=user, ref=ref or f'ROLE_{n}', evidence_version=f'{n + 1000:064x}', evidence=evidence if evidence is not None else dict(id=K(n), role=f'ROLE_{n}', tcodes=['SU01', 'PFCG'], n=n))

OPERATIONS = [
    dict(name='keep_two', kind='assignment', items=[item(1), item(2, user='user02 ')], decision='Keep', expected_revision=0),
    dict(name='stale_revision', kind='assignment', items=[item(3)], decision='Keep', expected_revision=0),
    dict(name='remove_one', kind='assignment', items=[item(1)], decision='Remove', expected_revision=1, justification='  Removal agreed  '),
    dict(name='conditional_without_controls', kind='activity', items=[item(10)], decision='Conditional', expected_revision=2),
    dict(name='conditional', kind='activity', items=[item(10)], decision='Conditional', controls='Monthly check', expected_revision=2),
    dict(name='acceptance_without_approver', kind='acceptance', items=[item(20)], decision='Accepted', expected_revision=3),
    dict(name='approver_on_assignment', kind='assignment', items=[item(4)], decision='Keep', approver='Boss', expected_revision=3),
    dict(name='duplicate_keys', kind='assignment', items=[item(5), item(5)], decision='Keep', expected_revision=3),
    dict(name='too_many', kind='assignment', items=[item(100 + n) for n in range(101)], decision='Keep', expected_revision=3),
    dict(name='acceptance', kind='acceptance', items=[item(20)], decision='Accepted', approver='Approver', expires='2099-01-01', expected_revision=3),
    dict(name='expired_on_entry', kind='acceptance', items=[item(21)], decision='Rejected', approver='Approver', expires='2000-01-01', expected_revision=4),
    dict(name='blank_justification', kind='risk', items=[item(30)], decision='Investigate', justification='   ', expected_revision=4),
    dict(name='control_character', kind='risk', items=[item(30)], decision='Investigate', justification='bad\x07text', expected_revision=4),
    dict(name='bad_context', kind='risk', items=[item(30)], decision='Investigate', context='bad context!', expected_revision=4),
    dict(name='wrong_decision', kind='assignment', items=[item(6)], decision='Approved', expected_revision=4),
    dict(name='risk_review', kind='risk', items=[item(30)], decision='Investigate', expected_revision=4),
    dict(name='period_context', kind='assignment', items=[item(1)], decision='Investigate', context='P2026-Q1', expected_revision=5),
    dict(name='keep_again', kind='assignment', items=[item(1), item(2, user='user02 ')], decision='Keep', expected_revision=6, reviewer='Second reviewer'),
    dict(name='same_evidence_shared', kind='assignment', items=[item(7, evidence=dict(same=True)), item(8, evidence=dict(same=True))], decision='Pending', expected_revision=7),
    dict(name='bulk_tagged', kind='assignment', items=[item(9)], decision='Investigate', bulk_operation_id='ab' * 16, expected_revision=8),
]

results = []
for op in OPERATIONS:
    expires = date.fromisoformat(op['expires']) if op.get('expires') else None
    try:
        result = decisions.record(op['kind'], op.get('context', 'current'), op['items'], op['decision'], op.get('reviewer', 'Synthetic reviewer'),
                                  op.get('justification', 'Synthetic justification'), op['expected_revision'], approver=op.get('approver', ''),
                                  controls=op.get('controls', ''), expires=expires, source_versions=dict(users='u' * 64, sod='s' * 64),
                                  bulk_operation_id=op.get('bulk_operation_id', ''))
        outcome = dict(status=200, revision=result['revision'],
                       events=[{k: v for k, v in e.items() if k not in ('event_id', 'timestamp')} for e in result['events']])
    except HTTPException as error:
        outcome = dict(status=error.status_code, detail=error.detail)
    except ValueError:
        outcome = dict(status=422)
    results.append(dict(op, items=[dict(i) for i in op['items']], outcome=outcome))

histories = {}
for kind, context, n in [('assignment', 'current', 1), ('assignment', 'current', 2), ('assignment', 'P2026-Q1', 1), ('activity', 'current', 10), ('acceptance', 'current', 20)]:
    events = decisions.history(kind, context, K(n))
    histories[f'{kind}:{context}:{n}'] = [dict(decision=e['decision'], previous_decision=e['previous_decision'], reviewer=e['reviewer'],
                                               evidence=decisions.evidence_for(e)) for e in events]
with open(out, 'w', encoding='utf-8') as stream:
    json.dump(dict(operations=results, histories=histories, revision=decisions.read().revision), stream, indent=1, ensure_ascii=False)
