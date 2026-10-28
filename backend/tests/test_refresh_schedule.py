"""Scheduled refresh: cron rules, validation, persistence, overlap safety and failure recovery."""
import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
import cache
import cron_schedule as cron
from main import create_app
from scheduler import Scheduler, read_state
from config_models import RefreshSchedule

H = {'X-SAP-Lens': '1'}
utc = lambda *args: datetime(*args, tzinfo=timezone.utc)


class CronRules(unittest.TestCase):
    def test_parser_accepts_lists_ranges_steps_names_and_rejects_bad_fields(self):
        rule = cron.parse_cron('0,30 6-8 * JAN,MAR MON-FRI')
        self.assertEqual((rule['minute'], rule['hour'], rule['month'], rule['dow']), ({0, 30}, {6, 7, 8}, {1, 3}, {1, 2, 3, 4, 5}))
        self.assertEqual(cron.parse_cron('*/20 * * * 7')['dow'], {0})
        for bad in ('', '* * * *', '60 * * * *', '* 24 * * *', '* * 0 * *', '* * * 13 *', '*/0 * * * *', '5-1 * * * *', 'x * * * *', '* * * * 8'):
            with self.assertRaises(ValueError, msg=bad):
                cron.parse_cron(bad)

    def test_daily_time_is_converted_and_validated(self):
        self.assertEqual(cron.daily_cron('06:30'), '30 6 * * *')
        for bad in ('6:30', '24:00', '06:60', ''):
            with self.assertRaises(ValueError):
                cron.daily_cron(bad)

    def test_readable_explanations(self):
        self.assertEqual(cron.describe('30 6 * * *', 'Europe/Oslo'), 'At 06:30 every day (Europe/Oslo)')
        self.assertEqual(cron.describe('0 6 * * 1-5', 'UTC'), 'At 06:00 on weekdays (UTC)')
        self.assertEqual(cron.describe('*/15 * * * *', 'local'), 'Every 15 minutes every day (local time)')
        self.assertIn('on Monday, Wednesday', cron.describe('0 8 * * 1,3', 'UTC'))
        self.assertIn('on day 1 of the month in January', cron.describe('0 3 1 JAN *', 'UTC'))

    def test_next_runs_follow_the_selected_time_zone_and_daylight_saving(self):
        self.assertEqual(cron.next_runs('30 6 * * *', 'UTC', utc(2026, 10, 28, 12), 2), [utc(2026, 10, 29, 6, 30), utc(2026, 10, 30, 6, 30)])
        try:
            cron.zone('Europe/Oslo')
        except ValueError:
            self.skipTest('platform has no IANA database')
        self.assertEqual(cron.next_runs('30 6 * * *', 'Europe/Oslo', utc(2026, 10, 28, 12), 1), [utc(2026, 10, 29, 5, 30)])
        self.assertEqual(cron.next_runs('30 6 * * *', 'Europe/Oslo', utc(2026, 7, 1, 12), 1), [utc(2026, 7, 2, 4, 30)])
        # 02:30 does not exist on 2026-03-29 in Oslo: skipped; on 2026-10-25 it happens twice: runs once
        self.assertEqual(cron.next_runs('30 2 * * *', 'Europe/Oslo', utc(2026, 3, 28, 12), 2), [utc(2026, 3, 30, 0, 30), utc(2026, 3, 31, 0, 30)])
        self.assertEqual(cron.next_runs('30 2 * * *', 'Europe/Oslo', utc(2026, 10, 24, 12), 2), [utc(2026, 10, 25, 0, 30), utc(2026, 10, 26, 1, 30)])

    def test_day_of_month_and_weekday_combine_like_cron_and_impossible_dates_are_rejected(self):
        runs = cron.next_runs('0 9 13 * 5', 'UTC', utc(2026, 10, 1), 3)
        self.assertEqual([run.day for run in runs[:2]], [2, 9])  # Fridays or the 13th
        with self.assertRaises(ValueError):
            cron.check('0 0 31 2 *', 'UTC', utc(2026, 1, 1))

    def test_minimum_interval_and_unknown_zone(self):
        with self.assertRaises(ValueError):
            cron.check('*/2 * * * *', 'UTC')
        self.assertEqual(len(cron.check('*/5 * * * *', 'UTC')), 5)
        with self.assertRaises(ValueError):
            cron.zone('Nowhere/Land')


class ConfigAndApi(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': self.temp.name, 'DATA_CSV_PATH': ''})
        self.env.start(); config.get_settings.cache_clear(); cache.clear_cache()
        self.client = TestClient(create_app(session_token='1'), base_url='http://127.0.0.1:18743')

    def tearDown(self):
        cache.clear_cache(); config.get_settings.cache_clear(); self.env.stop(); self.temp.cleanup()

    def save(self, **schedule):
        settings = config.get_settings().model_dump()
        settings['refresh_schedule'] = {**settings['refresh_schedule'], **schedule}
        return self.client.post('/api/configuration', headers=H, json=settings)

    def test_defaults_are_disabled_and_the_schedule_persists_across_restart(self):
        status = self.client.get('/api/refresh-schedule', headers=H).json()
        self.assertFalse(status['schedule']['enabled'])
        self.assertIsNone(status['next_run'])
        self.assertEqual(status['runtime'], dict(deployment_mode='desktop', requires_running_application=True))
        saved = self.save(enabled=True, mode='cron', cron='15 7 * * 1-5', timezone='UTC')
        self.assertEqual(saved.status_code, 200, saved.text)
        config.get_settings.cache_clear()
        status = self.client.get('/api/refresh-schedule', headers=H).json()
        self.assertEqual((status['schedule']['cron'], status['description']), ('15 7 * * 1-5', 'At 07:15 on weekdays (UTC)'))
        self.assertIsNotNone(status['next_run'])
        self.assertEqual(len(status['next_runs']), 5)

    def test_invalid_schedules_are_rejected_with_a_readable_reason_and_keep_previous_settings(self):
        self.assertEqual(self.save(enabled=True, mode='cron', cron='* * * *').status_code, 422)
        response = self.save(enabled=True, mode='cron', cron='*/2 * * * *', timezone='UTC')
        self.assertEqual((response.status_code, response.json()['detail']), (422, 'Refreshes must be at least 5 minutes apart.'))
        response = self.save(enabled=True, timezone='Nowhere/Land')
        self.assertEqual(response.status_code, 422)
        self.assertIn('not available on this system', response.json()['detail'])
        self.assertFalse(config.get_settings().refresh_schedule.enabled)

    def test_preview_explains_a_draft_without_saving(self):
        ok = self.client.post('/api/refresh-schedule/preview', headers=H, json=dict(mode='daily', time='05:45', timezone='UTC')).json()
        self.assertEqual((ok['valid'], ok['description'], ok['expression']), (True, 'At 05:45 every day (UTC)', '45 5 * * *'))
        bad = self.client.post('/api/refresh-schedule/preview', headers=H, json=dict(mode='cron', cron='99 * * * *')).json()
        self.assertFalse(bad['valid'])
        self.assertIn('minute must be between 0 and 59', bad['error'])
        self.assertFalse(config.get_settings().refresh_schedule.enabled)
        self.assertEqual(self.client.post('/api/refresh-schedule/preview', json={}).status_code, 403)

    def test_diagnostics_summarize_the_schedule_without_paths(self):
        from diagnostics import diagnostics_snapshot
        summary = diagnostics_snapshot()['scheduled_refresh']
        self.assertEqual(summary['enabled'], False)
        self.assertNotIn(self.temp.name, str(summary))


class FakeLoader:
    def __init__(self, status='unchanged', error=None):
        self.loading, self.calls, self.status, self.error = False, 0, status, error

    async def load(self, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return dict(status=self.status)


class Runtime(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': self.temp.name, 'DATA_CSV_PATH': ''})
        self.env.start(); config.get_settings.cache_clear()
        settings = config.get_settings().model_copy(deep=True)
        settings.refresh_schedule = RefreshSchedule(enabled=True, mode='daily', time='06:00', timezone='UTC')
        config.save_configuration(settings, settings.revision)

    def tearDown(self):
        config.get_settings.cache_clear(); self.env.stop(); self.temp.cleanup()

    def tick(self, scheduler, *args):
        return asyncio.run(scheduler.tick(utc(*args)))

    def test_runs_once_per_slot_and_records_success(self):
        loader = FakeLoader(); scheduler = Scheduler(loader)
        self.assertEqual(self.tick(scheduler, 2026, 10, 28, 5, 59), 'idle')
        self.assertEqual(self.tick(scheduler, 2026, 10, 28, 6, 0), 'succeeded')
        self.assertEqual(self.tick(scheduler, 2026, 10, 28, 6, 0), 'idle')  # same minute never runs twice
        self.assertEqual(self.tick(scheduler, 2026, 10, 28, 6, 5), 'idle')
        self.assertEqual(loader.calls, 1)
        state = read_state()
        self.assertEqual((state['last_status'], state['consecutive_failures'], state['last_success'][:16]), ('succeeded', 0, '2026-10-28T06:00'))

    def test_missed_slots_are_skipped_not_replayed_and_a_changed_definition_starts_fresh(self):
        loader = FakeLoader(); scheduler = Scheduler(loader)
        self.tick(scheduler, 2026, 10, 25, 12)  # starts watching
        self.assertEqual(self.tick(scheduler, 2026, 10, 28, 12), 'succeeded')  # three days later: one catch-up run, not three
        self.assertEqual(loader.calls, 1)
        settings = config.get_settings().model_copy(deep=True)
        settings.refresh_schedule = RefreshSchedule(enabled=True, mode='daily', time='05:00', timezone='UTC')
        config.save_configuration(settings, settings.revision)
        self.assertEqual(self.tick(scheduler, 2026, 10, 29, 5, 30), 'idle')  # slot 05:00 passed before the edit was noticed
        self.assertEqual(loader.calls, 1)

    def test_never_overlaps_a_running_load_and_disabled_schedules_do_nothing(self):
        loader = FakeLoader(); loader.loading = True
        scheduler = Scheduler(loader)
        self.tick(scheduler, 2026, 10, 28, 5, 59)
        self.assertEqual(self.tick(scheduler, 2026, 10, 28, 6, 0), 'skipped')
        self.assertEqual((loader.calls, read_state()['last_status']), (0, 'skipped'))
        settings = config.get_settings().model_copy(deep=True)
        settings.refresh_schedule = RefreshSchedule(enabled=False)
        config.save_configuration(settings, settings.revision)
        loader.loading = False
        self.assertEqual(self.tick(scheduler, 2026, 10, 29, 6, 0), 'idle')
        self.assertEqual(loader.calls, 0)

    def test_failures_are_recorded_and_the_schedule_keeps_running(self):
        loader = FakeLoader(status='failed'); scheduler = Scheduler(loader)
        self.tick(scheduler, 2026, 10, 28, 5, 59)
        self.assertEqual(self.tick(scheduler, 2026, 10, 28, 6, 0), 'failed')
        self.tick(scheduler, 2026, 10, 29, 5, 59)
        loader.error = RuntimeError('private path /srv/secret.csv')
        self.assertEqual(self.tick(scheduler, 2026, 10, 29, 6, 0), 'failed')
        state = read_state()
        self.assertEqual((state['last_status'], state['consecutive_failures']), ('failed', 2))
        self.assertNotIn('secret', str(state))
        loader.error, loader.status = None, 'changed'
        self.tick(scheduler, 2026, 10, 30, 5, 59)
        self.assertEqual(self.tick(scheduler, 2026, 10, 30, 6, 0), 'succeeded')
        self.assertEqual(read_state()['consecutive_failures'], 0)
        loader.status = 'partial'
        self.tick(scheduler, 2026, 10, 31, 5, 59)
        self.assertEqual(self.tick(scheduler, 2026, 10, 31, 6, 0), 'partial')

    def test_corrupt_state_is_ignored(self):
        (Path(self.temp.name) / 'refresh-schedule.json').write_text('{broken')
        self.assertIsNone(read_state()['last_status'])


if __name__ == '__main__':
    unittest.main()
