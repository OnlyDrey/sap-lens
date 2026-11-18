"""Anomaly detection holds suspicious but valid replacements, never invalid ones, and never touches what is active."""
import csv
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cache
import config
import csv_lifecycle
import import_checks as checks
from config_models import ImportChecks

HEADER = 'USERNAME,ROLE_NAME,EMAIL,USER_GROUP,USER_VALID_FROM,USER_VALID_TO,ROLE_VALID_FROM,ROLE_VALID_TO'.split(',')
ROLES = 'FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT\nFI,Z:FI,Finance,Z:FI:READ,Read,FB03,Display\n'


def rows(users, per_user=2, groups=('FIN', 'MM')):
    return [[f'U{u:03d}', f'Z:FI:{r}', f'u{u}@example.test', groups[u % len(groups)], '20200101', '99991231', '20200101', '99991231'] for u in range(users) for r in range(per_user)]


class Evaluate(unittest.TestCase):
    def rec(self, users, per_user=2, groups=('FIN', 'MM')):
        return [dict(zip(HEADER, row)) for row in rows(users, per_user, groups)]

    def test_drop_beyond_threshold_is_suspicious_and_reports_old_and_new(self):
        result = checks.evaluate('users', self.rec(40), self.rec(20), ImportChecks())
        self.assertTrue(result['suspicious'])
        metrics = {a['metric']: a for a in result['anomalies'] if a['rule'] == 'drop'}
        self.assertEqual((metrics['records']['old'], metrics['records']['new'], metrics['records']['percent']), (80, 40, 50.0))
        self.assertEqual((metrics['SAP users']['old'], metrics['SAP users']['new']), (40, 20))
        self.assertEqual(result['old']['records'], 80)

    def test_small_reduction_unchanged_and_growth_are_normal(self):
        for after in (self.rec(40), self.rec(36), self.rec(80)):
            self.assertFalse(checks.evaluate('users', self.rec(40), after, ImportChecks())['suspicious'])

    def test_threshold_is_configurable_and_checks_can_be_disabled(self):
        self.assertTrue(checks.evaluate('users', self.rec(40), self.rec(36), ImportChecks(max_drop_percent=5))['suspicious'])
        self.assertFalse(checks.evaluate('users', self.rec(40), self.rec(10), ImportChecks(enabled=False))['suspicious'])
        self.assertFalse(checks.evaluate('users', self.rec(5), self.rec(1), ImportChecks(min_previous_records=50))['suspicious'])  # small sources are never held

    def test_a_vanished_organizational_group_is_flagged_even_without_a_large_drop(self):
        before = self.rec(40, groups=('FIN', 'MM', 'HR'))
        after = [row for row in before if row['USER_GROUP'] != 'HR']
        result = checks.evaluate('users', before, after, ImportChecks(max_drop_percent=60))
        self.assertEqual([(a['rule'], a['group']) for a in result['anomalies']], [('group_missing', 'hr')])

    def test_other_sources_use_their_own_entities(self):
        before = [{'AGR_NAME': f'R{i}', 'TCODE': f'T{i}', 'FUNCTION_KEY': 'FI'} for i in range(40)]
        self.assertTrue(checks.evaluate('roles', before, before[:10], ImportChecks())['suspicious'])
        employees = [{'SamAccountName': f'a{i}', 'Department': 'X'} for i in range(40)]
        self.assertTrue(checks.evaluate('employees', employees, employees[:5], ImportChecks())['suspicious'])
        self.assertEqual(checks.metrics('sod', [{'RISK': 'R1'}, {'RISK': 'r1'}, {'RISK': 'R2'}])['risks'], 2)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patcher = patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': str(self.root / 'private'), 'DATA_CSV_PATH': ''}); patcher.start(); self.addCleanup(patcher.stop)
        config.get_settings.cache_clear(); cache.clear_cache(); self.addCleanup(cache.clear_cache); self.addCleanup(config.get_settings.cache_clear)
        (self.root / 'roles.csv').write_text(ROLES)
        self.write(40)
        settings = config.get_settings().model_copy(deep=True)
        settings.data_csv_path = str(self.root / 'roles.csv'); settings.user_csv_path = str(self.root / 'users.csv')
        config.save_configuration(settings, settings.revision)

    def write(self, users, **kwargs):
        with (self.root / 'users.csv').open('w', newline='') as stream:
            writer = csv.writer(stream); writer.writerow(HEADER); writer.writerows(rows(users, **kwargs))

    def imported(self, confirm=(), strict=True):
        return csv_lifecycle.load(config.get_settings(), operation='import', strict=strict, force=('users',), confirm=confirm)

    def active_users(self):
        return len(cache.get_snapshot().users.users)

class Lifecycle(Fixture):
    def test_first_import_is_never_held_and_identical_reimport_is_unchanged(self):
        self.imported()
        self.assertEqual(self.active_users(), 40)
        report = self.imported()
        self.assertEqual(next(s for s in report['sources'] if s['source'] == 'users')['status'], 'unchanged')
        self.assertEqual(self.active_users(), 40)

    def test_suspicious_shrink_is_held_and_previous_data_and_settings_are_untouched(self):
        self.imported()
        revision, active = config.get_settings().revision, config.get_settings().data_lifecycle.sources['users'].snapshot
        self.write(15)
        with self.assertRaises(checks.ImportHeld) as held:
            self.imported()
        self.assertEqual(held.exception.detail()['code'], 'import_needs_confirmation')
        self.assertEqual(self.active_users(), 40)
        self.assertEqual((config.get_settings().revision, config.get_settings().data_lifecycle.sources['users'].snapshot), (revision, active))
        self.assertEqual(config.get_settings().data_lifecycle.confirmations, [])

    def test_confirmation_activates_and_records_who_what_and_why(self):
        self.imported(); self.write(15)
        with patch('server_access.actor', return_value='Admin One'):
            self.imported(confirm=('users',))
        self.assertEqual(self.active_users(), 15)
        entry = config.get_settings().data_lifecycle.confirmations[-1]
        self.assertEqual((entry.source, entry.actor, entry.old_records, entry.new_records), ('users', 'Admin One', 80, 30))
        self.assertTrue(any('fell from' in text for text in entry.anomalies))
        self.imported()                                           # comparing again is against the newly active revision: no new anomaly
        self.assertEqual(self.active_users(), 15)

    def test_a_confirmation_for_one_source_does_not_cover_another(self):
        self.imported(); self.write(15)
        with self.assertRaises(checks.ImportHeld):
            self.imported(confirm=('roles',))

    def test_refresh_reports_a_held_source_as_failed_with_previous_preserved_and_a_report(self):
        self.imported(); self.write(15)
        report = csv_lifecycle.load(config.get_settings(), operation='refresh', force=('users',))
        row = next(s for s in report['sources'] if s['source'] == 'users')
        self.assertEqual((row['status'], row['category'], row['severity'], row['confirmable'], row['previous_preserved']), ('failed', 'needs_confirmation', 'suspicious', True, True))
        self.assertTrue(row['anomalies'] and row['old']['records'] == 80 and row['new']['records'] == 30)
        self.assertEqual(self.active_users(), 40)

    def test_invalid_files_are_rejected_not_held_and_cannot_be_confirmed(self):
        self.imported()
        (self.root / 'users.csv').write_text(','.join(HEADER) + '\n')   # structurally valid header, no records
        with self.assertRaises(Exception) as caught:
            self.imported(confirm=('users',))
        self.assertNotIsInstance(caught.exception, checks.ImportHeld)
        (self.root / 'users.csv').write_text('X,Y\n1,2\n')
        report = csv_lifecycle.load(config.get_settings(), operation='refresh', force=('users',))
        row = next(s for s in report['sources'] if s['source'] == 'users')
        self.assertEqual((row['status'], row['severity'], row['confirmable']), ('failed', 'invalid', False))
        self.assertEqual(self.active_users(), 40)

    def test_threshold_setting_is_applied(self):
        self.imported(); self.write(37)
        settings = config.get_settings().model_copy(deep=True); settings.import_checks = ImportChecks(max_drop_percent=5)
        config.save_configuration(settings, settings.revision)
        with self.assertRaises(checks.ImportHeld):
            self.imported()


class Api(Fixture):
    """The select endpoint answers a held import with a structured 409 and activates only when confirmation is sent."""
    def setUp(self):
        super().setUp()
        from fastapi.testclient import TestClient
        from main import create_app
        self.client = TestClient(create_app(session_token='1'), base_url='http://127.0.0.1:18743')
        self.H = {'X-SAP-Lens': '1'}
        self.imported()

    def select(self, **extra):
        body = dict(path=str(self.root / 'users.csv'), revision=config.get_settings().revision, mode='dynamic', **extra)
        return self.client.post('/api/data-sources/users/select', headers=self.H, json=body)

    def test_held_then_confirmed_over_http(self):
        self.write(15)
        held = self.select()
        self.assertEqual(held.status_code, 409, held.text)
        detail = held.json()['detail']
        self.assertEqual((detail['code'], detail['source'], detail['old']['records'], detail['new']['records']), ('import_needs_confirmation', 'users', 80, 30))
        self.assertTrue(detail['anomalies'])
        self.assertEqual(self.active_users(), 40)
        done = self.select(confirm_anomalies=True)
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(self.active_users(), 15)

    def test_thresholds_are_part_of_the_validated_configuration(self):
        settings = config.get_settings().model_dump()
        settings['import_checks'] = dict(enabled=True, max_drop_percent=96, min_previous_records=20)
        self.assertEqual(self.client.post('/api/configuration', headers=self.H, json=settings).status_code, 422)
        settings['import_checks']['max_drop_percent'] = 10
        self.assertEqual(self.client.post('/api/configuration', headers=self.H, json=settings).status_code, 200)
        self.assertEqual(config.get_settings().import_checks.max_drop_percent, 10)


if __name__ == '__main__':
    unittest.main()
