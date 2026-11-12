"""Session account API; mounted only for the new session boundary during migration."""
from fastapi import APIRouter, Request, Response
from pydantic import Field
from config_models import StrictModel
from auth_store import require

COOKIE = 'sap-lens-session'
CSRF_COOKIE = 'sap-lens-csrf'


class Login(StrictModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=1024)


class CreateUser(Login):
    display_name: str = Field(min_length=1, max_length=120)
    role: str


class UpdateUser(StrictModel):
    expected_revision: int = Field(ge=0)
    display_name: str = Field(min_length=1, max_length=120)
    role: str
    enabled: bool


class Password(StrictModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


class ResetPassword(StrictModel):
    code: str = Field(min_length=20, max_length=128)
    password: str = Field(min_length=12, max_length=1024)


class Activate(Login):
    code: str = Field(min_length=20, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)


class ConfirmReset(StrictModel):
    expected_revision: int = Field(ge=0)
    confirm: bool


class SessionPolicy(StrictModel):
    expected_revision: int = Field(ge=0)
    idle: int
    absolute: int


class Profile(StrictModel):
    expected_revision: int = Field(ge=0)
    display_name: str = Field(min_length=1, max_length=120)


def router_for(store, secure):
    router = APIRouter(prefix='/api/auth', tags=['Authentication'])

    def principal(request):
        return request.state.auth_principal

    @router.get('/state')
    def state(response: Response):
        response.headers['Cache-Control'] = 'no-store'
        from auth_provisioning import state
        return state(store)

    @router.post('/activate')
    def activate(body: Activate):
        from auth_provisioning import complete
        complete(store, body.code, body.username, body.display_name, body.password)
        return dict(ok=True, login_required=True)

    @router.post('/recover')
    def recover(body: ResetPassword):
        from auth_provisioning import complete
        complete(store, body.code, '', '', body.password, recovery=True)
        return dict(ok=True, login_required=True)

    @router.get('/migration')
    def migration_status(request: Request):
        require(principal(request),'accounts')
        from identity_migration import status
        return status(store.path.parent.parent)

    class MigrationConfirmation(StrictModel):
        confirm: bool

    @router.post('/migration/{identifier}/confirm')
    def migration_confirm(identifier: str, body: MigrationConfirmation, request: Request):
        require(principal(request),'accounts')
        from identity_migration import confirm
        if not body.confirm:
            from auth_store import AuthError
            raise AuthError('migration_confirmation_required')
        return confirm(store.path.parent.parent,identifier,principal(request))

    @router.post('/migration/{identifier}/delete')
    def migration_delete(identifier: str, body: MigrationConfirmation, request: Request):
        require(principal(request),'accounts')
        from identity_migration import confirm
        if not body.confirm:
            from auth_store import AuthError
            raise AuthError('migration_confirmation_required')
        return confirm(store.path.parent.parent,identifier,principal(request),delete=True)

    @router.post('/login')
    def login(body: Login, request: Request, response: Response):
        actor, token, csrf = store.login(body.username, body.password, request.app.state.deployment.client_address(request))
        for name, value, http_only in ((COOKIE, token, True), (CSRF_COOKIE, csrf, False)):
            response.set_cookie(name, value, httponly=http_only, secure=secure, samesite='lax', path='/')
        response.headers['Cache-Control'] = 'no-store'
        return actor.snapshot() | dict(role=actor.role)

    @router.get('/me')
    def me(request: Request, response: Response):
        response.headers['Cache-Control'] = 'no-store'
        return store.me(principal(request))

    @router.get('/sessions')
    def sessions(request: Request):
        return dict(items=store.sessions(principal(request)))

    @router.post('/logout')
    def logout(request: Request, response: Response):
        store.logout(principal(request))
        response.delete_cookie(COOKIE, path='/'); response.delete_cookie(CSRF_COOKIE, path='/')
        return dict(ok=True)

    @router.post('/logout-all')
    def logout_all(request: Request, response: Response):
        store.logout(principal(request), True)
        response.delete_cookie(COOKIE, path='/'); response.delete_cookie(CSRF_COOKIE, path='/')
        return dict(ok=True)

    @router.post('/password')
    def password(body: Password, request: Request, response: Response):
        store.change_password(principal(request), body.current_password, body.new_password)
        response.delete_cookie(COOKIE, path='/'); response.delete_cookie(CSRF_COOKIE, path='/')
        return dict(ok=True, login_required=True)

    @router.get('/users')
    def users(request: Request):
        return dict(items=store.users(principal(request)))

    @router.post('/users')
    def create(body: CreateUser, request: Request):
        return store.create_user(principal(request), body.username, body.display_name, body.role, body.password)

    @router.post('/users/{identity}')
    def update(identity: str, body: UpdateUser, request: Request):
        return store.update_user(principal(request), identity, body.expected_revision, role=body.role, enabled=body.enabled, display_name=body.display_name)

    @router.post('/users/{identity}/revoke')
    def revoke(identity: str, request: Request):
        store.revoke(principal(request), identity)
        return dict(ok=True)

    @router.get('/audit')
    def audit(request: Request, limit: int = 100):
        actor = principal(request)
        require(actor, 'accounts')
        with store.connection() as db:
            store._authorize(db, actor, 'accounts')
            return dict(items=[dict(row) for row in db.execute('SELECT * FROM audit ORDER BY at DESC LIMIT ?', (min(max(limit, 1), 200),))])

    @router.post('/profile')
    def profile(body: Profile, request: Request):
        return store.profile(principal(request), body.display_name, body.expected_revision)

    @router.post('/logout-others')
    def logout_others(request: Request):
        store.logout_others(principal(request))
        return dict(ok=True)

    @router.get('/policy')
    def policy(request: Request):
        return store.policy(principal(request))

    @router.post('/policy')
    def change_policy(body: SessionPolicy, request: Request):
        return store.update_policy(principal(request), body.expected_revision, body.idle, body.absolute)

    @router.post('/users/{identity}/reset')
    def request_reset(identity: str, body: ConfirmReset, request: Request, response: Response):
        from auth_store import AuthError
        if not body.confirm:
            raise AuthError('confirmation_required')
        response.headers['Cache-Control'] = 'no-store'
        return store.issue_reset(principal(request), identity, body.expected_revision)

    @router.post('/reset')
    def reset(body: ResetPassword, request: Request):
        store.complete_reset(body.code, body.password, request.app.state.deployment.client_address(request))
        return dict(ok=True, login_required=True)

    return router
