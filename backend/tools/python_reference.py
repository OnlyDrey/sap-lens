"""Runs the PRODUCTION Python v1 functions (backend/, unchanged) on a synthetic dataset and writes the neutral JSON that the .NET port also writes.

  python python_reference.py --data DATASETS_DIR --scenarios scenarios.json --malformed MALFORMED_DIR --out python.json [--dataset small|large]

Uses an isolated temporary configuration directory; never reads or writes a real SAP Lens installation."""
import argparse
import json
import os
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
os.environ['SAP_LENS_CONFIG_DIR'] = tempfile.mkdtemp(prefix='saplens-v1-ref-')
for name in ('SAP_LENS_DATA_DIR', 'SAP_LENS_DEPLOYMENT_MODE', 'DATA_CSV_PATH', 'USER_CSV_PATH', 'SOD_CSV_PATH'):
    os.environ.pop(name, None)
sys.path.insert(0, str(Path(__file__).resolve().parent))  # with -I the tool's own folder is not on sys.path
from v1_location import v1_backend  # noqa: E402
sys.path.insert(0, v1_backend())

import cache  # noqa: E402
import csv_lifecycle  # noqa: E402
import import_checks  # noqa: E402
import sod_analysis  # noqa: E402
from config_models import ImportChecks, ImportProfile, UserImportProfile  # noqa: E402
from csv_import import CsvImport  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from routers import roles as roles_router  # noqa: E402
from routers import access as access_router  # noqa: E402
from routers import user_comparison  # noqa: E402
from sod_import import parse_sod  # noqa: E402
from user_access import UserCsvImport, build_users  # noqa: E402

TODAY = date.today()


def catalogue_json(state):
    roles = []
    for role in state.roles.values():
        roles.append(dict(agr_name=role.agr_name, text=role.text, function_key=role.function_key, module_name=role.module_name, tcode_count=role.tcode_count,
                          module_ambiguous=role.module_ambiguous, source_modules=role.source_modules, alternate_descriptions=role.alternate_descriptions,
                          relationships=[[r.child_agr, r.parent_agr, r.effective_role] for r in role.relationships],
                          single_roles=[dict(child_agr=s.child_agr, assignment_kind=s.assignment_kind, child_agr_text=s.child_agr_text, alternate_descriptions=s.alternate_descriptions,
                                             tcodes=[dict(tcode=t.tcode, ttext=t.ttext, alternate_texts=t.alternate_texts,
                                                          sources=[[x.child_agr, x.parent_agr, x.effective_role] for x in t.assignment_sources]) for t in s.tcodes])
                                        for s in role.single_roles]))
    report = state.import_report
    return dict(roles=roles, tcode_index={code: sorted(names) for code, names in sorted(state.tcode_index.items())},
                counts=dict(unique_roles=report['unique_roles'], unique_transactions=report['unique_transactions'], transaction_assignments=report['transaction_assignments'],
                            relationship_count=report['relationship_count'], parsed_rows=report['parsed_rows'], unique_records=report['unique_records'],
                            duplicate_rows=report['duplicate_rows']), warnings=report['warnings'])


def users_json(users):
    rows = []
    for key, user in users.users.items():
        rows.append(dict(key=key, username=user['username'], names=[list(n) for n in user['names']], emails=user['emails'], groups=user['groups'],
                         accounts=user['accounts'],
                         assignments=[dict(id=a['id'], role_name=a['role_name'], user_group=a['user_group'], scope=a['scope'], valid_from=a['valid_from'], valid_to=a['valid_to'],
                                           user_valid_from=a['user_valid_from'], user_valid_to=a['user_valid_to'], user_locked=a['user_locked'], user_type=a['user_type'],
                                           match_status=a['match_status'], catalogue_roles=a['catalogue_roles'], tcodes=a['tcodes'],
                                           release=a['release']) for a in user['assignments']]))
    report = users.report
    return dict(users=rows, role_index={k: [a['id'] for a in v] for k, v in sorted(users.role_index.items())}, tcode_index={k: v for k, v in sorted(users.tcode_index.items())},
                counts=dict(unique_users=report['unique_users'], assignments=report['assignments'], relevant_assignments=report['relevant_assignments'],
                            directory_only_users=report['directory_only_users'], invalid_catalogue_patterns=report['invalid_catalogue_patterns'], group_count=users.group_count,
                            parsed_rows=report['parsed_rows'], unique_records=report['unique_records'], duplicate_rows=report['duplicate_rows']), warnings=report['warnings'])


def role_lookup(query):
    result = roles_router.list_roles(function_key=query.get('function_key'), function_keys=query.get('function_keys', []), transaction_mode=query.get('transaction_mode', 'and'),
                                     search=query.get('search'), tcodes=query.get('tcodes', []), exclude_matching=query.get('exclude_matching', False), tcode=query.get('tcode'),
                                     exclude_tcodes=query.get('exclude_tcodes', []), exclude_mode=query.get('exclude_mode', 'any'))
    return [dict(agr_name=r.agr_name, text=r.text, function_key=r.function_key, module_name=r.module_name, tcode_count=r.tcode_count,
                 single_role_count=r.single_role_count, matching_tcodes=r.matching_tcodes) for r in result]


def user_lookup(snapshot, query):
    rows, _ = access_router.directory_selection(snapshot, search=query.get('search', ''), group=query.get('group', ''), role=query.get('role', ''), tcode=query.get('tcode', ''),
                                                groups=query.get('groups', []), roles=query.get('roles', []), tcodes=query.get('tcodes', []),
                                                transaction_mode=query.get('transaction_mode', 'and'), status=query.get('status', ''), show_expired=query.get('show_expired', False),
                                                sort=query.get('sort', 'username'), descending=query.get('descending', False), today=TODAY,
                                                exclude_transactions=query.get('exclude_transactions', False), exclude_tcodes=query.get('exclude_tcodes', []),
                                                exclude_mode=query.get('exclude_mode', 'any'))
    return [dict(username=u['username'], user_key=u['user_key'], groups=u['groups'], first_name=u['first_name'], last_name=u['last_name'], email=u['email'],
                 account_status=u['account_status'], lock_status=u['lock_status'], relevant_roles=u['relevant_roles']) for u in rows]


def comparison(snapshot, pair):
    try:
        result = user_comparison._compare(snapshot, pair['user_a'], pair['user_b'], pair['validity'])
    except HTTPException as error:
        return dict(error=str(error.detail))
    users = [dict(username=u['username'], user_key=u['user_key'], groups=u['groups'], first_name=u['first_name'], last_name=u['last_name'], email=u['email'],
                  account_status=u['account_status'], lock_status=u['lock_status'], relevant_roles=u['relevant_roles'], identity_ambiguous=u['identity_ambiguous']) for u in result['users']]
    return dict(users=users, roles=list(result['roles'].values()), transactions=list(result['transactions'].values()))


def listing(snapshot, pairs, spec):
    pair = pairs[spec['pair']]
    result = user_comparison._compare(snapshot, pair['user_a'], pair['user_b'], pair['validity'])
    rows = list(result[spec['kind']].values())
    wanted = set(spec['areas'])
    from search_matching import search_fields
    term = spec['search'].strip()
    rows = [r for r in rows if (not spec['difference'] or r['difference'] == spec['difference']) and (not wanted or wanted & set(r['areas']))
            and (not term or search_fields(term, r['identifier'], r.get('description', '')))]
    sort = spec['sort']
    rows.sort(key=lambda r: (len(r[sort]) if sort in {'a', 'b'} else r[sort], r['identifier']), reverse=spec['descending'])
    return [r['identifier'] for r in rows]


def sod_json(snapshot, spec):
    try:
        result = sod_analysis.analyze(snapshot, {}, TODAY, spec['validity'], spec.get('selected_roles'))
    except ValueError as error:
        return dict(error=str(error))
    finding = lambda f: dict(finding_id=f['finding_id'], subject=f['subject'], kind=f['kind'], risk_id=f['risk_id'], criticality=f['criticality'],
                             current_potential=f['current_potential'], evidence_version=f['evidence_version'])
    coverage = result['coverage']
    return dict(users=[finding(f) for f in result['users']], roles=[finding(f) for f in result['roles']],
                coverage=dict(eligible=coverage['eligible_assignment_records'], mapped=coverage['mapped_assignment_records'], supported_risks=coverage['supported_risks'],
                              status=coverage['status']), sod_content_hash=result['sources']['sod_content_hash'])


def records(source, path):
    profile = {'roles': ImportProfile(id='default', name='x'), 'users': UserImportProfile(id='default', name='x')}.get(source)
    if source == 'sod':
        return parse_sod(path)['records']
    parser = (CsvImport if source == 'roles' else UserCsvImport)(Path(path), profile)
    return list(parser.records())


def malformed(directory):
    cases = json.loads((Path(directory) / 'cases.json').read_text())
    result = {}
    for name, source in sorted(cases.items()):
        path = Path(directory) / f'{name}.csv'
        try:
            if source == 'roles':
                state = cache._build_catalog(path=str(path))
                result[name] = dict(ok=True, roles=[r.agr_name for r in state.roles.values()], texts=[r.text for r in state.roles.values()],
                                    warnings=state.import_report['warnings'], parsed_rows=state.import_report['parsed_rows'])
            else:
                users = build_users(str(path), UserImportProfile(id='default', name='x'), {})
                result[name] = dict(ok=True, users=list(users.users), assignments=len(users.assignments), warnings=users.report['warnings'])
        except Exception as error:  # the exception TEXT is compared only for validation errors; csv module errors are compared by kind
            from analysis_errors import AnalysisValidationError
            result[name] = dict(ok=False, error=str(error) if isinstance(error, AnalysisValidationError) else 'csv-format-error')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', required=True)
    parser.add_argument('--scenarios', required=True)
    parser.add_argument('--malformed', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--dataset', default='small', help='base dataset folder; import checks use <dataset>-changed/-shrunk')
    args = parser.parse_args()
    data = Path(args.data)
    scenarios = json.loads(Path(args.scenarios).read_text())
    timings = {}
    started = time.perf_counter()
    state = cache._build_catalog(path=str(data / args.dataset / 'roles.csv'))
    timings['catalogue_ms'] = round((time.perf_counter() - started) * 1000, 1)
    started = time.perf_counter()
    users = build_users(str(data / args.dataset / 'users.csv'), UserImportProfile(id='default', name='x'), state.roles)
    timings['users_ms'] = round((time.perf_counter() - started) * 1000, 1)
    sod = parse_sod(str(data / args.dataset / 'sod.csv'))
    state.users, state.sod, state.directory = users, sod, None
    cache._cache = state
    snapshot = state
    output = dict(implementation='python-v1', today=TODAY.isoformat(), catalogue=catalogue_json(state), users=users_json(users),
                  sod_source=dict(content_hash=sod['content_hash'], warnings=sod['warnings'], risks=len(sod['risks'])))
    output['role_lookup'] = [role_lookup(q) for q in scenarios['role_lookup']]
    output['user_lookup'] = [user_lookup(snapshot, q) for q in scenarios['user_lookup']]
    output['comparison'] = [comparison(snapshot, pair) for pair in scenarios['comparison']]
    output['comparison_listing'] = [listing(snapshot, scenarios['comparison'], spec) for spec in scenarios['comparison_listing']]
    output['sod'] = [sod_json(snapshot, spec) for spec in scenarios['sod']]
    checks = []
    for spec in scenarios['import_checks']:
        before = records(spec['source'], data / args.dataset / f"{spec['source']}.csv")
        after = records(spec['source'], data / spec['after'].replace('small', args.dataset) / f"{spec['source']}.csv")
        evaluation = import_checks.evaluate(spec['source'], before, after, ImportChecks())
        diff = csv_lifecycle.diff_records(spec['source'], before, after, include_changes=False)
        checks.append(dict(suspicious=evaluation['suspicious'], anomalies=[a['message'] for a in evaluation['anomalies']], old=evaluation['old'], new=evaluation['new'],
                           diff=dict(added=diff['added'], removed=diff['removed'], modified=diff['modified'], unchanged=diff['unchanged'], ambiguous=diff['ambiguous_identifiers'])))
    output['import_checks'] = checks
    output['malformed'] = malformed(args.malformed)
    output['timings'] = timings
    Path(args.out).write_text(json.dumps(output, indent=1, sort_keys=True, ensure_ascii=False, default=str))
    print(f'wrote {args.out}')


if __name__ == '__main__':
    main()
