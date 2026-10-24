"""Raw, authenticated, bounded CSV staging; existing previews/imports confirm activation."""
import asyncio
from pathlib import Path
import secrets
from urllib.parse import unquote
from fastapi import APIRouter, HTTPException, Request
from config import get_settings


def upload_router(settings):
    router=APIRouter(prefix='/api/server/uploads',tags=['Server imports'])
    lock=asyncio.Lock()

    @router.post('/{source}')
    async def upload(source:str, request:Request):
        if source not in {'roles','users','employees'}: raise HTTPException(404,'Unknown source.')
        try: name=unquote(request.headers.get('x-upload-filename',''),errors='strict')
        except UnicodeError: raise HTTPException(400,'Choose a valid UTF-8 CSV filename.') from None
        if not name or len(name)>200 or not name.lower().endswith('.csv') or any(c in name for c in '/\\\x00<>:"|?*') or '..' in name or any(ord(c)<32 for c in name):
            raise HTTPException(400,'Choose a CSV filename without path components.')
        maximum=(50 if source=='employees' else 128)*1024*1024
        directory=settings.data/'uploads'
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        async with lock:
            current=get_settings()
            referenced={Path(v).resolve() for v in (current.data_csv_path,current.user_csv_path,current.employee_csv_path) if v}
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

    return router
