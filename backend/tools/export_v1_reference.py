"""Exports reference data the React UI needs from the PRODUCTION Python v1 code (unchanged) into JSON the .NET server embeds:
the SAP area registry (names, icons, colours, categories) and the v1 default settings document. Re-run after v1 changes these:

  python -I export_v1_reference.py OUT_DIR

Uses an isolated temporary configuration directory; never reads a real installation."""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ['SAP_LENS_CONFIG_DIR'] = tempfile.mkdtemp(prefix='saplens-v1-export-')
sys.path.insert(0, str(Path(__file__).resolve().parent))  # with -I the tool's own folder is not on sys.path
from v1_location import v1_backend  # noqa: E402
sys.path.insert(0, v1_backend())

from config_models import ICONS, AppConfig  # noqa: E402
from module_registry import registry_list  # noqa: E402

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
registry = {'modules': registry_list(None), 'icons': list(ICONS),
            'sources': ['https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE', 'https://help.sap.com/docs/SAP_ERP'],
            'reference_note': 'Stable SAP area terminology; products/components/submodules are distinguished. Live source retrieval must be verified separately when network access permits.'}
(out / 'registry.json').write_text(json.dumps(registry, indent=1, ensure_ascii=False, sort_keys=True) + '\n', encoding='utf-8')
(out / 'default-settings.json').write_text(json.dumps(AppConfig().model_dump(mode='json'), indent=1, ensure_ascii=False, sort_keys=True) + '\n', encoding='utf-8')
print(f'wrote {out}')
