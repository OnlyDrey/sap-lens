"""Synthetic workbooks only; reference data cannot activate access or overwrite decisions."""
import base64
import io
import json
import zipfile
from unittest.mock import patch
from lxml import etree
from fastapi import HTTPException
from test_sod_metadata import Case, rows, write, H
import test_sod_metadata as metadata_tests
from fastapi.testclient import TestClient
from main import create_app
import sod_reference as reference
import sod_metadata
import config
import cache


def workbook(risks=None, activities=None, formula=False):
    output = io.BytesIO()
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('xl/workbook.xml', '<workbook xmlns="'+ns+'" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Risks" r:id="r1"/><sheet name="Activities" r:id="r2"/></sheets></workbook>')
        archive.writestr('xl/_rels/workbook.xml.rels', '<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/><Relationship Id="r2" Target="worksheets/sheet2.xml"/></Relationships>')
        for index, header, mapping, values in [(1, 'Risk', reference.RISK, risks or [('R1', 'Reference R1'), ('INACTIVE', 'Inactive reference')]), (2, 'Activity', reference.ACTIVITY, activities or [('A', 'Reference A')])]:
            sheet = etree.Element('worksheet', nsmap={None: ns}); data = etree.SubElement(sheet, 'sheetData')
            content = [[header, *mapping]] + [[key, name, 'Synthetic area', 'Synthetic description', *(['Synthetic impact','Synthetic controls'] if index == 1 else []), 'Synthetic guidance', ''] for key, name in values]
            for number, values in enumerate(content, 1):
                row = etree.SubElement(data, 'row')
                for column, value in enumerate(values):
                    cell = etree.SubElement(row, 'c', r=f'{chr(65+column)}{number}', t='inlineStr')
                    etree.SubElement(etree.SubElement(cell, 'is'), 't').text = value
                    if formula and number == 2 and column == 1:
                        etree.SubElement(cell, 'f').text = '1+1'
            archive.writestr(f'xl/worksheets/sheet{index}.xml', etree.tostring(sheet))
    return output.getvalue()


class ReferenceTests(Case):
    def test_parser_exact_ids_duplicates_formula_and_invalid_archive(self):
        parsed = reference.parse(workbook())
        self.assertEqual(set(parsed.risks), {'R1', 'INACTIVE'})
        self.assertEqual(parsed.risks['R1']['mitigating_controls_en'], 'Synthetic controls')
        for raw in [b'not xlsx', b'', workbook(risks=[('R1', 'One'), ('R1', 'Two')]), workbook(formula=True), workbook(risks=[('', 'No ID')])]:
            with self.assertRaises(ValueError): reference.parse(raw)

    def test_atomic_reimport_stale_revision_and_failed_write(self):
        first = reference.install(workbook(), 0)
        self.assertEqual(reference.install(workbook(), 1).revision, 1)
        original = (config.config_dir() / 'sod-reference.json').read_bytes()
        for raw, revision, code in [(b'invalid', 1, 422), (workbook(risks=[('R2','New')]), 0, 409)]:
            with self.assertRaises(HTTPException) as error: reference.install(raw, revision)
            self.assertEqual(error.exception.status_code, code)
        with patch.object(reference, 'atomic_write', side_effect=OSError):
            with self.assertRaises(HTTPException): reference.install(workbook(risks=[('R2','New')]), 1)
        self.assertEqual((config.config_dir() / 'sod-reference.json').read_bytes(), original)
        self.assertEqual(reference.read().digest, first.digest)

    def test_precedence_active_scope_coverage_and_frozen_history(self):
        write(self.path, rows()); self.activate()
        snapshot = cache.get_snapshot()
        baseline = json.dumps(snapshot.sod, sort_keys=True)
        reference.install(workbook(), 0)
        saved = metadata_tests.ResolutionTests.local(self, risks={'R1': {'display_name': 'Local override'}})
        found = sod_metadata.lookup(snapshot, saved)
        self.assertEqual(found['risks']['R1']['name'], 'Local override')
        self.assertEqual(found['risks']['R1']['origin']['description'], 'reference')
        self.assertNotIn('INACTIVE', found['risks'])
        self.assertEqual(sod_metadata.resolve('Imported', '', 'Reference')['origin'], 'imported')
        self.assertEqual(sod_metadata.resolve('Imported', 'Local', 'Reference')['origin'], 'local')
        self.assertEqual(sod_metadata.resolve('', '', 'Reference')['origin'], 'reference')
        coverage = sod_metadata.coverage(snapshot, saved)
        self.assertEqual(coverage['reference']['unmatched_risks'], ['INACTIVE'])
        self.assertEqual(next(row for row in coverage['indicators'] if row['id']=='risk_names')['local_fallback'], 1)
        frozen = sod_metadata.frozen(snapshot, saved, ['R1'])
        reference.install(workbook(risks=[('R1','Changed')]), 1)
        self.assertEqual(frozen['risks']['R1']['description'], 'Synthetic description')
        self.assertEqual(frozen['source']['reference']['revision'], 1)
        self.assertEqual(json.dumps(snapshot.sod, sort_keys=True), baseline)
        self.assertEqual(saved.entries['R1'].metadata.display_name, 'Local override')

    def test_api_validates_and_preserves_private_storage(self):
        with TestClient(create_app(session_token=H['X-SAP-Lens']), base_url='http://127.0.0.1:18743') as client:
            response = client.put('/api/sod/reference', headers=H, json={'expected_revision': 0, 'workbook_base64': base64.b64encode(workbook()).decode()})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['risks'], 2)
            self.assertEqual(client.get('/api/sod/reference', headers=H).json()['revision'], 1)
            self.assertEqual(client.put('/api/sod/reference', headers=H, json={'expected_revision':1,'workbook_base64':'!'}).status_code, 422)
            self.assertEqual(reference.read().revision, 1)
            self.assertEqual(client.put('/api/sod/reference', headers=H, content=b' ' * 2_800_513).status_code, 413)
            self.assertEqual(reference.read().revision, 1)

    def test_exact_case_and_prefix_ids_do_not_enrich_or_activate(self):
        write(self.path, rows()); self.activate()
        reference.install(workbook(risks=[('r1','Lower case'),('R','Prefix')], activities=[('a','Lower activity'),('AA','Longer activity')]), 0)
        found = sod_metadata.lookup(cache.get_snapshot())
        self.assertNotIn('name', found['risks']['R1'])
        self.assertEqual(found['activities'], {})
        coverage = sod_metadata.coverage(cache.get_snapshot())['reference']
        self.assertEqual((coverage['matched_risks'], coverage['matched_activities']), (0, 0))

    def test_concurrent_replacements_have_one_winner_and_corrupt_storage_is_preserved(self):
        from concurrent.futures import ThreadPoolExecutor
        def save(name):
            try:
                return reference.install(workbook(risks=[('R1', name)]), 0).revision
            except HTTPException as error:
                return error.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(save, ['First', 'Second'])), [1, 409])
        target = config.config_dir() / 'sod-reference.json'
        target.write_bytes(b'not json')
        with self.assertRaises(HTTPException): reference.install(workbook(), 1)
        self.assertEqual(target.read_bytes(), b'not json')
