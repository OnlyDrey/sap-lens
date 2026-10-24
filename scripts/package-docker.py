"""Build-only Docker image export. No registry or release publication."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('packages',ROOT/'scripts/deployment-package.py')
pkg=importlib.util.module_from_spec(spec);spec.loader.exec_module(pkg)


def main():
    pkg.require_ci() if os.environ.get('GITHUB_ACTIONS')=='true' else None
    info=pkg.identity();tag='sap-lens:'+info['version'].replace('+','-')
    command=['docker','build','--build-arg','SAP_LENS_BUILD_INFO='+json.dumps(info,separators=(',',':')),'-t',tag,'.']
    # Preserve managed build proxies and optional CA without putting them into image layers.
    for key in ('HTTP_PROXY','HTTPS_PROXY','NO_PROXY'):
        if os.environ.get(key):command[2:2]=['--build-arg',key]
    ca=os.environ.get('SAP_LENS_BUILD_CA')
    if ca:command[2:2]=['--secret','id=build_ca,src='+ca]
    host=os.environ.get('SAP_LENS_BUILD_PROXY_HOST')
    if host:command[2:2]=['--add-host',host]
    subprocess.run(command,cwd=ROOT,check=True)
    subprocess.run([os.sys.executable,str(ROOT/'scripts/test-docker-deployment.py'),'--image',tag],check=True)
    with tempfile.TemporaryDirectory() as temporary:
        target=Path(temporary)
        frozen=subprocess.check_output(['docker','run','--rm','--network','none','--entrypoint','python',tag,'-c','import importlib.metadata as m; print("\\n".join(sorted(d.metadata["Name"]+"=="+d.version for d in m.distributions())))'],text=True)
        audit_file=target/'runtime-audit.txt';audit_file.write_text(frozen)
        subprocess.run([os.environ.get('SAP_LENS_AUDIT_PYTHON',os.sys.executable),'-m','pip_audit','--disable-pip','--no-deps','-r',str(audit_file)],check=True)
        audit_file.unlink()
        subprocess.run(['docker','save','-o',str(target/'image.tar'),tag],check=True)
        # This is a deployment file for a locally loaded, already-built image.
        (target/'compose.yml').write_text((ROOT/'compose.yml').read_text().replace('    build: .','    image: '+tag),encoding='utf-8')
        shutil.copyfile(ROOT/'docs/DEPLOYMENT_LINUX_DOCKER.md',target/'README.md')
        shutil.copyfile(ROOT/'docs/DEPLOYMENT_SECURITY.md',target/'SECURITY.md')
        pkg.finish(target,'Linux-Docker-amd64',ROOT/'dist/deployment')


if __name__=='__main__':main()
