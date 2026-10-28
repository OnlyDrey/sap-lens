"""Backend scheduled refresh. Runs inside the single SAP Lens process, so it never depends on an open browser tab.

One process owns the mutable data store (storage lease), and the loader refuses to start while another load runs, so
refreshes cannot overlap or run twice. A missed slot (application not running) is skipped, not replayed. A failed
refresh keeps the previously validated data exactly like a manual refresh."""
import asyncio
import json
import logging
from datetime import datetime, timezone

import cron_schedule as schedule
from config import atomic_write, config_dir, get_settings

TICK = 20  # seconds between evaluations; also how quickly a settings change is noticed
STATE_FILE = 'refresh-schedule.json'
log = logging.getLogger('sap-lens')
FIELDS = ('last_attempt', 'last_success', 'last_failure', 'last_status', 'last_message', 'consecutive_failures')


def read_state():
    path = config_dir() / STATE_FILE
    try:
        data = json.loads(path.read_bytes()[:65536]) if path.exists() else {}
        if not isinstance(data, dict):
            raise ValueError()
        state = {key: data.get(key) for key in FIELDS}
        for key in ('last_attempt', 'last_success', 'last_failure'):
            if state[key] is not None:
                datetime.fromisoformat(state[key])
        if state['last_status'] not in {None, 'succeeded', 'partial', 'failed', 'skipped'} or not isinstance(state['consecutive_failures'] or 0, int):
            raise ValueError()
        return state
    except (OSError, ValueError, TypeError):
        return {key: None for key in FIELDS}


def write_state(state):
    try:
        atomic_write(config_dir() / STATE_FILE, json.dumps({key: state.get(key) for key in FIELDS}).encode())
    except OSError:
        log.warning('Scheduled refresh status could not be saved; the schedule keeps running.')


class Scheduler:
    def __init__(self, loader):
        self.loader = loader
        self.cursor = datetime.now(timezone.utc)
        self.signature = None
        self.task = None

    def runtime(self, server):
        """What the schedule needs from the deployment: only the desktop application depends on staying open."""
        return dict(deployment_mode='server' if server else 'desktop', requires_running_application=not server)

    def status(self, server=False, now=None):
        now = now or datetime.now(timezone.utc)
        settings = get_settings().refresh_schedule
        info = dict(schedule=settings.model_dump(), state=read_state(), runtime=self.runtime(server), expression=None, description=None, next_runs=[], error=None)
        try:
            info['expression'] = settings.expression
            info['description'] = schedule.describe(settings.expression, settings.timezone)
            info['next_runs'] = [run.isoformat() for run in schedule.check(settings.expression, settings.timezone, now)]
        except ValueError as error:
            info['error'] = str(error)
        info['next_run'] = info['next_runs'][0] if settings.enabled and info['next_runs'] else None
        return info

    async def tick(self, now=None):
        """Evaluate once; returns the outcome ('idle', 'skipped', 'succeeded', 'partial', 'failed')."""
        now = now or datetime.now(timezone.utc)
        settings = get_settings().refresh_schedule
        signature = settings.model_dump_json()
        if signature != self.signature:  # a changed definition starts from now, without replaying older slots
            self.signature, self.cursor = signature, now
        if not settings.enabled:
            self.cursor = now
            return 'idle'
        try:
            due = schedule.next_runs(settings.expression, settings.timezone, self.cursor, 1)
        except ValueError:
            self.cursor = now
            return 'idle'
        self.cursor = now  # slots missed while stopped or busy are skipped, never replayed in a burst
        if not due or due[0] > now:
            return 'idle'
        return await self.run(now)

    async def run(self, now):
        state = read_state()
        state['last_attempt'] = now.isoformat()
        if self.loader.loading:
            state.update(last_status='skipped', last_message='Skipped: another load or refresh was already running.')
            write_state(state)
            return 'skipped'
        try:
            report = await self.loader.load(operation='refresh')
            outcome = 'succeeded' if report['status'] in {'changed', 'unchanged'} else 'partial' if report['status'] == 'partial' else 'failed'
            message = {'succeeded': 'Refresh completed.', 'partial': 'Some sources failed; their previous validated data was kept.',
                       'failed': 'The refresh failed; previous validated data was kept.'}[outcome]
        except Exception as error:  # noqa: BLE001 - never stops the schedule
            outcome, message = 'failed', 'The refresh could not run; previous validated data was kept.'
            log.warning('Scheduled refresh failed (%s); previous data retained.', type(error).__name__)
        if outcome == 'failed':
            state.update(last_failure=now.isoformat(), consecutive_failures=(state.get('consecutive_failures') or 0) + 1)
        else:
            state.update(last_success=now.isoformat(), consecutive_failures=0)
            if outcome == 'partial':
                state['last_failure'] = now.isoformat()
        state.update(last_status=outcome, last_message=message)
        write_state(state)
        return outcome

    async def loop(self):
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001
                log.warning('Scheduler evaluation failed (%s).', type(error).__name__)
            await asyncio.sleep(TICK)
