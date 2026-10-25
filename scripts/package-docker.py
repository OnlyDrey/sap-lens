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


def main(output=None, no_cache=False):
    pkg.require_inputs()
    info=pkg.identity();tag='sap-lens:'+info['version'].replace('+','-')
    command=['docker','build','--platform','linux/amd64','--build-arg','SAP_LENS_FRONTEND_STAGE=validated_frontend','--build-arg','SAP_LENS_BUILD_INFO='+json.dumps(info,separators=(',',':')),'-t',tag,'.']
    if no_cache:command[2:2]=['--no-cache']
    # Preserve managed build proxies and optional CA without putting them into image layers.
    for key in ('HTTP_PROXY','HTTPS_PROXY','NO_PROXY'):
        if os.environ.get(key):command[2:2]=['--build-arg',key]
    ca=os.environ.get('SAP_LENS_BUILD_CA')
    if ca:command[2:2]=['--secret','id=build_ca,src='+ca]
    host=os.environ.get('SAP_LENS_BUILD_PROXY_HOST')
    if host:command[2:2]=['--add-host',host]
    subprocess.run(command,cwd=ROOT,check=True)
    subprocess.run([os.sys.executable,str(ROOT/'scripts/test-docker-deployment.py'),'--image',tag],check=True)
    subprocess.run([os.sys.executable,str(ROOT/'scripts/test-docker-lifecycle.py'),'--image',tag],check=True)
    with tempfile.TemporaryDirectory() as temporary:
        target=Path(temporary)
        frozen=subprocess.check_output(['docker','run','--rm','--network','none','--entrypoint','python',tag,'-c','import importlib.metadata as m; print("\\n".join(sorted(d.metadata["Name"]+"=="+d.version for d in m.distributions())))'],text=True)
        audit_file=target/'runtime-audit.txt';audit_file.write_text(frozen)
        subprocess.run([os.environ.get('SAP_LENS_AUDIT_PYTHON',os.sys.executable),'-m','pip_audit','--disable-pip','--no-deps','-r',str(audit_file)],check=True)
        audit_file.unlink()
        subprocess.run(['docker','save','-o',str(target/'image.tar'),tag],check=True)
        # This is a deployment file for a locally loaded, already-built image.
        (target/'compose.yml').write_text((ROOT/'compose.yml').read_text().replace('    build: .','    image: '+tag),encoding='utf-8')
        (target/'compose.env.example').write_text('SAP_LENS_PUBLISH_ADDRESS=127.0.0.1\nSAP_LENS_PUBLISH_PORT=18743\nSAP_LENS_PUBLIC_ORIGIN=http://127.0.0.1:18743\nSAP_LENS_ALLOWED_HOSTS=127.0.0.1\nSAP_LENS_AUTH=basic\n')
        shutil.copyfile(ROOT/'deploy/docker/manage.sh',target/'manage.sh')
        (target/'manage.sh').chmod(0o755)
        shutil.copyfile(ROOT/'LICENSE.md',target/'LICENSE.md')
        shutil.copyfile(ROOT/'docs/DEPLOYMENT_LINUX_DOCKER.md',target/'README.md')
        shutil.copyfile(ROOT/'docs/DEPLOYMENT_SECURITY.md',target/'SECURITY.md')
        pkg.finish(target,'Linux-Docker-amd64',output or ROOT/'dist/deployment')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--no-cache',action='store_true')
    args=parser.parse_args();main(args.output,args.no_cache)
