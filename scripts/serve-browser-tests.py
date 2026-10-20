"""Isolated production-asset test server; not an end-user launch command."""
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import os
import uvicorn

with tempfile.TemporaryDirectory(prefix='sap-lens-browser-') as directory:
    os.environ['SAP_LENS_CONFIG_DIR'] = directory
    os.environ['DATA_CSV_PATH'] = ''
    from main import create_app
    uvicorn.run(create_app(origin='http://127.0.0.1:18745', session_token='browser-test-session'),
                host='127.0.0.1', port=18745, access_log=False, log_level='warning')
