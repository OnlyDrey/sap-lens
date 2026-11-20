"""Synthetic SAP Lens v1 installation for the v1 to v2 migration tests, produced by the real v1 application (FastAPI TestClient, desktop mode) and the
real v1 backup engine. Synthetic, reserved-domain data only; the keys and the passphrase are synthetic test secrets.

Usage: .venv/bin/python -I tools/v1_data_fixture.py BACKEND_DIR OUT_DIR

Writes OUT_DIR/data (the v1 data directory), OUT_DIR/v1-host.slbak and OUT_DIR/v1-passphrase.slbak (application backups of that directory written by
application_backups.startup: host-key HKDF and scrypt passphrase modes) and OUT_DIR/expected.json (what the .NET tests compare with, including the
synthetic passphrase and the escrowed recovery copy of the synthetic host key; no *.key file is written, so nothing key-shaped is committed).

Content: two role, user and SoD matrix revisions (Norwegian names), a saved filter, Account Review decisions with history, SoD 2.0 decisions in the live
context (activity, assignment, risk review), a remediation action with history, an approved review period with its decisions and frozen snapshot, a
second draft period, and legacy SoD 1.0 reviews."""
import csv, json, os, shutil, sys, tempfile
from pathlib import Path

backend, out = sys.argv[1:3]
work = Path(tempfile.mkdtemp())
private = work / 'private'
keys = work / 'keys'
keys.mkdir()
os.environ['SAP_LENS_CONFIG_DIR'] = str(private)
os.environ['SAP_LENS_DATA_DIR'] = str(private)
os.environ['SAP_LENS_DEPLOYMENT_MODE'] = 'desktop'
os.environ['DATA_CSV_PATH'] = ''
os.environ['SAP_LENS_BACKUP_KEY_FILE'] = str(keys / 'host.key')
sys.path.insert(0, backend)
import cache, config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from main import create_app  # noqa: E402

PASSPHRASE = 'Synthetic v1 migration passphrase'
H = {'X-SAP-Lens': '1'}
files = {name: work / f'{name}.csv' for name in ('roles', 'users', 'sod')}
HEADERS = dict(
    roles=['FUNCTION_KEY', 'AGR_NAME', 'TEXT', 'CHILD_AGR', 'CHILD_AGR_TEXT', 'PARENT_AGR', 'Effective_Role', 'TCODE', 'TTEXT'],
    users=['USERNAME', 'ROLE_NAME', 'USER_GROUP', 'FIRST_NAME', 'LAST_NAME', 'EMAIL', 'USER_VALID_FROM', 'USER_VALID_TO', 'ROLE_VALID_FROM', 'ROLE_VALID_TO', 'USER_LOCKED', 'USER_TYPE'],
    sod=['RISK', 'CRITICITY', 'TYPE', 'TEXT', 'ACTVT1', 'ACTVT2', 'ACTIVITY_SLOT', 'ACTIVITY', 'TCODE', 'TTEXT'])


def write(name, rows):
    with files[name].open('w', encoding='utf-8', newline='') as f:
        w = csv.writer(f, delimiter=';'); w.writerow(HEADERS[name]); w.writerows(rows)


def sources(revision):
    roles = [('ZC:FI:ROLE_A1', 'X1'), ('ZC:FI:ROLE_A2', 'X1'), ('ZC:FI:ROLE_B', 'X2'), ('ZC:FI:ROLE_C', 'X3'), ('ZC:FI:ROLE_AB', 'X1'), ('ZC:FI:ROLE_AB', 'X2')]
    if revision: roles.append(('ZC:FI:ROLE_D', 'X4'))
    write('roles', [['FI', r, f'Økonomi {r[-4:]}', '', '', '', '', t, f'Transaksjon {t}'] for r, t in roles])
    people = [('KARI', ['ZC:FI:ROLE_A1', 'ZC:FI:ROLE_A2', 'ZC:FI:ROLE_B', 'ZC:FI:ROLE_C'], 'Kari', 'Nordmann'), ('ØYSTEIN', ['ZC:FI:ROLE_AB'], 'Øystein', 'Ødegård'),
              ('ÅSE', ['ZC:FI:ROLE_A1'], 'Åse', 'Ærøy')]
    if revision: people.append(('OLA', ['ZC:FI:ROLE_D'], 'Ola', 'Nordmann'))
    write('users', [[u, r, 'GRP_ØKONOMI', f, l, f'{u.lower()}@example.com', '20000101', '99991231', '20000101', '99991231', '0', 'A'] for u, rs, f, l in people for r in rs])
    risks = [('R1', 'High', 'A', 'B', 'X1', 'X2'), ('R2', 'Medium' if revision else 'High', 'A', 'C', 'X1', 'X3')]
    write('sod', [[r, c, 'S', f'Synthetic {r}', a1, a2, slot, act, t, 'Synthetic'] for r, c, a1, a2, c1, c2 in risks for slot, act, t in (('ACTVT1', a1, c1), ('ACTVT2', a2, c2))])


import backup_crypto as crypto  # noqa: E402
private.mkdir()
crypto.create_key(keys / 'host.key', private)
crypto.verify_escrow((keys / 'host.key').read_text().strip(), private)
sources(0)
settings = config.get_settings().model_copy(deep=True)
settings.data_csv_path, settings.user_csv_path, settings.sod_csv_path = str(files['roles']), str(files['users']), str(files['sod'])
settings.features.sod = True
settings.source_modes.sod = 'dynamic'
config.save_configuration(settings, settings.revision); cache.load_cache()
from review_identity import profile  # noqa: E402
profile('Synthetic Reviewer', 0)
client = TestClient(create_app(session_token='1'), base_url='http://127.0.0.1:18743')


def get(path, **params):
    r = client.get(path, params=params, headers=H); assert r.status_code == 200, (path, r.text); return r.json()


def post(path, body, status=200):
    r = client.post(path, json=body, headers=H); assert r.status_code == status, (path, r.text); return r.json()


post('/api/refresh', {})
sources(1)
post('/api/refresh', {})
assert set(config.get_settings().data_lifecycle.sources) == {'roles', 'users', 'sod'}, config.get_settings().data_lifecycle.sources

# Saved filter and Account Review decisions (KARI twice: one history event).
post('/api/saved-filters', dict(name='Økonomi brukere', view='users', filters=dict(search='ø')))
for user_name, states in (('KARI', ('Investigating', 'No action required')), ('OLA', ('Investigating',))):
    for state in states:
        row = get('/api/account-review', search=user_name)['items'][0]
        post('/api/account-review/decision/' + user_name, dict(state=state, reviewer='Synthetic Reviewer', rationale=f'Synthetic {state}', evidence_version=row['evidence_version']))


def subject(user_name, context='current', **params):
    return get('/api/sod/subject', user=user_name, context=context, **params)


def decide(kind, items, decision, context='current', **extra):
    view = get('/api/sod/matrix/risk', context=context)
    body = dict(context=context, expected_revision=view['revision'], expected_generation=view['generation'], items=items, decision=decision,
                reviewer='Synthetic Reviewer', justification='Synthetic business need')
    body.update(extra)
    return post(f'/api/sod/decisions/{kind}', body)


def activity_item(user_name, name, context='current'):
    detail = next(row for row in subject(user_name, context)['activities'] if row['activity'] == name)
    return dict(key=detail['key'], user=user_name, ref=name, evidence_version=detail['evidence_version'])


def assignment_item(user_name, role_name, activity='A', context='current'):
    detail = next(row for row in subject(user_name, context)['activities'] if row['activity'] == activity)
    found = next(item for item in detail['assignments'] if item['role'] == role_name)
    return dict(key=found['id'], user=user_name, ref=role_name, evidence_version=found['evidence_version'])


def risk_item(user_name, risk_id, context='current'):
    detail = subject(user_name, context, risk=risk_id)['risk']
    return dict(key=detail['finding_id'], user=user_name, ref=risk_id, evidence_version=detail['evidence_version'])


# SoD 2.0 in the live context: an assignment removal (then a remediation action with history), an activity approval and a risk review.
remove = assignment_item('KARI', 'ZC:FI:ROLE_A2')
decide('assignment', [remove], 'Remove')
decide('activity', [activity_item('ØYSTEIN', 'B')], 'Approved')
decide('risk', [risk_item('KARI', 'R1')], 'Approved')
decide('risk', [risk_item('KARI', 'R1')], 'Remove')                       # a second event on the same key
view = get('/api/sod/remediation')
post('/api/sod/remediation/actions', dict(context='current', expected_revision=view['revision'], actor='Synthetic Owner', user='KARI', assignment_id=remove['key'],
                                          role='ZC:FI:ROLE_A2', recommended='Remove assignment', reason='Duplicate access', owner='Synthetic Owner', due_date='2099-12-31'))
view = get('/api/sod/remediation')
action = view['actions'][0]
post('/api/sod/remediation/actions', dict(context='current', expected_revision=view['revision'], actor='Synthetic Owner', user='KARI', assignment_id=remove['key'],
                                          role='ZC:FI:ROLE_A2', recommended='Remove assignment', reason='Duplicate access', owner='Synthetic Owner', due_date='2099-12-31',
                                          action_id=action['id'], status='In progress'))

# An approved review period with every blocking item decided, and a second draft period with one decision.
def new_period(name):
    revision = get('/api/sod/periods')['revision']
    return post('/api/sod/periods', dict(name=name, start='2026-01-01', end='2026-12-31', evaluation_date='2026-10-27', expected_revision=revision))['period']['id']


def move(pid, state, **extra):
    details = get(f'/api/sod/periods/{pid}')
    return post(f'/api/sod/periods/{pid}/transition', dict(state=state, expected_revision=details['revision'], expected_review_revision=details['review_revision'], actor='Synthetic Actor', **extra))


approved = new_period('Kvartal Ø1 2026')
for user_name in ('KARI', 'ØYSTEIN'):
    view = subject(user_name, approved)
    decide('activity', [activity_item(user_name, row['activity'], approved) for row in view['activities']], 'Approved', context=approved)
    for risk in sorted({row['risk_id'] for row in view['overview']['risks']}):
        decide('acceptance', [risk_item(user_name, risk, approved)], 'Accepted', context=approved, approver='Synthetic Approver', expires='2099-12-31')
move(approved, 'In review')
move(approved, 'Ready for approval')
move(approved, 'Approved', reviewer='Synthetic Reviewer', approver='Synthetic Approver', approval_date='2026-10-27', confirm=True)
draft = new_period('Utkast 2027')
decide('activity', [activity_item('KARI', 'A', draft)], 'Remove', context=draft)

# Legacy SoD 1.0 reviews of the live context.
legacy = get('/api/sod/reviews', limit=100)
target = next(row for row in legacy['items'] if row['finding']['current_potential'])
for decision in ('Further investigation required', 'Access removal required'):
    legacy = get('/api/sod/reviews', limit=100)
    post(f"/api/sod/reviews/{target['finding_id']}", dict(expected_revision=legacy['revision'], expected_generation=legacy['generation'], evidence_version=target['finding']['evidence_version'],
                                                         annotation=dict(decision=decision, reviewer='Synthetic Reviewer', rationale=f'Synthetic {decision}', action_owner='Synthetic Owner')))

# Application backups of this directory, as the administrator downloads them: host key, then passphrase (one pending operation at a time).
import application_backups as backups  # noqa: E402
from storage_lease import StorageLease  # noqa: E402
archives = {}
for mode, passphrase in (('host', ''), ('passphrase', PASSPHRASE)):
    request = backups.request_backup(private, passphrase=passphrase)
    lease = StorageLease(private, 'desktop').acquire()
    try: backups.startup(lease)
    finally: lease.close()
    state = backups.read(private)
    assert state['status'] == 'ready', state
    archives[mode] = backups.download(request['id'], data=private)

decisions = json.loads((private / 'sod-decisions.json').read_text(encoding='utf-8'))
periods = json.loads((private / 'sod-periods.json').read_text(encoding='utf-8'))
reviews = json.loads((private / 'sod-reviews.json').read_text(encoding='utf-8'))
snapshots = sorted(p.stem for p in (private / 'csv-data' / 'snapshots').glob('*.json'))
source_snapshots = [s for s in snapshots if json.loads((private / 'csv-data' / 'snapshots' / f'{s}.json').read_text(encoding='utf-8')).get('source') in ('roles', 'users', 'sod')]
events = [e for kinds in decisions['contexts'].values() for keys in kinds.values() for items in keys.values() for e in items]
settings = config.get_settings()
expected = dict(
    sources={name: s.snapshot for name, s in settings.data_lifecycle.sources.items()},
    saved_filters=[f['name'] for f in json.loads((private / 'saved-filters.json').read_text(encoding='utf-8'))['items']],
    account_review={k: dict(state=v['state'], history=len(v.get('history', []))) for k, v in json.loads((private / 'account-review.json').read_text(encoding='utf-8'))['decisions'].items()},
    users=sorted(r['username'] for r in get('/api/access/users', show_expired='true')['items']),
    snapshots=snapshots, source_snapshots=sorted(source_snapshots), evidence_snapshots=sorted(set(snapshots) - set(source_snapshots)),
    reports=sorted(p.stem for p in (private / 'csv-data' / 'reports').glob('*.json')),
    sod=dict(
        events=len(events), event_ids=sorted(e['event_id'] for e in events), contexts=sorted(decisions['contexts']), decisions_revision=decisions['revision'],
        actions={a['id']: dict(status=a['status'], history=len(a['history'])) for a in decisions['actions'].values()},
        periods={p['id']: dict(name=p['name'], state=p['state'], snapshot=p['snapshot'], snapshots=p['snapshots'], history=len(p.get('history', []))) for p in periods['items']},
        periods_revision=periods['revision'], approved=approved, draft=draft,
        legacy={context: {fid: len(items) for fid, items in findings.items()} for context, findings in reviews['contexts'].items()},
        legacy_finding=target['finding_id'],
        queue_current=get('/api/sod/queue', context='current', limit=100)['counts'],
        matrix_approved=get('/api/sod/matrix/risk', context=approved)['totals'],
        remediation=sorted((i['user'], i['role'], i['action_status']) for i in get('/api/sod/remediation')['items'] if i.get('action_status')),
    ),
    passphrase=PASSPHRASE, recovery_key=(keys / 'host.key').read_text().strip(),
)

target_dir = Path(out)
if target_dir.exists(): shutil.rmtree(target_dir)
ignore = lambda d, names: [n for n in names if n.endswith('.log') or n in {'store', '.key', 'cache', '.application-backups', '.sap-lens-instance.lock'}]
shutil.copytree(private, target_dir / 'data', ignore=ignore)
shutil.copyfile(archives['host'], target_dir / 'v1-host.slbak')
shutil.copyfile(archives['passphrase'], target_dir / 'v1-passphrase.slbak')
(target_dir / 'expected.json').write_text(json.dumps(expected, ensure_ascii=False, indent=1, sort_keys=True), encoding='utf-8')
shutil.rmtree(work, ignore_errors=True)
print(json.dumps(dict(events=expected['sod']['events'], periods=len(expected['sod']['periods']), evidence=len(expected['evidence_snapshots']), legacy=expected['sod']['legacy']), ensure_ascii=False))
