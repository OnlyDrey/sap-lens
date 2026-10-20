"""Cancelable application-owned CSV loads; a stalled share cannot keep Python alive."""
import asyncio
import csv
import logging
import threading

from fastapi import HTTPException

import cache
from config import save_data_path

logger = logging.getLogger(__name__)


class LoadCancelled(Exception):
    pass


class DataLoader:
    def __init__(self):
        self.loading = False
        self.error: str | None = None

    async def load(self, path: str | None = None, persist: bool = False):
        if self.loading:
            raise HTTPException(409, 'A CSV is already loading. Please wait before trying again.')
        self.loading = True
        loop = asyncio.get_running_loop()
        result = loop.create_future()
        cancelled = threading.Event()

        def commit():
            if cancelled.is_set():
                raise LoadCancelled()
            if persist:
                save_data_path(path)

        def finish(error):
            self.loading = False
            if result.done():
                return
            if error:
                self.error = error
                result.set_exception(HTTPException(400, error))
            else:
                self.error = None
                result.set_result(None)

        def read():
            error = None
            try:
                cache.load_cache(path, before_commit=commit)
            except LoadCancelled:
                return
            except FileNotFoundError:
                error = 'CSV file not found. Choose an existing file or reconnect the network share.'
            except PermissionError:
                error = 'Cannot read the CSV. Check your account permissions and network-share access.'
            except (OSError, ValueError, RuntimeError, csv.Error):
                error = 'Could not load the CSV. Use a readable UTF-8 CSV with the required columns.'
            except Exception:
                # Do not send tracebacks or CSV content/paths to the UI or logs.
                error = 'The CSV could not be loaded. Choose another file and try again.'
            if error:
                logger.warning('CSV load unsuccessful; previous data retained')
            try:
                loop.call_soon_threadsafe(finish, error)
            except RuntimeError:
                pass  # The owning application has already closed.

        # Never use a subprocess or the non-daemon asyncio default executor for
        # unbounded filesystem I/O. Python can exit even if a share stops responding.
        threading.Thread(target=read, name='sap-lens-csv', daemon=True).start()
        try:
            await result
        finally:
            if result.cancelled():
                cancelled.set()
