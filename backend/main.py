"""Local API and static frontend shared by desktop and development runtimes."""
import asyncio
import hmac
import sys
from datetime import datetime, timezone
from uuid import uuid4
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

import cache
from config import get_settings
from data_loader import DataLoader
from routers import comparison, modules, roles, access, employees, dashboard, account_review, user_comparison, data_health, saved_filters, data_sources, sod, sod_analysis, sod_reviews, sod_periods, sod_reports, sod_governance
from request_limits import RequestBodyLimit
from version import VERSION, BUILD_INFO
from configuration_routes import configuration_router

frontend_dir = (Path(sys._MEIPASS) if getattr(sys, 'frozen', False)
                else Path(__file__).resolve().parent.parent) / 'frontend' / 'dist'


class DataSettings(BaseModel):
    data_csv_path: str = Field(min_length=1, max_length=4096)


def create_app(origin: str | None = None, session_token: str | None = None,
               instance_id: str | None = None, server=None, browser_access: bool = False, desktop_preferences=None, startup_observer=None) -> FastAPI:
    from deployment import server_mode, ServerSettings, AuthThrottle
    if server is None and server_mode():
        server = ServerSettings.from_env()
    def notify(stage, result, error=None):
        if startup_observer: startup_observer(stage, result, error)
    notify('data_loader', 'starting')
    loader = DataLoader()
    notify('data_loader', 'ready')
    notify('scheduler', 'starting')
    from scheduler import Scheduler
    scheduler = Scheduler(loader)
    notify('scheduler', 'created')
    allowed_origins = list(server.origins) if server else [origin] if origin else get_settings().cors_origins
    if not server and any(not _is_loopback_origin(value) for value in allowed_origins):
        raise ValueError('Only explicit HTTP loopback origins are supported.')
    if browser_access:
        if server or not origin or not session_token or not _is_loopback_origin(origin):
            raise ValueError('Browser handoff requires an owned desktop loopback session.')
        port = urlsplit(origin).port or 80
        allowed_origins = [f'http://127.0.0.1:{port}', f'http://localhost:{port}']
    desktop_hosts = {urlsplit(value).netloc for value in allowed_origins} if browser_access else set()
    request_header = session_token or '1'
    throttle = AuthThrottle(server.max_failures, server.lockout_seconds) if server and server.auth in {'basic','users'} else None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async def initial_load():
            with suppress(HTTPException):
                await loader.load()

        scheduled = asyncio.create_task(scheduler.loop())
        task = None
        try:
            if get_settings().data_csv_path or get_settings().user_csv_path or get_settings().employee_csv_path or get_settings().employee_snapshot_id or get_settings().sod_csv_path:
                task = asyncio.create_task(initial_load())
            else:
                loader.error = 'Choose a SAP role catalogue or user access CSV in Settings.'
            # Start the supervised scheduler and let persisted-data loading mark its state.
            await asyncio.sleep(0)
            if scheduled.done():
                scheduled.result()
                raise RuntimeError('Scheduler stopped during initialization')
            notify('scheduler', 'ready')
            notify('initialization', 'ready')
            yield
        except Exception as error:
            notify('initialization','failed',error)
            raise
        finally:
            scheduled.cancel()
            if task: task.cancel()
            await asyncio.gather(scheduled, *([task] if task else []), return_exceptions=True)
            notify('initialization', 'stopped')

    app = FastAPI(title='SAP Lens API', version=VERSION, lifespan=lifespan,
                  docs_url=None, redoc_url=None)
    app.state.loader = loader

    def failure_response(request, error):
        import logging
        identity=getattr(request.state,'request_id',None) or uuid4().hex
        timestamp=datetime.now(timezone.utc).isoformat()
        route=getattr(request.scope.get('route'),'path','unmatched')
        logging.getLogger('sap-lens').error('backend_failure operation=%s category=%s request_id=%s timestamp=%s',route,type(error).__name__,identity,timestamp)
        return JSONResponse({'detail':'The operation failed unexpectedly. Retry; if it persists, check the application logs.',
                             'request_id':identity,'timestamp':timestamp},status_code=500,headers={'X-Request-ID':identity})

    @app.exception_handler(Exception)
    async def unexpected_failure(request: Request, error: Exception):
        return failure_response(request,error)
    app.state.deployment = server
    app.state.auth_throttle = throttle
    app.add_middleware(RequestBodyLimit)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(server.hosts) if server else ['127.0.0.1', 'localhost'])
    app.add_middleware(
        CORSMiddleware, allow_origins=allowed_origins, allow_credentials=False,
        allow_methods=['GET', 'POST'], allow_headers=['Content-Type', 'X-SAP-Lens'],
    )

    @app.middleware('http')
    async def local_browser_boundary(request: Request, call_next):
        request.state.request_id=uuid4().hex
        request_origin = request.headers.get('origin')
        if browser_access and (request.headers.get('host','').lower() not in desktop_hosts
                               or not request.client or request.client.host not in {'127.0.0.1','::1'}):
            return JSONResponse({'detail':'Desktop access requires its exact loopback listener.'},status_code=403)
        if server and request.url.path not in {'/health/live','/health/ready'}:
            offered = bool(request.headers.get('authorization'))
            client = server.client_address(request) if throttle is not None else None
            if throttle is not None and offered and (wait := throttle.blocked_for(client)):
                # Credentials from a locked-out client are not evaluated at all; a request without credentials is just challenged.
                return JSONResponse({'detail':'Too many failed sign-in attempts. Try again later.'},status_code=429,headers={'Retry-After':str(wait)})
            from starlette.concurrency import run_in_threadpool
            if not await run_in_threadpool(server.authorized, request):
                if throttle is not None and offered and (cooldown := throttle.failure(client)):
                    import logging
                    logging.getLogger('sap-lens-server').warning('Sign-in throttled for client %s for %s seconds after repeated failures',client,cooldown)
                return JSONResponse({'detail':'Server access is not authorized.'},status_code=401,
                                    headers={'WWW-Authenticate':'Basic realm="SAP Lens", charset="UTF-8"'} if server.auth in {'basic','users'} else {})
            if throttle is not None and offered: throttle.success(client)
            if server.auth == 'users':
                from server_access import may_access
                username, role = request.state.server_principal
                if not may_access(role, request.method, request.url.path):
                    return JSONResponse({'detail':'Your account does not have permission for this operation.'},status_code=403)
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
                return JSONResponse({'detail': 'Application request is not authorized.', **({'code':'stale_session'} if browser_access else {})}, status_code=403)
        from application_backups import pending
        if request.method=='POST' and not request.url.path.startswith('/api/backups') and pending():
            return JSONResponse({'detail':'Backup/restore restart is pending. Restart SAP Lens or cancel it in Settings → Backup & Restore before editing.'},status_code=409)
        from server_access import ACTOR
        principal = getattr(request.state, 'server_principal', None)
        actor_token = ACTOR.set(principal[0] if principal else '')
        try:
            response = await call_next(request)
        except Exception as error:
            response=failure_response(request,error)
        finally:
            ACTOR.reset(actor_token)
        response.headers['X-Request-ID']=request.state.request_id
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=(), payment=(), usb=(), serial=(), bluetooth=()'
        if request.url.path.startswith(('/api/', '/health')):
            response.headers['Cache-Control'] = 'no-store'
        nonce = getattr(request.state,'desktop_nonce',None)
        script_policy = "'self'" + (f" 'nonce-{nonce}'" if nonce else '')
        response.headers['Content-Security-Policy'] = (
            f"default-src 'self'; script-src {script_policy}; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
            "object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        return response

    app.include_router(configuration_router(loader, desktop_preferences=desktop_preferences))
    from routers.refresh_schedule import refresh_schedule_router
    app.include_router(refresh_schedule_router(scheduler, server))
    app.state.scheduler = scheduler
    app.include_router(roles.router)
    app.include_router(access.router)
    app.include_router(employees.router)
    app.include_router(dashboard.router)
    app.include_router(account_review.router)
    app.include_router(user_comparison.router)
    app.include_router(data_health.router)
    app.include_router(saved_filters.router)
    from routers.backups import router as backups_router
    app.include_router(backups_router)
    app.include_router(data_sources.router)
    app.include_router(sod.router)
    app.include_router(sod_analysis.router)
    app.include_router(sod_reviews.router)
    app.include_router(sod_periods.router)
    app.include_router(sod_reports.router)
    app.include_router(sod_governance.router)
    from server_uploads import upload_router
    app.include_router(upload_router(server))
    app.include_router(modules.router)
    app.include_router(comparison.router)

    @app.get('/api/version', tags=['Application'])
    def application_version():
        return {'app': 'SAP Lens', 'version': VERSION, 'mode': BUILD_INFO['mode']}

    @app.get('/api/runtime')
    def runtime_capabilities(request: Request):
        from application_backups import pending
        if request.method=='POST' and not request.url.path.startswith('/api/backups') and pending():
            return JSONResponse({'detail':'Backup/restore restart is pending. Restart SAP Lens or cancel it in Settings → Backup & Restore before editing.'},status_code=409)
        from server_access import ACTOR
        principal = getattr(request.state, 'server_principal', None)
        return dict(deployment_mode='server' if server else 'desktop', browser_upload=True, username=ACTOR.get(),
                    role=principal[1] if principal else '',
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
        def spa_entry(path: str, request: Request):
            query = ('?' + request.url.query) if request.url.query else ''
            return RedirectResponse('/' + query + '#/' + path)
        def register_entry(section):
            def entry(request: Request):
                return spa_entry(section, request)
            def nested(request: Request, rest: str):
                return spa_entry(section + '/' + rest, request)
            app.add_api_route('/'+section, entry, methods=['GET'], include_in_schema=False)
            app.add_api_route('/'+section+'/{rest:path}', nested, methods=['GET'], include_in_schema=False)
        for section in ('dashboard','role-lookup','user-access','release-roles','sod'):
            register_entry(section)
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
