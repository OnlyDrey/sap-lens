"""Extract, audit, offline-install, upgrade and start a Linux package without root/systemd."""
import argparse
import http.client
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]


def smoke(artifacts):
    spec=importlib.util.spec_from_file_location('packages',ROOT/'scripts/deployment-package.py')
    pkg=importlib.util.module_from_spec(spec);spec.loader.exec_module(pkg)
    archives=list(artifacts.glob('SAP-Lens-Linux-Native-x64-*.tar.gz'))
    if len(archives)!=1:raise ValueError('Expected exactly one native archive.')
    archive=archives[0];digest=archive.with_name(archive.name+'.sha256').read_text().split()[0]
    with tempfile.TemporaryDirectory(prefix='SAP Lens native ø ') as temp:
        root=Path(temp);bundle=root/'bundle';manifest=pkg.verify_extract(archive,bundle,digest)
        audit=os.environ.get('SAP_LENS_AUDIT_PYTHON')
        if os.environ.get('GITHUB_ACTIONS')=='true' or audit:
            subprocess.run([audit or sys.executable,'-m','pip_audit','--disable-pip','--no-deps','-r',str(bundle/'requirements-runtime.txt')],check=True)
        prefix=root/'application';data=root/'data';config=root/'config/server.env'
        def install(source,action):
            subprocess.run([sys.executable,str(source/'scripts/install-linux-server.py'),action,'--user','--prefix',str(prefix),'--data',str(data),'--config',str(config)],check=True)
        install(bundle,'install')
        with socket.socket() as reserve:reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
        config.write_text(config.read_text().replace('"18743"',json.dumps(str(port))).replace('127.0.0.1:18743',f'127.0.0.1:{port}'))
        expected=config.read_bytes()
        def request(method,path,body=None,headers=None):
            connection=http.client.HTTPConnection('127.0.0.1',port,timeout=2)
            try:
                connection.request(method,path,json.dumps(body) if isinstance(body,dict) else body,
                                   headers={'X-SAP-Lens':'1','Content-Type':'application/json',**(headers or {})})
                response=connection.getresponse();return response.status,response.read()
            finally:connection.close()
        def start(version):
            env=os.environ.copy()
            for key in ('SAP_LENS_CONFIG_DIR','SAP_LENS_DATA_DIR','SAP_LENS_DEPLOYMENT_MODE'):env.pop(key,None)
            command=[str(prefix/'current/.venv/bin/python'),str(prefix/'current/scripts/run-installed-server.py'),'--env',str(config)]
            process=subprocess.Popen(command,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            for _ in range(150):
                try:
                    status,raw=request('GET','/api/version')
                    if status==200:
                        if json.loads(raw)['version']!=version:raise ValueError('Installed version mismatch.')
                        return process
                except OSError:pass
                if process.poll() is not None:break
                time.sleep(.1)
            process.terminate();process.wait(timeout=20);raise ValueError('Installed runtime did not start.')
        process=start(manifest['identity']['version'])
        try:
            status,raw=request('POST','/api/server/uploads/roles',b'AGR_NAME,TCODE\nZC:SYNTHETIC,MIGO\n',{'X-Upload-Filename':'Synthetic.csv','Content-Type':'text/csv'})
            if status!=200:raise ValueError('Installed upload failed.')
            settings=json.loads(request('GET','/api/configuration')[1])['settings']
            settings['data_csv_path']=json.loads(raw)['path'];settings['source_modes']['roles']='static'
            if request('POST','/api/configuration',settings)[0]!=200:raise ValueError('Installed import failed.')
        finally:process.terminate();process.wait(timeout=20)
        # Exercise upgrade semantics with a synthetic next-version bundle; never publish it.
        upgraded=root/'upgrade';shutil.copytree(bundle,upgraded)
        new_info=pkg.make_local_package_info('0.1.1','b'*40)
        pkg.write(upgraded/'backend/build/build-version.json',new_info)
        new_files=pkg.files(upgraded);new_files.pop('package-manifest.json')
        pkg.write(upgraded/'package-manifest.json',dict(schema=1,platform='Linux-Native-x64',identity=new_info,files=new_files))
        install(upgraded,'install')
        process=start(new_info['version'])
        try:
            for _ in range(100):
                roles=json.loads(request('GET','/api/roles')[1])
                if roles:break
                time.sleep(.05)
            if not roles or roles[0]['agr_name']!='ZC:SYNTHETIC':raise ValueError('Upgrade lost persisted source records.')
        finally:process.terminate();process.wait(timeout=20)
        install(bundle,'uninstall')
        if config.read_bytes()!=expected or not (data/'settings.json').is_file():raise ValueError('Upgrade/uninstall changed configuration or removed data.')
        print('Linux archive, offline wheelhouse installation, Unicode paths, startup/version/import/shutdown, synthetic upgrade persistence and data-preserving uninstall passed. systemd was not exercised.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--artifacts',type=Path,required=True);smoke(p.parse_args().artifacts)
