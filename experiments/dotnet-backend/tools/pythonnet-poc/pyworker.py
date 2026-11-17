"""Conventional Python subprocess worker for the REPORTING_ARCHITECTURE.md comparison (JSON lines on stdin/stdout). Not shipped."""
import base64, json, os, sys, tempfile
os.environ['SAP_LENS_CONFIG_DIR'] = tempfile.mkdtemp()
sys.path.insert(0, os.environ['SAPLENS_V1_BACKEND'])
import branding, sod_reports
for line in sys.stdin:
    r = json.loads(line); out = dict(id=r.get('id'))
    try:
        if r['op'] == 'render':
            sod_reports.report_logo = lambda d: None
            out['data'] = base64.b64encode(sod_reports.render(json.loads(r['model']), r['kind'])).decode()
        elif r['op'] == 'sanitize':
            out['data'] = base64.b64encode(branding.sanitize_image(base64.b64decode(r['image']))).decode()
    except Exception as e: out['error'] = type(e).__name__
    print(json.dumps(out), flush=True)
