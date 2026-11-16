"""Python v1 reference for GET /api/diagnostics and /export: the allowlisted key sets (top level, per source, refresh history item) of a private
(Desktop) and an exported report on an empty installation. Usage: python -I tools/diagnostics_reference.py BACKEND_DIR OUT.json"""
import json, os, sys, tempfile
os.environ['SAP_LENS_CONFIG_DIR'] = tempfile.mkdtemp()
backend, out = sys.argv[1:3]
sys.path.insert(0, backend)
from diagnostics import diagnostics_snapshot
result = {}
for name, private in (('private', True), ('export', False)):
    report = diagnostics_snapshot(None, private=private)
    result[name] = dict(top=sorted(report), sources={s['id']: sorted(s) for s in report['sources']}, scheduled_refresh=sorted(report['scheduled_refresh']),
                        source_order=[s['id'] for s in report['sources']], review_continuity=report['review_continuity'], backend_status=report['backend_status'])
with open(out, 'w', encoding='utf-8') as stream: json.dump(result, stream, indent=1)
