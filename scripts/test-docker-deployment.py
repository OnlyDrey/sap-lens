"""Synthetic image acceptance, including persistent state after container recreation."""
import argparse
import base64
import http.client
import json
import subprocess
import time
import uuid


def run(image):
    name='sap-lens-smoke-'+uuid.uuid4().hex[:12];secret=name+'-synthetic-access-password'
    volume=name+'-data';access=name+'-secret'
    def docker(*args):return subprocess.check_output(['docker',*args],text=True).strip()
    def start():
        docker('run','-d','--name',name,'--read-only','--cap-drop=ALL','--security-opt=no-new-privileges',
               '--tmpfs','/tmp:size=64m,mode=1777','-p','127.0.0.1::18743','-v',volume+':/data','-v',access+':/run/secrets:ro',
               '-e','SAP_LENS_AUTH=basic','-e','SAP_LENS_AUTH_SECRET_FILE=/run/secrets/access',image)
        return int(docker('port',name,'18743/tcp').rsplit(':',1)[1])
    def request(method,path,body=None,auth=True,headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',port,timeout=3)
        head={'X-SAP-Lens':'1','Content-Type':'application/json','Host':'127.0.0.1:18743',**(headers or {})}
        if auth:head['Authorization']='Basic '+base64.b64encode(('saplens:'+secret).encode()).decode()
        try:
            connection.request(method,path,json.dumps(body) if isinstance(body,dict) else body,headers=head)
            result=connection.getresponse();return result.status,result.read()
        finally:connection.close()
    def ready():
        for _ in range(150):
            try:
                if request('GET','/health/ready')[0]==200:return
            except OSError:pass
            time.sleep(.1)
        print(docker('logs',name))
        print('Container state: '+docker('inspect',name,'--format','{{.State.Status}} {{.State.ExitCode}}'))
        raise ValueError('Container readiness failed.')
    def roles():return json.loads(request('GET','/api/roles')[1])
    try:
        docker('run','--rm','--network','none','--user','0:0','-v',access+':/secret','--entrypoint','python',image,'-c',
               f"import os,pathlib;p=pathlib.Path('/secret/access');p.write_text({secret!r});p.chmod(0o600);os.chown(p,10001,10001)")
        port=start();ready()
        assert request('GET','/')[0]==200
        assert request('GET','/api/configuration',auth=False)[0]==401
        status,content=request('POST','/api/server/uploads/roles',b'AGR_NAME,TCODE\nZC:SYNTHETIC,MIGO\n',headers={'X-Upload-Filename':'Synthetic.csv','Content-Type':'text/csv'})
        assert status==200
        config=json.loads(request('GET','/api/configuration')[1])['settings']
        config['data_csv_path']=json.loads(content)['path'];config['source_modes']['roles']='static'
        assert request('POST','/api/configuration',config)[0]==200
        assert roles()[0]['agr_name']=='ZC:SYNTHETIC'
        docker('restart','--time','25',name);port=int(docker('port',name,'18743/tcp').rsplit(':',1)[1]);ready()
        for _ in range(100):
            if roles():break
            time.sleep(.05)
        assert roles()[0]['agr_name']=='ZC:SYNTHETIC'
        docker('stop','--time','25',name);docker('rm',name);port=start();ready()
        for _ in range(100):
            if roles():break
            time.sleep(.05)
        assert roles()[0]['agr_name']=='ZC:SYNTHETIC'
        assert docker('exec',name,'id','-u')=='10001'
        docker('exec',name,'python','backend/healthcheck.py')
        expected=json.loads(subprocess.check_output(['docker','run','--rm','--network','none','--entrypoint','python',image,'-c',
            'import json;from pathlib import Path;print(Path("backend/build/build-version.json").read_text())'],text=True))
        assert json.loads(request('GET','/api/version')[1])['version']==expected['version']
        print('Docker frontend/authentication/import/health/version/restart/recreation persistence passed.')
    finally:
        subprocess.run(['docker','rm','-f',name],capture_output=True)
        subprocess.run(['docker','volume','rm',volume,access],capture_output=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--image',required=True);run(p.parse_args().image)
