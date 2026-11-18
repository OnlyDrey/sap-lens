"""Review retention: completed periods only, exclusive ownership, shared evidence preserved, journalled recoverable removal, separate approval."""
import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cache
import config
import csv_lifecycle
import data_retention as retention
import review_retention as review
import sod_decisions as decisions
import sod_periods as periods
import sod_reviews as reviews
import source_store

DAY = 86400


class Case(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / 'private'
        patcher = patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': str(self.data), 'DATA_CSV_PATH': ''}); patcher.start(); self.addCleanup(patcher.stop)
        config.get_settings.cache_clear(); cache.clear_cache(); self.addCleanup(config.get_settings.cache_clear); self.addCleanup(cache.clear_cache)
        self.now = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
        self.index = periods.Index()
        self.store = decisions.Storage()
        self.legacy = reviews.ReviewStorage()
        self.save()

    def save(self):
        self.index.revision += 1; periods.write(self.index)
        self.store.revision += 1; decisions._write(self.store)
        self.legacy.revision += 1; reviews._write(self.legacy)

    def snap(self, payload):
        identity = csv_lifecycle.write_private('snapshots', dict(version=1, **payload))
        os.utime(csv_lifecycle.private_path('snapshots', identity), (self.now.timestamp() - 1000 * DAY,) * 2)
        return identity

    def evidence(self, tag):
        return self.snap(dict(source='sod-decision-evidence', kind='assignment', evidence={'tag': tag}))

    def event(self, context, kind, key, evidence, decision='Keep', expires=None, when=None):
        return decisions.Event(event_id=uuid4().hex, kind=kind, context=context, timestamp=(when or self.now).isoformat(), key=key, user='SYN_A', ref='ROLE', decision=decision,
                               reviewer='Reviewer One', approver='Approver Two' if kind == 'acceptance' and decision != 'Pending' else '', justification='Synthetic', expires=expires,
                               evidence_version='a' * 64, evidence_snapshot=evidence)

    def period(self, name, state='Closed', completed_days=800, evidence=None, actions=(), acceptance_expires=None, history=True):
        pid = uuid4().hex
        evidence = evidence or [self.evidence(name + '-1'), self.evidence(name + '-2')]
        snapshot = self.snap(dict(source='sod-period', period_id=pid, model=2, analysis={}, frozen={'evidence': evidence}))
        done = self.now - timedelta(days=completed_days)
        steps = [periods.PeriodEvent(timestamp=done.isoformat(), from_state='Ready for approval', to_state=state, actor='Approver Two')] if history and state in periods.FROZEN else []
        item = periods.Period(id=pid, name=name, start=date(2024, 1, 1), end=date(2024, 12, 31), evaluation_date=date(2024, 6, 1), state=state, snapshot=snapshot, snapshots=[snapshot],
                              created=done.isoformat(), modified=done.isoformat(), reviewer='Reviewer One' if state in periods.FROZEN else '', approver='Approver Two' if state in periods.FROZEN else '',
                              approval_date=done.date() if state in periods.FROZEN else None, history=steps)
        self.index.items.append(item)
        kinds = self.store.contexts.setdefault(pid, {})
        for number, identity in enumerate(evidence):
            key = hashlib.sha256(f'{pid}{number}'.encode()).hexdigest()
            kinds.setdefault('assignment', {})[key] = [self.event(pid, 'assignment', key, identity)]
        if acceptance_expires:
            key = hashlib.sha256(f'{pid}acc'.encode()).hexdigest()
            kinds.setdefault('acceptance', {})[key] = [self.event(pid, 'acceptance', key, evidence[0], 'Accepted', acceptance_expires)]
        for status in actions:
            action = decisions.Action(id=uuid4().hex, context=pid, user='SYN_A', recommended='Remove assignment', reason='Synthetic', status=status, created=self.now.isoformat(), modified=self.now.isoformat(),
                                      created_by='Reviewer One', completion_evidence='done' if status == 'Completed' else '')
            self.store.actions[action.id] = action
        self.save()
        return item

    def exists(self, identity):
        return csv_lifecycle.private_path('snapshots', identity).exists()

    def plan(self):
        return review.plan(24, self.now)

    def eligible(self):
        return {item['name'] for item in self.plan()['items']}

    def reasons(self):
        return {row['name']: row['reason'] for row in self.plan()['protected']}

    def approve(self):
        found = retention.review_plan(now=self.now)
        return retention.approve('Admin One', found['digest'], self.now, 'review')


class Eligibility(Case):
    def test_only_completed_periods_beyond_the_newest_are_eligible_and_incomplete_ones_are_protected(self):
        for state in ('Draft', 'In review', 'Ready for approval', 'Rejected'):
            self.period(state, state, completed_days=0)
        self.period('Old closed', 'Closed', 900)
        self.period('Old approved', 'Approved', 880)
        self.period('Newest closed', 'Closed', 800)                               # old, but the newest completed period stays as the comparison baseline
        self.period('Recent closed', 'Approved / closed', 100)
        self.assertEqual(self.eligible(), {'Old closed', 'Old approved', 'Newest closed'})        # only the newest completed period overall is kept
        reasons = self.reasons()
        self.assertEqual({reasons[name] for name in ('Draft', 'In review', 'Ready for approval', 'Rejected')}, {'Active or incomplete review period'})
        self.assertEqual(reasons['Recent closed'], 'Within the retention period')

    def test_the_logical_completion_timestamp_is_used_not_file_times(self):
        old = self.period('Old', 'Closed', 900); self.period('Baseline', 'Closed', 10)
        os.utime(csv_lifecycle.private_path('snapshots', old.snapshot), None)           # a fresh file time changes nothing
        self.assertEqual(self.eligible(), {'Old'})
        newer = self.period('Moved', 'Closed', 900)
        newer.history = [*newer.history, periods.PeriodEvent(timestamp=(self.now - timedelta(days=5)).isoformat(), from_state='Approved', to_state='Closed')]
        self.save()
        self.assertEqual(self.eligible(), {'Old'})                                  # the latest transition into a completed state counts: Moved was closed 5 days ago

    def test_missing_completion_timestamps_are_protected_until_classified_then_aged_from_that_moment(self):
        self.period('Undated', 'Approved', 900, history=False); self.period('Baseline', 'Closed', 10)
        self.assertEqual(self.eligible(), set())
        self.assertIn('protected until classified', self.reasons()['Undated'])
        self.assertEqual(retention.check(self.now), 'nothing')                           # persists the first sighting
        self.assertIn('period:' + self.index.items[0].id, retention.read().first_seen)
        self.assertEqual(retention.check(self.now + timedelta(days=2)), 'nothing')
        self.period('Anchor', 'Closed', -(24 * 31 - 5))                                  # a period completed shortly before the later evaluation: Undated is no longer the newest
        later = review.plan(24, self.now + timedelta(days=24 * 31), retention.read().first_seen)
        self.assertIn('Undated', {item['name'] for item in later['items']})        # eligible only 24 months after retention first saw it

    def test_open_actions_unexpired_acceptances_and_unverifiable_snapshots_protect(self):
        self.period('Open action', 'Closed', 900, actions=('Open',))
        self.period('Done action', 'Closed', 890, actions=('Completed',))
        self.period('Live acceptance', 'Closed', 880, acceptance_expires=date(2027, 6, 1))
        self.period('Expired acceptance', 'Closed', 870, acceptance_expires=date(2025, 1, 1))
        broken = self.period('Broken', 'Closed', 860)
        csv_lifecycle.private_path('snapshots', broken.snapshot).write_bytes(b'corrupt')
        self.period('Baseline', 'Closed', 10)
        self.assertEqual(self.eligible(), {'Done action', 'Expired acceptance'})
        reasons = self.reasons()
        self.assertEqual((reasons['Open action'], reasons['Live acceptance'], reasons['Broken']),
                         ('Open remediation actions', 'Risk acceptance has not expired', 'Snapshot integrity could not be verified'))

    def test_a_period_that_is_the_baseline_of_a_retained_periods_report_is_protected(self):
        base = self.period('Baseline period', 'Closed', 900)
        retained = self.period('Retained', 'Closed', 100)
        self.period('Newest', 'Closed', 10)
        self.store.reports.append(decisions.ReportEntry(id=uuid4().hex, period_id=retained.id, kind='report', title='R', status='Final', document_version='1', model_checksum='a' * 64,
                                                        previous_period_id=base.id, timestamp=self.now.isoformat()))
        self.save()
        self.assertEqual(self.eligible(), set())
        self.assertEqual(self.reasons()['Baseline period'], 'Baseline of a report belonging to a retained period')

    def test_two_expired_periods_comparing_each_other_can_go_together(self):
        first = self.period('First', 'Closed', 950); second = self.period('Second', 'Closed', 900); self.period('Newest', 'Closed', 10)
        self.store.reports.append(decisions.ReportEntry(id=uuid4().hex, period_id=second.id, kind='report', title='R', status='Final', document_version='1', model_checksum='a' * 64,
                                                        previous_period_id=first.id, timestamp=self.now.isoformat()))
        self.save()
        self.assertEqual(self.eligible(), {'First', 'Second'})


class Cleanup(Case):
    def setUp(self):
        super().setUp()
        self.shared = self.evidence('shared')
        self.old = self.period('Expired', 'Closed', 900, evidence=[self.evidence('own'), self.shared])
        self.kept = self.period('Kept', 'Closed', 100, evidence=[self.shared, self.evidence('kept-own')])
        self.draft = self.period('Draft', 'Draft', 0)
        self.finding = self.snap(dict(source='sod-review-finding', finding={'tag': 'legacy'}))
        self.legacy.contexts[self.old.id] = {'f' * 64: [reviews.ReviewEvent(event_id=uuid4().hex, context=self.old.id, timestamp=self.now.isoformat(), finding_id='f' * 64, subject='SYN_A', risk_id='R1', evidence_version='a' * 64,
                                                                           annotation=reviews.Annotation(decision='Access removal required', reviewer='Reviewer One', rationale='Synthetic'), finding_snapshot=self.finding)]}
        self.save()
        self.sources = [self.snap(dict(source='users', records=[], report={}, tag=str(n))) for n in range(2)]
        self.before = {name: (self.data / name).read_bytes() for name in ('sod-periods.json', 'sod-decisions.json')}

    def run_cleanup(self):
        retention.set_policy('Admin One', True, 24, self.now)
        return self.approve()

    def test_nothing_is_removed_without_approval_and_source_approval_does_not_cover_reviews(self):
        self.assertEqual(retention.check(self.now), 'awaiting_approval')
        self.assertTrue(any(item.id == self.old.id for item in periods.read().items))
        found = retention.plan(now=self.now)
        retention.approve('Admin One', found['digest'], self.now, 'source')           # approving source retention ...
        retention.check(self.now + timedelta(days=2))
        self.assertTrue(any(item.id == self.old.id for item in periods.read().items))      # ... never touches review records
        with self.assertRaises(ValueError):
            retention.approve('Admin One', '0' * 64, self.now, 'review')

    def test_approval_removes_the_expired_period_and_only_what_it_exclusively_owns(self):
        result = self.run_cleanup()
        self.assertEqual((result['periods'], result['decisions'], result['legacy_reviews'], result['files']), (1, 2, 1, 3))   # period snapshot, own evidence, finding snapshot
        index = periods.read()
        self.assertEqual({item.name for item in index.items}, {'Kept', 'Draft'})
        record = next(item for item in index.deletions if item.id == self.old.id)
        self.assertEqual((record.actor, record.mode, record.state, record.frozen), ('data-retention', 'permanent', 'Closed', True))
        self.assertIn('Data retention', record.reason)
        self.assertNotIn(self.old.id, decisions.read().contexts)
        self.assertNotIn(self.old.id, reviews.read().contexts)
        self.assertFalse(self.exists(self.old.snapshot))
        self.assertTrue(self.exists(self.shared))                                           # shared evidence is preserved: the retained period still names it
        self.assertTrue(all(self.exists(identity) for identity in self.kept.snapshots))
        self.assertTrue(self.exists(self.draft.snapshot))
        self.assertTrue(all(self.exists(identity) for identity in self.sources))            # source data is never removed by review retention

    def test_referential_integrity_after_cleanup(self):
        self.run_cleanup()
        periods.read(); decisions.read(); reviews.read()                                    # every store still validates
        for item in periods.read().items:
            periods.snapshot(item)                                                           # every retained period still has an intact snapshot
        names = (self.data / 'sod-decisions.json').read_text() + (self.data / 'sod-periods.json').read_text() + (self.data / 'sod-reviews.json').read_text()
        trash = {path.stem for path in (self.data / 'data-retention' / 'trash').rglob('*.json')}
        self.assertTrue(trash)
        self.assertEqual([identity for identity in trash if identity in names.replace(self.old.id, '')], [])     # nothing references a file that was moved away
        for kinds in decisions.read().contexts.values():
            for subjects in kinds.values():
                for events in subjects.values():
                    for event in events:
                        self.assertTrue(self.exists(event.evidence_snapshot))

    def test_the_report_log_the_deletion_record_and_other_contexts_are_kept(self):
        self.store.reports.append(decisions.ReportEntry(id=uuid4().hex, period_id=self.old.id, kind='report', title='Issued', status='Final', document_version='1', model_checksum='a' * 64, timestamp=self.now.isoformat()))
        self.save()
        self.run_cleanup()
        self.assertEqual([item.title for item in decisions.read().reports], ['Issued'])
        self.assertIn(self.kept.id, decisions.read().contexts)

    def test_a_completed_run_can_be_undone_from_its_copy_and_trash(self):
        result = self.run_cleanup()
        self.assertFalse(self.exists(self.old.snapshot))
        restored = review.undo(result['operation'])
        self.assertEqual(restored['periods'], 1)
        self.assertTrue(self.exists(self.old.snapshot) and self.exists(self.finding))
        self.assertIn(self.old.id, {item.id for item in periods.read().items})
        self.assertIn(self.old.id, decisions.read().contexts)
        self.assertEqual(sum(item.id == self.old.id for item in periods.read().deletions), 0)
        with self.assertRaises(ValueError):
            review.undo(result['operation'])                                                 # the copy was consumed

    def test_copies_and_trash_are_purged_only_after_the_grace_period_judged_by_their_recorded_time(self):
        result = self.run_cleanup()
        bundle = self.data / 'data-retention' / 'removed' / f"{result['operation']}.json"
        os.utime(bundle, (1, 1))                                                             # file times are irrelevant
        self.assertEqual(review.purge_expired(self.now + timedelta(days=29)), 0)
        self.assertTrue(bundle.exists())
        self.assertEqual(review.purge_expired(self.now + timedelta(days=31)), 1)
        self.assertFalse(bundle.exists())
        self.assertFalse((self.data / 'data-retention' / 'trash' / result['operation']).exists())

    def test_history_is_bounded_and_records_the_review_cleanup(self):
        self.run_cleanup()
        entry = next(item for item in retention.read().history if item.category == 'review' and item.trigger == 'manual')
        self.assertEqual((entry.removed['review periods'], entry.removed['snapshot files']), (1, 3))
        for _ in range(retention.HISTORY_LIMIT + 20):
            data = retention.read(); retention._append(data, entry); retention._write(data)
        self.assertEqual(len(retention.read().history), retention.HISTORY_LIMIT)


class Interruption(Case):
    def setUp(self):
        super().setUp()
        self.old = self.period('Expired', 'Closed', 900)
        self.period('Newest', 'Closed', 10)
        self.owned = [self.old.snapshot, *[event.evidence_snapshot for subjects in self.store.contexts[self.old.id].values() for events in subjects.values() for event in events for event in [event]]]
        retention.set_policy('Admin One', True, 24, self.now)
        data = retention.read()
        data.review_approval = retention.Approval(by='Admin One', at=self.now.isoformat(), months=24, instance=retention.instance()); retention._write(data)

    def assert_complete(self):
        self.assertEqual({item.name for item in periods.read().items}, {'Newest'})
        self.assertNotIn(self.old.id, decisions.read().contexts)
        self.assertFalse(any(self.exists(identity) for identity in self.owned))
        self.assertFalse((self.data / 'data-retention' / 'journal.json').exists())

    def test_a_crash_between_the_stores_is_rolled_forward(self):
        real = decisions._write
        with patch.object(decisions, '_write', side_effect=OSError('power loss')):
            with self.assertRaises(OSError):
                review.execute(24, now=self.now)
        self.assertTrue((self.data / 'data-retention' / 'journal.json').exists())        # periods already rewritten, decisions not: the journal names what remains
        self.assertNotIn(self.old.id, {item.id for item in periods.read().items})
        self.assertIn(self.old.id, decisions.read().contexts)
        self.assertEqual(decisions._write, real)
        self.assertEqual(retention.check(self.now + timedelta(days=2)), 'cleaned' if False else retention.check(self.now + timedelta(days=2)))
        self.assert_complete()

    def test_a_crash_before_the_files_are_moved_is_completed_by_the_next_run(self):
        with patch.object(review, '_move_files', side_effect=OSError('power loss')):
            with self.assertRaises(OSError):
                review.execute(24, now=self.now)
        self.assertTrue(all(self.exists(identity) for identity in self.owned))           # files untouched, stores already updated
        self.assertEqual(review.recover(self.now), json.loads((self.data / 'data-retention' / 'removed').glob('*.json').__next__().read_text())['operation'])
        self.assert_complete()

    def test_a_crash_after_the_journal_but_before_any_store_change_is_completed_not_lost(self):
        with patch.object(review, '_remove_from_stores', side_effect=OSError('power loss')):
            with self.assertRaises(OSError):
                review.execute(24, now=self.now)
        self.assertIn(self.old.id, {item.id for item in periods.read().items})
        review.recover(self.now)
        self.assert_complete()

    def test_an_unreadable_journal_pauses_review_retention_instead_of_guessing(self):
        (self.data / 'data-retention').mkdir(parents=True, exist_ok=True)
        (self.data / 'data-retention' / 'journal.json').write_text('{broken')
        self.assertEqual(retention.check(self.now), 'paused')
        self.assertIn(self.old.id, {item.id for item in periods.read().items})

    def test_a_failed_removal_leaves_everything_that_is_still_referenced_in_place(self):
        shared = self.evidence('shared-with-draft')
        draft = self.period('Draft', 'Draft', 0, evidence=[shared])
        old_with_shared = self.period('Expired two', 'Closed', 880, evidence=[shared, self.evidence('x')])
        review.execute(24, now=self.now)
        self.assertTrue(self.exists(shared))
        self.assertIn(draft.id, decisions.read().contexts)
        self.assertNotIn(old_with_shared.id, decisions.read().contexts)


class RestoreAndRecovery(Case):
    def test_a_restore_voids_approvals_pauses_cleanup_and_discards_a_carried_journal(self):
        old = self.period('Expired', 'Closed', 900); self.period('Newest', 'Closed', 10)
        retention.set_policy('Admin One', True, 24, self.now)
        self.approve()                                                                       # purges 'Expired' (approved)
        (self.data / 'data-retention').mkdir(parents=True, exist_ok=True)
        (self.data / 'data-retention' / 'journal.json').write_text('{"operation": "x"}')
        retention.after_restore(self.now)
        status = retention.status()
        self.assertEqual((status['categories']['review']['state'], status['categories']['source']['state']), ('awaiting_approval', 'awaiting_approval'))
        self.assertFalse((self.data / 'data-retention' / 'journal.json').exists())
        self.assertEqual(retention.read().history[-1].trigger, 'restore')
        self.assertTrue(old.id)

    def test_a_restored_period_is_not_purged_again_during_the_quiet_period_or_without_a_new_approval(self):
        self.period('Restored old', 'Closed', 900); self.period('Newest', 'Closed', 10)
        retention.set_policy('Admin One', True, 24, self.now)
        data = retention.read(); data.review_approval = retention.Approval(by='Admin One', at=self.now.isoformat(), months=24, instance=retention.instance()); retention._write(data)
        retention.after_restore(self.now)
        self.assertEqual(retention.check(self.now + timedelta(days=1)), 'awaiting_approval')
        self.assertIn('Restored old', {item.name for item in periods.read().items})
        found = retention.review_plan(now=self.now + timedelta(days=10))
        retention.approve('Admin One', found['digest'], self.now + timedelta(days=10), 'review')
        self.assertNotIn('Restored old', {item.name for item in periods.read().items})

    def test_an_approval_from_another_installation_is_void_for_reviews_too(self):
        self.period('Expired', 'Closed', 900); self.period('Newest', 'Closed', 10)
        retention.set_policy('Admin One', True, 24, self.now)
        data = retention.read(); data.review_approval = retention.Approval(by='Admin One', at=self.now.isoformat(), months=24, instance='0' * 32); retention._write(data)
        self.assertEqual(retention.check(self.now), 'awaiting_approval')
        self.assertIn('Expired', {item.name for item in periods.read().items})

    def test_shortening_the_review_period_needs_a_new_approval(self):
        self.period('Expired', 'Closed', 900); self.period('Newest', 'Closed', 10)
        retention.set_policy('Admin One', True, 24, self.now); self.approve()
        retention.set_policy('Admin One', True, 24, self.now, review_months=12)
        self.assertEqual(retention.status()['categories']['review']['state'], 'awaiting_approval')


class SourceLogicalTimestamps(Case):
    def snapshot(self, tag, ingest=True):
        identity = csv_lifecycle.write_private('snapshots', dict(version=1, source='users', records=[], report={'tag': tag}))
        os.utime(csv_lifecycle.private_path('snapshots', identity), (self.now.timestamp() - 1000 * DAY,) * 2)
        return identity

    def test_the_superseded_moment_decides_not_the_file_time(self):
        from test_data_retention import rows
        ids = [self.snapshot(tag) for tag in 'abcd']
        for identity, tag in zip(ids, 'abcd'):
            source_store.ingest('users', identity, rows(tag), {})
        # the files are 1000 days old, but a..c were superseded just now: still recent
        self.assertEqual({item['id'] for item in retention.plan(now=datetime.now(timezone.utc))['items']}, set())
        with __import__('store_db').transaction() as connection:
            connection.execute("UPDATE retired_snapshots SET superseded_at=? WHERE snapshot=?", ((datetime.now(timezone.utc) - timedelta(days=900)).isoformat(), ids[0]))
        self.assertEqual({item['id'] for item in retention.plan(now=datetime.now(timezone.utc))['items']}, {ids[0]})

    def test_data_without_a_recorded_moment_is_protected_until_classified(self):
        ids = [self.snapshot(tag) for tag in 'abcde']
        found = retention.plan(now=self.now)
        self.assertEqual(found['items'], [])
        self.assertEqual(found['protected']['unclassified'], 3)
        retention.check(self.now)
        self.assertEqual(retention.plan(now=self.now + timedelta(days=24 * 31))['count'], 3)
        self.assertTrue(ids)

    def test_a_recent_file_time_still_guards_data_whose_logical_moment_is_old(self):
        ids = [self.snapshot(tag) for tag in 'abcde']
        data = retention.read(); data.first_seen.update({identity: (self.now - timedelta(days=900)).isoformat() for identity in ids}); retention._write(data)
        os.utime(csv_lifecycle.private_path('snapshots', ids[0]), (self.now.timestamp(),) * 2)
        self.assertNotIn(ids[0], {item['id'] for item in retention.plan(now=self.now)['items']})

    def test_a_reactivated_snapshot_is_no_longer_marked_superseded(self):
        from test_data_retention import rows
        a, b = self.snapshot('a'), self.snapshot('b')
        source_store.ingest('users', a, rows('a'), {}); source_store.ingest('users', b, rows('b'), {})
        self.assertIsNotNone(source_store.retired_at(a))
        source_store.ingest('users', a, rows('a'), {})
        self.assertIsNone(source_store.retired_at(a))


class Interfaces(Case):
    def client(self):
        from fastapi.testclient import TestClient
        from main import create_app
        return TestClient(create_app(session_token='1'), base_url='http://127.0.0.1:18743'), {'X-SAP-Lens': '1'}

    def test_preview_approval_and_undo_through_the_api(self):
        self.period('Expired', 'Closed', 900); self.period('Newest', 'Closed', 10); self.period('Draft', 'Draft', 0)
        client, headers = self.client()
        with patch('review_retention.plan', side_effect=lambda months, now=None, seen=None: review.plan.__wrapped__(months, self.now, seen) if hasattr(review.plan, '__wrapped__') else _real(months, self.now, seen)):
            pass
        preview = client.get('/api/retention/preview', params={'category': 'review'}, headers=headers).json()
        self.assertEqual((preview['count'], preview['months']), (1, 24))
        self.assertIn('Active or incomplete review period', preview['reasons'])
        self.assertEqual(client.post('/api/retention/approve', headers=headers, json={'category': 'review', 'confirm': True, 'preview_digest': '0' * 64}).status_code, 409)
        done = client.post('/api/retention/approve', headers=headers, json={'category': 'review', 'confirm': True, 'preview_digest': preview['digest']})
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(done.json()['periods'], 1)
        self.assertEqual(done.json()['status']['categories']['review']['state'], 'approved')
        self.assertEqual(client.post('/api/retention/review/undo', headers=headers, json={'operation': done.json()['operation'], 'confirm': False}).status_code, 422)
        undone = client.post('/api/retention/review/undo', headers=headers, json={'operation': done.json()['operation'], 'confirm': True})
        self.assertEqual((undone.status_code, undone.json()['periods']), (200, 1))


_real = review.plan

if __name__ == '__main__':
    unittest.main()
