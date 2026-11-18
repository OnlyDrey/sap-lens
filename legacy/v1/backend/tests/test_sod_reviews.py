"""Synthetic evidence-bearing SoD review history and safe local persistence."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
from fastapi import HTTPException
from pydantic import ValidationError
import sod_reviews as reviews


def finding(identity='a' * 64, version='b' * 64):
    def path(side, activity, code):
        return dict(matched_catalogue_pattern='ZC:SYN:*', single_role='ZO:SYN:ROLE',
                    assignment_kind='child', tcode=code,
                    source_provenance=[dict(child_agr='ZO:SYN:ROLE', parent_agr=None, effective_role=None)],
                    activity_slot=side, activity=activity, matrix_transaction=code,
                    actual_assigned_role='ZC:SYN:EXACT', matching_status='wildcard',
                    role_valid_from='2020-01-01', role_valid_to='9999-12-31', interval_status='active',
                    user_group='SYNTHETIC')
    return dict(finding_id=identity, subject='SYN_USER', kind='user', risk_id='SYN01',
                criticality='H', evaluation_policy='sod-two-sided-v1',
                evidence=dict(ACTVT1=[path('ACTVT1', 'CREATE', 'X001')],
                              ACTVT2=[path('ACTVT2', 'APPROVE', 'X002')]),
                current_potential=True,
                account=dict(accounts=[dict(valid_from='2020-01-01', valid_to='9999-12-31',
                                           locked=False, user_type='A', user_group='SYNTHETIC')],
                             directory_match='directory_disabled', ad_status='Unknown'),
                evidence_version=version,
                risk=dict(display_name='', source_text='Synthetic two-sided risk', business_category='', risk_type='S'))


def annotation(**changes):
    return dict(decision='Further investigation required', reviewer='Synthetic Reviewer',
                rationale='Inspect synthetic evidence.', **changes)


class SodReviewsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': str(self.root / 'private'), 'DATA_CSV_PATH': ''})
        self.env.start(); config.get_settings.cache_clear()

    def tearDown(self):
        config.get_settings.cache_clear(); self.env.stop(); self.temp.cleanup()

    def save(self, row=None, notes=None, context='current'):
        row = row or finding(); notes = notes or annotation()
        return reviews.save(row, notes, reviews.read().revision, row['evidence_version'], context)

    def test_pending_and_justification_requirements(self):
        row = reviews.listing([finding()])['items'][0]
        self.assertEqual((row['decision'], row['lifecycle'], row['history_count']), ('Pending review', 'Pending', 0))
        for changes in ({'reviewer':''}, {'reviewer':'   '}, {'rationale':'\t '}, {'decision':'Unsupported'}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.save(notes={**annotation(), **changes})
        self.assertEqual(reviews.read().revision, 0)

    def test_saves_full_evidence_and_appends_history_without_mutating_prior_events(self):
        source = finding(); result = self.save(source)
        self.assertEqual(result['revision'], 1)
        self.assertIn('Self-reported', result['reviewer_identity'])
        previous = deepcopy(result['event'])
        source['evidence']['ACTVT1'][0]['tcode'] = 'MUTATED_AFTER_SAVE'
        later = self.save(notes={**annotation(), 'decision':'Accepted with mitigating controls', 'mitigating_controls':'Synthetic independent approval'})
        events = reviews.history(finding()['finding_id'])
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1], previous)
        self.assertNotEqual(events[0]['event_id'], events[1]['event_id'])
        self.assertEqual(events[0]['event_id'], later['event']['event_id'])
        self.assertEqual(reviews.finding_for_event(events[1])['evidence']['ACTVT1'][0]['tcode'], 'X001')
        item = reviews.listing([finding()])['items'][0]
        self.assertEqual((item['decision'], item['lifecycle'], item['history_count']), ('Accepted with mitigating controls', 'Reviewed', 2))

    def test_persistence_in_fresh_process(self):
        self.save()
        script = "import sod_reviews; d=sod_reviews.read(); assert d.revision==1; e=next(iter(d.contexts['current'].values()))[0]; assert e.annotation.reviewer=='Synthetic Reviewer'; assert sod_reviews.finding_for_event(e)['evidence']['ACTVT1'][0]['tcode']=='X001'"
        result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, 'Fresh-process SoD review persistence failed')

    def test_revision_and_evidence_concurrency_guards_preserve_history(self):
        self.save(); row = finding()
        for revision, version in [(0, row['evidence_version']), (1, 'f' * 64)]:
            with self.assertRaises(HTTPException) as caught:
                reviews.save(row, annotation(), revision, version)
            self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(len(reviews.history(row['finding_id'])), 1)

    def test_evidence_changes_require_review_but_unrelated_changes_do_not(self):
        row = finding(); self.save(row, {**annotation(), 'decision':'Accepted with mitigating controls','mitigating_controls':'Synthetic control'})
        same = reviews.listing([row], coverage={'status':'available','source_revision':'unrelated-new-import'})['items'][0]
        self.assertFalse(same['stale']); self.assertEqual(same['lifecycle'], 'Reviewed')
        changed = reviews.listing([finding(version='c' * 64)])['items'][0]
        self.assertTrue(changed['stale']); self.assertEqual(changed['lifecycle'], 'Outdated')
        self.assertEqual(changed['event']['evidence_version'], row['evidence_version'])
        self.assertEqual(changed['finding']['evidence_version'], 'c' * 64)

    def test_missing_or_disabled_source_is_historical_not_automatically_resolved(self):
        self.save()
        absent = reviews.listing([], coverage={'status':'unavailable','reason':'mapping_disabled'})
        row = absent['items'][0]
        self.assertEqual(row['presence'], 'historical'); self.assertEqual(row['lifecycle'], 'Historical')
        self.assertTrue(row['stale']); self.assertNotIn('Resolved', row.values())
        self.assertEqual(row['finding']['subject'], 'SYN_USER')
        returned = reviews.listing([finding()])['items'][0]
        self.assertEqual(returned['history_count'], 1); self.assertFalse(returned['stale'])

    def test_contexts_are_independent_without_filesystem_path_derivation(self):
        self.save()
        self.save(notes={**annotation(), 'decision':'Not applicable / false positive'}, context='period_synthetic')
        self.assertEqual(reviews.listing([finding()])['items'][0]['lifecycle'], 'Action required')
        self.assertEqual(reviews.listing([finding()], context='period_synthetic')['items'][0]['lifecycle'], 'Reviewed')
        self.assertEqual(reviews.read().revision, 2)
        for invalid in ('../private', '/absolute', '', 'context:bad'):
            with self.subTest(context=invalid), self.assertRaises(HTTPException):
                reviews.listing([], context=invalid)
        self.assertEqual(sorted(path.name for path in (self.root / 'private').iterdir()), ['csv-data', 'sod-reviews.json'])

    def test_completed_action_needs_notes_and_is_not_a_resolved_risk(self):
        with self.assertRaises(ValidationError):
            self.save(notes={**annotation(), 'action_status':'Completed'})
        result = self.save(notes={**annotation(), 'decision':'Access removal required',
                                  'action_status':'Completed', 'completion_notes':'Synthetic completion evidence',
                                  'target_date':'2026-12-31', 'action_owner':'Synthetic Owner'})
        self.assertEqual(result['event']['annotation']['target_date'], '2026-12-31')
        self.assertEqual(reviews.listing([finding()])['items'][0]['lifecycle'], 'Action required')
        with self.assertRaises(ValidationError):
            self.save(notes={**annotation(), 'target_date':'31.12.2026'})

    def test_storage_and_event_capacity_fail_without_overwriting_previous_data(self):
        self.save(); path = self.root / 'private' / 'sod-reviews.json'; original = path.read_bytes()
        with patch('sod_reviews.MAX_EVENTS', 1):
            with self.assertRaises(HTTPException): self.save()
        self.assertEqual(path.read_bytes(), original)
        with patch('sod_reviews.MAX_REVIEWS', 1):
            with self.assertRaises(HTTPException): self.save(finding(identity='c' * 64))
        self.assertEqual(path.read_bytes(), original)
        with patch('sod_reviews.MAX_BYTES', len(original) + 10):
            with self.assertRaises(HTTPException): self.save()
        self.assertEqual(path.read_bytes(), original)
        with patch('sod_reviews.atomic_write', side_effect=PermissionError('Synthetic storage failure')):
            with self.assertRaises(HTTPException): self.save()
        self.assertEqual(path.read_bytes(), original)

    def test_corrupt_unsupported_or_inconsistent_history_is_preserved(self):
        self.save(); path = self.root / 'private' / 'sod-reviews.json'; original = json.loads(path.read_text())
        invalid = [b'{invalid', json.dumps({**original, 'version':2}).encode()]
        changed = deepcopy(original)
        next(iter(changed['contexts']['current'].values()))[0]['evidence_version'] = 'f' * 64
        invalid.append(json.dumps(changed).encode())
        for payload in invalid:
            with self.subTest(payload=payload[:20]):
                path.write_bytes(payload)
                with self.assertRaises(HTTPException): self.save()
                self.assertEqual(path.read_bytes(), payload)

    def test_content_addressed_evidence_is_reused_and_checked_on_demand(self):
        first = self.save(); second = self.save()
        self.assertEqual(first['event']['finding_snapshot'], second['event']['finding_snapshot'])
        self.assertNotIn('finding', first['event'])
        snapshots = list((self.root / 'private' / 'csv-data' / 'snapshots').glob('*.json'))
        self.assertEqual(len(snapshots), 1)
        snapshots[0].write_text('corrupt')
        with self.assertRaises(HTTPException): reviews.finding_for_event(first['event'])
        with self.assertRaises(HTTPException): reviews.listing([])
        original = (self.root / 'private' / 'sod-reviews.json').read_bytes()
        with self.assertRaises(HTTPException): self.save()
        self.assertEqual((self.root / 'private' / 'sod-reviews.json').read_bytes(), original)

    def test_source_versions_and_evaluation_date_are_retained_without_changing_identity(self):
        row = finding(); row['source_versions'] = {'roles':'c' * 64, 'sod':'d' * 64}
        row['evaluation_as_of'] = '2026-10-27'
        event = self.save(row)['event']; restored = reviews.finding_for_event(event)
        self.assertEqual(restored['source_versions'], row['source_versions'])
        self.assertEqual(restored['evaluation_as_of'], '2026-10-27')
        self.assertEqual(restored['finding_id'], finding()['finding_id'])
        row['source_versions'] = {'private':'e' * 64}
        with self.assertRaises(ValidationError): self.save(row)

    def test_incomplete_wrong_kind_or_oversized_evidence_is_not_recorded(self):
        row = finding(); row['evidence']['ACTVT2'] = []
        with self.assertRaises(ValidationError): self.save(row)
        row = finding(); row['kind'] = 'role'
        with self.assertRaises(ValidationError): self.save(row)
        with patch('sod_reviews.MAX_FINDING_BYTES', 100):
            with self.assertRaises(ValidationError): self.save()
        self.assertFalse((self.root / 'private' / 'sod-reviews.json').exists())


if __name__ == '__main__':
    unittest.main()
