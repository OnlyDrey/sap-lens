"""Python v1 reference for MIG-009 (POST /api/import/headers, /api/import/preview, /api/user-import/headers, /api/user-import/preview).
Derives synthetic case files from the SoD analysis fixtures, writes them to FIXTURE_DIR (as .txt: the test copies them to .csv), and records what
v1's route bodies return for each: the same CsvImport.inspect_header, cache._build_catalog(...).import_report and build_users(...).report calls
and the same error mapping as configuration_routes.py. Usage: python -I tools/import_preview_reference.py BACKEND_DIR FIXTURE_DIR"""
import json, os, shutil, sys, tempfile
os.environ['SAP_LENS_CONFIG_DIR'] = tempfile.mkdtemp()
backend, fixtures = sys.argv[1:3]
sys.path.insert(0, backend)
from pathlib import Path
import cache, config
from config_models import ImportProfile, UserImportProfile
from csv_import import CsvImport
from user_access import UserCsvImport, build_users
from analysis_errors import AnalysisValidationError

source = Path(fixtures).parent / 'sod' / 'analysis'
roles = (source / 'roles.sod.txt').read_text(encoding='utf-8').splitlines()
users = (source / 'users.sod.txt').read_text(encoding='utf-8').splitlines()
cases = {
    'roles_default': ('\n'.join(roles) + '\n', 'utf-8'),
    # semicolons, cp1252, a renamed required column and a non-ASCII description
    'roles_mapped_cp1252': ('\n'.join([roles[0].replace('AGR_NAME', 'Rolle')] + [line.replace('Synthetic role 1;', 'Synthetic rolle ø 1;') for line in roles[1:300]]) + '\n', 'cp1252'),
    # commas, an identical duplicate record and a blank record
    'roles_comma_duplicates': ('\n'.join([l.replace(';', ',') for l in roles[:200]] + [roles[5].replace(';', ','), ',,,,,,,,']) + '\n', 'utf-8'),
    'roles_duplicate_header': ('\n'.join([roles[0].replace('TEXT;CHILD_AGR', 'Agr Name;CHILD_AGR', 1)] + roles[1:50]) + '\n', 'utf-8'),
    'roles_missing_required': ('\n'.join([';'.join(c for c in line.split(';')[:1] + line.split(';')[2:]) for line in roles[:50]]) + '\n', 'utf-8'),
    'roles_ragged': ('\n'.join(roles[:40] + [roles[40] + ';extra']) + '\n', 'utf-8'),
    'users_default': ('\n'.join(users) + '\n', 'utf-8'),
    'users_ragged': ('\n'.join(users[:30] + [users[30] + ';extra']) + '\n', 'utf-8'),
}
work = Path(tempfile.mkdtemp())
paths = {}
for name, (text, encoding) in cases.items():
    (Path(fixtures) / f'{name}.txt').write_bytes(text.encode(encoding))
    paths[name] = work / f'{name}.csv'
    shutil.copy(Path(fixtures) / f'{name}.txt', paths[name])

settings = config.get_settings()
nordic = dict(id='nordic', name='Nordic export', version=2, mapping=dict(AGR_NAME='Rolle'), delimiter=';', encoding='cp1252')
role_runs = [('roles_default', None), ('roles_mapped_cp1252', nordic), ('roles_mapped_cp1252', None), ('roles_comma_duplicates', dict(id='comma', name='Comma', delimiter=',')),
             ('roles_duplicate_header', None), ('roles_missing_required', None), ('roles_ragged', None)]
user_runs = [('users_default', None), ('users_default', dict(id='u2', name='Users', delimiter=';', encoding='utf-8-sig')), ('users_ragged', None)]


def role_headers(path, profile):
    profile = ImportProfile(**profile) if profile else next(p for p in settings.import_profiles if p.id == settings.active_import)
    try: return dict(status=200, body=CsvImport(path, profile).inspect_header())
    except Exception: return dict(status=400, body=dict(detail='Could not inspect the CSV header. Check path, encoding and delimiter.'))


def role_preview(path, profile):
    configuration = settings.model_copy(deep=True)
    if profile:
        parsed = ImportProfile(**profile); configuration.import_profiles = [parsed]; configuration.active_import = parsed.id
    try: return dict(status=200, body=cache._build_catalog(str(path), configuration).import_report)
    except Exception: return dict(status=400, body=dict(detail='Import preview failed. Check the absolute path, encoding, delimiter, mappings and required AGR_NAME column.'))


catalogue = cache._build_catalog(str(paths['roles_default']), settings).roles


def user_headers(path, profile):
    profile = UserImportProfile(**profile) if profile else next(p for p in settings.user_import_profiles if p.id == settings.active_user_import)
    try: return dict(status=200, body=UserCsvImport(path, profile).inspect_header())
    except Exception: return dict(status=400, body=dict(detail='Could not inspect user CSV. Check path, encoding and delimiter.'))


def user_preview(path, profile):
    profile = UserImportProfile(**profile) if profile else next(p for p in settings.user_import_profiles if p.id == settings.active_user_import)
    keys = ('USERNAME', 'ROLE_NAME', 'USER_GROUP', 'FIRST_NAME', 'LAST_NAME', 'EMAIL', 'ROLE_VALID_FROM', 'ROLE_VALID_TO')
    try:
        preview = build_users(str(path), profile, catalogue)
        return dict(status=200, body=dict(preview.report, samples=[{key: row.get(key, '') for key in keys} for row in preview.source_records[:20]]))
    except AnalysisValidationError as exc: return dict(status=400, body=dict(detail=str(exc)))
    except Exception: return dict(status=400, body=dict(detail='User CSV preview failed. Check USERNAME, mappings, row widths and YYYY-MM-DD/YYYYMMDD dates.'))


runs = []
for name, profile in role_runs:
    runs.append(dict(route='/api/import/headers', case=name, profile=profile, result=role_headers(paths[name], profile)))
    runs.append(dict(route='/api/import/preview', case=name, profile=profile, result=role_preview(paths[name], profile)))
for name, profile in user_runs:
    runs.append(dict(route='/api/user-import/headers', case=name, profile=profile, result=user_headers(paths[name], profile)))
    runs.append(dict(route='/api/user-import/preview', case=name, profile=profile, result=user_preview(paths[name], profile)))
(Path(fixtures) / 'preview.python.json').write_text(json.dumps(dict(catalogue='roles_default', runs=runs), indent=1, ensure_ascii=False, default=str), encoding='utf-8')
print(len(runs), 'runs;', ', '.join(f"{r['route'].split('/')[-1]}:{r['case']}:{r['result']['status']}" for r in runs))
