"""Authenticated CSV uploads; multipart activation reuses the canonical selection service.

The raw staging endpoint remains compatible with existing desktop/deployment tools.
"""
from contextlib import asynccontextmanager
import asyncio
from pathlib import Path
import secrets
from urllib.parse import unquote
from fastapi import APIRouter, HTTPException, Request
from starlette.formparsers import MultiPartParser, MultiPartException
from starlette.datastructures import UploadFile
from starlette.requests import ClientDisconnect
import json
from pydantic import ValidationError
from config import config_dir
from config import get_settings


@asynccontextmanager
async def close_form(form):
    try:
        yield form
    finally:
        await form.close()


def upload_router(settings=None):
    router=APIRouter(prefix='/api/server/uploads',tags=['Server imports'])
    lock=asyncio.Lock()

    @router.post('/{source}')
    async def upload(source:str, request:Request):
        if source not in {'roles','users','employees','sod'}: raise HTTPException(404,'Unknown source.')
        try: name=unquote(request.headers.get('x-upload-filename',''),errors='strict')
        except UnicodeError: raise HTTPException(400,'Choose a valid UTF-8 CSV filename.') from None
        if not name or len(name)>200 or not name.lower().endswith('.csv') or any(c in name for c in '/\\\x00<>:"|?*') or '..' in name or any(ord(c)<32 for c in name):
            raise HTTPException(400,'Choose a CSV filename without path components.')
        maximum=(50 if source=='employees' else 128)*1024*1024
        directory=(settings.data if settings else config_dir())/'uploads'
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        async with lock:
            current=get_settings()
            referenced={Path(v).resolve() for v in (current.data_csv_path,current.user_csv_path,current.employee_csv_path,current.sod_csv_path) if v}  # noqa: ASYNC240 (a staging directory of at most a few files, scanned under the upload lock)
            pending=[p for p in directory.glob('*.csv') if p.resolve() not in referenced]
            # Bounded staging. Active source paths are never deleted here.
            for stale in sorted(pending,key=lambda p:p.stat().st_mtime)[:-2]: stale.unlink()
            target=directory/(secrets.token_hex(16)+'-'+Path(name).stem[:40]+'.csv')
            total=0
            try:
                with target.open('xb') as stream:
                    import os
                    if os.name!='nt': os.chmod(target,0o600)
                    async for chunk in request.stream():
                        total+=len(chunk)
                        if total>maximum: raise HTTPException(413,'CSV exceeds its source size limit.')
                        stream.write(chunk)
                if not total: raise HTTPException(400,'The CSV is empty.')
            except BaseException:
                target.unlink(missing_ok=True)
                raise
        return dict(path=str(target),file_name=name,size=total,mode='static',
                    message='Uploaded only. Validate, preview and confirm import before records are replaced.')

    @router.post('/{source}/activate')
    async def upload_and_activate(source: str, request: Request):
        from routers.data_sources import SourceSelection, select_source
        if source not in {'roles', 'users', 'employees', 'sod'}:
            raise HTTPException(404, 'Unknown source.')
        if not request.headers.get('content-type', '').lower().startswith('multipart/form-data;'):
            raise HTTPException(415, 'Choose a CSV using the browser file picker.')
        if lock.locked() or request.app.state.loader.loading:
            raise HTTPException(409, 'Another CSV operation is running. Wait for it to finish.')
        maximum = (50 if source == 'employees' else 128) * 1024 * 1024
        class TooLarge(MultiPartException):
            pass
        async def bounded():
            count = 0
            try:
                async for chunk in request.stream():
                    count += len(chunk)
                    if count > maximum + 65536:
                        raise TooLarge('CSV exceeds its source size limit.')
                    yield chunk
            except ClientDisconnect:
                raise MultiPartException('Upload was interrupted. Previous data is unchanged.') from None
        async with lock:
            try:
                form = await MultiPartParser(request.headers, bounded(), max_files=1, max_fields=3, max_part_size=16384).parse()
            except TooLarge:
                raise HTTPException(413, 'CSV exceeds its source size limit.') from None
            except MultiPartException:
                raise HTTPException(400, 'Invalid or interrupted multipart upload. Choose one CSV file and retry.') from None
            async with close_form(form):
                if set(form) - {'file', 'revision', 'profile', 'confirm_anomalies'} or any(len(form.getlist(key)) != 1 for key in form):
                    raise HTTPException(400, 'Upload one CSV file with one settings revision.')
                file = form.get('file')
                if not isinstance(file, UploadFile):
                    raise HTTPException(400, 'Choose one CSV file.')
                name = file.filename or ''
                if not name or len(name.encode('utf-8')) > 200 or not name.lower().endswith('.csv') or '..' in name or any(c in name for c in '/\\\x00<>:"|?*') or any(ord(c) < 32 for c in name):
                    raise HTTPException(400, 'Choose a CSV filename without path components.')
                if file.content_type not in {'text/csv', 'application/csv', 'application/vnd.ms-excel', 'text/plain', 'application/octet-stream', None}:
                    raise HTTPException(415, 'Choose a CSV file, not a spreadsheet or executable.')
                if not file.size or file.size > maximum:
                    raise HTTPException(413 if file.size else 400, 'Choose a non-empty CSV within its source size limit.')
                try:
                    profile = json.loads(form['profile']) if 'profile' in form else None
                    revision = int(form['revision'])
                    if revision != get_settings().revision:
                        raise HTTPException(409, 'Settings changed. Reload this source before selecting it again.')
                    directory = (settings.data if settings else config_dir()) / 'uploads'
                    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                    previous = get_settings()
                    old_path = getattr(previous, {'roles':'data_csv_path','users':'user_csv_path','employees':'employee_csv_path','sod':'sod_csv_path'}[source])
                    target = directory / (secrets.token_hex(16) + '-' + name)
                    selection = SourceSelection(path=str(target), mode='static', revision=revision, profile=profile, confirm_anomalies=form.get('confirm_anomalies') == 'true')
                except (ValueError, TypeError, KeyError, ValidationError):
                    raise HTTPException(400, 'The upload revision or import profile is invalid.') from None
                created = False
                try:
                    with target.open('xb') as destination:
                        created = True
                        import os
                        if os.name != 'nt': os.chmod(target, 0o600)
                        while chunk := await file.read(1024 * 1024):
                            destination.write(chunk)
                    result = await select_source(source, selection, request)
                    if old_path and Path(old_path).parent == directory and old_path != str(target):
                        active_paths = (get_settings().data_csv_path, get_settings().user_csv_path, get_settings().employee_csv_path, get_settings().sod_csv_path)
                        if old_path not in active_paths:
                            try: await asyncio.to_thread(Path(old_path).unlink, missing_ok=True)
                            except OSError: pass  # A committed import remains successful if obsolete-file cleanup is denied.
                    return {**result, 'file_name': name}
                finally:
                    current = get_settings()
                    active = {str(value) for value in (current.data_csv_path, current.user_csv_path, current.employee_csv_path, current.sod_csv_path) if value}
                    # Never delete a file that committed successfully, even when the
                    # response/client disconnects after publication.
                    if created and str(target) not in active:
                        target.unlink(missing_ok=True)

    return router
