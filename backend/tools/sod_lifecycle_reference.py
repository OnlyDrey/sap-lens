"""Python v1 reference for assignment reappearance memory: a multi-import sequence through v1's decide(), assignment_lifecycle.observe() and subject().
Usage: python -I tools/sod_lifecycle_reference.py BACKEND_DIR FIXTURE_DIR(analysis) OUT.json

Every import is a scripted transform of the synthetic users CSV (the same transforms the .NET test applies); the catalogue drops its one invalid
pattern so that absence can be verified (v1 requires a catalogue without invalid patterns for complete coverage)."""
import hashlib, json, os, sys, tempfile
from datetime import datetime, timezone
config_dir = tempfile.mkdtemp()
os.environ['SAP_LENS_CONFIG_DIR'] = config_dir
backend, fixtures, out = sys.argv[1:4]
sys.path.insert(0, backend)
import cache, config
from config_models import UserImportProfile, SourceSnapshot
from user_access import build_users
from sod_import import parse_sod
import assignment_lifecycle as lifecycle
import sod_decisions as decisions
import sod_scope as scope
from routers.sod_governance import decide, subject, DecisionBody, DecisionItem

USER, ROLE_A, ROLE_B = 'USER00007', 'ZC:MM:ROLE_00194', 'ZC:MM:ROLE_00182'
work = tempfile.mkdtemp()
with open(os.path.join(fixtures, 'roles.sod.txt'), encoding='utf-8') as stream:
    roles = ''.join(line for line in stream if 'ZC:BAD?PATTERN' not in line)
with open(os.path.join(work, 'roles.csv'), 'w', encoding='utf-8', newline='') as stream: stream.write(roles)
with open(os.path.join(fixtures, 'users.sod.txt'), encoding='utf-8') as stream: base_users = stream.read()

def transform(text, spec):
    """drop: [user, role] rows removed; identity: {user: [first, last, email]}; valid_to: {user|role: date}."""
    lines = text.splitlines(keepends=True)
    header = lines[0].rstrip('\r\n').split(';')
    col = {name: i for i, name in enumerate(header)}
    result = [lines[0]]
    for line in lines[1:]:
        ending = line[len(line.rstrip('\r\n')):]
        cells = line.rstrip('\r\n').split(';')
        user, role = cells[col['USERNAME']].strip().upper(), cells[col['ROLE_NAME']]
        if [user, role] in spec.get('drop', []): continue
        if user in spec.get('identity', {}):
            cells[col['FIRST_NAME']], cells[col['LAST_NAME']], cells[col['EMAIL']] = spec['identity'][user]
        if f'{user}|{role}' in spec.get('valid_to', {}): cells[col['ROLE_VALID_TO']] = spec['valid_to'][f'{user}|{role}']
        result.append(';'.join(cells) + ending)
    return ''.join(result)

settings = config.get_settings().model_copy(deep=True)
settings.features.sod = True
settings.features.user_role_mapping = True
config.save_configuration(settings, settings.revision)
catalogue = cache._build_catalog(path=os.path.join(work, 'roles.csv'))
import shutil
shutil.copy(os.path.join(fixtures, 'sod.sod.txt'), os.path.join(work, 'sod.csv'))
sod = parse_sod(os.path.join(work, 'sod.csv'))

def publish(spec):
    text = transform(base_users, spec)
    path = os.path.join(work, 'users.csv')
    with open(path, 'w', encoding='utf-8', newline='') as stream: stream.write(text)
    state = cache._build_catalog(path=os.path.join(work, 'roles.csv'))
    state.users = build_users(path, UserImportProfile(id='default', name='x'), state.roles)
    state.sod, state.directory = sod, None
    cache._cache = state
    current = config.get_settings().model_copy(deep=True)
    stamp = datetime.now(timezone.utc).isoformat()
    current.data_lifecycle.sources['users'] = SourceSnapshot(snapshot=hashlib.sha256(text.encode()).hexdigest(), path=path, imported_at=stamp, checked_at=stamp)
    current.data_lifecycle.sources['roles'] = SourceSnapshot(snapshot=hashlib.sha256(roles.encode()).hexdigest(), path=os.path.join(work, 'roles.csv'), imported_at=stamp, checked_at=stamp)
    config.save_configuration(current, current.revision)
    return lifecycle.observe()

def overview():
    result = subject(dict(context='current', validity='active', as_of=None), user=USER, risk='', activity='')
    clean = lambda rows, drop: [{k: v for k, v in row.items() if k not in drop} for row in rows]
    return json.loads(json.dumps(dict(user=result['user'], groups=result['groups'],
                                      assignments=clean(result['overview']['assignments'], ('event', 'remediation_verification')),
                                      activities=clean(result['overview']['activities'], ('event',)),
                                      risks=clean(result['overview']['risks'], ('event', 'risk_review_event'))), default=str))

def keep(role):
    bundle = scope.load('current')
    entry = scope.review_model_for(bundle)[USER]
    aid, item = next((aid, a) for aid, a in entry['assignments'].items() if a['role'] == role)
    body = DecisionBody(context='current', expected_revision=decisions.read().revision, expected_generation=bundle['generation'], decision='Keep',
                        items=[DecisionItem(key=aid, user=USER, ref=role, evidence_version=item['evidence_version'])], reviewer='Synthetic reviewer',
                        justification='Synthetic justification')
    decide('assignment', body)

STEPS = [
    dict(name='reviewed', users={}, keep=[ROLE_A, ROLE_B]),
    dict(name='removed', users={'drop': [[USER, ROLE_A]]}),
    dict(name='reappeared', users={}),
    dict(name='reviewed_again', users=None, keep=[ROLE_A]),
    dict(name='removed_again', users={'drop': [[USER, ROLE_A]]}),
    dict(name='reappeared_again', users={}),
    dict(name='reviewed_third', users=None, keep=[ROLE_A]),
    dict(name='identity_changed', users={'identity': {USER: ['Other', 'Person', 'other.person@example.invalid']}}),
    dict(name='validity_changed', users={'identity': {USER: ['Other', 'Person', 'other.person@example.invalid']}, 'valid_to': {f'{USER}|{ROLE_B}': '2097-12-31'}}),
]
results = []
for step in STEPS:
    observed = publish(step['users']) if step['users'] is not None else None
    for role in step.get('keep', []): keep(role)
    results.append(dict(name=step['name'], users=step['users'], keep=step.get('keep', []), observed=observed, subject=overview(),
                        lifecycle={key: dict(state=item.state, reason=item.reason, reappeared=bool(item.reappeared_at)) for key, item in lifecycle.read().items.items()},
                        events=sum(len(events) for kinds in decisions.read().contexts.values() for events in kinds.get('assignment', {}).values())))
with open(out, 'w', encoding='utf-8') as stream:
    json.dump(dict(user=USER, roles=[ROLE_A, ROLE_B], steps=results), stream, indent=1, ensure_ascii=False)
