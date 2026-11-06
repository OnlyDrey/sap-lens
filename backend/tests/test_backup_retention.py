"""Backup retention: automatic backups expire by recorded time, manual and migration backups are protected, unreliable metadata is protected."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import application_backups as backups
import backup_retention as retention
import backup_schedule
import cache
from links import symlink
import config
import data_retention
import storage_migration

NOW = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)


class Case(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / 'private'
        self.data.mkdir()
        patcher = patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': str(self.data), 'DATA_CSV_PATH': ''}); patcher.start(); self.addCleanup(patcher.stop)
        config.get_settings.cache_clear(); cache.clear_cache(); self.addCleanup(config.get_settings.cache_clear)
        self.area = backups.area(self.data)

    def backup(self, origin='scheduled', age=100, status='ready', verified=True, digest_ok=True, identity=None, stamp=True, write_archive=True):
        identity = identity or uuid4().hex
        folder = self.area / identity
        folder.mkdir(mode=0o700)
        archive = folder / 'backup.tar.gz'
        if write_archive:
            archive.write_bytes(os.urandom(64))
        created = (NOW - timedelta(days=age)).isoformat()
        value = dict(id=identity, kind='backup', status=status, verified=verified, sha256=backups.engine.digest(archive) if write_archive and digest_ok else 'a' * 64)
        if origin:
            value['origin'] = origin
        if stamp:
            value.update(requested_at=created, completed_at=created)
        backups.write(folder / 'result.json', value)
        return identity

    def exists(self, identity):
        return (self.area / identity / 'backup.tar.gz').exists()

    def record(self, identity):
        return json.loads((self.area / identity / 'result.json').read_text())

    def approve(self):
        found = retention.plan(now=NOW, data=self.data)
        return retention.approve('Admin One', found['digest'], NOW, self.data)

    def eligible(self):
        return {item['id'] for item in retention.plan(now=NOW, data=self.data)['items']}

    def reasons(self):
        return {row['id']: row['reason'] for row in retention.plan(now=NOW, data=self.data)['protected']}


class Classification(Case):
    def test_automatic_backups_expire_after_90_days_from_their_recorded_time_and_younger_ones_stay(self):
        old, edge, young = self.backup(age=91), self.backup(age=90, identity='b' * 32), self.backup(age=89)
        self.assertEqual(self.eligible(), {old})                                         # exactly 90 days is not yet older than the period
        self.assertIn('Younger than 90 days', self.reasons()[young])
        self.assertIn(edge, self.reasons())

    def test_file_times_do_not_decide(self):
        young = self.backup(age=5)
        os.utime(self.area / young / 'backup.tar.gz', (1, 1))
        os.utime(self.area / young / 'result.json', (1, 1))
        self.assertEqual(self.eligible(), set())

    def test_manual_backups_are_never_automatic_candidates_whatever_their_age(self):
        manual = self.backup(origin='manual', age=2000)
        self.assertEqual(self.eligible(), set())
        self.assertIn('Manual backup', self.reasons()[manual])
        self.approve()
        retention.check(NOW + timedelta(days=5), self.data)
        self.assertTrue(self.exists(manual))
        self.assertEqual(self.record(manual)['origin'], 'manual')                         # never reclassified

    def test_missing_unknown_or_corrupt_metadata_is_protected(self):
        no_origin = self.backup(origin=None, age=500)
        unknown = self.backup(origin='imported', age=500)
        no_time = self.backup(age=500, stamp=False)
        unverified = self.backup(age=500, verified=False)
        mismatch = self.backup(age=500, digest_ok=False)
        failed = self.backup(age=500, status='failed')
        corrupt = uuid4().hex; (self.area / corrupt).mkdir(); (self.area / corrupt / 'result.json').write_text('{broken')
        wrong_id = self.backup(age=500, identity='c' * 32); value = self.record(wrong_id); value['id'] = 'd' * 32; backups.write(self.area / wrong_id / 'result.json', value)
        self.assertEqual(self.eligible(), set())
        reasons = self.reasons()
        for identity in (no_origin, unknown, no_time, unverified, mismatch, failed, corrupt, wrong_id):
            self.assertIn(identity, reasons)
            self.assertTrue(self.exists(identity) or identity == corrupt)
        self.assertIn('No reliable classification', reasons[no_origin])
        self.assertEqual(reasons[mismatch], 'Archive does not match its recorded digest')
        self.assertEqual(reasons[wrong_id], 'Metadata does not match the backup folder')

    def test_links_are_never_followed(self):
        link_archive = self.backup(age=500, write_archive=False)
        target = Path(self.temp.name) / 'outside.bin'; target.write_bytes(b'precious')
        symlink(target, self.area / link_archive / 'backup.tar.gz')
        link_folder = Path(self.temp.name) / 'elsewhere'; (link_folder).mkdir()
        symlink(link_folder, self.area / ('e' * 32), directory=True)
        self.assertEqual(self.eligible(), set())
        self.assertEqual(self.reasons()[link_archive], 'Archive is not a regular file')
        self.approve()
        self.assertEqual(target.read_bytes(), b'precious')
        self.assertTrue(link_folder.is_dir())

    def test_migration_backups_are_listed_as_protected_and_never_candidates(self):
        folder = self.area / 'migration'
        for status, identity in (('migrated', '1' * 32), ('confirmed', '2' * 32)):
            (folder / identity).mkdir(parents=True)
            (folder / identity / 'pre-migration.tar.gz').write_bytes(b'x')
            storage_migration._write(self.data, dict(id=identity, created=(NOW - timedelta(days=900)).isoformat(), status=status, backup=dict(sha256='a' * 64, size=1, files=1)))
        self.assertEqual(self.eligible(), set())
        reasons = self.reasons()
        self.assertIn('waiting for administrator confirmation', reasons['1' * 32])
        self.assertIn('delete it explicitly', reasons['2' * 32])
        self.approve()
        self.assertTrue((folder / ('1' * 32) / 'pre-migration.tar.gz').exists() and (folder / ('2' * 32) / 'pre-migration.tar.gz').exists())
        self.assertEqual(retention.plan(now=NOW, data=self.data)['counts']['migration'], 2)


class Approval(Case):
    def test_nothing_is_removed_before_approval_and_the_digest_binds_the_preview(self):
        old = self.backup(age=200)
        self.assertEqual(retention.check(NOW, self.data), 'awaiting_approval')
        self.assertTrue(self.exists(old))
        digest = retention.plan(now=NOW, data=self.data)['digest']
        self.backup(age=300)                                                              # the set changes after the preview
        with self.assertRaises(ValueError):
            retention.approve('Admin One', digest, NOW, self.data)
        self.assertTrue(self.exists(old))
        self.assertIsNone(retention.read(self.data).approval)

    def test_approval_removes_expired_automatic_backups_keeps_the_record_and_cleans_up_automatically_later(self):
        old, young = self.backup(age=200), self.backup(age=10)
        result = self.approve()
        self.assertEqual(result['removed'], 1)
        self.assertFalse(self.exists(old))
        self.assertTrue(self.exists(young))
        self.assertEqual(self.record(old)['status'], 'deleted')                          # audit record kept
        later = self.backup(age=95)
        self.assertEqual(retention.check(NOW + timedelta(hours=1), self.data), 'cleaned')
        self.assertFalse(self.exists(later))
        self.assertTrue(self.exists(young))
        state = retention.read(self.data)
        self.assertEqual([entry.trigger for entry in state.history], ['approval', 'manual', 'automatic'])
        self.assertTrue(state.last_cleanup)

    def test_an_approval_from_another_installation_or_a_shortened_period_does_not_apply(self):
        self.backup(age=200); self.approve()
        state = retention.read(self.data); state.approval = state.approval.model_copy(update=dict(instance='0' * 32)); retention._write(state, self.data)
        late = self.backup(age=300)
        self.assertEqual(retention.check(NOW, self.data), 'awaiting_approval')
        self.assertTrue(self.exists(late))
        state = retention.read(self.data); state.approval = state.approval.model_copy(update=dict(instance=data_retention.instance(), days=90)); retention._write(state, self.data)
        retention.set_policy('Admin One', 30, NOW, self.data)
        self.assertEqual(retention.check(NOW, self.data), 'awaiting_approval')                # shorter than approved: needs a new approval

    def test_policy_bounds(self):
        with self.assertRaises(ValueError):
            retention.Policy(days=3)
        self.assertEqual(retention.read(self.data).policy.days, 90)


class Safety(Case):
    def test_nothing_is_removed_while_an_operation_is_pending_and_new_backups_are_untouched(self):
        old = self.backup(age=300); self.approve()
        another = self.backup(age=300)
        pending = backups.request_backup(self.data, origin='scheduled')                      # a scheduled backup is waiting for the restart
        outcome = retention.execute(now=NOW, data=self.data)
        self.assertIn('skipped', outcome)
        self.assertTrue(self.exists(another))
        retention.check(NOW, self.data)                                                    # the daily check meanwhile removes nothing either
        self.assertTrue(self.exists(another))
        self.assertEqual(self.record(pending['id'])['status'], 'waiting_for_restart')      # the new backup is never classified as expired
        self.assertFalse(self.exists(old))

    def test_a_staged_restore_protects_its_archive(self):
        old = self.backup(age=300)
        sha = self.record(old)['sha256']
        staged = self.area / uuid4().hex; staged.mkdir()
        backups.write(staged / 'preview.json', dict(archive_sha256=sha))
        self.assertEqual(self.eligible(), set())
        self.assertEqual(self.reasons()[old], 'Protects a staged restore')

    def test_a_backup_created_during_cleanup_survives(self):
        first = self.backup(age=300); self.approve()
        second = self.backup(age=300)
        created = []
        real = backup_schedule.remove
        def remove_and_create(identity, confirm, data=None):
            created.append(self.backup(age=0))                                                # a backup appears mid-run
            return real(identity, confirm, data)
        with patch.object(backup_schedule, 'remove', remove_and_create):
            retention.execute(now=NOW, data=self.data)
        self.assertFalse(self.exists(second))
        self.assertTrue(all(self.exists(identity) for identity in created))
        self.assertTrue(first)

    def test_an_interrupted_cleanup_is_finished_and_repeating_it_changes_nothing(self):
        stale = self.backup(age=400); self.approve()
        half = self.backup(age=400)
        (self.area / half / 'backup.tar.gz').unlink()                                         # crash after the archive was removed, before the record was updated
        self.assertEqual(self.record(half)['status'], 'ready')
        self.assertEqual(self.eligible(), {half})
        retention.execute(now=NOW, data=self.data)
        self.assertEqual(self.record(half)['status'], 'deleted')
        before = retention.read(self.data).history
        retention.execute(now=NOW, data=self.data)
        self.assertEqual(retention.read(self.data).history, before)                          # nothing left to do
        self.assertEqual(retention.plan(now=NOW, data=self.data)['count'], 0)
        self.assertTrue(stale)

    def test_a_failed_removal_leaves_the_backup_and_is_retried(self):
        self.backup(age=300); self.approve()
        victim = self.backup(age=300)
        with patch.object(backup_schedule, 'remove', side_effect=ValueError('An active operation prevents archive deletion.')):
            self.assertEqual(retention.execute(now=NOW, data=self.data)['removed'], 0)
        self.assertTrue(self.exists(victim))
        retention.execute(now=NOW, data=self.data)
        self.assertFalse(self.exists(victim))

    def test_the_existing_count_limit_still_works_independently(self):
        for number in range(9):
            self.backup(age=number)
        backup_schedule.retention(self.data)
        remaining = [identity for identity in os.listdir(self.area) if backups.ID.fullmatch(identity) and (self.area / identity / 'backup.tar.gz').exists()]
        self.assertEqual(len(remaining), 7)                                                   # keep=7 as before, without approval

    def test_the_preview_names_the_rule_of_every_candidate_and_the_period_is_a_maximum_not_a_minimum(self):
        old = [self.backup(age=200 + number) for number in range(3)]                           # older than 90 days, beyond the newest 7
        recent = [self.backup(age=number) for number in range(9)]                              # younger than 90 days; the 8th and 9th are beyond the newest 7
        found = retention.plan(now=NOW, data=self.data)
        self.assertEqual(found['keep'], 7)
        self.assertEqual({item['id'] for item in found['items']}, set(old))
        for item in found['items']:
            self.assertEqual(item['rules'], ['age', 'count'])                                 # both rules apply: older than 90 days and beyond the newest 7
            self.assertIn('Older than 90 days and beyond the newest 7', item['rule'])
        early = {item['id'] for item in found['count_limit']}
        self.assertEqual(early, set(recent[7:]))                                              # removed long before 90 days by the count limit, no approval
        self.assertTrue(all('count limit' in item['rule'] for item in found['count_limit']))
        self.assertTrue(early.isdisjoint(self.eligible()))
        backup_schedule.retention(self.data)                                                  # the count rule really removes exactly what the preview said
        gone = {identity for identity in old + recent if not self.exists(identity)}
        self.assertEqual(gone, set(old) | early)

    def test_an_age_only_candidate_is_labelled_with_the_age_rule_alone(self):
        for number in range(3):
            self.backup(age=number)
        old = self.backup(age=120)                                                            # fewer than 7 newer backups: only the age rule applies
        item = next(row for row in retention.plan(now=NOW, data=self.data)['items'] if row['id'] == old)
        self.assertEqual(item['rules'], ['age'])
        self.assertEqual(item['rule'], 'Older than 90 days')
        self.assertEqual(retention.plan(now=NOW, data=self.data)['count_limit'], [])
        self.assertEqual(retention.status(self.data, NOW)['keep'], 7)


class RestoreAndCompatibility(Case):
    def test_a_restore_does_not_void_the_backup_approval_or_bring_back_old_state(self):
        self.backup(age=300); self.approve()
        data_retention.after_restore(NOW)                                                      # source and review approvals are voided by a restore ...
        self.assertTrue(retention.status(self.data)['approval']['valid'])                     # ... the backup approval lives with the backups and is untouched
        late = self.backup(age=300)
        self.assertEqual(retention.check(NOW, self.data), 'cleaned')
        self.assertFalse(self.exists(late))

    def test_cleanup_does_not_break_creating_or_listing_backups_afterwards(self):
        self.backup(age=300); self.approve()
        fresh = backups.request_backup(self.data, origin='manual')
        rows = backup_schedule.rows(self.data)
        self.assertIn(fresh['id'], {row['id'] for row in rows})
        self.assertEqual(backup_schedule.history(self.data)['total'], len(rows))

    def test_existing_installations_without_metadata_are_untouched(self):
        legacy = self.backup(origin=None, age=2000)                                           # as created before backups carried an origin
        self.assertFalse((self.area / 'retention.json').exists())
        self.assertEqual(retention.read(self.data).policy.days, 90)
        self.assertEqual(retention.check(NOW, self.data), 'nothing')
        self.approve()
        self.assertTrue(self.exists(legacy))

    def test_restore_of_a_deleted_backups_record_does_not_resurrect_an_archive(self):
        old = self.backup(age=300); self.approve()
        self.assertEqual(retention.plan(now=NOW, data=self.data)['count'], 0)
        self.assertFalse(self.exists(old))


class Interfaces(Case):
    def client(self):
        from fastapi.testclient import TestClient
        from main import create_app
        return TestClient(create_app(session_token='1'), base_url='http://127.0.0.1:18743'), {'X-SAP-Lens': '1'}

    def test_api_preview_approval_policy_and_status(self):
        old = self.backup(age=now_age())
        self.backup(origin='manual', age=now_age())
        client, headers = self.client()
        status = client.get('/api/retention', headers=headers).json()['categories']['backup']
        self.assertEqual((status['days'], status['state']), (90, 'awaiting_approval'))
        preview = client.get('/api/retention/preview', params={'category': 'backup'}, headers=headers).json()
        self.assertEqual((preview['count'], preview['days'], preview['counts']['manual']), (1, 90, 1))
        self.assertEqual(client.put('/api/retention/policy', headers=headers, json={'enabled': True, 'months': 24, 'backup_days': 3}).status_code, 422)
        self.assertEqual(client.post('/api/retention/approve', headers=headers, json={'category': 'backup', 'confirm': True, 'preview_digest': '0' * 64}).status_code, 409)
        done = client.post('/api/retention/approve', headers=headers, json={'category': 'backup', 'confirm': True, 'preview_digest': preview['digest']})
        self.assertEqual((done.status_code, done.json()['removed']), (200, 1), done.text)
        self.assertFalse(self.exists(old))
        saved = client.put('/api/retention/policy', headers=headers, json={'enabled': True, 'months': 24, 'backup_days': 120}).json()
        self.assertEqual(saved['categories']['backup']['days'], 120)


def now_age():
    """Days between the fixed test clock and the real clock plus 400: API calls use the real clock, so the backup must be old for it too."""
    return (datetime.now(timezone.utc) - NOW).days + 400


if __name__ == '__main__':
    unittest.main()
