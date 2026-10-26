"""Owned, cancelable file reads with bounded abandonment of stalled OS I/O."""
import asyncio
import csv
import logging
import threading
from fastapi import HTTPException
import cache
from analysis_errors import AnalysisValidationError

logger=logging.getLogger(__name__)


class LoadCancelled(Exception): pass


class DataLoader:
    def __init__(self):
        self.loading=False
        self.error: str | None=None
        self.source_attempts = {}
        self.last_failed_load = None
        self._generation=0
        self._cancel=None
        self._result=None
        self._workers=[]
        self.last_report=None
        self.progress=None

    def cancel(self):
        if self._cancel:
            cache.cancel_publication(self._cancel)
        self._generation+=1
        self.loading=False
        if self._result is not None and not self._result.done():
            self._result.set_exception(HTTPException(409,'Data load canceled. Previous data and settings were retained.'))
        self._result=None
        self._cancel=None

    async def load(self,path: str | None=None,persist: bool=False,configuration=None,commit=None,operation=None,force=()):
        if self.loading: raise HTTPException(409,'A CSV is already loading. Wait or cancel it before trying another file.')
        self._workers=[worker for worker in self._workers if worker.is_alive()]
        if len(self._workers)>=2:
            raise HTTPException(409,'Two reads are still waiting on the filesystem. Restore access or close and reopen SAP Lens.')
        from config import get_settings
        settings = configuration or get_settings()
        if path is not None:
            settings = settings.model_copy(deep=True)
            settings.data_csv_path = path
        operation = operation or ('import' if persist or configuration is not None else 'startup')
        attempted_paths = {'roles': path if path is not None else settings.data_csv_path, 'users': settings.user_csv_path, 'employees': settings.employee_csv_path}
        self.loading=True
        self.progress={'stage':'Reading file','source':force[0] if len(force)==1 else None}
        self._generation+=1
        generation=self._generation
        loop=asyncio.get_running_loop()
        result=loop.create_future()
        cancelled=threading.Event()
        self._result,self._cancel=result,cancelled

        def before_commit():
            if cancelled.is_set(): raise LoadCancelled()
            if commit: commit()

        def finish(error, source=None, category=None, report=None):
            if generation != self._generation or result.done(): return
            self.loading=False
            self._result=None;self._cancel=None
            self.progress={'stage':'Failed' if error else 'Completed','source':force[0] if len(force)==1 else None}
            if error:
                from datetime import datetime, timezone
                self.last_failed_load = datetime.now(timezone.utc).isoformat()
                if source in attempted_paths:
                    self.source_attempts[source] = {'path': attempted_paths[source], 'error': category}
                self.error=error
                result.set_exception(HTTPException(400,error))
            else:
                self.last_report = report
                failures = [r for r in (report or {}).get('sources', []) if r['status'] == 'failed']
                self.source_attempts = {r['source']: {'path': {'roles': settings.data_csv_path, 'users': settings.user_csv_path, 'employees': settings.employee_csv_path}[r['source']], 'error': r['category']} for r in failures}
                if failures:
                    from datetime import datetime, timezone
                    self.last_failed_load = datetime.now(timezone.utc).isoformat()
                self.error = 'CSV data could not be loaded. Review Data Sources.' if failures and not cache.get_snapshot().last_loaded else None
                result.set_result(report)

        def progress(stage, source=None):
            if generation==self._generation and not cancelled.is_set():
                self.progress={'stage':stage,'source':source}

        def read():
            error=None
            source=None
            category=None
            report=None
            try:
                from csv_lifecycle import load
                report = load(settings, operation=operation, before_commit=before_commit,
                              strict=operation == 'import', force=tuple(force) + (('roles',) if path is not None else ()), progress=progress)
            except LoadCancelled: return
            except Exception as exc:
                source = getattr(exc, 'sap_lens_source', None)
                if isinstance(exc, FileNotFoundError):
                    category='missing'; error='CSV file not found. Choose an existing file or reconnect the network share.'
                elif isinstance(exc, PermissionError):
                    category='access_denied'; error='Cannot read the CSV. Check your account permissions and network-share access.'
                elif isinstance(exc, AnalysisValidationError): category='invalid'; error=str(exc)
                elif isinstance(exc, (OSError,ValueError,RuntimeError,csv.Error)):
                    category='invalid'; error='Could not load the CSV. Use a readable CSV with valid column mappings and dates.'
                else: category='failed'; error='The CSV could not be loaded. Choose another file and try again.'
            if error: logger.warning('CSV load unsuccessful; previous data retained')
            try: loop.call_soon_threadsafe(finish,error,source,category,report)
            except RuntimeError: pass

        worker=threading.Thread(target=read,name='sap-lens-csv',daemon=True)
        self._workers.append(worker);worker.start()
        try: return await result
        finally:
            if result.cancelled():
                cache.cancel_publication(cancelled)
                if generation==self._generation:
                    self._generation+=1;self.loading=False;self._result=None;self._cancel=None
