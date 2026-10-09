"""HTTP layer: translates requests into AuthService calls and back."""

from html import escape
from importlib.resources import files
from string import Template
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from auth_service.config import AuthSettings
from auth_service.domain import InvalidCredentials, InvalidToken, Principal, Role, UserAlreadyExists
from auth_service.service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])

_LOGIN_PAGE = Template(files("auth_service").joinpath("templates/login.html").read_text())


# ---------- dependencies ----------


def get_service(request: Request) -> AuthService:
    return request.app.state.auth_service


def get_settings(request: Request) -> AuthSettings:
    return request.app.state.settings


ServiceDep = Annotated[AuthService, Depends(get_service)]
SettingsDep = Annotated[AuthSettings, Depends(get_settings)]


def extract_token(request: Request, settings: SettingsDep) -> str | None:
    """Token comes from the session cookie (browser) or a Bearer header (API clients)."""
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.cookies.get(settings.cookie_name)


def current_principal(service: ServiceDep, token: Annotated[str | None, Depends(extract_token)]) -> Principal:
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        return service.authenticate(token)
    except InvalidToken as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc


PrincipalDep = Annotated[Principal, Depends(current_principal)]


def require_admin(principal: PrincipalDep) -> Principal:
    if not principal.role.grants(Role.ADMIN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")
    return principal


# ---------- schemas ----------


class Credentials(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth2 token type, not a secret
    expires_in: int


class NewUser(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)
    role: Role = Role.VIEWER


class UserView(BaseModel):
    username: str
    role: Role


# ---------- browser flow ----------


def safe_redirect(target: str | None, default: str) -> str:
    """Allow only same-site relative paths to prevent open-redirect attacks."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return default
    return target


def _render_login(next_url: str, error: str | None = None) -> str:
    error_block = f'<p class="error">{escape(error)}</p>' if error else ""
    return _LOGIN_PAGE.substitute(next=escape(next_url, quote=True), error_block=error_block)


@router.get("/login", response_class=HTMLResponse)
def login_page(settings: SettingsDep, next: str | None = None) -> str:  # noqa: A002
    return _render_login(safe_redirect(next, settings.default_redirect))


@router.post("/login", response_class=HTMLResponse)
def login_form(
    service: ServiceDep,
    settings: SettingsDep,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    next: Annotated[str | None, Form()] = None,  # noqa: A002
) -> Response:
    target = safe_redirect(next, settings.default_redirect)
    try:
        token = service.login(username, password)
    except InvalidCredentials:
        return HTMLResponse(
            _render_login(target, "Invalid username or password"),
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    response = RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        settings.cookie_name,
        token,
        max_age=service.token_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/logout")
def logout(settings: SettingsDep) -> RedirectResponse:
    response = RedirectResponse("/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(settings.cookie_name, path="/")
    return response


# ---------- API flow ----------


@router.post("/token", response_model=TokenResponse)
def issue_token(credentials: Credentials, service: ServiceDep) -> TokenResponse:
    try:
        token = service.login(credentials.username, credentials.password)
    except InvalidCredentials as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password") from exc
    return TokenResponse(access_token=token, expires_in=service.token_ttl_seconds)


@router.get("/verify", status_code=status.HTTP_204_NO_CONTENT)
def verify(
    principal: PrincipalDep,
    response: Response,
    role: Annotated[Role, Query()] = Role.VIEWER,
) -> None:
    """Called by the nginx gateway (auth_request) before every protected request."""
    if not principal.role.grants(role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Role '{role}' required")
    response.headers["X-User"] = principal.username
    response.headers["X-Role"] = principal.role.value
    response.headers["X-Grafana-Role"] = principal.role.grafana_role


@router.get("/me", response_model=UserView)
def me(principal: PrincipalDep) -> UserView:
    return UserView(username=principal.username, role=principal.role)


@router.get("/users", response_model=list[UserView], dependencies=[Depends(require_admin)])
def list_users(service: ServiceDep) -> list[UserView]:
    return [UserView(username=u.username, role=u.role) for u in service.list_users()]


@router.post(
    "/users",
    response_model=UserView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def create_user(payload: NewUser, service: ServiceDep) -> UserView:
    try:
        user = service.register(payload.username, payload.password, payload.role)
    except UserAlreadyExists as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "User already exists") from exc
    return UserView(username=user.username, role=user.role)
