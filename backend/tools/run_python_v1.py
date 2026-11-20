"""Benchmark launcher for the PRODUCTION Python v1 backend (unchanged): desktop-mode create_app on a loopback port with a session token and an isolated
configuration directory. Optional CSV paths are written to that private configuration before start. Never touches a real installation.

  python -I run_python_v1.py --port P --token T --config-dir DIR [--roles CSV --users CSV]"""
import argparse
import os
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, required=True)
parser.add_argument('--token', required=True)
parser.add_argument('--config-dir', required=True)
parser.add_argument('--roles', default='')
parser.add_argument('--users', default='')
args = parser.parse_args()
os.environ['SAP_LENS_CONFIG_DIR'] = args.config_dir
for name in ('SAP_LENS_DATA_DIR', 'SAP_LENS_DEPLOYMENT_MODE'):
    os.environ.pop(name, None)
sys.path.insert(0, str(Path(__file__).resolve().parent))  # with -I the tool's own folder is not on sys.path
from v1_location import v1_backend  # noqa: E402
sys.path.insert(0, v1_backend())

import uvicorn  # noqa: E402
from config import get_settings, save_configuration  # noqa: E402
from main import create_app  # noqa: E402

if args.roles or args.users:
    current = get_settings()
    save_configuration(current.model_copy(update={'data_csv_path': args.roles, 'user_csv_path': args.users}), current.revision)
app = create_app(origin=f'http://127.0.0.1:{args.port}', session_token=args.token)
uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=args.port, log_config=None, access_log=False, timeout_graceful_shutdown=2)).run()
