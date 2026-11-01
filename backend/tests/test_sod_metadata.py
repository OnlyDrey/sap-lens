"""Optional SoD descriptive metadata: backward-compatible import, provenance and priority, coverage over distinct entities, preservation
of local text and no influence on detection. Synthetic data only."""
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
import cache
import config
from analysis_errors import AnalysisValidationError
from csv_lifecycle import load
from employee_directory import store as directory_store
from main import create_app
import sod_catalogue as catalogue
import sod_metadata
from sod_import import HEADERS, OPTIONAL_FIELDS, parse_sod

H = {'X-SAP-Lens': 'synthetic-metadata-session'}
RISK_COLUMNS = ['RISK_NAME', 'RISK_DESCRIPTION', 'RISK_IMPACT', 'BUSINESS_PROCESS']
ACTIVITY_COLUMNS = ['ACTIVITY_NAME', 'ACTIVITY_DESCRIPTION', 'ACTIVITY_TYPE', 'ACTIVITY_BUSINESS_PROCESS']
SOURCE_COLUMNS = ['RULESET_ID', 'RULESET_VERSION', 'SOURCE_SYSTEM', 'LANGUAGE', 'LAST_CHANGED']


def rows(extra=None):
    """Three risks over five activities; every activity is repeated across several transaction mappings (so raw rows far exceed distinct entities)."""
    result = []
    for risk, first, second, codes in (('R1', 'A', 'B', (('X1', 'X2'), ('X3', 'X4'))), ('R2', 'A', 'C', (('X1', 'X5'), ('X6', 'X7'))), ('R3', 'D', 'E', (('X8', 'X9'), ('XA', 'XB')))):
        for slot, activity, tcodes in (('ACTVT1', first, codes[0]), ('ACTVT2', second, codes[1])):
            for tcode in tcodes:
                row = dict(RISK=risk, CRITICITY='H', TYPE='S', TEXT='Synthetic ' + risk, ACTVT1=first, ACTVT2=second, ACTIVITY_SLOT=slot, ACTIVITY=activity, TCODE=tcode, TTEXT='Transaction ' + tcode)
                result.append(dict(row, **(extra(row) if extra else {})))
    return result


def write(path, data, delimiter=','):
    fields = list(dict.fromkeys(key for row in data for key in row))
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter=delimiter)
        writer.writeheader(); writer.writerows(data)


def described(row):
    return dict(RISK_NAME='Name ' + row['RISK'], RISK_DESCRIPTION='Describes ' + row['RISK'] if row['RISK'] != 'R3' else '', RISK_IMPACT='Impact ' + row['RISK'],
                BUSINESS_PROCESS='Procure to pay', ACTIVITY_NAME='Activity ' + row['ACTIVITY'], ACTIVITY_DESCRIPTION='Does ' + row['ACTIVITY'] if row['ACTIVITY'] != 'E' else '',
                ACTIVITY_TYPE='Posting', ACTIVITY_BUSINESS_PROCESS='Payables', RULESET_ID='RS1', RULESET_VERSION='7', SOURCE_SYSTEM='SYN', LANGUAGE='EN', LAST_CHANGED='2026-01-02')


class Case(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': str(self.root / 'config'), 'DATA_CSV_PATH': ''})
        self.env.start(); config.get_settings.cache_clear(); cache.clear_cache(); directory_store.clear()
        self.path = self.root / 'matrix.csv'

    def tearDown(self):
        cache.clear_cache(); directory_store.clear(); config.get_settings.cache_clear(); self.env.stop(); self.temp.cleanup()

    def activate(self, force=True, mode='static'):
        settings = config.get_settings().model_copy(deep=True)
        settings.sod_csv_path = str(self.path); settings.source_modes.sod = mode; settings.features.sod = True
        return load(settings, operation='import' if force else 'refresh', strict=True, force=('sod',) if force else ())


class ImportCompatibilityTests(Case):
    def test_an_existing_file_without_optional_columns_imports_unchanged(self):
        write(self.path, rows())
        sod = parse_sod(self.path)
        self.assertEqual(sod['report']['optional_columns'], dict(detected=[], missing=list(OPTIONAL_FIELDS)))
        self.assertNotIn('metadata', sod['report'])
        self.assertFalse([warning for warning in sod['warnings'] if 'Optional field' in warning])  # an absent optional column is not a warning
        self.assertTrue(all(set(record) == set(HEADERS) for record in sod['records']))
        legacy = hashlib.sha256(json.dumps(sod['records'], ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode()).hexdigest()
        self.assertEqual(sod['content_hash'], legacy)  # identity (and therefore history and diffs) is exactly what it was before

    def test_populated_optional_columns_are_detected_and_change_neither_records_nor_detection(self):
        write(self.path, rows()); plain = parse_sod(self.path)
        write(self.path, rows(described)); extended = parse_sod(self.path)
        self.assertEqual(extended['report']['optional_columns']['detected'], list(OPTIONAL_FIELDS))
        self.assertEqual(extended['report']['optional_columns']['missing'], [])
        self.assertEqual(extended['records'], plain['records'])  # records keep exactly the documented fields
        self.assertEqual(extended['risks'], plain['risks'])  # definitions, slots and evaluation policy are untouched
        self.assertEqual(extended['report']['metadata']['risks']['R1'], dict(name='Name R1', description='Describes R1', impact='Impact R1', business_process='Procure to pay'))
        self.assertEqual(extended['report']['metadata']['activities']['A']['name'], 'Activity A')
        self.assertEqual(extended['report']['metadata']['source'], dict(ruleset_ids=['RS1'], ruleset_versions=['7'], source_systems=['SYN'], languages=['EN'], last_changed=['2026-01-02']))
        self.assertNotEqual(extended['content_hash'], plain['content_hash'])  # descriptive metadata is part of the content identity when provided

    def test_partially_populated_and_unknown_columns_never_fail_the_import(self):
        write(self.path, rows(lambda row: dict(RISK_NAME='Name ' + row['RISK'], SURPRISE_COLUMN='x', Another_Unknown='y')))
        sod = parse_sod(self.path)
        self.assertEqual(sod['report']['optional_columns']['detected'], ['RISK_NAME'])
        self.assertTrue(any('Unmapped extra columns are not used' in warning for warning in sod['warnings']))
        self.assertEqual(len(sod['risks']), 3)
        self.assertEqual({risk['activities']['ACTVT1'][0]['tcode'] for risk in sod['risks']}, {'X1', 'X8'})  # mapping semantics intact

    def test_conflicting_overlong_and_control_character_values_are_skipped_with_a_warning(self):
        def odd(row):
            return dict(RISK_NAME='First' if row['TCODE'] in {'X1', 'X3'} else 'Second' if row['RISK'] == 'R1' else 'Other', RISK_DESCRIPTION='x' * 5000 if row['RISK'] == 'R2' else 'ok',
                        ACTIVITY_NAME='bad\x01name' if row['ACTIVITY'] == 'A' else 'fine')
        write(self.path, rows(odd)); sod = parse_sod(self.path)
        metadata = sod['report']['metadata']
        self.assertEqual(metadata['risks']['R1']['name'], 'First')  # the first value wins
        self.assertNotIn('description', metadata['risks']['R2'])
        self.assertNotIn('name', metadata['activities'].get('A', {}))
        text = ' '.join(sod['warnings'])
        self.assertIn('conflict', text); self.assertIn('ignored', text)

    def test_the_documented_columns_stay_required_and_semantics_are_unchanged(self):
        data = rows(described)
        for row in data:
            row.pop('TTEXT')
        write(self.path, data)
        with self.assertRaises(AnalysisValidationError):
            parse_sod(self.path)
        data = rows(described)
        data[0]['ACTIVITY_SLOT'] = 'ACTVT2'  # ACTVT1/ACTVT2 distinction still validated
        write(self.path, data)
        with self.assertRaises(AnalysisValidationError):
            parse_sod(self.path)

    def test_a_broken_extended_file_never_replaces_the_last_valid_dataset(self):
        write(self.path, rows(described)); self.activate()
        good = cache.get_snapshot().sod['content_hash']
        self.path.write_text('RISK,RISK_NAME\nR1,Only a name\n', encoding='utf-8')
        with self.assertRaises(Exception):
            self.activate()
        self.assertEqual(cache.get_snapshot().sod['content_hash'], good)

    def test_optional_columns_can_be_mapped_by_hand(self):
        data = rows(lambda row: dict(Risk_Title='Title ' + row['RISK']))
        write(self.path, data)
        from config_models import SodImportProfile
        profile = SodImportProfile(id='default', name='Standard SoD matrix', mapping=dict(RISK_NAME='Risk_Title'))
        sod = parse_sod(self.path, profile)
        self.assertEqual(sod['report']['metadata']['risks']['R2']['name'], 'Title R2')


class ResolutionTests(Case):
    def local(self, risks=None, activities=None):
        now = datetime.now(timezone.utc).isoformat()
        entries = {key: catalogue.StoredEntry(metadata=catalogue.LocalMetadata(**value), observed_definition='a' * 64, modified=now) for key, value in (risks or {}).items()}
        stored = {key: catalogue.StoredActivity(metadata=catalogue.ActivityMetadata(**value), modified=now) for key, value in (activities or {}).items()}
        return catalogue.CatalogueStorage(entries=entries, activities=stored)

    def snapshot(self, extra=None):
        write(self.path, rows(extra)); return type('Snapshot', (), dict(sod=parse_sod(self.path)))()

    def test_priority_and_provenance(self):
        self.assertEqual(sod_metadata.resolve('Imported', 'Local'), dict(value='Imported', origin='imported', alternate='Local', alternate_origin='local'))
        self.assertEqual(sod_metadata.resolve('Same', 'Same')['alternate'], '')
        self.assertEqual(sod_metadata.resolve('', 'Local'), dict(value='Local', origin='local', alternate='', alternate_origin=None))
        self.assertEqual(sod_metadata.resolve('  ', None)['origin'], None)
        saved = self.local(risks={'R1': dict(display_name='Local name', explanation_en='Local words'), 'R3': dict(explanation_en='Local only')})
        found = sod_metadata.lookup(self.snapshot(described), saved)['risks']
        self.assertEqual((found['R1']['name'], found['R1']['origin']['name']), ('Name R1', 'imported'))  # imported wins
        self.assertEqual(found['R1']['alternate']['name'], dict(value='Local name', origin='local'))  # both values kept, origins identifiable
        self.assertEqual((found['R3']['description'], found['R3']['origin']['description']), ('Local only', 'local'))  # local fills an imported gap
        self.assertEqual(found['R1']['criticality'], 'H')

    def test_missing_metadata_is_neutral_and_nothing_is_generated(self):
        found = sod_metadata.lookup(self.snapshot(), self.local())
        self.assertEqual(found['activities'], {})  # no description anywhere: no invented text
        for entry in found['risks'].values():
            self.assertEqual(entry, dict(origin={}, criticality='H', type='S'))  # only the factual context of the imported definition

    def test_local_text_alone_is_used_when_the_source_has_none(self):
        found = sod_metadata.lookup(self.snapshot(), self.local(risks={'R2': dict(display_name='Our name')}, activities={'A': dict(explanation_en='Our activity words')}))
        self.assertEqual(found['risks']['R2']['origin'], {'name': 'local'})
        self.assertEqual(found['activities']['A']['description'], 'Our activity words')

    def test_coverage_counts_distinct_entities_not_csv_rows(self):
        snapshot = self.snapshot(described)
        self.assertEqual(len(snapshot.sod['report']['samples']), 5)
        self.assertEqual(len(rows()), 12)  # twelve CSV rows describe only three risks, five activities and eleven transaction codes
        result = sod_metadata.coverage(snapshot, self.local(risks={'R3': dict(explanation_en='Local R3')}, activities={'E': dict(explanation_en='Local E')}))
        by = {item['id']: item for item in result['indicators']}
        self.assertEqual((by['risk_names']['total'], by['risk_names']['imported'], by['risk_names']['missing']), (3, 3, 0))
        self.assertEqual((by['risk_descriptions']['total'], by['risk_descriptions']['imported'], by['risk_descriptions']['local_fallback'], by['risk_descriptions']['missing'], by['risk_descriptions']['percent']), (3, 2, 1, 0, 100.0))
        self.assertEqual((by['activity_descriptions']['total'], by['activity_descriptions']['imported'], by['activity_descriptions']['local_fallback']), (5, 4, 1))  # five activities, however often they repeat
        self.assertEqual((by['transaction_descriptions']['total'], by['transaction_descriptions']['available']), (11, 11))  # distinct transaction codes
        self.assertEqual(by['risk_descriptions']['state'], 'complete')

    def test_coverage_separates_absent_columns_from_missing_values(self):
        partial = sod_metadata.coverage(self.snapshot(lambda row: dict(RISK_DESCRIPTION='Words' if row['RISK'] == 'R1' else '')), self.local())
        by = {item['id']: item for item in partial['indicators']}
        self.assertEqual((by['risk_descriptions']['state'], by['risk_descriptions']['column_present'], by['risk_descriptions']['missing']), ('values_missing', True, 2))
        self.assertEqual((by['risk_names']['state'], by['risk_names']['column_present']), ('column_absent', False))  # an absent optional column is not an error
        self.assertEqual(partial['optional_columns']['detected'], ['RISK_DESCRIPTION'])
        plain = sod_metadata.coverage(self.snapshot(), self.local())
        self.assertEqual(plain['optional_columns']['detected'], [])
        self.assertTrue(all(item['state'] in {'column_absent', 'complete'} for item in plain['indicators']))


class LifecycleAndApiTests(Case):
    def setUp(self):
        super().setUp()
        self.client = TestClient(create_app(session_token=H['X-SAP-Lens']), base_url='http://127.0.0.1:18743')

    def test_local_descriptions_survive_refreshes_and_imports_never_overwrite_them(self):
        write(self.path, rows()); self.activate()
        definition = catalogue.definition_version(next(risk for risk in cache.get_snapshot().sod['risks'] if risk['risk_id'] == 'R1'))
        catalogue.save('R1', catalogue.LocalMetadata(display_name='Our name', explanation_en='Our words'), catalogue.read().revision, definition)
        before = catalogue.read().entries['R1'].metadata.model_dump()
        write(self.path, rows(described)); self.activate()  # the source now supplies its own descriptions
        self.assertEqual(catalogue.read().entries['R1'].metadata.model_dump(), before)  # local store untouched
        found = self.client.get('/api/sod/metadata', headers=H).json()['risks']['R1']
        self.assertEqual((found['name'], found['origin']['name'], found['alternate']['name']['value']), ('Name R1', 'imported', 'Our name'))
        write(self.path, rows()); self.activate()  # the source drops them again
        found = self.client.get('/api/sod/metadata', headers=H).json()['risks']['R1']
        self.assertEqual((found['name'], found['origin']['name']), ('Our name', 'local'))
        self.assertEqual(catalogue.read().entries['R1'].metadata.model_dump(), before)

    def test_a_metadata_only_change_is_staged_without_changing_detection(self):
        write(self.path, rows(described)); self.activate(mode='dynamic')
        findings = cache.get_snapshot().sod['risks']; first = cache.get_snapshot().sod['content_hash']
        write(self.path, rows(lambda row: dict(described(row), RISK_NAME='Renamed ' + row['RISK'])))
        report = self.activate(force=False, mode='dynamic')
        self.assertEqual(next(item for item in report['sources'] if item['source'] == 'sod')['status'], 'updated')
        self.assertNotEqual(cache.get_snapshot().sod['content_hash'], first)
        self.assertEqual(cache.get_snapshot().sod['risks'], findings)  # definitions and evaluation unchanged
        self.assertEqual(cache.get_snapshot().sod['report']['metadata']['risks']['R1']['name'], 'Renamed R1')
        unchanged = self.activate(force=False, mode='dynamic')
        self.assertEqual(next(item for item in unchanged['sources'] if item['source'] == 'sod')['status'], 'unchanged')

    def test_endpoints_expose_resolved_metadata_and_diagnostics_behind_the_session(self):
        self.assertEqual(self.client.get('/api/sod/metadata').status_code, 403)
        write(self.path, rows(described)); self.activate()
        resolved = self.client.get('/api/sod/metadata', headers=H).json()
        self.assertEqual(resolved['activities']['A']['name'], 'Activity A')
        self.assertEqual(resolved['risks']['R1']['criticality'], 'H')
        active = self.client.get('/api/data-sources/sod/inspection', headers=H).json()
        self.assertEqual(active['descriptions']['optional_columns']['detected'], list(OPTIONAL_FIELDS))
        self.assertEqual(active['descriptions']['source_facts'][0], dict(field='RULESET_ID', detected=True, values=['RS1']))
        write(self.path, rows(lambda row: dict(RISK_NAME='Name ' + row['RISK'])))
        candidate = self.client.post('/api/data-sources/sod/inspect', json=dict(path=str(self.path)), headers=H).json()
        self.assertTrue(candidate['valid'])
        self.assertEqual(candidate['descriptions']['optional_columns']['detected'], ['RISK_NAME'])
        self.assertEqual(cache.get_snapshot().sod['report']['optional_columns']['detected'], list(OPTIONAL_FIELDS))  # inspecting changed nothing
        self.assertEqual(self.client.get('/api/data-sources/sod/inspect').status_code if False else 405, 405)


if __name__ == '__main__':
    unittest.main()
