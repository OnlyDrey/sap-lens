"""Deterministic synthetic SAP Lens datasets (roles, users, SoD) for equivalence tests and benchmarks. No real SAP data, names or e-mail domains.

  python generate_dataset.py --size small --out DIR        # edge cases, used by the functional equivalence comparison
  python generate_dataset.py --size large --out DIR        # volume for benchmarks
  python generate_dataset.py --size small --variant changed --out DIR   # a second revision for change detection

Dates are far from today (2001, 2000-2098, 2099), so validity classification does not depend on the day a test runs."""
import argparse
import csv
import random
from pathlib import Path

AREAS = ['FI', 'CO', 'MM', 'SD', 'PP', 'Finance', 'BASIS', 'HR', 'QM', 'PM', 'XX-UNKNOWN', '']


def write(path, header, rows, delimiter=';', encoding='utf-8'):
    with open(path, 'w', newline='', encoding=encoding) as stream:
        writer = csv.writer(stream, delimiter=delimiter, lineterminator='\r\n')
        writer.writerow(header)
        writer.writerows(rows)


def roles(rng, count, tcodes_per_child, edge):
    rows = []
    names = []
    codes = [f'T{n:04d}' for n in range(400 if count < 1000 else 3000)]
    for index in range(count):
        kind = 'ZC' if index % 5 else 'ZO'
        area = AREAS[index % len(AREAS)]
        name = f'{kind}:{area or "GEN"}:ROLE_{index:05d}'
        if kind == 'ZO' and index % 10 == 0:
            name = f'ZO:MM:M{index % 3}:{"PR" if index % 20 else "PO"}_REL_ST_E{index % 4}_{index % 7:02d}:ALL'
        names.append(name)
        text = f'Synthetic role {index}'
        for child in range(1 + index % 3):
            child_name = f'{name}_C{child}'
            for code in rng.sample(codes, tcodes_per_child):
                rows.append([area, name, text, child_name, f'Child {child} of {index}', name if child % 2 else '', '', code, f'Transaction {code}'])
        if index % 7 == 0:  # direct composite transaction (no child)
            rows.append([area, name, text, '', '', '', '', rng.choice(codes), ''])
        if index % 11 == 0:  # effective role path
            rows.append([area, name, text, '', '', name, f'{name}_EFF', rng.choice(codes), 'Effective path'])
    if edge:
        rows += [
            ['FI', 'ZC:FI:WILD*', 'Wildcard pattern', 'ZC:FI:WILD_CHILD', 'Wild child', '', '', 'FB01', 'Post document'],
            ['FI', 'ZC:FI:WILD*', 'Wildcard pattern', 'ZC:FI:WILD_CHILD', 'Wild child', '', '', 'fb03', 'Display document'],
            ['MM', 'ZC:MM:DUP A', 'Duplicate A', 'ZC:MM:DUPA_C', '', '', '', 'ME21N', 'Create PO'],
            ['MM', 'ZC:MM:DUPA', 'Duplicate B', 'ZC:MM:DUPA_C2', '', '', '', 'ME23N', 'Display PO'],
            ['FI', 'ZC:CONFLICT:AREA', 'Conflicting areas', 'ZC:CONFLICT:AREA_C', '', '', '', 'F110', 'Payment run'],
            ['MM', 'ZC:CONFLICT:AREA', 'Conflicting areas', 'ZC:CONFLICT:AREA_C', '', '', '', 'F110', 'Payment run (alt text)'],
            ['FI', 'ZC:CONFLICT:AREA', 'Other description', 'ZC:CONFLICT:AREA_C', 'Child alt', '', '', 'FK01', 'Create vendor'],
            ['FI', 'ZC:BAD?PATTERN', 'Invalid pattern', 'ZC:BAD_C', '', '', '', 'FB01', 'Post document'],
            ['', 'ZC:NO:TCODES', 'Role without transactions', 'ZC:NO:TCODES_C', '', '', '', '', ''],
            ['FI', 'ZC:FI:ROLE_00001', 'Synthetic role 1', 'ZC:FI:ROLE_00001_C0', 'Child 0 of 1', '', '', 'FB01', 'Post document'],  # possible duplicate of an existing row
        ]
        rows.append(['FI', 'ZC:FI:ROLE_00001', 'Synthetic role 1', 'ZC:FI:ROLE_00001_C0', 'Child 0 of 1', '', '', 'FB01', 'Post document'])  # exact duplicate
        rows.append(['', '', '', '', '', '', '', '', ''])  # blank record
        names += ['ZC:FI:WILD_SPECIFIC', 'ZC:MM:DUPA', ' zc:mm:dup a ', 'ZC:NOT:IN:CATALOGUE', 'ZC:CONFLICT:AREA', 'ZC:NO:TCODES']
    return rows, names


def users(rng, count, names, edge):
    rows = []
    groups = ['GRP_FIN', 'GRP_LOG', 'GRP_HR', 'GRP_IT', 'GRP_*LITERAL', '']
    validity = [('20000101', '20981231'), ('19990101', '20011231'), ('20990101', '20991231'), ('', ''), ('2000-01-01', '2098-12-31'), ('00000000', '99991231')]
    locks = ['', '0', 'X', '64', 'NO', 'LOCKED', 'maybe']
    for index in range(count):
        user = f'USER{index:05d}'
        group = groups[index % len(groups)]
        user_from, user_to = validity[index % 3 if index % 13 else 3]
        lock = locks[index % len(locks)]
        for _ in range(1 + index % 9):
            role = rng.choice(names)
            role_from, role_to = rng.choice(validity)
            rows.append([user if index % 17 else user.lower(), role, group, f'First{index % 50}', f'Last{index}', f'user{index}@example.invalid' if index % 4 else '',
                         user_from, user_to, role_from, role_to, lock, 'A' if index % 6 else 'S'])
        if index % 19 == 0:
            rows.append([user, '', group, f'First{index % 50}', f'Last{index}', '', user_from, user_to, '', '', lock, 'A'])  # directory-only record
    if edge:
        rows += [
            ['EDGE01', 'ZC:FI:WILD_SPECIFIC', 'GRP_FIN', 'Edge', 'One', 'edge01@example.invalid', '20000101', '20981231', '20000101', '20981231', '', 'A'],
            ['edge01', ' zc:mm:dup a ', 'GRP_FIN', 'Edge', 'One', 'edge01b@example.invalid', '20000101', '20981231', '20000101', '20981231', 'X', 'A'],
            ['EDGE01', 'ZC:CONFLICT:AREA', 'GRP_LOG', 'Edge', 'Uno', '', '20000101', '20981231', '', '', '0', 'A'],
            ['EDGE02', 'ZC:CONFLICT:AREA', 'GRP_FIN', 'Edge', 'Two', '', '20000101', '20981231', '20000101', '20981231', '', 'A'],
            ['EDGE02', 'ZC:NOT:IN:CATALOGUE', 'GRP_FIN', 'Edge', 'Two', '', '20000101', '20981231', '20000101', '20981231', '', 'A'],
            ['EDGE02', 'ZO:MM:M1:PR_REL_ST_E2_03:ALL', 'GRP_FIN', 'Edge', 'Two', '', '20000101', '20981231', '20000101', '20981231', '', 'A'],
            ['EDGE02', 'ZC:FI:WILD_SPECIFIC', 'GRP_FIN', 'Edge', 'Two', '', '20000101', '20981231', '19990101', '20011231', '', 'A'],
        ]
        rows.append(rows[-1])  # exact duplicate
    return rows


def sod(rng, risks, codes):
    rows = []
    for index in range(risks):
        risk = f'R{index:03d}'
        criticality = ['High', 'Medium', 'Low', 'Critical'][index % 4]
        risk_type = 'S' if index % 6 else 'P'
        a1, a2 = f'ACT_{index}_A', f'ACT_{index}_B'
        for slot, activity in (('ACTVT1', a1), ('ACTVT2', a2)):
            for code in rng.sample(codes, 3):
                rows.append([risk, criticality, risk_type, f'Risk {index}', a1, a2, slot, activity, code if index % 5 else code.lower(), f'Transaction {code}' if index % 9 else ''])
    rows.append(rows[0])  # duplicate
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--size', choices=['small', 'large'], required=True)
    parser.add_argument('--variant', choices=['base', 'changed', 'shrunk'], default='base')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    rng = random.Random(20261115)
    small = args.size == 'small'
    role_rows, names = roles(rng, 220 if small else 4000, 4 if small else 12, small)
    user_rows = users(rng, 300 if small else 20000, names, small)
    codes = sorted({row[7] for row in role_rows if row[7]})
    sod_rows = sod(rng, 40 if small else 300, codes)
    if args.variant == 'changed':
        role_rows = role_rows[: int(len(role_rows) * 0.9)] + [['SD', 'ZC:SD:NEW_ROLE', 'New role', 'ZC:SD:NEW_ROLE_C', '', '', '', 'VA01', 'Create order']]
        user_rows = [row[:3] + [row[3] + ('x' if i % 50 == 0 else '')] + row[4:] for i, row in enumerate(user_rows)]
    if args.variant == 'shrunk':
        role_rows = [row for row in role_rows if row[0] not in ('FI', 'Finance')][: len(role_rows) // 2]
        user_rows = user_rows[: len(user_rows) // 3]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    write(out / 'roles.csv', ['FUNCTION_KEY', 'AGR_NAME', 'TEXT', 'CHILD_AGR', 'CHILD_AGR_TEXT', 'PARENT_AGR', 'Effective_Role', 'TCODE', 'TTEXT'], role_rows)
    write(out / 'users.csv', ['USERNAME', 'ROLE_NAME', 'USER_GROUP', 'FIRST_NAME', 'LAST_NAME', 'EMAIL', 'USER_VALID_FROM', 'USER_VALID_TO', 'ROLE_VALID_FROM', 'ROLE_VALID_TO',
                              'USER_LOCKED', 'USER_TYPE'], user_rows)
    write(out / 'sod.csv', ['RISK', 'CRITICITY', 'TYPE', 'TEXT', 'ACTVT1', 'ACTVT2', 'ACTIVITY_SLOT', 'ACTIVITY', 'TCODE', 'TTEXT'], sod_rows)
    print(f'{out}: roles {len(role_rows)} rows, users {len(user_rows)} rows, sod {len(sod_rows)} rows')


if __name__ == '__main__':
    main()
