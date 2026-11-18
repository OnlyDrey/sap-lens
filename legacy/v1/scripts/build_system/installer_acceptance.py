"""Private installer acceptance plans and read-only production invariance checks."""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import time
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'backend'))
from build_system.artifacts import digest
from build_system.layout import is_linked_output

KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\{%s}_is1'


def production_id(repository=ROOT):
    recipe = (repository / 'deploy/windows/desktop-installer.iss').read_text(encoding='utf-8')
    return re.search(r'#define ProductionAppId "([A-F0-9-]{36})"', recipe)[1]


def registry(app_id):
    """Read only; never set/delete a production or test registry value."""
    import winreg
    result = {}
    def tree(hive, path, view):
        try:
            key = winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view)
        except FileNotFoundError:
            return None
        with key:
            children, count, written = winreg.QueryInfoKey(key)
            values = {}
            for index in range(count):
                name, value, kind = winreg.EnumValue(key, index)
                values[name] = dict(type=kind, value={'bytes': value.hex()} if isinstance(value, bytes) else value)
            return dict(values=values, written=written,
                        children={name: tree(hive, path+'\\'+name, view) for name in (winreg.EnumKey(key, i) for i in range(children))})
    for hive_name, hive in (('HKCU', winreg.HKEY_CURRENT_USER), ('HKLM', winreg.HKEY_LOCAL_MACHINE)):
        for bits, view in ((64, winreg.KEY_WOW64_64KEY), (32, winreg.KEY_WOW64_32KEY)):
            result[f'{hive_name}{bits}'] = tree(hive, KEY % app_id, view)
    return result


def file_tree(root):
    records = {}
    def visit(path, name):
        try:
            info = path.lstat()
        except FileNotFoundError:
            records[name] = dict(kind='absent')
            return
        row = dict(mtime=info.st_mtime_ns, attributes=getattr(info, 'st_file_attributes', info.st_mode))
        if is_linked_output(path):
            row.update(kind='reparse', tag=getattr(info, 'st_reparse_tag', 0))
        elif path.is_dir():
            row['kind'] = 'directory'
            for child in sorted(path.iterdir()):
                visit(child, name+'/'+child.name)
        else:
            row.update(kind='file', sha256=digest(path))
        records[name] = row
    visit(root, '.')
    return records


def protected_paths(registration):
    local = Path(os.environ['LOCALAPPDATA'])
    paths = [local/'Programs/SAP Lens', local/'SAP Lens', local/'SAP Lens Backups']
    for row in registration.values():
        if row:
            location = row['values'].get('InstallLocation', {}).get('value')
            if isinstance(location, str) and location:
                paths.append(Path(location))
    for name in ('SAP_LENS_CONFIG_DIR', 'SAP_LENS_BACKUP_DIR', 'SAP_LENS_DATA_DIR'):
        if os.environ.get(name):
            paths.append(Path(os.environ[name]))
    if os.environ.get('APPDATA'):
        paths.append(Path(os.environ['APPDATA'])/'Microsoft/Windows/Start Menu/Programs/SAP Lens.lnk')
    if os.environ.get('USERPROFILE'):
        paths.append(Path(os.environ['USERPROFILE'])/'Desktop/SAP Lens.lnk')
    result = sorted({str(path.resolve()) for path in paths})
    if any(Path(path) == Path(path).parent for path in result):
        raise ValueError('A production path is an entire drive; safe acceptance is blocked.')
    return result


def check_boundary(root, protected):
    if any(is_linked_output(path) for path in (root, *root.parents)):
        raise ValueError('Installer acceptance paths may not be linked.')
    for value in protected:
        path = Path(value).resolve()
        if root.is_relative_to(path) or path.is_relative_to(root):
            raise ValueError('Acceptance workspace overlaps a protected production path.')


def production_proof(installer, repository=ROOT):
    payload=repository/'backend/dist/SAP-Lens.exe'
    approved=json.loads((repository/'backend/build/package-verification.json').read_text(encoding='utf-8-sig'))
    if approved.get('status') != 'passed' or digest(payload) != approved['exe_sha256']:
        raise ValueError('Installer payload differs from its approved hash.')
    return dict(schema=1, production_id=production_id(repository), installer_sha256=digest(Path(installer)),
                payload_sha256=approved['exe_sha256'], recipe_sha256=digest(repository/'deploy/windows/desktop-installer.iss'),
                identity=json.loads((repository/'backend/build/build-version.json').read_text(encoding='utf-8-sig')))


def record_production(installer, repository=ROOT):
    """Called by the canonical producer after compilation and production PE verification."""
    proof=production_proof(installer, repository)
    path=repository/'backend/build/installer-proofs'/(proof['installer_sha256']+'.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != proof:
            raise ValueError('Existing production installer provenance differs.')
    else:
        with path.open('x',encoding='utf-8') as stream:
            json.dump(proof,stream,indent=2)
    return path


def prepare(installer, report, parent=None, repository=ROOT):
    expected=production_proof(installer,repository)
    proof_path=repository/'backend/build/installer-proofs'/(expected['installer_sha256']+'.json')
    if not proof_path.is_file() or json.loads(proof_path.read_text(encoding='utf-8')) != expected:
        raise ValueError('Production installer/payload provenance is missing or stale; use the validated installer builder.')
    prod = production_id(repository)
    registration = registry(prod)
    protected = protected_paths(registration)
    test_id = str(uuid.uuid4()).upper()
    if test_id == prod:
        raise ValueError('Test AppId must differ from production.')
    root = (Path(parent or tempfile.gettempdir()).resolve() / ('sap-lens-installer-'+test_id))
    check_boundary(root, protected)
    report = Path(report).resolve()
    check_boundary(report, protected)
    if report.exists():
        raise ValueError('Acceptance receipt already exists; choose a new report path.')
    if any(row is not None for row in registry(test_id).values()):
        raise ValueError('Test-only installer identity is already registered; nothing was changed.')
    payload = repository/'backend/dist/SAP-Lens.exe'
    approved = json.loads((repository/'backend/build/package-verification.json').read_text(encoding='utf-8-sig'))
    if approved.get('status') != 'passed' or digest(payload) != approved['exe_sha256']:
        raise ValueError('Installer payload differs from its approved hash.')
    baseline={path: file_tree(Path(path)) for path in protected}
    identity=json.loads((repository/'backend/build/build-version.json').read_text(encoding='utf-8-sig'))
    root.mkdir(mode=0o700)
    if os.name == 'nt':
        import windows_identity
        windows_identity.make_private(root, inherit_children=True)
    plan = dict(schema=1, identity=identity, production_id=prod, test_id=test_id, root=str(root), application=str(root/'application'),
                data=str(root/'data'), backups=str(root/'backups'), installer=str(Path(installer).resolve()),
                installer_sha256=digest(Path(installer)), payload_sha256=approved['exe_sha256'],
                recipe_sha256=digest(repository/'deploy/windows/desktop-installer.iss'), report=str(report),
                registry=registration, protected=protected, files=baseline)
    (root/'.owner').write_text(test_id, encoding='ascii')
    path=root/'plan.json'
    path.write_text(json.dumps(plan, indent=2), encoding='utf-8')
    return path, plan


def load(path, repository=ROOT):
    path=Path(path)
    plan=json.loads(path.read_text(encoding='utf-8'))
    root=Path(plan['root'])
    test_id=str(uuid.UUID(plan['test_id'])).upper()
    if (plan.get('schema') != 1 or test_id != plan['test_id'] or test_id == production_id(repository)
            or plan['production_id'] != production_id(repository) or root.name != 'sap-lens-installer-'+test_id
            or path.resolve() != root/'plan.json' or (root/'.owner').read_text(encoding='ascii') != test_id):
        raise ValueError('Invalid test-only installer identity or workspace ownership.')
    check_boundary(root, plan['protected'])
    for key, leaf in (('application','application'), ('data','data'), ('backups','backups')):
        if Path(plan[key]) != root/leaf or is_linked_output(root/leaf):
            raise ValueError('Test installation paths differ or are linked.')
    if (digest(repository/'backend/dist/SAP-Lens.exe') != plan['payload_sha256']
            or json.loads((repository/'backend/build/build-version.json').read_text(encoding='utf-8-sig')) != plan['identity']):
        raise ValueError('Validated payload or build identity changed during acceptance.')
    if digest(Path(plan['installer'])) != plan['installer_sha256'] or digest(repository/'deploy/windows/desktop-installer.iss') != plan['recipe_sha256']:
        raise ValueError('Bound installer or recipe changed during acceptance.')
    return plan


def verify_production(plan):
    differences=[]
    actual_registry=registry(plan['production_id'])
    for view, before in plan['registry'].items():
        if actual_registry.get(view) != before:
            differences.append('registry '+view+' '+KEY % plan['production_id'])
    for index, (name, before) in enumerate(plan['files'].items()):
        actual=file_tree(Path(name))
        differences += [f'protected root {index}: {entry}' for entry in sorted(set(before)|set(actual)) if before.get(entry) != actual.get(entry)]
    if differences:
        raise ValueError('Production state differs: '+'; '.join(differences[:30]))


def registration(plan, installed):
    found=registry(plan['test_id'])
    active=[(view, row) for view,row in found.items() if row is not None]
    if not installed:
        if active:
            raise ValueError('Test uninstall registration remains: '+', '.join(view for view,_ in active))
        return
    if not active:
        raise ValueError('Test-only Installed Apps registration is missing.')
    for view,row in active:
        location=row['values'].get('InstallLocation',{}).get('value','')
        if not view.startswith('HKCU') or not location or Path(location).resolve() != Path(plan['application']).resolve():
            raise ValueError('Test registration does not belong to the isolated application directory: '+view)
        command=row['values'].get('UninstallString',{}).get('value','')
        match=re.match(r'^"([^"]+)"(?:\s|$)|^([^\s]+)(?:\s|$)', command)
        if not match or Path(match[1] or match[2]).resolve() != Path(plan['application']).resolve()/'unins000.exe':
            raise ValueError('Test uninstall command differs from the isolated uninstaller: '+view)


def cleanup(plan):
    registration(plan, False)
    verify_production(plan)
    root=Path(plan['root'])
    check_boundary(root, plan['protected'])
    if root.name != 'sap-lens-installer-'+plan['test_id'] or (root/'.owner').read_text(encoding='ascii') != plan['test_id']:
        raise ValueError('Workspace ownership differs; cleanup refused.')
    # Reject the complete tree before any deletion; never follow a junction.
    try:
        for path in root.rglob('*'):
            if is_linked_output(path):
                raise ValueError('Linked test entry prevents cleanup; workspace retained.')
    except OSError as error:
        raise ValueError('Test cleanup failed to inspect its workspace; recovery files retained.') from error
    # Delete payloads first; retain ownership/snapshot/logs on a sharing failure.
    keep={'plan.json','.owner','compiled-acceptance.json'}
    entries=sorted(root.rglob('*'), key=lambda path: len(path.parts), reverse=True)
    def remove(path):
        for attempt in range(4):
            try:
                if is_linked_output(path):
                    raise ValueError('Linked entry prevents cleanup; workspace retained.')
                if path.is_dir(): path.rmdir()
                else: path.unlink(missing_ok=True)
                return
            except OSError as error:
                code=getattr(error,'winerror',None)
                readonly=path.exists() and bool(getattr(path.stat(),'st_file_attributes',0) & stat.FILE_ATTRIBUTE_READONLY)
                if attempt == 3 or code not in (32,33) and not (code == 5 and readonly):
                    raise ValueError('Test cleanup failed at '+str(path.relative_to(root))+'; workspace retained.') from error
                if readonly: path.chmod(stat.S_IWRITE | stat.S_IREAD)
                time.sleep(.1 * (2 ** attempt))
    for path in entries:
        if path.parent == root and (path.name in keep or path.suffix == '.log'):
            continue
        remove(path)
    verify_production(plan)
    for path in sorted(root.iterdir()):
        if path.name not in ('plan.json','.owner'): remove(path)
    remove(root/'plan.json')
    remove(root/'.owner')
    root.rmdir()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['record-production','prepare','validate','verify-production','registered','unregistered','state','cleanup'])
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--installer', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--parent', type=Path)
    args=parser.parse_args()
    try:
        if args.operation == 'record-production':
            if not args.installer: parser.error('record-production requires --installer')
            print(json.dumps({'proof':str(record_production(args.installer))}))
            return
        if args.operation == 'prepare':
            if not args.installer or not args.report:
                parser.error('prepare requires --installer and --report')
            path, plan=prepare(args.installer,args.report,args.parent)
        else:
            if not args.plan:
                parser.error('operation requires --plan')
            plan=load(args.plan); path=args.plan
            if args.operation == 'verify-production': verify_production(plan)
            elif args.operation == 'registered': registration(plan,True)
            elif args.operation == 'unregistered': registration(plan,False)
            elif args.operation == 'cleanup': cleanup(plan)
        state={}
        if args.operation == 'state':
            active=any(row is not None for row in registry(plan['test_id']).values())
            registration(plan,active)
            state['test_registered']=active
        print(json.dumps({key:plan[key] for key in ('identity','root','application','data','backups','test_id','production_id','installer_sha256','payload_sha256','recipe_sha256','report')} | {'plan_path':str(path)} | state))
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, 'Installer acceptance: '+str(error)+'\n')


if __name__ == '__main__':
    main()
