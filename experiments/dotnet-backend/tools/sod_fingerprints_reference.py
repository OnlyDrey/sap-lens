"""Python v1 reference for the SoD source fingerprints (content hash, optional metadata, warnings, definition_version per risk).
Usage: python -I tools/sod_fingerprints_reference.py FILE.csv OUT.json  (compare with SapLens.Cli sod-fingerprints)."""
import json, os, sys, tempfile
os.environ['SAP_LENS_CONFIG_DIR'] = tempfile.mkdtemp()
sys.path.insert(0, '/home/user/sap-lens/backend')
from sod_import import parse_sod
from sod_catalogue import definition_version
s = parse_sod(sys.argv[1])
out = dict(content_hash=s['content_hash'], metadata=s['report'].get('metadata'), warnings=s['warnings'],
           definition_versions={r['risk_id']: definition_version(r) for r in s['risks']})
open(sys.argv[2], 'w').write(json.dumps(out, sort_keys=True, ensure_ascii=False, separators=(',', ':')))
