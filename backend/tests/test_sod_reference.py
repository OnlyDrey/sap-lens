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


def workbook(risks=None, activities=None, formula=False, library=None):
    output = io.BytesIO()
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('xl/workbook.xml', '<workbook xmlns="'+ns+'" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Risks" r:id="r1"/><sheet name="Activities" r:id="r2"/></sheets></workbook>')
        archive.writestr('xl/_rels/workbook.xml.rels', '<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/><Relationship Id="r2" Target="worksheets/sheet2.xml"/></Relationships>')
        for index, header, mapping, values in [(1, 'Risk', reference.RISK, risks or [('R1', 'Reference R1'), ('INACTIVE', 'Inactive reference')]), (2, 'Activity', reference.ACTIVITY, activities or [('A', 'Reference A')])]:
            sheet = etree.Element('worksheet', nsmap={None: ns}); data = etree.SubElement(sheet, 'sheetData')
            content = [[header, *mapping]] + [[key, name, 'Synthetic area', 'Synthetic description', *(['Synthetic impact','Synthetic controls'] if index == 1 else []), 'Synthetic guidance', ''] for key, name in values]
            if library is not None:
                records=library.risks if index==1 else library.activities
                content=[[header,*mapping]]+[[key,*[metadata.get(field,'') for field in mapping.values()]] for key,metadata in sorted(records.items())]
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
        expected={'A':['R1','R2'],'B':['R1'],'C':['R2'],'D':['R3'],'E':['R3']}
        self.assertEqual(found['activities'],{key:dict(origin={},risks=len(risks),risk_ids=risks) for key,risks in expected.items()})
        self.assertEqual(found['active_activities'],sorted(expected))
        self.assertTrue({'a','AA'}.isdisjoint(found['activities']))
        self.assertTrue({'r1','R'}.isdisjoint(found['risks']))
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

    def test_active_reference_status_and_inherited_fields_for_exact_risk_and_activity_ids(self):
        data = rows()
        for row in data:
            if row['RISK'] == 'R1': row['RISK'] = 'F019'
            for field in ('ACTVT1','ACTVT2','ACTIVITY'):
                if row[field] == 'A': row[field] = 'AP01'
        write(self.path, data); self.activate()
        self.assertTrue(reference.status()['installed'])
        self.assertEqual(reference.status()['origin'],'bundled')
        reference.install(workbook(risks=[('F019','Synthetic reference risk'),('INACTIVE','Unused')],activities=[('AP01','Synthetic reference activity')]),0)
        status=reference.status()
        self.assertTrue(status['installed'])
        self.assertEqual((status['matched_risks'],status['matched_activities']),(1,1))
        self.assertEqual(status['unmatched_risks'],['INACTIVE'])
        self.assertIn('R2',status['missing_risks'])
        found=sod_metadata.lookup()
        self.assertEqual(found['risks']['F019']['inherited']['name'],'Synthetic reference risk')
        self.assertEqual(found['activities']['AP01']['inherited']['name'],'Synthetic reference activity')
        saved=metadata_tests.ResolutionTests.local(self,risks={'F019':{'display_name':'Explicit override'}})
        effective=sod_metadata.lookup(saved=saved)['risks']['F019']
        self.assertEqual(effective['name'],'Explicit override')
        self.assertEqual(effective['inherited']['name'],'Synthetic reference risk')
        self.assertEqual(effective['reference']['name'],'Synthetic reference risk')
        self.assertEqual(saved.entries['F019'].metadata.display_name,'Explicit override')
        self.assertNotIn('notes',effective['inherited'])
        # Matrix replacement removes enrichment; retained reference definitions do not activate it.
        write(self.path,rows());self.activate()
        self.assertNotIn('F019',sod_metadata.lookup()['risks'])
        self.assertEqual(reference.status()['matched_risks'],0)

    def test_multipart_reference_upload_uses_the_same_atomic_library_and_body_limits(self):
        with TestClient(create_app(session_token=H['X-SAP-Lens']),base_url='http://127.0.0.1:18743') as client:
            def send(name='reference.xlsx',raw=None,revision='0'):
                return client.post('/api/sod/reference/upload',headers=H,files={'file':(name,workbook() if raw is None else raw,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')},data={'revision':revision})
            response=send()
            self.assertEqual(response.status_code,200,response.text)
            self.assertTrue(response.json()['installed'])
            before=(config.config_dir()/'sod-reference.json').read_bytes()
            self.assertEqual(send(name='../private.xlsx',revision='1').status_code,422)
            self.assertEqual(send(raw=b'invalid',revision='1').status_code,422)
            self.assertEqual(send(raw=workbook(risks=[('R2','Replacement')]),revision='0').status_code,409)
            self.assertEqual(client.post('/api/sod/reference/upload',headers=H,content=b' ' * 2_162_689).status_code,413)
            self.assertEqual((config.config_dir()/'sod-reference.json').read_bytes(),before)

    def test_bundled_defaults_are_available_without_writing_private_data(self):
        value=reference.read()
        self.assertEqual((value.origin,value.library_version,len(value.risks),len(value.activities),len(value.terms)),('bundled','1.0.1',14,14,6))
        self.assertFalse((config.config_dir()/'sod-reference.json').exists())
        self.assertIn('F019',value.risks);self.assertIn('AP01',value.activities)

    def test_completed_defaults_cover_vendor_risks_without_activating_mappings(self):
        value=reference.defaults()
        for key in ('P001','P002','P008'):
            self.assertTrue(all(value.risks[key].get(field) for field in reference.RISK.values()))
        self.assertEqual(value.activities['PR01']['display_name'],'Vendor Master Maintenance')
        self.assertIn('conflicting labels',value.activities['PR01']['notes'])
        self.assertNotIn('tcodes',value.activities['PR01'])
        write(self.path,rows());self.activate()
        before=json.dumps(cache.get_snapshot().sod,sort_keys=True)
        resolved=sod_metadata.lookup()
        self.assertNotIn('P001',resolved['risks'])
        self.assertNotIn('PR01',resolved['active_activities'])
        self.assertEqual(json.dumps(cache.get_snapshot().sod,sort_keys=True),before)

    def test_reset_restores_only_library_and_keeps_local_overrides_and_matrix(self):
        write(self.path,rows());self.activate()
        local=metadata_tests.ResolutionTests.local(self,risks={'R1':{'display_name':'Explicit local guidance'}})
        import sod_catalogue
        sod_catalogue.write(local)
        original=(config.config_dir()/'sod-catalogue.json').read_bytes()
        active=json.dumps(cache.get_snapshot().sod,sort_keys=True)
        reference.install(workbook(),0)
        restored=reference.reset(1)
        self.assertEqual((restored.origin,restored.revision,len(restored.risks)),('bundled',2,14))
        self.assertEqual((config.config_dir()/'sod-catalogue.json').read_bytes(),original)
        self.assertEqual(json.dumps(cache.get_snapshot().sod,sort_keys=True),active)
        self.assertEqual(sod_metadata.lookup()['risks']['R1']['name'],'Explicit local guidance')
        with self.assertRaises(HTTPException):reference.reset(1)

    def test_existing_custom_library_survives_upgrade_and_missing_default_resource_is_safe(self):
        custom=reference.install(workbook(),0)
        before=(config.config_dir()/'sod-reference.json').read_bytes()
        with patch.object(reference,'default_path',return_value=self.root/'missing-resource.json'):
            self.assertEqual(reference.read().digest,custom.digest)
            self.assertFalse(reference.status()['defaults_available'])
            with self.assertRaises(HTTPException) as error:reference.reset(custom.revision)
            self.assertEqual(error.exception.status_code,503)
        self.assertEqual((config.config_dir()/'sod-reference.json').read_bytes(),before)

    def test_frozen_windows_resource_path_uses_meipass(self):
        import sys
        with patch.object(sys,'frozen',True,create=True),patch.object(sys,'_MEIPASS',str(self.root),create=True):
            self.assertEqual(reference.default_path(),self.root/'resources/reference-defaults.json')

    def test_bundled_records_round_trip_through_the_real_workbook_importer(self):
        library=reference.defaults()
        parsed=reference.parse(workbook(library=library))
        self.assertEqual(parsed.risks,library.risks)
        self.assertEqual(parsed.activities,library.activities)
        self.assertEqual(set(parsed.risks)&{'P001','P002','P008'},{'P001','P002','P008'})
        self.assertEqual(parsed.activities['PR01']['display_name'],'Vendor Master Maintenance')
        self.assertEqual(library.library_version,'1.0.1')

    def test_shipped_template_matches_its_canonical_generator(self):
        from pathlib import Path
        import runpy
        script=Path(__file__).resolve().parents[2]/'scripts/reference-template.py'
        target=self.root/'generated-template.xlsx'
        runpy.run_path(str(script))['generate'](target)
        with zipfile.ZipFile(target) as generated,zipfile.ZipFile(reference.default_path().with_name('sod-reference-template.xlsx')) as shipped:
            self.assertEqual(set(generated.namelist()),set(shipped.namelist()))
            for name in generated.namelist():self.assertEqual(generated.read(name),shipped.read(name))
        parsed=reference.parse(target.read_bytes())
        self.assertEqual(set(parsed.risks),{'R_EXAMPLE'})
        self.assertEqual(set(parsed.activities),{'ACT_EXAMPLE'})

    def test_repository_template_uses_real_schema_and_fixed_download(self):
        raw=reference.default_path().with_name('sod-reference-template.xlsx').read_bytes()
        parsed=reference.parse(raw)
        self.assertEqual(set(parsed.risks),{'R_EXAMPLE'})
        self.assertEqual(set(parsed.activities),{'ACT_EXAMPLE'})
        with TestClient(create_app(session_token=H['X-SAP-Lens']),base_url='http://127.0.0.1:18743') as client:
            response=client.get('/api/sod/reference/template',headers=H)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.content,raw)
            self.assertIn('sap-lens-sod-reference-template.xlsx',response.headers['content-disposition'])
