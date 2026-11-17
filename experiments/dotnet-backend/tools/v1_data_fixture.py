"""Synthetic SAP Lens v1 data directory for the v1 to v2 migration tests, written by the real v1 application (FastAPI TestClient, desktop mode).

Usage: .venv/bin/python -I tools/v1_data_fixture.py BACKEND_DIR OUT_DIR
Creates: two role revisions and two user revisions (the first of each superseded), Norwegian names, a saved filter, a reviewer profile, account review
decisions (with history), and an expected.json summary the .NET tests compare with. Synthetic, reserved-domain data only."""
import csv, json, os, shutil, sys, tempfile
from pathlib import Path

backend, out = sys.argv[1:3]
work = Path(tempfile.mkdtemp())
private = work / 'private'
os.environ['SAP_LENS_CONFIG_DIR'] = str(private)
os.environ['DATA_CSV_PATH'] = ''
sys.path.insert(0, backend)
import cache, config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from main import create_app  # noqa: E402

H = {'X-SAP-Lens': '1'}
roles_csv, users_csv = work / 'roles.csv', work / 'users.csv'
ROLE_HEADER = ['FUNCTION_KEY', 'AGR_NAME', 'TEXT', 'CHILD_AGR', 'CHILD_AGR_TEXT', 'PARENT_AGR', 'Effective_Role', 'TCODE', 'TTEXT']
USER_HEADER = ['USERNAME', 'ROLE_NAME', 'USER_GROUP', 'FIRST_NAME', 'LAST_NAME', 'EMAIL', 'USER_VALID_FROM', 'USER_VALID_TO', 'ROLE_VALID_FROM', 'ROLE_VALID_TO', 'USER_LOCKED', 'USER_TYPE']


def write(path, header, rows):
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.writer(f, delimiter=';'); w.writerow(header); w.writerows(rows)


def roles(extra):
    rows = [['FI', f'ZC:FI:ROLE_{i:04d}', f'Økonomi rolle {i}', '', '', '', '', f'T{i:03d}', f'Transaksjon {i}'] for i in range(4 + extra)]
    write(roles_csv, ROLE_HEADER, rows)


def users(extra):
    people = [('ØYSTEIN', 'Øystein', 'Ødegård'), ('ÅSE', 'Åse', 'Ærøy'), ('KARI', 'Kari', 'Nordmann'), ('OLA', 'Ola', 'Nordmann')][:3 + extra]
    rows = [[u, f'ZC:FI:ROLE_{i:04d}', 'GRP_ØKONOMI', f, l, f'{f.lower()}@example.com', '20000101', '99991231', '', '', '0', 'A'] for i, (u, f, l) in enumerate(people)]
    write(users_csv, USER_HEADER, rows)


roles(0); users(0)
settings = config.get_settings().model_copy(deep=True)
settings.data_csv_path, settings.user_csv_path = str(roles_csv), str(users_csv)
config.save_configuration(settings, settings.revision); cache.load_cache()
client = TestClient(create_app(session_token='1'), base_url='http://127.0.0.1:18743')
assert client.post('/api/refresh', headers=H, json={}).status_code == 200
roles(1); users(1)
response = client.post('/api/refresh', headers=H, json={})
assert response.status_code == 200, response.text
assert client.post('/api/saved-filters', headers=H, json=dict(name='Økonomi brukere', view='users', filters=dict(search='ø'))).status_code == 200
assert client.post('/api/reviewer-profile', headers=H, json=dict(name='Synthetic Reviewer', email='reviewer@example.com')).status_code in (200, 422)
review = client.get('/api/account-review', headers=H).json()
rows = {r['username']: r for r in review['items']}
for state in ('Investigating', 'No action required'):
    row = client.get('/api/account-review?search=' + 'KARI', headers=H).json()['items'][0]
    r = client.post('/api/account-review/decision/KARI', headers=H, json=dict(state=state, reviewer='Synthetic Reviewer', rationale=f'Synthetic {state}', evidence_version=row['evidence_version']))
    assert r.status_code == 200, r.text
row = client.get('/api/account-review?search=OLA', headers=H).json()['items'][0]
assert client.post('/api/account-review/decision/OLA', headers=H, json=dict(state='Investigating', reviewer='Synthetic Reviewer', rationale='Ola check', evidence_version=row['evidence_version'])).status_code == 200

settings = config.get_settings()
expected = dict(
    sources={name: s.snapshot for name, s in settings.data_lifecycle.sources.items()},
    saved_filters=[f['name'] for f in json.loads((private / 'saved-filters.json').read_text(encoding='utf-8'))['items']],
    account_review={k: dict(state=v['state'], history=len(v.get('history', []))) for k, v in json.loads((private / 'account-review.json').read_text(encoding='utf-8'))['decisions'].items()},
    users=sorted(r['username'] for r in client.get('/api/access/users?show_expired=true', headers=H).json()['items']),
    snapshots=sorted(p.stem for p in (private / 'csv-data' / 'snapshots').glob('*.json')),
    reports=sorted(p.stem for p in (private / 'csv-data' / 'reports').glob('*.json')),
)
target = Path(out)
if target.exists(): shutil.rmtree(target)
keep = lambda d, names: [n for n in names if n.endswith('.log') or n in {'store', '.key', 'cache'}]
shutil.copytree(private, target / 'data', ignore=keep)
(target / 'expected.json').write_text(json.dumps(expected, ensure_ascii=False, indent=1, sort_keys=True), encoding='utf-8')
shutil.rmtree(work)
print(json.dumps(expected, ensure_ascii=False)[:600])
