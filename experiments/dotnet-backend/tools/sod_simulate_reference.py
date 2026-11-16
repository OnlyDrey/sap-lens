"""Python v1 reference for POST /api/sod/simulate and GET /api/sod/review-subjects on the synthetic small dataset (Fixtures/sod/analysis), after an
explicit activity approval (so removals warn about approved access). Usage: python -I tools/sod_simulate_reference.py BACKEND_DIR FIXTURE_DIR OUT.json"""
import json, os, shutil, sys, tempfile
os.environ['SAP_LENS_CONFIG_DIR'] = tempfile.mkdtemp()
backend, fixtures, out = sys.argv[1:4]
sys.path.insert(0, backend)
from fastapi import HTTPException
import cache, config
from config_models import UserImportProfile
from user_access import build_users
from sod_import import parse_sod
import sod_decisions as decisions
import sod_scope as scope
from routers.sod_governance import decide, simulate, review_subjects, DecisionBody, DecisionItem, SimulateBody

work = tempfile.mkdtemp()
for name in ('roles', 'users', 'sod'):
    shutil.copy(os.path.join(fixtures, f'{name}.sod.txt'), os.path.join(work, f'{name}.csv'))
settings = config.get_settings().model_copy(deep=True)
settings.features.sod = True
config.save_configuration(settings, settings.revision)
state = cache._build_catalog(path=os.path.join(work, 'roles.csv'))
state.users = build_users(os.path.join(work, 'users.csv'), UserImportProfile(id='default', name='x'), state.roles)
state.sod, state.directory = parse_sod(os.path.join(work, 'sod.csv')), None
cache._cache = state

U = 'USER00035'
bundle = scope.load('current')
entry = scope.model_for(bundle)[U]
activity = sorted(entry['activities'])[0]
item = entry['activities'][activity]
decide('activity', DecisionBody(context='current', expected_revision=0, expected_generation=bundle['generation'], decision='Approved', reviewer='Synthetic actor',
                                justification='Synthetic justification', items=[DecisionItem(key=item['key'], user=U, ref=activity, evidence_version=item['evidence_version'])]))
roles = sorted({a['role'] for a in entry['assignments'].values()})
by_role = {a['role']: aid for aid, a in entry['assignments'].items()}
CASES = [dict(name=f'remove_{i}', removed=[r]) for i, r in enumerate(roles)] + [
    dict(name='remove_pair', removed=roles[:2]), dict(name='remove_all', removed=roles), dict(name='remove_nothing', removed=[]),
    dict(name='unknown', removed=['UNKNOWN']), dict(name='unknown_user', removed=[], user='NOBODY')]

def strip(result):
    return {k: v for k, v in result.items() if k not in ('generation', 'as_of', 'revision', 'coverage', 'context', 'frozen', 'reviewable', 'legacy', 'period')}

results = {}
for case in CASES:
    removed = [by_role[r] if r in by_role else 'f' * 64 for r in case['removed']]
    try:
        results[case['name']] = dict(status=200, body=strip(simulate(SimulateBody(context='current', user=case.get('user', U), removed=removed))))
    except HTTPException as error:
        results[case['name']] = dict(status=error.status_code, detail=error.detail)
subjects = review_subjects(context='current', usernames=[U, 'NOBODY', 'USER00007', 'USER00007', 'user00035'])
with open(out, 'w', encoding='utf-8') as stream:
    json.dump(dict(user=U, activity=activity, roles=roles, cases=[dict(c, removed_roles=c['removed']) for c in CASES], results=results,
                   review_subjects=subjects['users'], revision=decisions.read().revision), stream, indent=1, ensure_ascii=False)
