"""Python v1 reference for MIG-003 (position_changes.detect / detect_managers).
Writes synthetic Employee Directory pairs (before/after) to FIXTURE_DIR and records v1's events and notices for each pair (fixed detected_at).
Usage: python -I tools/position_changes_reference.py BACKEND_DIR FIXTURE_DIR"""
import json, os, sys, tempfile
os.environ['SAP_LENS_CONFIG_DIR'] = tempfile.mkdtemp()
backend, fixtures = sys.argv[1:3]
sys.path.insert(0, backend)
from pathlib import Path
from employee_directory import HEADERS, parse_directory
import position_changes as pc

def row(i, dept='Finance', title='Analyst', mail=None, manager='boss@example.invalid', manager_name='Boss', sam=None):
    v = dict(Site='HQ', Name=f'Person {i}', SamAccountName=sam if sam is not None else f'P{i:03}', UserPrincipalName=f'p{i}@example.invalid',
             Mail=mail if mail is not None else f'person{i}@example.invalid', Department=dept, Title=title, Enabled='True', DistinguishedName=f'CN=Person {i},OU=Staff',
             ManagerDN='', ManagerName=manager_name, ManagerSamAccountName='', ManagerMail=manager, ManagerDepartment='', ManagerTitle='', ManagerLookupStatus='Resolved')
    return ';'.join(v[h] for h in HEADERS)

base = [row(i) for i in range(20)] + [row(90, mail='dup@example.invalid'), row(91, mail='dup@example.invalid')]
cases = {
    'changes': (base, [row(i, dept='Sales' if i == 1 else '  finance ' if i == 2 else 'Finance', title='Lead' if i in (3, 1) else 'Analyst',
                           manager='other@example.invalid' if i == 4 else '' if i == 5 else 'boss@example.invalid', manager_name='Other' if i == 4 else 'Boss') for i in range(20)]
               + [row(90, mail='dup@example.invalid', dept='HR'), row(91, mail='dup@example.invalid'), row(30, dept='New')]),
    'incomplete': (base, [row(i, dept='Sales') for i in range(5)]),
    'blank_titles': (base, [row(i, title='', dept='Sales' if i == 0 else 'Finance') for i in range(20)]),
    'unchanged': (base, base),
}
out = {}
work = Path(tempfile.mkdtemp())
for name, (before, after) in cases.items():
    directories = []
    for side, rows in (('before', before), ('after', after)):
        text = ';'.join(HEADERS) + '\n' + '\n'.join(rows) + '\n'
        (Path(fixtures) / f'{name}_{side}.txt').write_text(text, encoding='utf-8')
        (work / f'{name}_{side}.csv').write_text(text, encoding='utf-8')
        directories.append(parse_directory(work / f'{name}_{side}.csv'))
    events, notices = pc.detect(directories[0], directories[1], '2026-11-16T08:00:00+00:00')
    managers = pc.detect_managers(directories[0], directories[1], '2026-11-16T08:00:00+00:00')
    out[name] = dict(events=events, notices=notices, managers=managers)
(Path(fixtures) / 'position-changes.python.json').write_text(json.dumps(out, ensure_ascii=False, indent=0, sort_keys=True) + '\n', encoding='utf-8')
print({k: (len(v['events']), len(v['managers']), len(v['notices'])) for k, v in out.items()})
