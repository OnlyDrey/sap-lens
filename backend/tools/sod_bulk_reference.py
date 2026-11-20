"""Python v1 reference for POST /api/sod/decisions/assignment/bulk and POST /api/sod/remediation/actions: a scripted sequence through v1's route
functions on the synthetic small dataset (Fixtures/sod/analysis). Items are named by (user, role) and resolved to keys/versions on both sides.
Usage: python -I tools/sod_bulk_reference.py BACKEND_DIR FIXTURE_DIR OUT.json"""
import json, os, shutil, sys, tempfile
from datetime import datetime, timezone
os.environ['SAP_LENS_CONFIG_DIR'] = tempfile.mkdtemp()
backend, fixtures, out = sys.argv[1:4]
sys.path.insert(0, backend)
from fastapi import HTTPException
from pydantic import ValidationError
import cache, config
from config_models import UserImportProfile, SourceSnapshot
from user_access import build_users
from sod_import import parse_sod
import sod_decisions as decisions
import sod_scope as scope
from routers.sod_governance import bulk_assignment_review, save_action, BulkAssignmentBody, ActionBody

work = tempfile.mkdtemp()
for name in ('roles', 'users', 'sod'):
    shutil.copy(os.path.join(fixtures, f'{name}.sod.txt'), os.path.join(work, f'{name}.csv'))
settings = config.get_settings().model_copy(deep=True)
settings.features.sod = True
stamp = datetime.now(timezone.utc).isoformat()
settings.data_lifecycle.sources['users'] = SourceSnapshot(snapshot='a' * 64, path=os.path.join(work, 'users.csv'), imported_at=stamp, checked_at=stamp)
config.save_configuration(settings, settings.revision)
state = cache._build_catalog(path=os.path.join(work, 'roles.csv'))
state.users = build_users(os.path.join(work, 'users.csv'), UserImportProfile(id='default', name='x'), state.roles)
state.sod, state.directory = parse_sod(os.path.join(work, 'sod.csv')), None
cache._cache = state

U = 'USER00035'
roles = sorted(a['role'] for a in scope.review_model_for(scope.load('current'))[U]['assignments'].values())
A1, A2, A3, A4, A5 = roles[:5]

def resolve(user, role, override=None):
    bundle = scope.load('current')
    item = next(a for a in scope.review_model_for(bundle)[user]['assignments'].values() if a['role'] == role)
    key, version = item['id'], item['evidence_version']
    if override == 'stale_version': version = 'c' * 64
    if override == 'unknown_key': key = 'd' * 64
    return dict(key=key, user=user, ref=role, evidence_version=version)

STEPS = [
    dict(name='keep_two', call='bulk', items=[[U, A1], [U, A2]], action='Keep'),
    dict(name='mixed', call='bulk', items=[[U, A1], [U, A3], [U, A4, 'stale_version'], [U, A5, 'unknown_key']], action='Keep'),
    dict(name='replace_protected', call='bulk', items=[[U, A1]], action='Remove', replace_existing=True),
    dict(name='investigate_tracked', call='bulk', items=[[U, A2], [U, A5]], action='Investigate', track_action=True),
    dict(name='investigate_again', call='bulk', items=[[U, A5], [U, A4]], action='Investigate', track_action=True),
    dict(name='atomic_refused', call='bulk', items=[[U, A2], [U, A3]], action='Keep', atomic=True),
    dict(name='atomic_replace', call='bulk', items=[[U, A2], [U, A5]], action='Keep', atomic=True, replace_existing=True),
    dict(name='stale_revision', call='bulk', items=[[U, A3]], action='Remove', revision_offset=-1),
    dict(name='duplicates', call='bulk', items=[[U, A3], [U, A3]], action='Keep'),
    dict(name='atomic_with_tracking', call='bulk', items=[[U, A3]], action='Investigate', atomic=True, track_action=True),
    dict(name='stale_generation', call='bulk', items=[[U, A3]], action='Keep', generation='0' * 64),
    dict(name='action_create', call='action', user=U, assignment=A1, recommended='Remove assignment', reason='  Separate duties  ', owner='Owner One', due_date='2099-01-31'),
    dict(name='action_complete_without_evidence', call='action', user=U, assignment=A1, recommended='Remove assignment', reason='Separate duties', status='Completed', update='last'),
    dict(name='action_complete', call='action', user=U, assignment=A1, recommended='Remove assignment', reason='Separate duties', status='Completed', completion_evidence='Ticket 42', owner='Owner Two', update='last'),
    dict(name='action_unknown_id', call='action', user=U, assignment=A1, recommended='Remove assignment', reason='x', update='f' * 32),
    dict(name='action_foreign_user', call='action', user='NOBODY', recommended='No action required', reason='x'),
    dict(name='action_stale_revision', call='action', user=U, recommended='Maintain access', reason='x', revision_offset=-1),
]

def strip_action(action):
    action = {k: v for k, v in action.items() if k not in ('id', 'created', 'modified')}
    action['history'] = [{k: v for k, v in h.items() if k not in ('timestamp', 'actor_identity')} for h in action['history']]
    return action

results, last_action = [], None
for step in STEPS:
    revision = decisions.read().revision + step.get('revision_offset', 0)
    try:
        if step['call'] == 'bulk':
            body = BulkAssignmentBody(context='current', expected_revision=revision, expected_generation=step.get('generation') or scope.load('current')['generation'],
                                      items=[resolve(*item) for item in step['items']], action=step['action'], reviewer='Synthetic actor',
                                      justification='Synthetic justification', replace_existing=step.get('replace_existing', False),
                                      atomic=step.get('atomic', False), track_action=step.get('track_action', False))
            result = bulk_assignment_review(body)
            outcome = dict(status=200, action=result['action'], recorded=result['recorded'], skipped=result['skipped'], failed=result['failed'],
                           tracked_actions=result['tracked_actions'], revision=result['revision'])
        else:
            update = step.get('update')
            action_id = last_action if update == 'last' else (update or '')
            assignment = resolve(step['user'], step['assignment'])['key'] if step.get('assignment') else ''
            body = ActionBody(context='current', expected_revision=revision, actor='Synthetic actor', action_id=action_id, user=step['user'], assignment_id=assignment,
                              role=step.get('assignment', ''), recommended=step['recommended'], reason=step['reason'], owner=step.get('owner', ''),
                              due_date=step.get('due_date'), status=step.get('status', 'Open'), completion_evidence=step.get('completion_evidence', ''))
            result = save_action(body)
            last_action = result['action']['id']
            outcome = dict(status=200, revision=result['revision'], action=strip_action(json.loads(json.dumps(result['action'], default=str))))
    except HTTPException as error:
        outcome = dict(status=error.status_code, detail=error.detail if isinstance(error.detail, str) else None)
    except (ValidationError, ValueError):
        outcome = dict(status=422, detail=None)
    results.append(dict(step, outcome=outcome))

histories = {role: [e['decision'] for e in decisions.history('assignment', 'current', resolve(U, role)['key'])] for role in (A1, A2, A3, A4, A5)}
bulk_ids = {role: sorted({e['bulk_operation_id'] != '' for e in decisions.history('assignment', 'current', resolve(U, role)['key'])}) for role in (A1, A2, A3, A4, A5)}
actions = [strip_action(json.loads(json.dumps(a.model_dump(mode='json')))) for a in decisions.actions_for('current')]
with open(out, 'w', encoding='utf-8') as stream:
    json.dump(dict(user=U, roles=[A1, A2, A3, A4, A5], steps=results, histories=histories, bulk_tagged=bulk_ids, actions=actions,
                   revision=decisions.read().revision), stream, indent=1, ensure_ascii=False)
