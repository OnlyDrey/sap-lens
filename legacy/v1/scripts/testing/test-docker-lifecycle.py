"""Disposable offline management acceptance. No registry, real data or shared volumes.

Drives deploy/docker/manage.sh as an operator would: install with a generated certificate, local activation, encrypted backup,
same-version upgrade, restore into a second installation with the exported recovery key, and an isolated purge.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from docker_session import PASSWORD, Session, activate, docker, sign_in  # noqa: E402


def check(condition, message):
    if not condition: raise ValueError(message)


def smoke(image):
    with tempfile.TemporaryDirectory(prefix='SAP Lens Docker ø ') as temporary:
        temp = Path(temporary); bundle = temp/'bundle'; bundle.mkdir()
        roots = [temp/'installation', temp/'recovered-installation']
        projects = ['sap-lens-'+hashlib.sha256(str(root).encode()).hexdigest()[:12] for root in roots]
        info = json.loads(docker('run','--rm','--network','none','--entrypoint','python',image,'-c',
                                'from pathlib import Path;print(Path("backend/build/build-version.json").read_text())'))
        ports = []
        for _ in roots:
            with socket.socket() as listener:
                listener.bind(('127.0.0.1',0)); ports.append(listener.getsockname()[1])
        docker('save','-o',bundle/'image.tar',image)
        compose = (ROOT/'compose.yml').read_text().replace('    build: .','    image: '+image)
        # Speed up disposable health polling while retaining the image's real probe.
        compose = compose.replace('    restart: unless-stopped','    restart: unless-stopped\n    healthcheck:\n      interval: 1s\n      start_period: 1s\n      timeout: 3s\n      retries: 10')
        (bundle/'compose.yml').write_text(compose)
        shutil.copyfile(ROOT/'deploy/docker/manage.sh',bundle/'manage.sh')
        shutil.copyfile(ROOT/'LICENSE.md',bundle/'LICENSE.md')
        files={path.name:hashlib.file_digest(path.open('rb'),'sha256').hexdigest() for path in bundle.iterdir()}
        (bundle/'package-manifest.json').write_text(json.dumps(dict(schema=1,platform='Linux-Docker-amd64',identity=info,files=files),indent=2)+'\n')
        def manage(action,root,*args,script=None,stdin=None,expect=0):
            done=subprocess.run(['sh',str(script or bundle/'manage.sh'),action,str(root),*map(str,args)],input=stdin,capture_output=True,text=True)
            if done.returncode!=expect:
                print(done.stdout[-3000:]+done.stderr[-3000:])
                raise ValueError(f'manage.sh {action}: expected exit {expect}, got {done.returncode}.')
            return done.stdout+done.stderr
        def host_files(root):
            return {name:(root/'local-config'/name).read_bytes() for name in ('tls.crt','tls.key','backup.key','proxy-token.secret')}
        def wait_roles(session):
            for _ in range(100):
                status,raw=session.request('GET','/api/roles')
                rows=json.loads(raw) if status==200 else []
                if rows:
                    check(rows[0]['agr_name']=='ZC:SYNTHETIC','Unexpected recovered role identity.')
                    return
                time.sleep(.1)
            raise ValueError('Persisted synthetic records were not restored.')
        try:
            check('Unknown installation option' in manage('install',roots[0],'--insecure',expect=1),'An unknown option must be refused before anything is created.')
            check(not roots[0].exists(),'A refused installation created files.')
            output=manage('install',roots[0],'--port',ports[0])
            check('SELF-SIGNED' in output and 'activation-code' in output,'Installation must warn about the generated certificate and name the activation step.')
            original=host_files(roots[0])
            for name in ('tls.key','backup.key','proxy-token.secret'):
                check((roots[0]/'local-config'/name).stat().st_mode&0o777==0o640,f'{name} must be private to the owner and the container group.')
            check(original['backup.key'].strip() not in output.encode() and b'PRIVATE KEY' not in output.encode(),'A secret was printed.')
            manage('install',roots[0])
            check(host_files(roots[0])==original,'Reinstallation replaced a certificate, key or token.')
            environment=(roots[0]/'compose.env').read_text()
            check('SAP_LENS_AUTH' not in environment and f'https://localhost:{ports[0]}' in environment,'Environment must be HTTPS without an access mode switch.')
            session=Session(ports[0],roots[0]/'local-config/tls.crt')
            check(session.request('GET','/api/configuration')[0]==401,'Authentication was bypassed.')
            check(session.plain_http_is_refused(),'Plain HTTP was answered.')
            activate(session,lambda:manage('activation-code',roots[0]).strip().splitlines()[-1])
            manage('activation-code',roots[0],expect=1)                                                # setup is closed: no further first-run code
            status,raw=session.request('POST','/api/server/uploads/roles',b'AGR_NAME,TCODE\nZC:SYNTHETIC,MIGO\n',headers={'X-Upload-Filename':'Synthetic.csv','Content-Type':'text/csv'})
            check(status==200,'Synthetic upload failed.')
            settings=session.json('GET','/api/configuration')['settings']
            settings['data_csv_path']=json.loads(raw)['path'];settings['source_modes']['roles']='static'
            session.json('POST','/api/configuration',settings)
            wait_roles(session)
            session.json('POST','/api/auth/users',dict(username='reviewer',display_name='Synthetic Reviewer',role='reviewer',password=PASSWORD))
            identity=session.json('GET','/api/auth/me')['id']
            configuration=(roots[0]/'compose.env').read_bytes()
            manage('backup',roots[0])
            backup_root=Path(str(roots[0])+'-backups');backups=list(backup_root.glob('*.slbak'))
            check(len(backups)==1 and not backups[0].stat().st_mode&0o077 and not list(backup_root.glob('*.tar.gz')),'Expected one owner-only encrypted backup and no plaintext archive.')
            content=backups[0].read_bytes()
            check(content.startswith(b'SLBAK2') and b'ZC:SYNTHETIC' not in content and b'accounts.sqlite3' not in content and original['backup.key'].strip() not in content,'Backup is not an opaque encrypted archive.')
            manage('upgrade',roots[0]);wait_roles(session);manage('restart',roots[0]);wait_roles(session)
            check((roots[0]/'compose.env').read_bytes()==configuration and host_files(roots[0])==original,'Upgrade reset administrator configuration, certificate or keys.')
            check('"self_signed": true' in manage('status',roots[0]),'Status must describe the certificate.')
            recovery=json.loads(manage('recover-administrator',roots[0],'admin').strip().splitlines()[-1])
            check(recovery['purpose']=='recovery' and session.request('GET','/api/configuration')[0]==401,'Local recovery must revoke the administrator sessions.')
            session.json('POST','/api/auth/recover',dict(code=recovery['code'],password=PASSWORD+' recovered'),cookies=False)
            check(sign_in(session,'admin',PASSWORD+' recovered')['id']==identity,'Recovery must keep the administrator identity.')
            manage('uninstall',roots[0])
            check(docker('volume','inspect',projects[0]+'_sap-lens-data','--format','{{.Name}}'),'Default uninstall removed data.')
            # A second installation has its own key and certificate: the archive opens only with the first installation's recovery key.
            manage('install',roots[1],'--no-start','--port',ports[1])
            tampered=temp/'tampered.slbak';data=bytearray(content);data[len(data)//2]^=1;tampered.write_bytes(data)
            manage('restore',roots[1],backups[0],'--confirm-restore',expect=1)                                        # wrong key (this installation's own)
            manage('restore',roots[1],tampered,'--confirm-restore','--secret-stdin',stdin=original['backup.key'].decode(),expect=1)   # modified ciphertext
            manage('restore',roots[1],backups[0],expect=1)                                                             # no confirmation
            manage('restore',roots[1],backups[0],'--confirm-restore','--secret-stdin',stdin=original['backup.key'].decode())
            check(not list(temp.glob('recovered-installation-restore-work-*')),'Restore left decrypted working files.')
            manage('start',roots[1])
            restored=Session(ports[1],roots[1]/'local-config/tls.crt')
            restored.cookies.update(session.cookies)
            check(restored.request('GET','/api/configuration')[0]==401,'A session from the source installation was accepted after restore.')
            check(sign_in(restored)['id']==identity,'The restored administrator must keep its identity and the password at backup time.')
            check({row['username'] for row in restored.json('GET','/api/auth/users')['items']}=={'admin','reviewer'},'Restored accounts differ.')
            wait_roles(restored);manage('status',roots[1])
            manage('uninstall',roots[1],'--purge-data','--confirm-purge')
            check(docker('volume','inspect',projects[0]+'_sap-lens-data','--format','{{.Name}}'),'Purge affected another installation.')
            print('Offline Docker install/reinstall with generated TLS, local activation and recovery, encrypted backup, same-version upgrade, restart, '
                  'preserving uninstall, wrong-key/tampered/unconfirmed restore refusal, keyed empty-volume recovery with accounts and isolated confirmed purge passed.')
        finally:
            for project in projects:
                for container in docker('ps','-aq','--filter','label=com.docker.compose.project='+project).splitlines():
                    subprocess.run(['docker','rm','-f',container],capture_output=True)
                for volume in docker('volume','ls','-q','--filter','label=com.docker.compose.project='+project).splitlines():
                    subprocess.run(['docker','volume','rm',volume],capture_output=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--image',required=True);smoke(parser.parse_args().image)
