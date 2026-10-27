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
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

import cache
from config import get_settings
from data_loader import DataLoader
from routers import comparison, modules, roles, access, employees, dashboard, account_review, user_comparison, data_health, saved_filters, data_sources, sod
from request_limits import RequestBodyLimit
from version import VERSION, BUILD_INFO
from configuration_routes import configuration_router

frontend_dir = (Path(sys._MEIPASS) if getattr(sys, 'frozen', False)
                else Path(__file__).resolve().parent.parent) / 'frontend' / 'dist'


class DataSettings(BaseModel):
    data_csv_path: str = Field(min_length=1, max_length=4096)


def create_app(origin: str | None = None, session_token: str | None = None,
               instance_id: str | None = None, server=None, browser_access: bool = False, desktop_preferences=None) -> FastAPI:
    from deployment import server_mode, ServerSettings
    if server is None and server_mode():
        server = ServerSettings.from_env()
    loader = DataLoader()
    allowed_origins = [server.origin] if server else [origin] if origin else get_settings().cors_origins
    if not server and any(not _is_loopback_origin(value) for value in allowed_origins):
        raise ValueError('Only explicit HTTP loopback origins are supported.')
    if browser_access:
        if server or not origin or not session_token or not _is_loopback_origin(origin):
            raise ValueError('Browser handoff requires an owned desktop loopback session.')
        port = urlsplit(origin).port or 80
        allowed_origins = [f'http://127.0.0.1:{port}', f'http://localhost:{port}']
    desktop_hosts = {urlsplit(value).netloc for value in allowed_origins} if browser_access else set()
    request_header = session_token or '1'

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async def initial_load():
            with suppress(HTTPException):
                await loader.load()

        task = None
        if get_settings().data_csv_path or get_settings().user_csv_path or get_settings().employee_csv_path or get_settings().employee_snapshot_id or get_settings().sod_csv_path:
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
    app.state.deployment = server
    app.add_middleware(RequestBodyLimit)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(server.hosts) if server else ['127.0.0.1', 'localhost'])
    app.add_middleware(
        CORSMiddleware, allow_origins=allowed_origins, allow_credentials=False,
        allow_methods=['GET', 'POST'], allow_headers=['Content-Type', 'X-SAP-Lens'],
    )

    @app.middleware('http')
    async def local_browser_boundary(request: Request, call_next):
        request_origin = request.headers.get('origin')
        if browser_access and (request.headers.get('host','').lower() not in desktop_hosts
                               or not request.client or request.client.host not in {'127.0.0.1','::1'}):
            return JSONResponse({'detail':'Desktop access requires its exact loopback listener.'},status_code=403)
        if server and request.url.path not in {'/health/live','/health/ready'}:
            if not server.authorized(request):
                return JSONResponse({'detail':'Server access is not authorized.'},status_code=401,
                                    headers={'WWW-Authenticate':'Basic realm="SAP Lens", charset="UTF-8"'} if server.auth=='basic' else {})
            if request.method not in {'GET','HEAD','POST','OPTIONS'}:
                return JSONResponse({'detail':'Method not allowed.'},status_code=405)
            if request.url.path == '/api/branding/preview':
                return JSONResponse({'detail':'Native filesystem image selection is unavailable in server mode. Import a validated branding configuration package.'},status_code=403)
        if request.url.path.startswith('/api/'):
            if request_origin and request_origin not in allowed_origins:
                return JSONResponse({'detail': 'Origin is not allowed.'}, status_code=403)
            # Desktop reads as well as writes need the ephemeral launch capability.
            guarded = session_token is not None or request.method == 'POST'
            if request.method != 'OPTIONS' and guarded and not hmac.compare_digest(
                    request.headers.get('x-sap-lens', '').encode(), request_header.encode()):
                return JSONResponse({'detail': 'Application request is not authorized.'}, status_code=403)
        try:
            response = await call_next(request)
        except Exception as error:
            if not server: raise
            import logging
            logging.getLogger('sap-lens-server').error('Request failed (%s); private exception details omitted',type(error).__name__)
            return JSONResponse({'detail':'The operation failed. Check service permissions and operational logs.'},status_code=500)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        if request.url.path.startswith(('/api/', '/health')):
            response.headers['Cache-Control'] = 'no-store'
        nonce = getattr(request.state,'desktop_nonce',None)
        script_policy = "'self'" + (f" 'nonce-{nonce}'" if nonce else '')
        response.headers['Content-Security-Policy'] = (
            f"default-src 'self'; script-src {script_policy}; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        return response

    app.include_router(configuration_router(loader, desktop_preferences=desktop_preferences))
    app.include_router(roles.router)
    app.include_router(access.router)
    app.include_router(employees.router)
    app.include_router(dashboard.router)
    app.include_router(account_review.router)
    app.include_router(user_comparison.router)
    app.include_router(data_health.router)
    app.include_router(saved_filters.router)
    app.include_router(data_sources.router)
    app.include_router(sod.router)
    if server:
        from server_uploads import upload_router
        app.include_router(upload_router(server))
    app.include_router(modules.router)
    app.include_router(comparison.router)

    @app.get('/api/version', tags=['Application'])
    def application_version():
        return {'app': 'SAP Lens', 'version': VERSION, 'mode': BUILD_INFO['mode']}

    @app.get('/api/runtime')
    def runtime_capabilities():
        return dict(deployment_mode='server' if server else 'desktop', browser_upload=bool(server),
                    native_dialogs=not bool(server), source_path_policy='configured_root' if server else 'desktop_filesystem')

    @app.get('/health/live')
    def liveness(): return {'status':'alive'}

    @app.get('/health/ready')
    def readiness():
        # Optional CSV configuration never makes the process unready.
        return JSONResponse({'status':'starting' if loader.loading else 'ready'},status_code=503 if loader.loading else 200)

    @app.get('/api/application-info', tags=['Application'])
    def application_info():
        from platform import python_version, system
        return {key: BUILD_INFO.get(key) for key in ('version', 'mode', 'source_sha', 'file_version')} | {'python': python_version(), 'platform': system()}

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
        report = await loader.load(operation='refresh')
        summary = {**report, 'sources': [{k:v for k,v in source.items() if k != 'changes'} for source in report['sources']]}
        return {**health_check(), 'refresh': summary}

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
        if browser_access:
            @app.get('/', include_in_schema=False)
            def desktop_document(request: Request):
                # Only user navigation may bootstrap a browser. Never expose the
                # capability through a cross-site fetch, script, frame or API.
                if not (request.headers.get('sec-fetch-mode') == 'navigate'
                        and request.headers.get('sec-fetch-dest') == 'document'
                        and request.headers.get('sec-fetch-site') in {'none','same-origin','same-site'}
                        and (not request.headers.get('origin') or request.headers['origin'] in allowed_origins)):
                    return FileResponse(frontend_dir/'index.html',headers={'Cache-Control':'no-store'})
                import secrets, json
                nonce = secrets.token_urlsafe(24)
                request.state.desktop_nonce = nonce
                capability = json.dumps(session_token).replace('<',r'\u003c')
                handoff = f"try{{sessionStorage.setItem('sap-lens-session',{capability})}}catch(e){{history.replaceState(null,'',location.pathname+location.search+'#session='+encodeURIComponent({capability}))}}"
                html = (frontend_dir/'index.html').read_text(encoding='utf-8')
                html = html.replace('<head>',f'<head><script nonce="{nonce}">{handoff}</script>',1)
                return HTMLResponse(html,headers={'Cache-Control':'no-store'})
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
