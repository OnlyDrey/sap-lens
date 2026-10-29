"""Isolated production-asset test server; not an end-user launch command."""
from pathlib import Path
import os
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import uvicorn

# Parallel test processes each own one server (port and configuration directory); the default is the CI port.
PORT = int(os.environ.get('SAP_LENS_BROWSER_TEST_PORT', '18745'))
with tempfile.TemporaryDirectory(prefix='sap-lens-browser-') as directory:
    os.environ['SAP_LENS_CONFIG_DIR'] = directory
    os.environ['DATA_CSV_PATH'] = ''
    from main import create_app
    uvicorn.run(create_app(origin=f'http://127.0.0.1:{PORT}', session_token='browser-test-session'),
                host='127.0.0.1', port=PORT, access_log=False, log_level='warning')
