"""Canonical build-only deployment identity, same-run validation and archive integrity."""
import argparse
import email
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from version import make_build_info,make_local_package_info,parse_build_info,make_deployment_info
# Lightweight package-integrity checks only. Neither the full backend suite nor the browser suite is a prerequisite for building or publishing; see docs/deployment/CI_CD.md.
CHECKS={'types','build','catalog','python_audit','javascript_audit','pip_check','workflow_lint','powershell'}


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')


def git_sha():return subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()


def identity():return parse_build_info(json.loads((ROOT/'backend/build/build-version.json').read_text()))


def safe(name):
    path=PurePosixPath(name)
    if not name or '\\' in name or ':' in name or path.is_absolute() or any(v in {'','.','..'} for v in name.split('/')):
        raise ValueError('Unsafe archive member.')
    return path


def files(directory):
    result={}
    for path in sorted(Path(directory).rglob('*')):
        if path.is_symlink():raise ValueError('Distribution links are not allowed.')
        if path.is_file():result[path.relative_to(directory).as_posix()]=sha(path)
    return result


def privacy(names):
    for name in names:
        parts=safe(name).parts;base=parts[-1].lower()
        if any(p.lower() in {'node_modules','.git','.venv','__pycache__','tests','fixtures','csv-data','employee-directory','local-config','snapshots','user-branding'} for p in parts):
            raise ValueError('Private/development directory in artifact.')
        if base in {'settings.json','runtime.json','account-review.json','position-changes.json','saved-filters.json'} or base.startswith('.env') or base.endswith(('.csv','.secret','.log','.bak','.tmp')):
            raise ValueError('Private file in artifact.')


def prepare(version):
    if os.environ.get('DEPLOYMENT_TARGET'):
        release_spec=importlib.util.spec_from_file_location('deployment_release',ROOT/'scripts/deployment-release.py')
        release=importlib.util.module_from_spec(release_spec);release_spec.loader.exec_module(release)
        try:release.resolve(os.environ['DEPLOYMENT_TARGET'])
        except release.DeliveryError as error:raise ValueError(str(error)) from None
    if os.environ.get('GITHUB_ACTIONS')=='true':
        if os.environ.get('DEPLOYMENT_CHANNEL'):
            release_spec=importlib.util.spec_from_file_location('deployment_release',ROOT/'scripts/deployment-release.py')
            release=importlib.util.module_from_spec(release_spec);release_spec.loader.exec_module(release)
            value=make_deployment_info(version,release.channel(os.environ['DEPLOYMENT_CHANNEL']),
                os.environ.get('DEPLOYMENT_SEQUENCE',''),git_sha(),os.environ['GITHUB_RUN_ID'],os.environ['GITHUB_RUN_NUMBER'],int(os.environ['GITHUB_RUN_ATTEMPT']))
            if os.environ.get('PUBLISH_RELEASE') not in {'true','false'}:raise ValueError('Explicit publication choice is required.')
            if os.environ['PUBLISH_RELEASE']=='true':
                try:release.GitHub(os.environ['GITHUB_REPOSITORY'],os.environ['GITHUB_TOKEN']).available(value['tag'])
                except release.DeliveryError as error:
                    print(str(error),file=sys.stderr)
                    raise ValueError('Publication preflight failed.') from None
        else:
            value=make_build_info('build',version,git_sha(),os.environ['GITHUB_RUN_ID'],os.environ['GITHUB_RUN_NUMBER'],int(os.environ['GITHUB_RUN_ATTEMPT']))
    else:value=make_local_package_info(version,git_sha())
    write(ROOT/'backend/build/build-version.json',value)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as output:
            output.write('version='+value['version']+'\n')
            output.write('identity='+json.dumps(value,separators=(',',':'))+'\n')
    print(value['version'])


def frontend_licenses():
    subprocess.run(['node',str(ROOT/'scripts/frontend-licenses.mjs')],check=True)


def seal(output):
    timings=Path(os.environ.get('RUNNER_TEMP',ROOT/'backend/build'))/'sap-lens-ci-timings.jsonl'
    records={row['stage']:row for row in map(json.loads,timings.read_text().splitlines())}
    if any(records.get(key,{}).get('status')!='passed' for key in CHECKS):raise ValueError('Shared validation is incomplete.')
    info=identity()
    subprocess.run(['git','diff','--quiet','HEAD'],cwd=ROOT,check=True)
    if info['source_sha']!=git_sha():raise ValueError('Validation source mismatch.')
    frontend_licenses()
    manifest={'frontend/'+name:value for name,value in files(ROOT/'frontend/dist').items()}
    privacy(manifest)
    receipt=dict(schema=1,identity=info,checks=sorted(CHECKS),validated_at=time.time(),files=manifest)
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('validation.json',json.dumps(receipt))
        for name in manifest:archive.write(ROOT/'frontend/dist'/name.removeprefix('frontend/'),name)


def consume(archive):
    with zipfile.ZipFile(archive) as source:
        names=source.namelist()
        if len(names)!=len(set(n.casefold() for n in names)) or sum(i.file_size for i in source.infolist())>128*1024*1024:
            raise ValueError('Invalid validated-input archive.')
        for item in source.infolist():
            safe(item.filename)
            if item.is_dir() or (item.external_attr>>16)&0o170000==0o120000:raise ValueError('Unexpected archive entry type.')
        receipt=json.loads(source.read('validation.json'));info=parse_build_info(receipt['identity'])
        if receipt.get('schema')!=1 or set(receipt.get('checks',[]))!=CHECKS or not 0<=time.time()-receipt['validated_at']<=86400:
            raise ValueError('Invalid or stale validation receipt.')
        if info['source_sha']!=git_sha():raise ValueError('Validation belongs to another source commit.')
        if os.environ.get('GITHUB_ACTIONS')!='true' or info['run_id']!=os.environ.get('GITHUB_RUN_ID') or info['attempt']!=int(os.environ.get('GITHUB_RUN_ATTEMPT','0')):
            raise ValueError('CI validation must originate in this workflow run and attempt.')
        if set(names)!={'validation.json',*receipt['files']} or not receipt['files']:raise ValueError('Unexpected validated files.')
        for name,digest in receipt['files'].items():
            if not name.startswith('frontend/') or hashlib.sha256(source.read(name)).hexdigest()!=digest:raise ValueError('Validated asset mismatch.')
        frontend=ROOT/'frontend/dist'
        if frontend.exists():shutil.rmtree(frontend)
        for name in receipt['files']:
            path=frontend/name.removeprefix('frontend/');path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(source.read(name))
    write(ROOT/'backend/build/build-version.json',info)
    write(ROOT/'backend/build/deployment-validation.json',receipt)
    return receipt


def require_ci():
    subprocess.run(['git','diff','--quiet','HEAD'],cwd=ROOT,check=True)
    receipt=json.loads((ROOT/'backend/build/deployment-validation.json').read_text())
    info=identity()
    if os.environ.get('GITHUB_ACTIONS')!='true' or receipt['identity']!=info or info['source_sha']!=git_sha() or info['run_id']!=os.environ.get('GITHUB_RUN_ID') or info['attempt']!=int(os.environ.get('GITHUB_RUN_ATTEMPT','0')):
        raise ValueError('Missing same-run validated inputs.')
    if set(receipt['checks'])!=CHECKS or not 0<=time.time()-receipt['validated_at']<=86400 or receipt['files']!={'frontend/'+n:h for n,h in files(ROOT/'frontend/dist').items()}:
        raise ValueError('Validated inputs changed or expired.')
    return receipt


def local_tools():
    spec=importlib.util.spec_from_file_location('local_deployment_inputs',ROOT/'scripts/local-build.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def record_local():
    tools=local_tools();tools.clean(ROOT)
    info=identity()
    if os.environ.get('GITHUB_ACTIONS')=='true' or info['schema']!=3 or info['source_sha']!=git_sha():
        raise ValueError('Local validation requires a local identity for the clean source commit.')
    timings=Path(os.environ['RUNNER_TEMP'])/'sap-lens-ci-timings.jsonl'
    records={row['stage']:row for row in map(json.loads,timings.read_text().splitlines())}
    if any(records.get(key,{}).get('status')!='passed' for key in CHECKS):
        raise ValueError('Local deployment validation is incomplete.')
    frontend_licenses()
    privacy(files(ROOT/'frontend/dist'))
    value=dict(schema=1,identity=info,host=sys.platform,checks=sorted(CHECKS),
               validated_at=time.time(),inputs=tools.inputs(ROOT,allow_interpreter_links=True))
    write(ROOT/'backend/build/deployment-local-validation.json',value)
    return value


def require_inputs():
    if os.environ.get('GITHUB_ACTIONS')=='true':return require_ci()
    tools=local_tools();tools.clean(ROOT)
    path=ROOT/'backend/build/deployment-local-validation.json'
    if path.is_symlink() or not path.is_file() or path.stat().st_size>16384:
        raise ValueError('Run build.sh/build.ps1 without --reuse-validation first.')
    receipt=json.loads(path.read_text());info=identity()
    if (info['schema']!=3 or receipt['identity']!=info or info['source_sha']!=git_sha()
            or receipt.get('schema')!=1 or receipt.get('host')!=sys.platform
            or set(receipt.get('checks',[]))!=CHECKS
            or not 0<=time.time()-receipt.get('validated_at',0)<=86400
            or receipt.get('inputs')!=tools.inputs(ROOT,allow_interpreter_links=True)):
        raise ValueError('Local validation is stale or inputs changed; rebuild without --reuse-validation.')
    return receipt


def finish(directory,platform,output):
    info=identity()
    if output.resolve().is_relative_to(directory.resolve()):
        raise ValueError('Keep deployment archive output outside its input bundle.')
    output.mkdir(parents=True,exist_ok=True)
    stem=f'SAP-Lens-{platform}-{info["version"]}'
    archive=output/(stem+('.zip' if platform.startswith('Windows') else '.tar.gz'))
    checksum=archive.with_name(archive.name+'.sha256')
    if any(path.exists() or path.is_symlink() for path in (archive,checksum)):
        raise ValueError('Deployment output already exists; choose a new output directory. Existing packages were preserved.')
    manifest=files(directory);manifest.pop('package-manifest.json',None);privacy(manifest)
    write(directory/'package-manifest.json',dict(schema=1,platform=platform,identity=info,files=manifest))
    if platform.startswith('Windows'):
        with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
            for path in sorted(directory.rglob('*')):
                if path.is_file():z.write(path,path.relative_to(directory).as_posix())
    else:
        with tarfile.open(archive,'x:gz') as z:
            for path in sorted(directory.rglob('*')):
                if path.is_file():z.add(path,arcname=path.relative_to(directory).as_posix(),recursive=False)
    with tempfile.TemporaryDirectory() as temp:verify_extract(archive,Path(temp),sha(archive))
    with checksum.open('x',encoding='ascii') as stream:stream.write(sha(archive)+'  '+archive.name+'\n')
    print('Verified deployment archive: '+archive.name+' SHA-256 '+sha(archive))
    return archive


def verify_extract(archive,destination,expected):
    if sha(archive)!=expected:raise ValueError('Archive checksum mismatch.')
    if destination.exists() and any(destination.iterdir()):raise ValueError('Extraction requires an empty directory.')
    destination.mkdir(parents=True,exist_ok=True)
    if archive.name.endswith('.zip'):
        with zipfile.ZipFile(archive) as z:
            members=[(i.filename,i.file_size,i.external_attr>>16,lambda i=i:z.read(i)) for i in z.infolist()]
            _extract(members,destination)
    else:
        with tarfile.open(archive,'r:gz') as z:
            members=[]
            for i in z.getmembers():
                if not i.isfile():raise ValueError('Archive contains a non-regular member.')
                members.append((i.name,i.size,i.mode,lambda i=i:z.extractfile(i).read()))
            _extract(members,destination)
    manifest=json.loads((destination/'package-manifest.json').read_text());parse_build_info(manifest['identity'])
    actual=files(destination);actual.pop('package-manifest.json')
    if manifest.get('schema')!=1 or actual!=manifest['files']:raise ValueError('Exact artifact contents or hashes differ.')
    privacy(actual)
    return manifest


def _extract(members,destination):
    names=[n for n,_,_,_ in members]
    if len(names)!=len(set(n.casefold() for n in names)) or sum(s for _,s,_,_ in members)>2*1024**3:raise ValueError('Invalid archive size or duplicate members.')
    for name,size,mode,read in members:
        safe(name)
        if mode&0o170000 not in (0,0o100000):raise ValueError('Non-regular archive members are forbidden.')
        path=destination/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(read())
        path.chmod(0o755 if mode&0o111 else 0o644)


def package_document(document, destination):
    """Keep operational guides self-contained; don't ship dead checkout links."""
    import re
    if document.suffix != '.md' or not document.resolve().is_relative_to((ROOT/'docs').resolve()): raise ValueError('Use a repository deployment guide.')
    if destination.is_symlink(): raise ValueError('Documentation destination may not be a link.')
    def reference(match):
        label,link=match.groups()
        if re.match(r'^[a-zA-Z][\w+.-]*:',link) or link.startswith('#'): return match[0]
        target,separator,fragment=link.partition('#')
        if Path(target).name in ('DEPLOYMENT_SECURITY.md','SECURITY.md') and (destination.parent/'SECURITY.md').exists():return f'[{label}](SECURITY.md'+('#'+fragment if separator else '')+')'
        # A repository directory index is not the platform README in a bundle.
        if Path(target).name=='README.md': return label+' (repository documentation)'
        candidate=(destination.parent/target).resolve()
        if candidate.is_relative_to(destination.parent.resolve()) and candidate.is_file(): return match[0]
        return label+' (repository documentation)'
    text=re.sub(r'\[([^\]]+)\]\(([^\s)]+)\)',reference,document.read_text(encoding='utf-8'))
    destination.write_text(text+'\n\nFull repository documentation: https://github.com/OnlyDrey/sap-lens/tree/work/docs . Match the source/version recorded in the package manifest.\n',encoding='utf-8')


def copy_source(target):
    names=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    selected=[n for n in names if (n.startswith('backend/') and n.endswith('.py') and '/tests/' not in n and '/build/' not in n)]
    selected+=['LICENSE.md','assets/sap-lens.png','assets/sap-lens.ico','backend/requirements.txt','deploy/server.env.example','deploy/linux/sap-lens.service']
    selected+=['scripts/install-linux-server.py','scripts/run-installed-server.py','scripts/deployment-package.py']
    for name in selected:
        path=target/name;path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,path)
    shutil.copytree(ROOT/'frontend/dist',target/'frontend/dist')
    write(target/'backend/build/build-version.json',identity())
    # Keep published bundle member names stable while repository guides move.
    documents = {
        'README.md': 'deployment/LINUX_NATIVE.md',
        'SECURITY.md': 'deployment/SECURITY.md',
        'DEPLOYMENT_LINUX_NATIVE.md': 'deployment/LINUX_NATIVE.md',
        'DEPLOYMENT_SECURITY.md': 'deployment/SECURITY.md',
        'DEPLOYMENT_PACKAGES.md': 'deployment/BUILD.md',
        'PACKAGING_VALIDATION.md': 'archive/validation/PACKAGING_VALIDATION.md',
        'LOCAL_BUILD_VALIDATION.md': 'archive/validation/LOCAL_BUILD_VALIDATION.md',
        'INSTALLATION_LIFECYCLE_VALIDATION.md': 'archive/validation/INSTALLATION_LIFECYCLE_VALIDATION.md',
    }
    for name, source in documents.items():
        package_document(ROOT/'docs'/source, target/name)


def native(output):
    require_inputs()
    if sys.platform!='linux' or sys.version_info[:2]!=(3,12):raise ValueError('Build native bundles on Linux/Python 3.12.')
    import platform
    if platform.machine() not in {'x86_64','AMD64'}:raise ValueError('Linux x86-64 is required.')
    with tempfile.TemporaryDirectory() as temp:
        target=Path(temp);copy_source(target);wheels=target/'wheelhouse';wheels.mkdir()
        pin=target/'pip-build-pin.txt'
        pins=[line for line in (ROOT/'backend/requirements-build.txt').read_text().splitlines() if line.startswith('pip==')]
        if len(pins)!=1:raise ValueError('Require the canonical pinned pip security version.')
        pin.write_text(pins[0]+'\n')
        subprocess.run([sys.executable,'-m','pip','download','--only-binary=:all:','--dest',str(wheels),'-r',str(ROOT/'backend/requirements.txt'),'-r',str(pin)],check=True)
        pin.unlink()
        requirements=[]
        for wheel in sorted(wheels.glob('*.whl')):
            with zipfile.ZipFile(wheel) as z:
                metadata=[n for n in z.namelist() if n.endswith('.dist-info/METADATA')]
                if len(metadata)!=1:raise ValueError('Invalid wheel metadata.')
                value=email.message_from_bytes(z.read(metadata[0]))
                wheel_info=email.message_from_bytes(z.read(metadata[0].replace('/METADATA','/WHEEL')))
                tags=wheel_info.get_all('Tag',[])
                platforms=[p for tag in tags for p in tag.rsplit('-',1)[-1].split('.')]
                compatible=any(p=='any' or p in {'manylinux1_x86_64','manylinux2010_x86_64','manylinux2014_x86_64'} or (re.fullmatch(r'manylinux_2_([0-9]+)_x86_64',p) and int(re.fullmatch(r'manylinux_2_([0-9]+)_x86_64',p)[1])<=35) for p in platforms)
                if not compatible:raise ValueError('Wheel exceeds the supported Linux/glibc baseline.')
            requirements.append(f'{value["Name"]}=={value["Version"]} --hash=sha256:{sha(wheel)}')
        if not requirements:raise ValueError('No wheels downloaded.')
        (target/'requirements-runtime.txt').write_text('\n'.join(requirements)+'\n',encoding='utf-8')
        finish(target,'Linux-Native-x64',output)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('operation',choices=['prepare','seal','consume','require-ci','require-inputs','record-local','native','finish','extract','readme'])
    p.add_argument('--version',default='0.1.0');p.add_argument('--archive',type=Path);p.add_argument('--output',type=Path,default=ROOT/'dist/deployment')
    p.add_argument('--directory',type=Path);p.add_argument('--platform');p.add_argument('--sha256')
    p.add_argument('--document',type=Path)
    a=p.parse_args()
    try:
        if a.operation=='prepare':prepare(a.version)
        elif a.operation=='seal':seal(a.output)
        elif a.operation=='consume':consume(a.archive)
        elif a.operation=='require-ci':require_ci()
        elif a.operation=='require-inputs':require_inputs()
        elif a.operation=='record-local':record_local()
        elif a.operation=='native':native(a.output)
        elif a.operation=='finish':finish(a.directory,a.platform,a.output)
        elif a.operation=='extract':verify_extract(a.archive,a.directory,a.sha256)
        elif a.operation=='readme':
            if a.document is None or a.directory is None: raise ValueError('Specify document and package directory.')
            package_document(a.document,a.directory/'README.md')
    except (ValueError,OSError,KeyError,subprocess.CalledProcessError,zipfile.BadZipFile,tarfile.TarError):
        p.exit(1,'Deployment packaging failed; check identity, validation, archive integrity and build prerequisites.\n')


if __name__=='__main__':main()
