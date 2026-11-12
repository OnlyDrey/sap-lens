"""Synthetic image acceptance: TLS-only sessions, local first-run activation, roles, persistence after restart and recreation."""
import argparse
import base64
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from docker_session import PASSWORD, Session, activate, docker, sign_in  # noqa: E402


def run(image):
    name='sap-lens-smoke-'+uuid.uuid4().hex[:12];volume=name+'-data'
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='sap-lens-smoke-') as temporary:
        config=Path(temporary)/'local-config';config.mkdir(mode=0o700)
        def setup(*args):
            return docker('run','--rm','--network','none','--read-only','--user','0:0','--cap-drop=ALL','--cap-add=DAC_OVERRIDE','--cap-add=CHOWN',
                          '-v',f'{config}:/configuration','--entrypoint','python',image,'backend/container_setup.py',*args,'--directory','/configuration','--owner',os.getuid(),'--group','10001')
        def start():
            docker('run','-d','--name',name,'--read-only','--cap-drop=ALL','--security-opt=no-new-privileges','--tmpfs','/tmp:size=64m,mode=1777',
                   '-p',f'127.0.0.1:{port}:18743','-v',volume+':/data',
                   '-v',f'{config}/tls.crt:/run/secrets/tls_cert:ro','-v',f'{config}/tls.key:/run/secrets/tls_key:ro','-v',f'{config}/backup.key:/run/secrets/backup_key:ro',
                   '-e',f'SAP_LENS_PUBLIC_ORIGIN=https://localhost:{port}','-e','SAP_LENS_ALLOWED_HOSTS=localhost','-e','SAP_LENS_AUTH=sessions',
                   '-e','SAP_LENS_TLS_CERT_FILE=/run/secrets/tls_cert','-e','SAP_LENS_TLS_KEY_FILE=/run/secrets/tls_key',
                   '-e','SAP_LENS_BACKUP_KEY_FILE=/run/secrets/backup_key','-e','SAP_LENS_BACKUP_KEY_GROUP_READ=1',image)
        def ready():
            for _ in range(200):
                try:
                    if session.request('GET','/health/ready',cookies=False)[0]==200:return
                except OSError:pass
                time.sleep(.1)
            print(docker('logs',name))
            raise ValueError('Container readiness failed.')
        def roles():return session.json('GET','/api/roles')
        def wait_roles():
            for _ in range(100):
                if roles():break
                time.sleep(.05)
            assert roles()[0]['agr_name']=='ZC:SYNTHETIC'
        try:
            details=json.loads(setup('generate-tls','--host','localhost'));setup('backup-key')
            assert details['self_signed'] and {'localhost','127.0.0.1'}<=set(details['names'])
            assert (config/'tls.key').stat().st_mode&0o777==0o640 and (config/'backup.key').stat().st_mode&0o777==0o640
            before=(config/'tls.key').read_bytes()
            refused=subprocess.run(['docker','run','--rm','--network','none','--user','0:0','-v',f'{config}:/configuration','--entrypoint','python',image,
                                    'backend/container_setup.py','generate-tls','--directory','/configuration','--host','localhost'],capture_output=True,text=True)
            assert refused.returncode!=0 and (config/'tls.key').read_bytes()==before,'An existing private key must never be replaced.'
            session=Session(port,config/'tls.crt')
            start();ready()
            assert session.request('GET','/')[0]==200
            assert session.plain_http_is_refused()
            assert session.request('GET','/api/configuration')[0]==401
            basic={'Authorization':'Basic '+base64.b64encode(('admin:'+PASSWORD).encode()).decode()}
            assert session.request('GET','/api/configuration',headers=basic)[0]==401
            activate(session,lambda:docker('exec',name,'python','backend/server.py','--identity-code','--data-directory','/data'))
            assert session.request('GET','/api/configuration',headers=basic,cookies=False)[0]==401   # the new password is still no Basic credential
            assert session.request('POST','/api/refresh',{},headers={'X-SAP-Lens-CSRF':'wrong'})[0]==403
            status,content=session.request('POST','/api/server/uploads/roles',b'AGR_NAME,TCODE\nZC:SYNTHETIC,MIGO\n',headers={'X-Upload-Filename':'Synthetic.csv','Content-Type':'text/csv'})
            assert status==200,status
            settings=session.json('GET','/api/configuration')['settings']
            settings['data_csv_path']=json.loads(content)['path'];settings['source_modes']['roles']='static'
            session.json('POST','/api/configuration',settings)
            wait_roles()
            # Roles: a viewer reads, cannot administer; a disabled account and a revoked session are refused at once.
            created=session.json('POST','/api/auth/users',dict(username='viewer',display_name='Synthetic Viewer',role='viewer',password=PASSWORD))
            viewer=Session(port,config/'tls.crt');sign_in(viewer,'viewer')
            assert viewer.request('GET','/api/roles')[0]==200 and viewer.request('GET','/api/auth/users')[0]==403 and viewer.request('POST','/api/refresh',{})[0]==403
            session.json('POST','/api/auth/users/'+created['id']+'/revoke')
            assert viewer.request('GET','/api/roles')[0]==401
            sign_in(viewer,'viewer')
            session.json('POST','/api/auth/users/'+created['id'],dict(expected_revision=created['revision'],display_name='Synthetic Viewer',role='viewer',enabled=False))
            assert viewer.request('GET','/api/roles')[0]==401 and viewer.request('POST','/api/auth/login',dict(username='viewer',password=PASSWORD),cookies=False)[0]==401
            docker('restart','--time','25',name);ready();wait_roles()                                  # the session and the account survive a restart
            docker('stop','--time','25',name);docker('rm',name);start();ready()
            assert sign_in(session)['username']=='admin';wait_roles()                                  # and a recreated container
            assert session.json('GET','/api/auth/state')['setup_required'] is False
            assert docker('exec',name,'id','-u')=='10001'
            docker('exec',name,'python','backend/healthcheck.py')
            expected=json.loads(docker('run','--rm','--network','none','--entrypoint','python',image,'-c','from pathlib import Path;print(Path("backend/build/build-version.json").read_text())'))
            assert session.json('GET','/api/version')['version']==expected['version']
            session.json('POST','/api/auth/logout');assert session.request('GET','/api/configuration')[0]==401
            logs=docker('logs',name,stderr=subprocess.STDOUT)
            assert PASSWORD not in logs and 'sap-lens-session' not in logs
            print('Docker TLS/session/activation/roles/revocation/import/health/version/restart/recreation persistence passed.')
        finally:
            subprocess.run(['docker','rm','-f',name],capture_output=True)
            subprocess.run(['docker','volume','rm',volume],capture_output=True)
            subprocess.run(['docker','run','--rm','--network','none','--user','0:0','-v',f'{temporary}:/t','--entrypoint','python',image,'-c',
                            f'import os,pathlib\nfor p in pathlib.Path("/t").rglob("*"):os.chown(p,{os.getuid()},{os.getgid()})'],capture_output=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--image',required=True);run(p.parse_args().image)
