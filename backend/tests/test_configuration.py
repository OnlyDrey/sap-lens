import os
from pathlib import Path
import sys
import tempfile
import unittest
from io import BytesIO
from unittest.mock import patch
from PIL import Image
from fastapi.testclient import TestClient

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cache
import config
from config_models import AppConfig, ClassificationProfile, Domain, Rule, ModuleOverride
from classification import Classifier, classification_preview, legacy_child_module
from module_registry import REGISTRY, resolve_module, module_definition
from branding import stage_image, logo_bytes, sanitize_image
from portable_config import export_configuration, read_portable, PortableConfig
from main import create_app

H = {'X-SAP-Lens':'1'}


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ,{'SAP_LENS_CONFIG_DIR':str(self.root),'DATA_CSV_PATH':''})
        self.environment.start(); config.get_settings.cache_clear();cache.clear_cache()
        self.client_context=TestClient(create_app(),base_url='http://127.0.0.1:18743')
        self.client=self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None,None,None)
        self.environment.stop();config.get_settings.cache_clear();self.temp.cleanup()

    def png(self,color='red'):
        output=BytesIO();Image.new('RGBA',(160,40),color).save(output,format='PNG');return output.getvalue()

    def test_generic_defaults_and_versioned_persistence(self):
        settings=config.get_settings()
        self.assertEqual(settings.organization.name,'Example Inc.')
        self.assertEqual(settings.organization.system_id,'DEMO')
        self.assertEqual(settings.organization.client,'100')
        self.assertEqual(settings.schema_version,2)
        settings=settings.model_copy(deep=True);settings.organization.name='Synthetic Organization'
        saved=config.save_configuration(settings,0)
        config.get_settings.cache_clear()
        self.assertEqual(config.get_settings().organization.name,'Synthetic Organization')
        self.assertEqual(saved.revision,1)
        with self.assertRaises(ValueError): config.save_configuration(settings,0)

    def test_legacy_migration_keeps_original_backup(self):
        raw=b'{"data_csv_path":"C:/synthetic/example.csv"}'
        (self.root/'settings.json').write_bytes(raw);config.get_settings.cache_clear()
        settings=config.get_settings()
        self.assertEqual(settings.data_csv_path,'C:/synthetic/example.csv')
        self.assertEqual(settings.schema_version,2)
        backups=list((self.root/'configuration-backups').glob('migration-v1-*'))
        self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_bytes(),raw)
        self.assertIn('migrated',config.configuration_notice())

    def test_corruption_and_future_version_are_not_overwritten(self):
        for raw in [b'{invalid',b'{"schema_version":999,"private_field":"retained"}']:
            (self.root/'settings.json').write_bytes(raw);config.get_settings.cache_clear()
            self.assertEqual(config.get_settings().organization.name,'Example Inc.')
            self.assertEqual((self.root/'settings.json').read_bytes(),raw)
            self.assertIn('not been overwritten',config.configuration_notice())
            config.save_configuration(config.get_settings(),0)
            self.assertTrue(any(p.read_bytes()==raw for p in (self.root/'configuration-backups').glob('*')))

    def test_failed_atomic_save_preserves_prior_configuration(self):
        original=config.save_configuration(AppConfig(),0)
        raw=(self.root/'settings.json').read_bytes()
        with patch('config.os.replace',side_effect=OSError('simulated disk failure')):
            with self.assertRaises(OSError): config.save_configuration(original,1)
        self.assertEqual((self.root/'settings.json').read_bytes(),raw)

    def test_portable_exports_redact_paths_records_and_private_identity(self):
        cfg=AppConfig(data_csv_path=str(self.root/'private.csv'))
        cfg.organization.name='Synthetic Private Organization'
        default=export_configuration(cfg)
        self.assertEqual(default['settings']['organization']['name'],'Example Inc.')
        self.assertEqual(default['settings']['data_csv_path'],'')
        self.assertNotIn('cors_origins',default['settings'])
        private=export_configuration(cfg,True)
        self.assertEqual(private['settings']['organization']['name'],'Synthetic Private Organization')
        self.assertEqual(private['settings']['data_csv_path'],'')
        restored=read_portable(PortableConfig.model_validate(private),str(self.root/'local.csv'))
        self.assertEqual(restored.data_csv_path,str(self.root/'local.csv'))

    def test_logo_decode_storage_and_portable_round_trip(self):
        staged=stage_image(self.png())
        cfg=AppConfig(logo_id=staged['logo_id'])
        self.assertIsNotNone(logo_bytes(cfg.logo_id))
        with Image.open(BytesIO(logo_bytes(cfg.logo_id))) as logo:
            self.assertEqual(logo.size,(160,40));self.assertEqual(logo.format,'PNG')
        package=PortableConfig.model_validate(export_configuration(cfg,True))
        self.assertTrue(package.logo_base64)
        (self.root/'branding'/f'{cfg.logo_id}.png').unlink()
        self.assertIsNone(logo_bytes(cfg.logo_id))
        restored=read_portable(package,'')
        self.assertIsNotNone(logo_bytes(restored.logo_id))
        (self.root/'branding'/f'{restored.logo_id}.png').write_bytes(b'invalid')
        self.assertIsNone(logo_bytes(restored.logo_id))

    def test_image_validation_rejects_svg_size_dimensions_and_bad_encoding(self):
        for data in [b'<svg onload="alert(1)"></svg>',b'not an image',b'x'*2_000_001]:
            with self.assertRaises(ValueError): sanitize_image(data)
        output=BytesIO();Image.new('RGB',(4097,1)).save(output,format='PNG')
        with self.assertRaises(ValueError):sanitize_image(output.getvalue())
        package=PortableConfig(settings=AppConfig(),logo_base64='not-valid-base64')
        with self.assertRaises(ValueError):read_portable(package,'')
        with self.assertRaises(ValueError):ModuleOverride(color='url(javascript:alert(1))')
        with self.assertRaises(ValueError):ModuleOverride(icon='UnknownIcon')

    def test_configuration_api_system_theme_reset_and_revision(self):
        cfg=self.client.get('/api/configuration').json()['settings']
        cfg['organization']['name']='Synthetic Demo Organization'
        cfg['organization']['platform']='SAP ECC'
        result=self.client.post('/api/configuration',json=cfg,headers=H)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['settings']['organization']['platform'],'SAP ECC')
        self.assertEqual(self.client.post('/api/configuration',json=cfg,headers=H).status_code,409)
        self.assertEqual(self.client.post('/api/configuration/theme',json={'theme':'dark'},headers=H).status_code,200)
        package=self.client.post('/api/configuration/export?include_private=true',headers=H).json()
        reset=self.client.post('/api/configuration/reset',headers=H)
        self.assertEqual(reset.status_code,200)
        self.assertEqual(reset.json()['settings']['organization']['name'],'Example Inc.')
        restored=self.client.post('/api/configuration/import',json=package,headers=H)
        self.assertEqual(restored.status_code,200,restored.text)
        self.assertEqual(restored.json()['settings']['organization']['name'],'Synthetic Demo Organization')

    def test_missing_current_logo_does_not_prevent_other_settings(self):
        staged=stage_image(self.png())
        cfg=AppConfig(logo_id=staged['logo_id'])
        config.save_configuration(cfg,0)
        (self.root/'branding'/f"{staged['logo_id']}.png").unlink()
        self.assertEqual(self.client.get('/api/branding/logo').status_code,404)
        self.assertEqual(self.client.post('/api/configuration/theme',json={'theme':'dark'},headers=H).status_code,200)

    def test_import_rejects_unknown_fields_local_paths_and_missing_branding(self):
        package=export_configuration(AppConfig())
        package['settings']['data_csv_path']='/private/path.csv'
        self.assertEqual(self.client.post('/api/configuration/import',json=package,headers=H).status_code,400)
        package=export_configuration(AppConfig());package['unknown']='value'
        self.assertEqual(self.client.post('/api/configuration/import',json=package,headers=H).status_code,422)
        cfg=AppConfig(logo_id='a'*64).model_dump()
        self.assertEqual(self.client.post('/api/configuration',json=cfg,headers=H).status_code,400)
        self.assertEqual(self.client.get('/api/branding/logo').status_code,404)
        self.assertEqual(self.client.post('/api/configuration/reset').status_code,403)


class RegistryClassificationTests(unittest.TestCase):
    def profile(self,**kwargs):
        return ClassificationProfile(id='custom',name='Synthetic',mode='custom',
            domains=[Domain(id='finance',label='Example finance',module_id='FI'),Domain(id='supply',label='Example supply',module_id='MM')],**kwargs)

    def test_registry_categories_aliases_parents_icons_and_colors(self):
        self.assertEqual(resolve_module('BASIS'),'BC')
        self.assertEqual(resolve_module('fi_aa'),'FI-AA')
        self.assertEqual(REGISTRY['FI-AA']['parent'],'FI')
        self.assertEqual(REGISTRY['BTP']['category'],'product')
        self.assertIsNone(resolve_module('NOT_A_SAP_AREA'))
        for entry in REGISTRY.values():
            self.assertTrue(entry['color'].startswith('#'))
            self.assertTrue(entry['parent'] is None or entry['parent'] in REGISTRY)
        overridden=module_definition('FI',{'FI':ModuleOverride(display_name='Synthetic accounting',icon='Layers',color='#123456',enabled=False)})
        self.assertEqual(overridden['name'],'Synthetic accounting');self.assertEqual(overridden['icon'],'Layers')
        self.assertFalse(overridden['enabled'])
        self.assertEqual(module_definition('unknown')['id'],'unknown')

    def test_legacy_and_generic_evidence(self):
        legacy=Classifier(ClassificationProfile(id='legacy',name='Legacy',mode='legacy'))
        generic=Classifier(ClassificationProfile(id='generic',name='Generic',mode='generic'))
        self.assertEqual(legacy.classify('DEMO:FI:X','CUSTOM')['module_id'],'CUSTOM')
        self.assertEqual(generic.classify('DEMO:FI:X')['module_id'],'UNCLASSIFIED')
        self.assertEqual(generic.classify('DEMO','BASIS')['module_id'],'BC')
        self.assertEqual(legacy_child_module('DEMO:FI:X'),'FI')
        self.assertEqual(legacy_child_module('OPAQUE','MM - Synthetic child'),'MM')

    def test_priorities_overrides_fallback_and_ambiguity(self):
        p=self.profile(rules=[Rule(id='broad',kind='prefix',pattern='DEMO',domain_id='supply',priority=100),Rule(id='precise',kind='exact',pattern='DEMO_FIN',domain_id='finance',priority=10)],overrides={'EXACT':'finance'},fallback_domain='supply')
        c=Classifier(p)
        self.assertEqual(c.classify('DEMO_FIN')['domain_id'],'finance')
        self.assertEqual(c.classify('EXACT')['domain_id'],'finance')
        self.assertEqual(c.classify('OTHER')['domain_id'],'supply')
        p.rules.append(Rule(id='tie',kind='contains',pattern='FIN',domain_id='supply',priority=10))
        result=Classifier(p).classify('DEMO_FIN')
        self.assertTrue(result['ambiguous']);self.assertEqual(result['module_id'],'UNCLASSIFIED')

    def test_preview_counts_changes_conflicts_and_profile_trace(self):
        p=self.profile(rules=[Rule(id='one',pattern='DEMO',domain_id='finance'),Rule(id='two',pattern='DEMO',domain_id='supply')])
        result=classification_preview(p,[dict(agr_name='DEMO_FIN'),dict(agr_name='OTHER')],{'DEMO_FIN':{'module_id':'FI','domain_id':'finance'}},'DEMO_FIN')
        self.assertEqual(result['ambiguous_matches'],1)
        self.assertEqual(result['unclassified_roles'],2)
        self.assertEqual(result['changed_roles'],1)
        self.assertTrue(result['conflicting_rules']);self.assertEqual(result['profile_version'],1)
        self.assertEqual(len(result['profile_fingerprint']),16)

    def test_reserved_identifiers_are_rejected(self):
        for identifier in ['__proto__','prototype','constructor']:
            with self.assertRaises(ValueError):Domain(id=identifier,label='Synthetic')

    def test_regex_validation_and_timeout(self):
        import time
        with self.assertRaises(ValueError):Classifier(self.profile(rules=[Rule(id='bad',kind='regex',pattern='[',domain_id='finance')]))
        p=self.profile(rules=[Rule(id='bounded',kind='regex',pattern='(a|aa)+$',domain_id='finance')])
        start=time.monotonic()
        with self.assertRaises(ValueError):Classifier(p).classify('a'*500+'!')
        self.assertLess(time.monotonic()-start,0.25)
        with self.assertRaises(ValueError):self.profile(rules=[Rule(id='missing',pattern='DEMO',domain_id='not-defined')])


if __name__=='__main__':unittest.main()
