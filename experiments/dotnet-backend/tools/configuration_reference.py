"""Python v1 reference for POST /api/configuration/export and /reset: the portable package of a settings document with a private organization
name and a dark theme, redacted and private. Usage: python -I tools/configuration_reference.py BACKEND_DIR OUT.json"""
import json, os, sys, tempfile
os.environ['SAP_LENS_CONFIG_DIR'] = tempfile.mkdtemp()
backend, out = sys.argv[1:3]
sys.path.insert(0, backend)
from config_models import AppConfig
from portable_config import export_configuration

config = AppConfig()
config.theme = 'dark'
config.organization.name = 'Example Org'
config.organization.description = 'Synthetic organization'
result = dict(redacted=export_configuration(config, False), private=export_configuration(config, True), defaults=AppConfig().model_dump())
with open(out, 'w', encoding='utf-8') as stream: json.dump(result, stream, indent=1, sort_keys=True)
