"""Single-process headless entry point. Never imports the desktop/WebView runtime."""
import argparse
import logging
import os
from pathlib import Path
import secrets
import socket
import sys

from deployment import ServerSettings


def run():
    parser=argparse.ArgumentParser(description='SAP Lens headless server')
    parser.add_argument('--init-secret',type=Path,help='Create a new private shared-access secret, without printing it')
    args=parser.parse_args()
    if args.init_secret:
        with args.init_secret.open('x',encoding='ascii') as stream:
            if os.name!='nt': os.chmod(args.init_secret,0o600)
            stream.write(secrets.token_urlsafe(48)+'\n')
        return 0
    stage='configuration'
    try:
        os.environ['SAP_LENS_DEPLOYMENT_MODE']='server'
        settings=ServerSettings.from_env()
        os.environ['SAP_LENS_DATA_DIR']=str(settings.data)
        os.environ['SAP_LENS_CONFIG_DIR']=str(settings.data)
        os.environ['SAP_LENS_SOURCE_DIR']=str(settings.sources)
        logging.basicConfig(level=settings.log_level.upper(),format='%(asctime)s %(levelname)s %(message)s')
        stage='storage ownership and permissions'
        from storage_lease import StorageLease
        lease=StorageLease(settings.data,'server').acquire()
        try:
            from config import get_settings
            get_settings.cache_clear()
            stage='application resources'
            from main import create_app, frontend_dir
            if not (frontend_dir/'index.html').is_file(): raise ValueError('Build the production frontend before starting the server.')
            import uvicorn
            # Reserve before declaring readiness; never switch an operator-selected service port.
            stage='listener binding'
            family=socket.AF_INET6 if ':' in settings.host else socket.AF_INET
            with socket.socket(family,socket.SOCK_STREAM) as listener:
                if os.name=='nt': listener.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
                else: listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                listener.bind((settings.host,settings.port));listener.listen(128)
                logging.info('SAP Lens server starting (single worker, headless)')
                config=uvicorn.Config(create_app(server=settings),workers=1,access_log=False,proxy_headers=False,
                                      log_level=settings.log_level,timeout_graceful_shutdown=15)
                stage='server runtime'
                uvicorn.Server(config).run(sockets=[listener])
                logging.info('SAP Lens server stopped')
        finally: lease.close()
        return 0
    except (ValueError,OSError,RuntimeError) as error:
        # Exception strings can contain source paths or credentials.
        logging.error('Server startup failed at %s (%s); verify configuration, storage permissions, frontend assets and port availability.',stage,type(error).__name__)
        return 1


if __name__=='__main__': sys.exit(run())
