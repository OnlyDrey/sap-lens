"""Scheduled refresh status and draft validation. The schedule itself is saved with the normal settings transaction."""
from datetime import datetime, timezone
from fastapi import APIRouter, Body
from pydantic import ValidationError

import cron_schedule as schedule
from config_models import RefreshSchedule


def refresh_schedule_router(scheduler, server):
    router = APIRouter(prefix='/api/refresh-schedule', tags=['Scheduled refresh'])

    @router.get('')
    def status():
        return scheduler.status(bool(server))

    @router.post('/preview')
    def preview(draft: dict = Body(...)):
        """Explain an unsaved draft: readable sentence and the next runs, or the reason it is not valid."""
        try:
            parsed = RefreshSchedule.model_validate(draft)
            runs = schedule.check(parsed.expression, parsed.timezone, datetime.now(timezone.utc))
            return dict(valid=True, expression=parsed.expression, description=schedule.describe(parsed.expression, parsed.timezone),
                        next_runs=[run.isoformat() for run in runs], error=None)
        except ValidationError as error:
            first = error.errors()[0]
            field = '.'.join(str(part) for part in first['loc']) or 'schedule'
            message = str(first.get('ctx', {}).get('error') or first['msg']).removeprefix('Value error, ')
            return dict(valid=False, expression=None, description=None, next_runs=[], error=f'{field}: {message}' if field != 'schedule' and 'cron' not in message.lower() else message)
        except ValueError as error:
            return dict(valid=False, expression=None, description=None, next_runs=[], error=str(error))

    return router
