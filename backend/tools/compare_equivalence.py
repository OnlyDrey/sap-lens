"""Compares the Python v1 and .NET v2 equivalence outputs scenario by scenario. Only `implementation` and `timings` are excluded; nothing that
carries a decision, identity, permission, risk or calculation result is normalised. Writes a JSON report and prints a Markdown table.

  python compare_equivalence.py python.json dotnet.json --json report.json"""
import argparse
import json


def first_difference(a, b, path='$'):
    if type(a) is not type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        return f'{path}: type {type(a).__name__} vs {type(b).__name__} ({str(a)[:80]!r} vs {str(b)[:80]!r})'
    if isinstance(a, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                return f'{path}.{key}: present only in {"python" if key in a else "dotnet"}'
            found = first_difference(a[key], b[key], f'{path}.{key}')
            if found:
                return found
        return None
    if isinstance(a, list):
        for index, (x, y) in enumerate(zip(a, b)):
            found = first_difference(x, y, f'{path}[{index}]')
            if found:
                return found
        return f'{path}: length {len(a)} vs {len(b)}' if len(a) != len(b) else None
    return None if a == b else f'{path}: {str(a)[:120]!r} vs {str(b)[:120]!r}'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('python')
    parser.add_argument('dotnet')
    parser.add_argument('--json')
    args = parser.parse_args()
    py, net = json.load(open(args.python)), json.load(open(args.dotnet))
    rows = []
    for section in ('catalogue', 'users', 'sod_source'):
        rows.append((section, py[section], net[section]))
    for section in ('role_lookup', 'user_lookup', 'comparison', 'comparison_listing', 'sod', 'import_checks'):
        for index, (a, b) in enumerate(zip(py[section], net[section])):
            rows.append((f'{section}[{index}]', a, b))
    for name in sorted(set(py['malformed']) | set(net['malformed'])):
        rows.append((f'malformed/{name}', py['malformed'].get(name), net['malformed'].get(name)))
    report = []
    for name, a, b in rows:
        difference = first_difference(a, b)
        report.append(dict(scenario=name, match=difference is None, difference=difference,
                           python_summary=summary(a), dotnet_summary=summary(b)))
    if args.json:
        json.dump(dict(total=len(report), matched=sum(r['match'] for r in report), scenarios=report), open(args.json, 'w'), indent=1)
    print('| Scenario | Python | .NET | Result |')
    print('| --- | --- | --- | --- |')
    for r in report:
        print(f"| {r['scenario']} | {r['python_summary']} | {r['dotnet_summary']} | {'MATCH' if r['match'] else 'MISMATCH: ' + r['difference']} |")
    print(f"\n{sum(r['match'] for r in report)} of {len(report)} scenarios match")
    return 0 if all(r['match'] for r in report) else 1


def summary(value):
    if isinstance(value, list):
        return f'{len(value)} items'
    if isinstance(value, dict):
        if 'error' in value:
            return 'error: ' + str(value['error'])[:60]
        if 'ok' in value:
            return 'ok' if value['ok'] else 'rejected: ' + str(value.get('error'))[:60]
        if 'users' in value and 'roles' in value and isinstance(value['users'], list):
            return f"{len(value['users'])} users / {len(value['roles'])} roles"
        if 'suspicious' in value:
            return ('held' if value['suspicious'] else 'not held') + f", diff {value['diff']}"
        if 'counts' in value:
            return ', '.join(f'{k}={v}' for k, v in value['counts'].items())[:120]
        if 'content_hash' in value:
            return value['content_hash'][:16]
    return str(value)[:60]


if __name__ == '__main__':
    raise SystemExit(main())
