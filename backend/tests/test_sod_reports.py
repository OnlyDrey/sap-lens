"""Formal SoD review report, access remediation report, frozen models and untrusted-content boundaries."""
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException
import cache
import sod_decisions as decisions
import sod_periods as periods
import sod_reports as reports
from test_sod_governance import snapshot
from test_sod_periods_v2 import PeriodV2Case

H = {'X-SAP-Lens': 'synthetic-governance-session'}
SECTION_TITLES = reports.HEADINGS['en']


class ReportCase(PeriodV2Case):
    def setUp(self):
        super().setUp()
        self.pid = self.new_period('Synthetic report period')
        self.options = reports.Options(prepared_by='Synthetic Author', report_date=date(2026, 10, 27), management_comments='Synthetic ÆØÅ review <img src="https://example.invalid/image">')

    def mixed_decisions(self):
        pid = self.pid
        self.decide('activity', [self.activity_item('SYN_A', 'A', pid), self.activity_item('SYN_B', 'A', pid), self.activity_item('SYN_B', 'B', pid)], 'Approved', context=pid)
        self.decide('activity', [self.activity_item('SYN_A', 'B', pid)], 'Remove', context=pid)
        self.decide('activity', [self.activity_item('SYN_A', 'C', pid)], 'Conditional', context=pid, controls='Quarterly supervisor sign-off')
        self.decide('assignment', [self.assignment_item('SYN_A', 'ROLE_A2', 'A', pid)], 'Remove', context=pid)
        self.decide('acceptance', [self.acceptance_item('SYN_A', 'R1', pid)], 'Accepted', context=pid, approver='Synthetic Approver', controls='Monitoring report')
        self.decide('acceptance', [self.acceptance_item('SYN_A', 'R2', pid)], 'Rejected', context=pid, approver='Synthetic Approver')

    def model(self, **changes):
        return reports.model(self.pid, self.options.model_copy(update=changes))

    def metrics(self, data):
        table = next(section for section in data['sections'] if section['key'] == 'executive')['tables'][0]
        return {row[0]: (row[1], row[2]) for row in table[1:]}

    def approve_period(self):
        self.decide_everything(self.pid)
        for state in ('In review', 'Ready for approval'):
            self.move(self.pid, state)
        self.approve(self.pid)


class FormalReportTests(ReportCase):
    def test_summary_counts_are_semantically_precise_and_match_decisions(self):
        self.mixed_decisions()
        metrics = self.metrics(self.model())
        expected = {'SAP users evaluated': ('3', 'users'), 'Users with detected potential conflicts': ('2', 'users'),
                    'Detected potential conflicts': ('3', 'user-risk findings'), 'Activities in review scope': ('5', 'user-activity pairs'),
                    'Activities approved': ('3', 'activities'), 'Activities approved conditionally': ('1', 'activities'),
                    'Activities marked for removal': ('1', 'activities'), 'Activity reviews pending or outdated': ('0', 'activities'),
                    'Role assignments marked for removal': ('1', 'assignments'), 'Role assignments to keep': ('0', 'assignments'),
                    'Risks accepted': ('1', 'user-risk findings'), 'Risks rejected': ('1', 'user-risk findings'),
                    'Risk decisions pending or outdated': ('1', 'user-risk findings'), 'Open remediation actions': ('0', 'actions'),
                    'Overdue remediation actions': ('0', 'actions'), 'Removal recommendations without a tracked action': ('1', 'assignments')}
        for name, value in expected.items():
            self.assertEqual(metrics[name], value, name)

    def test_all_formal_sections_in_order_with_decisions_controls_and_remediation(self):
        self.mixed_decisions()
        data = self.model()
        self.assertEqual([section['title'] for section in data['sections']], SECTION_TITLES)
        text = str(data['sections'])
        for needle in ('Quarterly supervisor sign-off', 'Synthetic Approver', 'Monitoring report', 'SYN_A / ROLE_A2', 'Removal required', 'Rejected'):
            self.assertIn(needle, text)
        remediation = next(section for section in data['sections'] if section['key'] == 'remediation')
        self.assertIn('not proof that access was removed', ' '.join(remediation['paragraphs']))

    def test_remediation_status_and_overdue_reach_the_report(self):
        self.mixed_decisions()
        assignment = self.assignment_item('SYN_A', 'ROLE_A2', 'A', self.pid)
        view = self.get('/api/sod/remediation', context=self.pid)
        self.post('/api/sod/remediation/actions', dict(context=self.pid, expected_revision=view['revision'], actor='Owner', user='SYN_A', assignment_id=assignment['key'], role='ROLE_A2',
                                                       recommended='Remove assignment', reason='Duplicate coverage', owner='Access team', due_date=(date(2026, 10, 27) - timedelta(days=3)).isoformat()))
        metrics = self.metrics(self.model())
        self.assertEqual((metrics['Open remediation actions'][0], metrics['Overdue remediation actions'][0], metrics['Removal recommendations without a tracked action'][0]), ('1', '1', '0'))

    def test_editable_docx_without_external_relationships_and_signature_limits(self):
        self.mixed_decisions()
        data = self.model()
        content = reports.render(data, 'docx')
        self.assertEqual(content, reports.render(data, 'docx'))
        with ZipFile(BytesIO(content)) as archive:
            xml = archive.read('word/document.xml').decode()
            for heading in SECTION_TITLES:
                self.assertIn(heading.replace('&', '&amp;'), xml)
            for needle in ('Synthetic ÆØÅ', 'Reviewer signature', 'Approver signature', 'Document integrity', 'Recorded period approval: No', 'not verified digital signatures', 'w:tblHeader'):
                self.assertIn(needle, xml)
            self.assertNotIn('TargetMode="External"', ''.join(archive.read(name).decode() for name in archive.namelist() if name.endswith('.rels')))
            self.assertIn(data['snapshot_checksum'], xml)
            self.assertIn(data['model_checksum'], xml)
        from docx import Document
        self.assertGreater(len(Document(BytesIO(content)).tables), 8)

    def test_cover_shows_short_references_and_full_hashes_move_to_integrity_and_appendix(self):
        data = self.model()
        cover = reports.render(data, 'docx')
        with ZipFile(BytesIO(cover)) as archive:
            xml = archive.read('word/document.xml').decode()
        self.assertIn('Snapshot reference: ' + data['snapshot_checksum'][:12], xml)
        before_integrity = xml.split('Document integrity')[0]
        self.assertNotIn(data['snapshot_checksum'], before_integrity.split('Detailed Appendices')[0])
        appendix = next(section for section in data['sections'] if section['key'] == 'appendices')
        self.assertTrue(any(data['snapshot_checksum'] in str(table) for table in appendix['tables']))

    def test_pdf_unicode_safe_markup_and_repeatable_generation(self):
        self.mixed_decisions()
        data = self.model()
        content = reports.render(data, 'pdf')
        self.assertTrue(content.startswith(b'%PDF-'))
        self.assertTrue(content.rstrip().endswith(b'%%EOF'))
        self.assertEqual(content, reports.render(data, 'pdf'))
        if shutil.which('pdftotext'):
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / 'synthetic.pdf'
                path.write_bytes(content)
                result = subprocess.run(['pdftotext', str(path), '-'], capture_output=True, text=True, check=True).stdout
                for needle in ('ÆØÅ', 'Executive Summary', 'Outstanding Remediation', 'Document integrity', 'img src='):
                    self.assertIn(needle, result)

    def test_approved_status_requires_a_frozen_period_and_recorded_identity(self):
        with self.assertRaises(HTTPException) as error:
            self.model(status='Approved snapshot')
        self.assertEqual(error.exception.status_code, 422)
        self.approve_period()
        approved = self.model(status='Approved snapshot')
        self.assertEqual(approved['status'], 'Approved snapshot')
        self.assertIn('Recorded period approval: Yes (Approved)', str(approved['sections']))
        with self.assertRaises(HTTPException) as error:
            self.model(reviewer='Someone Else')
        self.assertEqual(error.exception.status_code, 422)

    def test_approved_report_is_reproducible_after_live_evidence_and_decisions_change(self):
        self.approve_period()
        first = self.model(status='Approved snapshot')
        pdf = reports.render(first, 'pdf')
        cache._cache = snapshot()
        cache._cache.users.users.pop('SYN_A')
        self.decide('activity', [self.activity_item('SYN_B', 'A')], 'Remove')
        second = self.model(status='Approved snapshot')
        self.assertEqual(first['model_checksum'], second['model_checksum'])
        self.assertEqual(pdf, reports.render(second, 'pdf'))

    def test_open_period_report_changes_with_decisions_so_stale_previews_fail(self):
        before = self.model()['model_checksum']
        self.decide('activity', [self.activity_item('SYN_A', 'A', self.pid)], 'Approved', context=self.pid)
        self.assertNotEqual(before, self.model()['model_checksum'])
        body = dict(period_id=self.pid, options=self.options.model_dump(mode='json'), expected_model=before)
        self.assertEqual(self.client.post('/api/sod/reports/pdf', json=body, headers=H).status_code, 409)

    def test_norwegian_headings_and_optional_sections(self):
        data = self.model(language='no', include_appendices=False, sections=['executive', 'conclusion'])
        self.assertEqual([section['title'] for section in data['sections']], ['Sammendrag', 'Konklusjon og godkjenning'])
        self.assertTrue(reports.render(data, 'pdf').startswith(b'%PDF'))
        self.assertEqual(len(reports.HEADINGS['no']), len(SECTION_TITLES))

    def test_legacy_period_report_states_what_was_not_recorded(self):
        legacy = periods.create('Legacy', date(2026, 1, 1), date(2026, 12, 31), date(2026, 10, 27), periods.read().revision, legacy=True)['period']['id']
        data = reports.model(legacy, self.options)
        text = str(data['sections'])
        self.assertIn('predates activity, role-assignment and risk-acceptance review', text)
        self.assertIn('Not recorded: this period predates activity review.', text)
        self.assertTrue(reports.render(data, 'pdf').startswith(b'%PDF'))

    def test_previous_period_comparison_requires_an_approved_period(self):
        other = self.new_period('Prior')
        with self.assertRaises(HTTPException) as error:
            self.model(previous_period_id=other)
        self.assertEqual(error.exception.status_code, 422)

    def test_long_rows_unicode_and_large_appendices_render(self):
        import copy
        data = copy.deepcopy(self.model())
        data['sections'][-1]['tables'].append([['Long identifier', 'Long explanation']] + [['ZC:SYN:' + ('LONG_' * 80), 'Synthetic ÆØÅ ' + ('long explanation ' * 150)] for _ in range(40)])
        self.assertGreater(len(reports.render(data, 'pdf')), 5000)
        self.assertGreater(len(reports.render(data, 'docx')), 5000)

    def test_report_api_auth_content_types_integrity_headers_and_report_log(self):
        body = dict(period_id=self.pid, options=self.options.model_copy(update=dict(status='For review')).model_dump(mode='json'))
        self.assertEqual(self.client.post('/api/sod/reports/preview', json=body).status_code, 403)
        preview = self.client.post('/api/sod/reports/preview', json=body, headers=H)
        self.assertEqual(preview.status_code, 200, preview.text)
        for kind, content_type in [('pdf', 'application/pdf'), ('docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')]:
            response = self.client.post('/api/sod/reports/' + kind, json=body, headers=H)
            self.assertEqual(response.status_code, 200, response.text[:100])
            self.assertTrue(response.headers['content-type'].startswith(content_type))
            self.assertEqual(response.headers['cache-control'], 'no-store')
        log = decisions.context_summary(self.pid)['reports']
        self.assertEqual([item['kind'] for item in log], ['pdf', 'docx'])
        self.assertEqual(log[0]['model_checksum'], preview.json()['model_checksum'])
        self.assertEqual(self.get(f'/api/sod/periods/{self.pid}/deletion-impact')['mode'], 'protected')

    def test_logo_extreme_aspect_ratio_does_not_overflow(self):
        from PIL import Image
        from branding import stage_image
        stream = BytesIO()
        Image.new('RGB', (1, 1024), 'white').save(stream, format='PNG')
        data = self.model()
        data['logo_id'] = stage_image(stream.getvalue())['logo_id']
        self.assertTrue(reports.render(data, 'pdf').startswith(b'%PDF'))
        self.assertTrue(reports.render(data, 'docx').startswith(b'PK'))

    def test_unsupported_pdf_symbols_fail_explicitly_without_losing_docx(self):
        data = self.model()
        data['title'] = 'Synthetic \U0001f680 title'
        with self.assertRaises(HTTPException) as error:
            reports.render(data, 'pdf')
        self.assertEqual(error.exception.status_code, 422)
        self.assertTrue(reports.render(data, 'docx').startswith(b'PK'))

    def test_missing_frozen_logo_fails_safely(self):
        data = self.model()
        data['logo_id'] = 'f' * 64
        for kind in ('pdf', 'docx'):
            with self.assertRaises(HTTPException) as error:
                reports.render(data, kind)
            self.assertEqual(error.exception.status_code, 409)


class RemediationReportTests(ReportCase):
    def request(self, kind, context=None, status=200, **options):
        body = dict(context=context or self.pid, options=dict(prepared_by='Synthetic Author', report_date='2026-10-27', **options))
        response = self.client.post(f'/api/sod/reports/remediation/{kind}', json=body, headers=H)
        self.assertEqual(response.status_code, status, response.text[:200])
        return response

    def test_groups_are_separated_and_proposals_are_not_completed_work(self):
        self.mixed_decisions()
        self.decide('activity', [self.activity_item('SYN_B', 'A', self.pid)], 'Approved', context=self.pid)
        preview = self.request('preview').json()
        titles = [section['title'] for section in preview['sections']]
        self.assertEqual(titles, ['Summary', 'Remove assignment', 'Investigate assignment', 'Apply compensating control', 'Maintain access', 'No action required'])
        summary = preview['sections'][0]['tables'][0]
        self.assertIn('A proposed removal is not completed remediation', preview['sections'][0]['paragraphs'][0])
        counts = {row[0]: row[1] for row in summary[1:]}
        self.assertEqual(counts['Remove assignment'], '1')
        self.assertGreaterEqual(int(counts['Investigate assignment']), 3)
        self.assertEqual(counts['Apply compensating control'], '0')

    def test_csv_rows_filters_and_formula_protection(self):
        self.mixed_decisions()
        response = self.request('csv')
        self.assertTrue(response.text.startswith('﻿"USERNAME"'))
        lines = response.text.strip().splitlines()
        self.assertGreater(len(lines), 2)
        self.assertIn('Remove assignment', response.text)
        only = self.request('csv', recommended=['Apply compensating control'])
        self.assertTrue(all('Apply compensating control' in line for line in only.text.strip().splitlines()[1:]))
        self.assertTrue(response.headers['x-sap-lens-model'])

    def test_docx_and_pdf_exports_and_current_context_are_not_logged(self):
        self.mixed_decisions()
        self.assertTrue(self.request('pdf').content.startswith(b'%PDF'))
        self.assertTrue(self.request('docx').content.startswith(b'PK'))
        self.assertEqual([item['kind'] for item in decisions.context_summary(self.pid)['reports']], ['remediation-pdf', 'remediation-docx'])
        self.request('csv', context='current')
        self.assertEqual(decisions.context_summary('current')['reports'], [])

    def test_approved_period_remediation_report_is_frozen(self):
        self.approve_period()
        first = self.request('preview').json()['model_checksum']
        cache._cache = snapshot()
        cache._cache.users.users.pop('SYN_A')
        self.assertEqual(self.request('preview').json()['model_checksum'], first)

    def test_stale_model_is_rejected_and_unknown_context_is_missing(self):
        body = dict(context=self.pid, expected_model='0' * 64, options=dict(report_date='2026-10-27'))
        self.assertEqual(self.client.post('/api/sod/reports/remediation/csv', json=body, headers=H).status_code, 409)
        self.assertEqual(self.client.post('/api/sod/reports/remediation/pdf', json=dict(context='a' * 32), headers=H).status_code, 404)
        self.assertEqual(self.client.post('/api/sod/reports/remediation/pdf', json=dict(context=self.pid)).status_code, 403)
