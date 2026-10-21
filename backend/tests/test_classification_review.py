"""Executed synthetic profile comparisons, preview fidelity and saved-color safety."""
import csv
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cache
import config
from classification import Classifier, classification_preview
from config_models import AppConfig, ClassificationProfile, Domain, ModuleOverride, Rule
from fastapi.testclient import TestClient
from main import create_app
from module_registry import REGISTRY, discovered_color, module_definition, registry_list
from portable_config import PortableConfig, export_configuration, read_portable
from routers.comparison import CompareRequest, compare_roles


def custom_profile():
    return ClassificationProfile(id='custom', name='Synthetic business grouping', mode='custom',
        domains=[Domain(id='finance',label='Accounts payable',module_id='FI'),
                 Domain(id='buying',label='Procurement',module_id='MM'),
                 Domain(id='technical',label='Technical operations',module_id='BC')],
        rules=[Rule(id='pay',pattern='Z_DEMO_PAY',domain_id='finance'),
               Rule(id='buyer',pattern='Z_DEMO_BUY',domain_id='buying'),
               Rule(id='local',kind='exact',pattern='Z_DEMO_LOCAL',domain_id='finance'),
               Rule(id='fi-child',pattern='Z:FI:',domain_id='finance'),
               Rule(id='mm-child',pattern='Z:MM:',domain_id='buying'),
               Rule(id='bc-child',pattern='Z:BC:',domain_id='technical')],
        overrides={'Z_DEMO_BASIS':'technical'})


class ClassificationReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR':str(self.root), 'DATA_CSV_PATH':''})
        self.environment.start(); self.addCleanup(self.environment.stop)
        config.get_settings.cache_clear(); cache.clear_cache()
        self.addCleanup(config.get_settings.cache_clear); self.addCleanup(cache.clear_cache)
        self.path = self.root/'synthetic.csv'
        with self.path.open('w',newline='') as output:
            writer = csv.writer(output)
            writer.writerow(['FUNCTION_KEY','AGR_NAME','TEXT','CHILD_AGR','CHILD_AGR_TEXT','TCODE'])
            writer.writerows([
                ['FI','Z_DEMO_PAYABLES','Vendor invoices','Z:FI:AP_POST','FI - Post invoice','FB60'],
                ['FI','Z_DEMO_BUYER','Procurement composite','Z:MM:PURCH','MM - Purchase','ME21N'],
                ['LOCAL_FIN','Z_DEMO_LOCAL','Local finance','Z:FI:DISPLAY','FI - Display','FB03'],
                ['','Z_DEMO_BASIS','Basis audit','Z:BC:AUDIT','BC - Audit','SUIM'],
                ['MM','Z_DEMO_MIXED','Mixed composite','Z:MM:DISPLAY','MM - Display','ME23N'],
                ['FI','Z_DEMO_MIXED','Mixed composite','Z:FI:DISPLAY','FI - Display','FB03'],
            ])

    def test_profiles_change_labels_but_preserve_roles_assignments_and_comparison_math(self):
        profiles = [ClassificationProfile(id=mode,name=mode,mode=mode) for mode in ('generic','legacy')] + [custom_profile()]
        cores, overlaps, states = [], [], {}
        for profile in profiles:
            state = cache.build_cache(str(self.path), AppConfig(classification_profiles=[profile],active_classification=profile.id))
            states[profile.id] = state; cache._cache = state
            cores.append({name: ([(child.child_agr,[tc.model_dump() for tc in child.tcodes]) for child in role.single_roles],
                                 [item.model_dump() for item in role.relationships]) for name,role in state.roles.items()})
            comparison = compare_roles(CompareRequest(roles=['Z_DEMO_LOCAL','Z_DEMO_MIXED']))
            overlaps.append(([tc.tcode for tc in comparison.shared_tcodes],[sr.child_agr for sr in comparison.shared_single_roles]))
            self.assertEqual([state.import_report[key] for key in ('unique_transactions','transaction_assignments','relationship_count')],[5,6,6])
        self.assertEqual(cores[0],cores[1]); self.assertEqual(cores[1],cores[2])
        self.assertEqual(overlaps,[(['FB03'],['Z:FI:DISPLAY'])]*3)
        self.assertEqual([states[mode].roles['Z_DEMO_BUYER'].function_key for mode in ('generic','legacy','custom')],['FI','FI','MM'])
        self.assertEqual([states[mode].roles['Z_DEMO_LOCAL'].function_key for mode in ('generic','legacy','custom')],['UNCLASSIFIED','LOCAL_FIN','FI'])
        self.assertEqual([states[mode].roles['Z_DEMO_PAYABLES'].single_roles[0].function_key for mode in ('generic','legacy','custom')],['UNCLASSIFIED','FI','FI'])

    def test_preview_preserves_multi_source_conflict_policy_without_fake_rule_conflicts(self):
        profile = ClassificationProfile(id='generic',name='Generic SAP')
        result = classification_preview(profile,[{'agr_name':'Z_DEMO_MIXED','source_modules':['FI','MM']}],test_role='Z_DEMO_MIXED')
        self.assertEqual(result['unclassified_roles'],1); self.assertEqual(result['ambiguous_matches'],1)
        self.assertEqual(result['conflicting_rules'],[])
        self.assertEqual(result['test_result']['module_id'],'UNCLASSIFIED')
        self.assertTrue(result['test_result']['source_conflict'])
        self.assertEqual(result['test_result']['source_modules'],['FI','MM'])

    def test_preview_reasons_cover_csv_rules_overrides_fallback_and_no_match(self):
        profile = custom_profile()
        for role, source, expected in [('Z_DEMO_PAYABLES','FI','rule'),('Z_DEMO_BASIS',None,'override'),('Z_OTHER','FI','csv'),('Z_OTHER',None,'unmatched')]:
            result = classification_preview(profile,[],test_role=role,test_source_module=source)['test_result']
            self.assertEqual(result['resolution'],expected)
        profile.fallback_domain = 'buying'
        result = classification_preview(profile,[],test_role='Z_OTHER',test_source_module='FI')['test_result']
        self.assertEqual((result['module_id'],result['resolution'],result['is_fallback']),('MM','fallback',True))
        # The production classifier still has exactly the same fallback override semantics.
        self.assertEqual(Classifier(profile).classify('Z_OTHER','FI')['module_id'],'MM')

    def test_api_preview_uses_loaded_csv_evidence_and_does_not_publish_or_save(self):
        with TestClient(create_app(),base_url='http://127.0.0.1:18743') as client:
            cache.load_cache(str(self.path))
            before = cache.get_snapshot()
            saved = client.get('/api/configuration').json()['settings']
            headers = {'X-SAP-Lens':'1'}
            body = {'profile':{'id':'generic','name':'Generic SAP'},'test_role':'Z_DEMO_PAYABLES'}
            response = client.post('/api/classification/preview',json=body,headers=headers)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['test_result']['module_id'],'FI')
            self.assertEqual(response.json()['test_result']['resolution'],'csv')
            response = client.post('/api/classification/preview',json={**body,'test_role':'Z_EXAMPLE','test_source_module':'MM'},headers=headers)
            self.assertEqual(response.json()['test_result']['module_id'],'MM')
            self.assertEqual(client.post('/api/classification/preview',json={**body,'test_source_module':'x'*101},headers=headers).status_code,422)
            self.assertIs(cache.get_snapshot(),before)
            self.assertEqual(client.get('/api/configuration').json()['settings'],saved)

    def test_profiles_and_explicit_colors_survive_settings_reload_and_private_export(self):
        profile = custom_profile()
        saved = AppConfig(classification_profiles=[profile],active_classification='custom',module_overrides={'FI':ModuleOverride(color='#3d4d8a',icon='Package',enabled=False)})
        config.save_configuration(saved,0); config.get_settings.cache_clear()
        loaded = config.get_settings()
        self.assertEqual(loaded.active_classification,'custom')
        self.assertEqual(loaded.classification_profiles,[profile])
        self.assertEqual(module_definition('FI',loaded.module_overrides)['color'],'#3d4d8a')
        self.assertFalse(module_definition('FI',loaded.module_overrides)['enabled'])
        portable = PortableConfig.model_validate(export_configuration(loaded,True))
        restored = read_portable(portable,'')
        self.assertEqual(restored.classification_profiles,[profile])
        self.assertEqual(restored.module_overrides,loaded.module_overrides)

    def test_area_defaults_are_varied_stable_and_do_not_replace_custom_values(self):
        items = {item['id']:item for item in registry_list()}
        self.assertEqual(len(items),49)
        self.assertGreaterEqual(len({item['color'] for item in items.values()}),40)
        for code in ['FI','CO','MM','SD','WM','EWM','PP','PM','QM','BW','BTP','ABAP']:
            self.assertEqual(items[code]['color'],module_definition(code)['color'])
            self.assertEqual(items[code]['icon'],REGISTRY[code]['icon'])
        self.assertEqual(discovered_color('local_fin'),discovered_color(' LOCAL-FIN '))
        self.assertEqual(discovered_color('X'*256+'Y'*100_000),discovered_color('X'*256))
        self.assertEqual(module_definition('LOCAL_FIN')['color'],discovered_color('LOCAL_FIN'))
        self.assertEqual(module_definition('FI',{'FI':ModuleOverride(color='#112233')})['color'],'#112233')
        effective = next(item for item in registry_list({'FI':ModuleOverride(color='#112233')}) if item['id'] == 'FI')
        self.assertEqual(effective['color'],'#112233')
        self.assertEqual(effective['default_color'],REGISTRY['FI']['color'])
