"""Local API and static frontend shared by desktop and development runtimes."""
import asyncio
import hmac
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

import cache
from config import get_settings
from data_loader import DataLoader
from routers import comparison, modules, roles, access, employees, dashboard
from request_limits import RequestBodyLimit
from version import VERSION, BUILD_INFO
from configuration_routes import configuration_router

frontend_dir = (Path(sys._MEIPASS) if getattr(sys, 'frozen', False)
                else Path(__file__).resolve().parent.parent) / 'frontend' / 'dist'


class DataSettings(BaseModel):
    data_csv_path: str = Field(min_length=1, max_length=4096)


def create_app(origin: str | None = None, session_token: str | None = None,
               instance_id: str | None = None) -> FastAPI:
    loader = DataLoader()
    allowed_origins = [origin] if origin else get_settings().cors_origins
    if any(not _is_loopback_origin(value) for value in allowed_origins):
        raise ValueError('Only explicit HTTP loopback origins are supported.')
    request_header = session_token or '1'

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async def initial_load():
            with suppress(HTTPException):
                await loader.load()

        task = None
        if get_settings().data_csv_path or get_settings().user_csv_path:
            task = asyncio.create_task(initial_load())
        else:
            loader.error = 'Choose a SAP role catalogue or user access CSV in Settings.'
        yield
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title='SAP Lens API', version=VERSION, lifespan=lifespan,
                  docs_url=None, redoc_url=None)
    app.state.loader = loader
    app.add_middleware(RequestBodyLimit)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost'])
    app.add_middleware(
        CORSMiddleware, allow_origins=allowed_origins, allow_credentials=False,
        allow_methods=['GET', 'POST'], allow_headers=['Content-Type', 'X-SAP-Lens'],
    )

    @app.middleware('http')
    async def local_browser_boundary(request: Request, call_next):
        request_origin = request.headers.get('origin')
        if request.url.path.startswith('/api/'):
            if request_origin and request_origin not in allowed_origins:
                return JSONResponse({'detail': 'Origin is not allowed.'}, status_code=403)
            # Desktop reads as well as writes need the ephemeral launch capability.
            guarded = session_token is not None or request.method == 'POST'
            if request.method != 'OPTIONS' and guarded and not hmac.compare_digest(
                    request.headers.get('x-sap-lens', '').encode(), request_header.encode()):
                return JSONResponse({'detail': 'Application request is not authorized.'}, status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        if request.url.path.startswith(('/api/', '/health')):
            response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        return response

    app.include_router(configuration_router(loader))
    app.include_router(roles.router)
    app.include_router(access.router)
    app.include_router(employees.router)
    app.include_router(dashboard.router)
    app.include_router(modules.router)
    app.include_router(comparison.router)

    @app.get('/api/version', tags=['Application'])
    def application_version():
        return {'app': 'SAP Lens', 'version': VERSION, 'mode': BUILD_INFO['mode']}

    @app.get('/health', tags=['Health'])
    def health_check():
        state = cache.get_snapshot()
        status = 'loading' if loader.loading else (
            'ok' if state.last_loaded and not loader.error else 'needs_configuration')
        return {'app': 'sap-lens', 'version': VERSION, 'instance_id': instance_id,
                'status': status, 'cached_roles': len(state.roles),
                'last_loaded': state.last_loaded.isoformat() if state.last_loaded else None}

    @app.post('/api/refresh', tags=['Data'])
    async def refresh_data():
        await loader.load()
        return health_check()

    @app.get('/api/settings', tags=['Settings'])
    def read_settings():
        return {'data_csv_path': get_settings().data_csv_path,
                'error': loader.error, 'loading': loader.loading}

    @app.post('/api/settings', tags=['Settings'])
    async def update_settings(settings: DataSettings):
        path = settings.data_csv_path.strip()
        if not path or '://' in path or '\x00' in path or not Path(path).is_absolute():
            # Windows UNC and drive paths are absolute when running on Windows.
            raise HTTPException(400, 'Enter a full local or network-share CSV path.')
        await loader.load(path, persist=True)
        return read_settings()

    if frontend_dir.exists():
        app.mount('/', StaticFiles(directory=str(frontend_dir), html=True), name='frontend')
    return app


def _is_loopback_origin(origin: str) -> bool:
    value = urlsplit(origin)
    try:
        return (value.scheme == 'http' and value.hostname in {'127.0.0.1', 'localhost'}
                and value.port is not None and 0 < value.port < 65536
                and not value.username and not value.password and not value.path
                and not value.query and not value.fragment)
    except ValueError:
        return False


app = create_app()
