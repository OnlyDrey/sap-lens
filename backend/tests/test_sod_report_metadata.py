"""SoD report descriptions (R8.1): the formal and remediation reports use the shared metadata resolver, keep imported and local text apart with a source label,
and read descriptions from the frozen review snapshot, never from whatever is imported later. Synthetic data only."""
from datetime import date
from io import BytesIO
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from zipfile import ZipFile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException
import cache
import sod_catalogue as catalogue
import sod_metadata
import sod_periods as periods
import sod_reports as reports
from test_sod_reports import ReportCase

IMPORTED_RISKS = {'R1': dict(name='Payables posting', description='Posting and approving a vendor invoice is incompatible. ÆØÅ é ü'), 'R2': dict(name='Vendor master', description='')}
IMPORTED_ACTIVITIES = {'A': dict(name='Post invoice', description='Creates a vendor invoice.')}


class MetadataCase(ReportCase):
    def put_imported(self, risks=None, activities=None):
        cache._cache.sod.setdefault('report', {})['metadata'] = dict(risks=risks if risks is not None else IMPORTED_RISKS, activities=activities if activities is not None else IMPORTED_ACTIVITIES, source={})

    def put_local(self, risk_id, **fields):
        definition = catalogue.definition_version(next(risk for risk in cache.get_snapshot().sod['risks'] if risk['risk_id'] == risk_id))
        catalogue.save(risk_id, catalogue.LocalMetadata(**fields), catalogue.read().revision, definition)

    def put_local_activity(self, name, **fields):
        catalogue.save_activity(name, catalogue.ActivityMetadata(**fields), catalogue.read().revision)

    def period(self, name='With descriptions'):
        return self.new_period(name)

    def report(self, pid=None, **changes):
        return reports.model(pid or self.pid, self.options.model_copy(update=changes))

    def section(self, data, key):
        return next(section for section in data['sections'] if section['key'] == key)

    def term_rows(self, data, key, header):
        table = next((table for table in self.section(data, key)['tables'] if table and table[0][0] == header and table[0][1:2] == ['Name']), None)
        return {row[0]: row[1:] for row in (table or [[None]])[1:]}


class ResolutionInReportTests(MetadataCase):
    def test_imported_local_fallback_and_missing_descriptions_carry_their_source(self):
        self.put_imported(); self.put_local('R2', explanation_en='Local words for R2'); self.put_local_activity('B', explanation_en='Local activity B', display_name='Approve invoice')
        pid = self.period()
        data = self.report(pid)
        risks = self.term_rows(data, 'risk_overview', 'Risk')
        self.assertEqual(risks['R1'], ['Payables posting', 'Posting and approving a vendor invoice is incompatible. ÆØÅ é ü', 'Imported'])
        self.assertEqual(risks['R2'], ['Vendor master', 'Local words for R2', 'Name: Imported · Description: Local fallback'])
        activities = self.term_rows(data, 'appendices', 'Activity')
        self.assertEqual(activities['A'], ['Post invoice', 'Creates a vendor invoice.', 'Imported'])
        self.assertEqual(activities['B'], ['Approve invoice', 'Local activity B', 'Local fallback'])
        self.assertEqual(activities['C'], ['—', '—', 'Not available'])
        text = ' '.join(self.section(data, 'risk_overview')['paragraphs'])
        self.assertIn('Imported = text supplied in the SoD Matrix CSV', text); self.assertIn('frozen with this review period', text)

    def test_a_different_local_text_is_reported_but_never_mixed_in(self):
        self.put_imported(); self.put_local('R1', explanation_en='Our own wording', display_name='Our name')
        data = self.report(self.period())
        row = self.term_rows(data, 'risk_overview', 'Risk')['R1']
        self.assertEqual(row[:2], ['Payables posting', 'Posting and approving a vendor invoice is incompatible. ÆØÅ é ü'])
        self.assertIn('a different local description exists', row[2]); self.assertNotIn('Our own wording', str(self.section(data, 'risk_overview')))  # the appendix guidance table already lists local business text under its own heading

    def test_reports_without_any_description_are_unchanged(self):
        data = self.report()
        overview = self.section(data, 'risk_overview')
        self.assertEqual(len(overview['tables']), 3, 'criticality, risk and business area tables only')
        self.assertNotIn('Sources: Imported', str(data['sections']))
        self.assertEqual(sod_metadata.for_period(periods.details(self.pid)['snapshot'])['risks'], {})
        for kind in ('docx', 'pdf'): self.assertTrue(reports.render(data, kind))

    def test_detection_results_do_not_depend_on_descriptions(self):
        plain = periods.details(self.pid)['snapshot']['analysis']['users']
        self.put_imported(); self.put_local('R1', explanation_en='Words')
        described = periods.details(self.period())['snapshot']['analysis']['users']
        pairs = lambda rows: sorted((row['subject'], row['risk_id'], row['criticality']) for row in rows)
        self.assertEqual(pairs(plain), pairs(described))


class FrozenHistoryTests(MetadataCase):
    def test_a_snapshot_carries_its_own_descriptions_only_for_risks_and_activities_in_scope(self):
        self.put_imported(risks={**IMPORTED_RISKS, 'NOT_A_RISK': dict(name='Stray')})
        saved = periods.details(self.period())['snapshot']
        self.assertEqual(saved['metadata']['version'], 1)
        self.assertEqual(set(saved['metadata']['risks']), {'R1', 'R2'}); self.assertEqual(set(saved['metadata']['activities']), {'A'})
        self.assertEqual(saved['metadata']['risks']['R1']['origin']['description'], 'imported')

    def test_an_approved_periods_report_never_shows_later_descriptions(self):
        self.put_imported()
        pid = self.period('Frozen')
        for state in ('In review', 'Ready for approval'):
            self.decide_everything(pid) if state == 'In review' else None
            self.move(pid, state)
        self.approve(pid)
        before = self.report(pid, status='Approved')
        self.put_imported(risks={'R1': dict(name='Renamed later', description='Replaced description')}, activities={'A': dict(name='Changed activity', description='Changed')})
        self.put_local('R2', explanation_en='Local text added later')
        after = self.report(pid, status='Approved')
        self.assertEqual(before['model_checksum'], after['model_checksum'])
        self.assertNotIn('Renamed later', str(after['sections'])); self.assertNotIn('Local text added later', str(after['sections']))
        newer = self.report(self.period('Captured later'))
        self.assertIn('Renamed later', str(newer['sections']))  # a period captured now sees the current descriptions
        self.assertEqual(reports.render(before, 'docx'), reports.render(after, 'docx'))

    def test_an_open_period_keeps_its_captured_descriptions_until_it_is_recaptured(self):
        self.put_imported(); pid = self.period('Open')
        self.put_imported(risks={'R1': dict(name='Renamed later', description='Replaced')})
        self.assertIn('Payables posting', str(self.report(pid)['sections']))
        self.assertNotIn('Renamed later', str(self.report(pid)['sections']))

    def test_a_legacy_snapshot_shows_only_its_frozen_local_text_and_says_so(self):
        self.put_local('R1', explanation_en='Local words captured with the period', display_name='Local R1')
        with patch('sod_metadata.frozen', return_value=None):  # a snapshot from before descriptions were retained has no copy
            pid = self.period('Legacy')
        self.put_imported()  # imported descriptions exist today, but were not part of that period
        saved = periods.details(pid)['snapshot']
        self.assertNotIn('metadata', {key for key, value in saved.items() if value})
        data = self.report(pid)
        row = self.term_rows(data, 'risk_overview', 'Risk')['R1']
        self.assertEqual(row, ['Local R1', 'Local words captured with the period', 'Local fallback'])
        text = str(data['sections'])
        self.assertIn('captured before imported descriptions were retained', text); self.assertNotIn('Payables posting', text)
        for kind in ('docx', 'pdf'): self.assertTrue(reports.render(data, kind))

    def test_an_old_dataset_without_optional_columns_still_reports(self):
        pid = self.period('Plain')
        data = self.report(pid)
        self.assertEqual(self.term_rows(data, 'risk_overview', 'Risk'), {})
        self.assertTrue(reports.render(data, 'pdf').startswith(b'%PDF'))


class RenderingTests(MetadataCase):
    def test_special_characters_markup_and_long_descriptions_render_in_both_formats(self):
        long_text = ' '.join(['Long business description with ÆØÅ éèê and <b>markup</b> & "quotes".'] * 40)
        self.put_imported(risks={'R1': dict(name='R1 <script>alert(1)</script>', description=long_text), 'R2': dict(name='x', description='y')})
        data = self.report(self.period())
        pdf = reports.render(data, 'pdf'); docx = reports.render(data, 'docx')
        self.assertTrue(pdf.startswith(b'%PDF'))
        with ZipFile(BytesIO(docx)) as archive:
            xml = archive.read('word/document.xml').decode()
        self.assertIn('Long business description with ÆØÅ éèê', xml); self.assertIn('&lt;script&gt;', xml); self.assertNotIn('<script>', xml)
        self.assertIn('Imported', xml); self.assertIn('Sources: Imported', xml)

    def test_characters_outside_the_pdf_font_fail_the_pdf_explicitly_and_leave_the_docx(self):
        self.put_imported(risks={'R1': dict(name='Rule', description='Contains 日本語 text'), 'R2': dict(name='x', description='y')})
        data = self.report(self.period())
        with self.assertRaises(HTTPException) as refused: reports.render(data, 'pdf')
        self.assertEqual(refused.exception.status_code, 422)
        self.assertTrue(reports.render(data, 'docx'))


class RemediationMetadataTests(MetadataCase):
    def remediation(self, context):
        return reports.remediation_model(context, reports.RemediationOptions(prepared_by='Synthetic Author', report_date=date(2026, 10, 27)))

    def test_current_evidence_uses_live_descriptions_and_a_period_uses_its_frozen_copy(self):
        self.put_imported(); pid = self.period('Remediation')
        live = self.remediation('current'); frozen = self.remediation(pid)
        for data in (live, frozen):
            rows = {row[0]: row[1:] for table in data['sections'][0]['tables'] if table and table[0][:2] == ['Risk', 'Name'] for row in table[1:]}
            self.assertEqual(rows['R1'][0], 'Payables posting')
        self.assertIn('Current evidence: descriptions reflect the data loaded now', ' '.join(live['sections'][0]['paragraphs']))
        self.assertIn('frozen with this review period', ' '.join(frozen['sections'][0]['paragraphs']))
        self.put_imported(risks={'R1': dict(name='Renamed later', description='Replaced')})
        self.assertIn('Renamed later', str(self.remediation('current')['sections'])); self.assertNotIn('Renamed later', str(self.remediation(pid)['sections']))
        for kind in ('docx', 'pdf'): self.assertTrue(reports.render(self.remediation(pid), kind))

    def test_a_remediation_report_without_descriptions_is_unchanged(self):
        data = self.remediation(self.pid)
        self.assertFalse([table for table in data['sections'][0]['tables'] if table and table[0][:2] == ['Risk', 'Name']])
        self.assertNotIn('Sources: Imported', str(data['sections']))


if __name__ == '__main__':
    unittest.main()
