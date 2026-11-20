"""Python v1 catalogue/activity catalogue/lookup for a SoD CSV and a v1 sod-catalogue.json (stdin args: csv storage out)."""
import json, os, sys, tempfile
os.environ['SAP_LENS_CONFIG_DIR'] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from v1_location import v1_backend; sys.path.insert(0, v1_backend())  # SAP Lens 1 backend of an external checkout (v1_location.py)
from types import SimpleNamespace
from sod_import import parse_sod
import sod_catalogue as store, sod_metadata
from config import get_settings
csv_path, storage_path, out = sys.argv[1:4]
sod = parse_sod(csv_path)
snapshot = SimpleNamespace(sod=sod)
saved = store.CatalogueStorage.model_validate_json(open(storage_path, 'rb').read())
settings = get_settings()
result = dict(catalogue=store.catalogue(snapshot, settings, saved), activities=store.activity_catalogue(snapshot, settings, saved),
              lookup=sod_metadata.lookup(snapshot, saved), appearance=store.appearance(saved))
result['catalogue'].pop('source')
open(out, 'w').write(json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(',', ':')))
