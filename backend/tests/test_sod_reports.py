"""Editable DOCX/PDF rendering, frozen models and untrusted-content boundaries."""
import copy
from datetime import date
from io import BytesIO
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import HTTPException
from fastapi.testclient import TestClient
import sod_periods as periods
import sod_reports as reports
from main import create_app
import test_sod_analysis_api as fixtures
H={'X-SAP-Lens':'synthetic-report-session'}

class SodReportTests(unittest.TestCase):
    def setUp(self):
        fixtures.SodAnalysisApiTests.setUp(self)
        self.period=periods.create('Synthetic report period',date(2026,1,1),date(2026,12,31),date(2026,10,27),0)['period']
        self.options=reports.Options(prepared_by='Synthetic Author',report_date=date(2026,10,27),management_comments='Synthetic ÆØÅ review <img src="https://example.invalid/image">')
        self.client=TestClient(create_app(session_token=H['X-SAP-Lens']),base_url='http://127.0.0.1:18743')
    tearDown=fixtures.SodAnalysisApiTests.tearDown
    def model(self):return reports.model(self.period['id'],self.options)
    def test_shared_model_and_editable_docx_without_external_relationships(self):
        data=self.model();content=reports.render(data,'docx')
        self.assertEqual(content,reports.render(data,'docx'))
        with ZipFile(BytesIO(content)) as archive:
            xml=archive.read('word/document.xml').decode()
            for heading in reports.HEADINGS['en']:self.assertIn(heading.replace('&','&amp;'),xml)
            self.assertIn('Synthetic ÆØÅ',xml);self.assertIn('Signature' .lower(),xml.lower());self.assertIn('w:tblHeader',xml)
            self.assertNotIn('TargetMode="External"',''.join(archive.read(name).decode() for name in archive.namelist() if name.endswith('.rels')))
            self.assertIn('Locally recorded period approval: No',xml)
        from docx import Document
        document=Document(BytesIO(content));self.assertGreater(len(document.tables),5)
        self.assertEqual(data['snapshot_checksum'],self.period['snapshot'])
    def test_pdf_unicode_safe_markup_and_repeatable_generation(self):
        data=self.model();content=reports.render(data,'pdf')
        self.assertTrue(content.startswith(b'%PDF-'));self.assertTrue(content.rstrip().endswith(b'%%EOF'))
        self.assertEqual(content,reports.render(data,'pdf'))
        if shutil.which('pdftotext'):
            with tempfile.TemporaryDirectory() as temp:
                path=Path(temp)/'synthetic.pdf';path.write_bytes(content)
                result=subprocess.run(['pdftotext',str(path),'-'],capture_output=True,text=True,check=True)
                self.assertIn('ÆØÅ',result.stdout);self.assertIn('Executive Summary',result.stdout)
                self.assertIn('not verified',result.stdout);self.assertIn('img src=',result.stdout)
    def test_approval_claim_rejected_for_open_period(self):
        with self.assertRaises(HTTPException) as error:reports.model(self.period['id'],reports.Options(status='Approved snapshot'))
        self.assertEqual(error.exception.status_code,422)
    def test_long_rows_unicode_and_large_appendices_render_without_office(self):
        data=self.model();data=copy.deepcopy(data)
        data['sections'][-1]['tables'].append([['Long identifier','Long explanation']]+[['ZC:SYN:'+('LONG_'*80),'Synthetic ÆØÅ '+('long explanation '*150)] for _ in range(40)])
        self.assertGreater(len(reports.render(data,'pdf')),5000)
        self.assertGreater(len(reports.render(data,'docx')),5000)
    def test_sections_norwegian_headings_and_optional_metadata(self):
        data=reports.model(self.period['id'],reports.Options(language='no',include_appendices=False,sections=['executive','conclusion']))
        self.assertEqual([section['title'] for section in data['sections']],['Sammendrag','Konklusjon og godkjenning'])
        self.assertTrue(reports.render(data,'pdf').startswith(b'%PDF'))
    def test_report_api_auth_content_types_and_integrity_metadata(self):
        body=dict(period_id=self.period['id'],options=self.options.model_dump(mode='json'))
        self.assertEqual(self.client.post('/api/sod/reports/preview',json=body).status_code,403)
        preview=self.client.post('/api/sod/reports/preview',json=body,headers=H)
        self.assertEqual(preview.status_code,200,preview.text)
        for kind,content_type in [('pdf','application/pdf'),('docx','application/vnd.openxmlformats-officedocument.wordprocessingml.document')]:
            response=self.client.post('/api/sod/reports/'+kind,json=body,headers=H)
            self.assertEqual(response.status_code,200,response.text[:100]);self.assertTrue(response.headers['content-type'].startswith(content_type))
            self.assertEqual(response.headers['x-sap-lens-report-model'],preview.json()['model_checksum'])
            self.assertEqual(response.headers['cache-control'],'no-store')
    def test_logo_extreme_aspect_ratio_does_not_overflow(self):
        from PIL import Image
        from branding import stage_image
        from unittest.mock import patch
        stream=BytesIO();Image.new('RGB',(1,1024),'white').save(stream,format='PNG');identity=stage_image(stream.getvalue())['logo_id'];data=self.model();data['logo_id']=identity
        self.assertTrue(reports.render(data,'pdf').startswith(b'%PDF'))
        self.assertTrue(reports.render(data,'docx').startswith(b'PK'))

    def test_unsupported_pdf_symbols_fail_explicitly_without_losing_docx(self):
        data=self.model();data['title']='Synthetic \U0001f680 title'
        with self.assertRaises(HTTPException) as error:reports.render(data,'pdf')
        self.assertEqual(error.exception.status_code,422)
        self.assertTrue(reports.render(data,'docx').startswith(b'PK'))

    def test_missing_frozen_logo_and_stale_preview_fail_safely(self):
        data=self.model();data['logo_id']='f'*64
        for kind in ('pdf','docx'):
            with self.assertRaises(HTTPException) as error:reports.render(data,kind)
            self.assertEqual(error.exception.status_code,409)
        body=dict(period_id=self.period['id'],options=self.options.model_dump(mode='json'),expected_model='0'*64)
        self.assertEqual(self.client.post('/api/sod/reports/pdf',json=body,headers=H).status_code,409)
