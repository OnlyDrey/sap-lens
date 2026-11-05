"""Data retention: narrow scope, protection by reference and age, one-time approval, SQLite/JSON consistency, interrupted-run recovery."""
import hashlib
import json
import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cache
import config
import csv_lifecycle
import data_retention as retention
import persistent_cache
import source_store
import store_db
from config_models import USER_FIELDS

DAY = 86400


def rows(tag, count=3):
    return [{**{name: '' for name in USER_FIELDS}, 'USERNAME': f'{tag}{n}', 'ROLE_NAME': 'Z:R'} for n in range(count)]


class Case(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / 'private'
        patcher = patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': str(self.data), 'DATA_CSV_PATH': ''}); patcher.start(); self.addCleanup(patcher.stop)
        config.get_settings.cache_clear(); cache.clear_cache(); self.addCleanup(config.get_settings.cache_clear); self.addCleanup(cache.clear_cache)
        self.now = datetime.now(timezone.utc)

    def log(self, name, age_days):
        """The logical moment retention knows for an item (first seen unreferenced / superseded), age_days ago."""
        moment = (self.now - timedelta(days=age_days)).isoformat()
        data = retention.read(); data.first_seen[name] = moment; retention._write(data)
        try:
            with store_db.transaction() as connection:
                connection.execute('UPDATE retired_snapshots SET superseded_at=? WHERE snapshot=?', (moment, name))
        except Exception:  # noqa: BLE001
            pass

    def snapshot(self, source='users', tag='a', age_days=900, ingest=False):
        identity = csv_lifecycle.write_private('snapshots', dict(version=1, source=source, records=rows(tag), report={'tag': tag}))
        path = csv_lifecycle.private_path('snapshots', identity)
        os.utime(path, (self.now.timestamp() - age_days * DAY,) * 2)
        if ingest:
            source_store.ingest(source, identity, rows(tag), {'tag': tag})
        self.log(identity, age_days)
        return identity

    def other(self, source, tag, age_days=900):
        """A non-source snapshot (decision evidence, period capture, review finding)."""
        identity = csv_lifecycle.write_private('snapshots', dict(version=1, source=source, evidence={'tag': tag}))
        os.utime(csv_lifecycle.private_path('snapshots', identity), (self.now.timestamp() - age_days * DAY,) * 2)
        return identity

    def store(self, name, value):
        path = self.data / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        return path

    def exists(self, identity):
        return csv_lifecycle.private_path('snapshots', identity).exists()

    def plan(self):
        return retention.plan(now=self.now)

    def approve(self):
        return retention.approve('Admin One', self.plan()['digest'], self.now)


class Scope(Case):
    def test_defaults_are_24_months_enabled_and_unapproved(self):
        value = retention.status()
        self.assertEqual((value['policy'], value['categories']['source']['state'], value['categories']['source']['approval']), ({'enabled': True, 'months': 24, 'review_months': 24}, 'awaiting_approval', None))
        self.assertEqual(value['categories']['review']['state'], 'awaiting_approval')

    def test_only_superseded_unreferenced_old_snapshots_beyond_the_newest_two_are_candidates(self):
        old = [self.snapshot('users', tag, 1000 - n * 10) for n, tag in enumerate('abcde')]       # a is the oldest ... e the newest
        recent = self.snapshot('users', 'z', 100)                                                 # younger than 24 months
        found = self.plan()
        removable = {item['id'] for item in found['items']}
        self.assertEqual(removable, set(old[:4]))                                                 # the two newest overall (z and e) stay as previous approved revisions
        self.assertNotIn(recent, removable)
        self.assertEqual(found['categories']['users snapshots']['count'], 4)
        self.assertEqual(found['protected']['kept_newest'], 2)

    def test_references_anywhere_in_the_json_stores_or_in_other_snapshots_protect(self):
        a, b, c, d = (self.snapshot('users', tag, 1000) for tag in 'abcd')
        spare = [self.snapshot('users', tag, 900 - n) for n, tag in enumerate('vwxyz')]           # v is the oldest unreferenced
        self.store('sod-periods.json', {'periods': [{'snapshots': [a], 'nested': {'deep': [b]}}]})                    # a period's frozen evidence
        evidence = self.other('sod-decision-evidence', 'e1')
        decision = self.store('sod-decisions.json', {'events': [{'source_versions': {'users': c}, 'evidence_snapshot': evidence}]})
        self.store('configuration-backups/old.json', {'sources': {'users': d}})                                       # recovery copies still protect
        found = {item['id'] for item in self.plan()['items']}
        self.assertTrue({a, b, c, d}.isdisjoint(found))
        self.assertNotIn(evidence, found)                                                                              # not a source snapshot: never a candidate
        self.assertEqual(found, set(spare[:3]))                                                                        # only unreferenced ones beyond the newest two
        self.assertTrue(decision.exists())

    def test_unclassified_and_non_source_snapshots_are_never_candidates_and_their_references_count(self):
        target = self.snapshot('users', 'q'); keep1, keep2 = self.snapshot('users', 'r', 800), self.snapshot('users', 's', 790)
        period = csv_lifecycle.write_private('snapshots', dict(version=1, source='sod-period', captured={'users': target}))
        unknown = csv_lifecycle.private_path('snapshots', hashlib.sha256(b'unknown').hexdigest())
        unknown.write_bytes(b'not json at all')
        for path in (csv_lifecycle.private_path('snapshots', period), unknown):
            os.utime(path, (self.now.timestamp() - 2000 * DAY,) * 2)
        found = {item['id'] for item in self.plan()['items']}
        self.assertNotIn(target, found)                                                                                # named by a period snapshot
        self.assertNotIn(period, found)
        self.assertNotIn(unknown.stem, found)
        self.assertEqual(found, set())
        self.assertTrue(keep1 and keep2)

    def test_employee_directory_snapshots_follow_the_same_rules(self):
        folder = self.data / 'employee-directory'; folder.mkdir(parents=True)
        ids = []
        for n in range(4):
            identity = hashlib.sha256(f'dir{n}'.encode()).hexdigest()
            path = folder / f'{identity}.json'; path.write_text('{"version":1}')
            os.utime(path, (self.now.timestamp() - (900 + n) * DAY,) * 2)
            self.log(identity, 900 + n)
            ids.append(identity)
        self.store('settings.json', {'employee_snapshot_id': ids[3]})                                                  # the active one is referenced
        found = {item['id'] for item in self.plan()['items'] if item['category'] == 'directory snapshots'}
        self.assertEqual(found, {ids[2]})                                                                              # ids[3] is referenced; the two newest others are kept

    def test_diagnostic_leftovers_are_candidates_only_when_old(self):
        store_db.private_directory()
        old, young = store_db.directory() / 'sap-lens.sqlite3.corrupt-1', store_db.directory() / 'sap-lens.sqlite3.corrupt-2'
        for path, age in ((old, 900), (young, 3)):
            path.write_bytes(b'x'); os.utime(path, (self.now.timestamp() - age * DAY,) * 2); self.log(path.name, age)
        self.assertEqual({item['id'] for item in self.plan()['items']}, {old.name})


class Approval(Case):
    def setUp(self):
        super().setUp()
        self.ids = [self.snapshot('users', tag, 1000 - n * 10) for n, tag in enumerate('abcde')]
        self.decisions = self.store('sod-decisions.json', {'version': 1, 'revision': 3, 'contexts': {}, 'actions': {}, 'reports': []})
        self.periods = self.store('sod-periods.json', {'version': 1, 'revision': 2, 'items': [], 'deletions': []})
        self.before = (self.decisions.read_bytes(), self.periods.read_bytes())

    def test_nothing_is_removed_before_the_first_approval_even_by_the_daily_check(self):
        self.assertEqual(retention.check(self.now), 'awaiting_approval')
        self.assertTrue(all(self.exists(identity) for identity in self.ids))
        self.assertEqual(retention.read().last_preview['source']['count'], 3)

    def test_approval_is_bound_to_the_previewed_data(self):
        digest = self.plan()['digest']
        self.snapshot('users', 'late', 950)                                                                            # something changes after the preview
        with self.assertRaises(ValueError):
            retention.approve('Admin One', digest, self.now)
        self.assertTrue(all(self.exists(identity) for identity in self.ids))
        self.assertIsNone(retention.read().approval)

    def test_approval_runs_the_first_cleanup_and_keeps_decisions_and_periods_byte_identical(self):
        result = self.approve()
        self.assertEqual(result['removed'], {'users snapshots': 3})
        self.assertEqual([self.exists(identity) for identity in self.ids], [False, False, False, True, True])
        self.assertEqual((self.decisions.read_bytes(), self.periods.read_bytes()), self.before)
        history = retention.read().history
        self.assertEqual([(entry.trigger, entry.by) for entry in history], [('approval', 'Admin One'), ('manual', 'Admin One')])
        self.assertTrue(retention.status()['categories']['source']['approval']['valid'])

    def test_later_cleanups_run_automatically_on_the_daily_schedule(self):
        self.approve()
        extra = self.snapshot('users', 'next', 990)
        self.assertEqual(retention.tick(self.now + timedelta(hours=1)), 'idle')                                       # checked less than 24 h ago
        self.assertTrue(self.exists(extra))
        self.assertEqual(retention.tick(self.now + timedelta(hours=25)), 'cleaned')
        self.assertEqual([self.exists(self.ids[3]), self.exists(extra)], [True, False])                               # the two newest stay; the older extra goes

    def test_shortening_the_period_needs_a_new_approval_lengthening_does_not(self):
        self.approve()
        retention.set_policy('Admin One', True, 12, self.now)
        self.assertEqual(retention.status()['categories']['source']['state'], 'awaiting_approval')
        fresh = self.snapshot('users', 'mid', 500)
        self.assertEqual(retention.check(self.now + timedelta(days=2)), 'awaiting_approval')
        self.assertTrue(self.exists(fresh))
        retention.set_policy('Admin One', True, 36, self.now)
        self.assertEqual(retention.status()['categories']['source']['state'], 'approved')

    def test_an_approval_restored_onto_another_installation_is_void(self):
        self.approve()
        data = retention.read(); data.approval = data.approval.model_copy(update=dict(instance='0' * 32)); retention._write(data)
        self.assertEqual(retention.status()['categories']['source']['state'], 'awaiting_approval')
        self.snapshot('users', 'next', 990)
        self.assertEqual(retention.check(self.now + timedelta(days=2)), 'awaiting_approval')

    def test_disabled_retention_never_checks_or_removes(self):
        self.approve()
        retention.set_policy('Admin One', False, 24, self.now)
        self.assertEqual(retention.tick(self.now + timedelta(days=5)), 'idle')
        self.assertEqual(retention.check(self.now + timedelta(days=5)), 'disabled')

    def test_a_restore_that_resets_file_times_removes_nothing(self):
        self.approve()
        extra = self.snapshot('users', 'old', 1200)
        for path in (self.data / 'csv-data' / 'snapshots').glob('*.json'):
            os.utime(path)                                                                                             # as after extracting an archive
        self.assertEqual(retention.check(self.now + timedelta(days=2)), 'nothing')
        self.assertTrue(self.exists(extra))

    def test_scan_failure_removes_nothing(self):
        self.approve()
        extra = self.snapshot('users', 'next', 990)
        with patch.object(retention, '_ids', side_effect=OSError('unreadable')):
            self.assertEqual(retention.tick(self.now + timedelta(hours=25)), 'failed')
        self.assertTrue(self.exists(extra))


class Consistency(Case):
    def test_sqlite_revisions_and_derived_values_of_removed_snapshots_go_first_and_the_active_one_stays(self):
        ids = [self.snapshot('users', tag, 1000 - n * 10, ingest=True) for n, tag in enumerate('abcdef')]
        for n, identity in enumerate(ids):
            self.log(identity, 1000 - n * 10)                                                                          # superseded moments are recorded when the next import activates
        active = source_store.active('users')['snapshot']
        oldest = source_store.revision_id('users', ids[0])
        persistent_cache.put('users', 'dep-oldest', {'v': 1}, revisions=(oldest,)) if oldest else None
        persistent_cache.put('users', 'dep-active', {'v': 2}, revisions=(source_store.active('users')['id'],))
        self.assertEqual(active, ids[-1])
        Approval.approve(self)
        self.assertEqual(source_store.revision_id('users', ids[0]), None) if not self.exists(ids[0]) else None
        self.assertFalse(self.exists(ids[0]))
        self.assertIsNone(persistent_cache.get('users', 'dep-oldest'))
        self.assertEqual(persistent_cache.get('users', 'dep-active'), {'v': 2})
        self.assertEqual(source_store.active('users')['snapshot'], active)
        self.assertIsNotNone(source_store.read('users', active))
        self.assertEqual(store_db.health(), [])

    def test_an_interrupted_cleanup_is_completed_by_the_next_run(self):
        ids = [self.snapshot('users', tag, 1000 - n * 10, ingest=True) for n, tag in enumerate('abcde')]
        Approval.approve(self)
        later = self.snapshot('users', 'x', 995, ingest=True)                                                          # superseded as soon as the next import is active
        newer = self.snapshot('users', 'n', 5, ingest=True)
        self.log(later, 995)
        real = Path.unlink
        calls = []
        def failing(path, *args, **kwargs):
            if path.name == f'{later}.json' and not calls:
                calls.append(1); raise OSError('crash')
            return real(path, *args, **kwargs)
        with patch.object(Path, 'unlink', failing):
            result = retention.execute('automatic', now=self.now)
        self.assertEqual(result['errors'], 1)
        self.assertTrue(self.exists(later))
        self.assertIsNone(source_store.revision_id('users', later))                                                    # derived copy already gone, authoritative file still there
        self.assertEqual(retention.read().history[-1].status, 'partial')
        retention.execute('automatic', now=self.now)
        self.assertFalse(self.exists(later))
        self.assertTrue(self.exists(newer) and self.exists(ids[-1]))

    def test_store_revisions_whose_file_vanished_are_removed(self):
        ids = [self.snapshot('users', tag, 900, ingest=True) for tag in 'abc']
        csv_lifecycle.private_path('snapshots', ids[0]).unlink()
        self.assertGreaterEqual(source_store.drop_missing(lambda snapshot: csv_lifecycle.private_path('snapshots', snapshot).exists()), 1)
        self.assertIsNone(source_store.revision_id('users', ids[0]))
        self.assertIsNotNone(source_store.active('users'))

    def test_symlinks_are_never_followed_or_removed(self):
        ids = [self.snapshot('users', tag, 1000 - n * 10) for n, tag in enumerate('abcd')]
        Approval.approve(self)
        victim = Path(self.temp.name) / 'outside.json'; victim.write_text('precious')
        target = self.snapshot('users', 'link', 980)
        path = csv_lifecycle.private_path('snapshots', target)
        path.unlink(); os.symlink(victim, path)
        retention.execute('automatic', now=self.now)
        self.assertEqual(victim.read_text(), 'precious')
        self.assertTrue(ids)

    def test_concurrent_cleanups_and_new_imports_do_not_conflict(self):
        for n, tag in enumerate('abcdef'):
            self.snapshot('users', tag, 1000 - n * 10, ingest=True)
        Approval.approve(self)
        errors = []
        def clean():
            try:
                retention.execute('automatic', now=self.now)
            except Exception as error:  # noqa: BLE001
                errors.append(error)
        def import_new():
            try:
                for n in range(3):
                    identity = csv_lifecycle.write_private('snapshots', dict(version=1, source='users', records=rows(f'n{n}'), report={}))
                    source_store.ingest('users', identity, rows(f'n{n}'), {})
            except Exception as error:  # noqa: BLE001
                errors.append(error)
        threads = [threading.Thread(target=clean), threading.Thread(target=clean), threading.Thread(target=import_new)]
        for item in threads: item.start()
        for item in threads: item.join(timeout=60)
        self.assertEqual(errors, [])
        self.assertEqual(store_db.health(), [])
        active = source_store.active('users')
        self.assertTrue(self.exists(active['snapshot']))                                                               # a fresh snapshot is protected by its age


class Interfaces(Case):
    def client(self):
        from fastapi.testclient import TestClient
        from main import create_app
        return TestClient(create_app(session_token='1'), base_url='http://127.0.0.1:18743'), {'X-SAP-Lens': '1'}

    def test_api_policy_preview_and_approval(self):
        ids = [self.snapshot('users', tag, 1000 - n * 10) for n, tag in enumerate('abcd')]
        client, headers = self.client()
        self.assertEqual(client.get('/api/retention', headers=headers).json()['categories']['source']['state'], 'awaiting_approval')
        self.assertEqual(client.put('/api/retention/policy', headers=headers, json={'enabled': True, 'months': 3}).status_code, 422)
        self.assertEqual(client.put('/api/retention/policy', headers=headers, json={'enabled': True, 'months': 200}).status_code, 422)
        preview = client.get('/api/retention/preview', headers=headers).json()
        self.assertEqual((preview['count'], preview['months']), (2, 24))
        self.assertTrue(preview['sample'] and 'path' not in preview['sample'][0])
        self.assertEqual(client.post('/api/retention/approve', headers=headers, json={'confirm': False, 'preview_digest': preview['digest']}).status_code, 422)
        self.assertEqual(client.post('/api/retention/approve', headers=headers, json={'confirm': True, 'preview_digest': '0' * 64}).status_code, 409)
        self.assertTrue(all(self.exists(identity) for identity in ids))
        done = client.post('/api/retention/approve', headers=headers, json={'confirm': True, 'preview_digest': preview['digest']})
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(done.json()['removed'], {'users snapshots': 2})
        self.assertEqual(done.json()['status']['categories']['source']['state'], 'approved')

    def test_the_settings_file_validates_for_backup_and_restore(self):
        self.approve()
        from application_backups import validate_store
        self.store('settings.json', {})
        retention.Storage.model_validate_json((self.data / retention.FILE).read_bytes())
        self.assertTrue(callable(validate_store))

    def test_the_scheduler_hook_skips_while_a_load_is_running(self):
        loader = type('Loader', (), {'loading': True})()
        self.assertEqual(retention.tick(self.now, loader), 'skipped')
        self.assertEqual(retention.tick(self.now, type('Loader', (), {'loading': False})()), 'nothing')
        self.assertEqual(retention.tick(self.now, None), 'idle')

    def approve(self):
        for n, tag in enumerate('abc'):
            self.snapshot('users', tag, 1000 - n * 10)
        return retention.approve('Admin One', retention.plan(now=self.now)['digest'], self.now)


if __name__ == '__main__':
    unittest.main()
