"""Disposable offline management acceptance. No registry, real data or shared volumes."""
import argparse
import base64
import hashlib
import http.client
import json
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def smoke(image):
    def docker(*args):
        return subprocess.check_output(['docker', *map(str, args)], text=True).strip()
    with tempfile.TemporaryDirectory(prefix='SAP Lens Docker ø ') as temporary:
        temp = Path(temporary); bundle = temp/'bundle'; bundle.mkdir()
        roots = [temp/'installation', temp/'recovered-installation']
        projects = ['sap-lens-'+hashlib.sha256(str(root).encode()).hexdigest()[:12] for root in roots]
        info = json.loads(docker('run','--rm','--network','none','--entrypoint','python',image,'-c',
                                'from pathlib import Path;print(Path("backend/build/build-version.json").read_text())'))
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0)); port = listener.getsockname()[1]
        docker('save','-o',bundle/'image.tar',image)
        compose = (ROOT/'compose.yml').read_text().replace('    build: .','    image: '+image)
        # Speed up disposable health polling while retaining the image's real probe.
        compose = compose.replace('    restart: unless-stopped','    restart: unless-stopped\n    healthcheck:\n      interval: 1s\n      start_period: 1s\n      timeout: 3s\n      retries: 10')
        (bundle/'compose.yml').write_text(compose)
        (bundle/'compose.env.example').write_text(f'SAP_LENS_PUBLISH_ADDRESS=127.0.0.1\nSAP_LENS_PUBLISH_PORT={port}\nSAP_LENS_PUBLIC_ORIGIN=http://127.0.0.1:{port}\nSAP_LENS_ALLOWED_HOSTS=127.0.0.1\nSAP_LENS_AUTH=basic\n')
        shutil.copyfile(ROOT/'deploy/docker/manage.sh',bundle/'manage.sh')
        shutil.copyfile(ROOT/'LICENSE.md',bundle/'LICENSE.md')
        files={path.name:hashlib.file_digest(path.open('rb'),'sha256').hexdigest() for path in bundle.iterdir()}
        (bundle/'package-manifest.json').write_text(json.dumps(dict(schema=1,platform='Linux-Docker-amd64',identity=info,files=files),indent=2)+'\n')
        def manage(action,root,*args):
            subprocess.run(['sh',str(bundle/'manage.sh'),action,str(root),*map(str,args)],check=True)
        def request(root,method,path,body=None,auth=True,headers=None):
            password=(root/'local-config/server-access.secret').read_text().strip()
            head={'X-SAP-Lens':'1','Content-Type':'application/json',**(headers or {})}
            if auth: head['Authorization']='Basic '+base64.b64encode(('saplens:'+password).encode()).decode()
            connection=http.client.HTTPConnection('127.0.0.1',port,timeout=3)
            try:
                connection.request(method,path,json.dumps(body) if isinstance(body,dict) else body,headers=head)
                result=connection.getresponse();return result.status,result.read()
            finally:connection.close()
        def wait_roles(root):
            for _ in range(100):
                status,raw=request(root,'GET','/api/roles')
                rows=json.loads(raw)
                if status==200 and rows:
                    if rows[0]['agr_name']!='ZC:SYNTHETIC':raise ValueError('Unexpected recovered role identity.')
                    return
                time.sleep(.1)
            raise ValueError('Persisted synthetic records were not restored.')
        try:
            manage('install',roots[0]); manage('install',roots[0])
            if request(roots[0],'GET','/api/configuration',auth=False)[0]!=401:raise ValueError('Authentication was bypassed.')
            status,raw=request(roots[0],'POST','/api/server/uploads/roles',b'AGR_NAME,TCODE\nZC:SYNTHETIC,MIGO\n',headers={'X-Upload-Filename':'Synthetic.csv','Content-Type':'text/csv'})
            if status!=200:raise ValueError('Synthetic upload failed.')
            settings=json.loads(request(roots[0],'GET','/api/configuration')[1])['settings']
            settings['data_csv_path']=json.loads(raw)['path'];settings['source_modes']['roles']='static'
            if request(roots[0],'POST','/api/configuration',settings)[0]!=200:raise ValueError('Synthetic import failed.')
            wait_roles(roots[0])
            configuration=(roots[0]/'compose.env').read_bytes();secret=(roots[0]/'local-config/server-access.secret').read_bytes()
            manage('backup',roots[0])
            backup_root=Path(str(roots[0])+'-backups');backups=list(backup_root.glob('*.tar.gz'))
            if len(backups)!=1 or backups[0].stat().st_mode&0o077:raise ValueError('Expected one owner-only private backup.')
            manage('upgrade',roots[0]);wait_roles(roots[0]);manage('restart',roots[0]);wait_roles(roots[0])
            if (roots[0]/'compose.env').read_bytes()!=configuration or (roots[0]/'local-config/server-access.secret').read_bytes()!=secret:raise ValueError('Upgrade reset administrator configuration or secret.')
            manage('uninstall',roots[0])
            preserved=docker('volume','inspect',projects[0]+'_sap-lens-data','--format','{{.Name}}')
            if not preserved:raise ValueError('Default uninstall removed data.')
            manage('install',roots[1],'--no-start')
            manage('restore',roots[1],backups[0],'--confirm-restore')
            recovered=list(temp.glob('recovered-installation-recovered-configuration-*'))
            if len(recovered)!=1 or (recovered[0]/'compose.env').read_bytes()!=configuration:raise ValueError('Configuration recovery failed.')
            manage('start',roots[1]);wait_roles(roots[1]);manage('status',roots[1])
            manage('uninstall',roots[1],'--purge-data','--confirm-purge')
            if not docker('volume','inspect',projects[0]+'_sap-lens-data','--format','{{.Name}}'):raise ValueError('Purge affected another installation.')
            print('Offline Docker install/reinstall, authentication, import, backup, same-version upgrade, restart, preserving uninstall, empty-volume recovery and isolated confirmed purge passed.')
        finally:
            for project in projects:
                for container in docker('ps','-aq','--filter','label=com.docker.compose.project='+project).splitlines():
                    subprocess.run(['docker','rm','-f',container],capture_output=True)
                for volume in docker('volume','ls','-q','--filter','label=com.docker.compose.project='+project).splitlines():
                    subprocess.run(['docker','volume','rm',volume],capture_output=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--image',required=True);smoke(parser.parse_args().image)
