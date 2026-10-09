from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from auth_service.api import safe_redirect
from auth_service.config import AuthSettings
from auth_service.domain import InvalidCredentials, Role
from auth_service.main import build_app, build_service
from auth_service.security import PasswordHasher

ADMIN_PASSWORD = "super-secret-admin"


@pytest.fixture
def settings(tmp_path: Path) -> AuthSettings:
    return AuthSettings(
        database_path=str(tmp_path / "auth.db"),
        jwt_secret="test-secret-test-secret-test-secret",
        admin_password=ADMIN_PASSWORD,
        tracing_enabled=False,
    )


@pytest.fixture
def client(settings: AuthSettings) -> TestClient:
    service = build_service(settings, hasher=PasswordHasher(rounds=4))
    return TestClient(build_app(settings, service), follow_redirects=False)


def _bearer(client: TestClient, username: str, password: str) -> dict[str, str]:
    token = client.post("/auth/token", json={"username": username, "password": password}).json()
    return {"Authorization": f"Bearer {token['access_token']}"}


def test_browser_login_sets_http_only_cookie_and_redirects(client: TestClient) -> None:
    response = client.post(
        "/auth/login", data={"username": "admin", "password": ADMIN_PASSWORD, "next": "/grafana/d/x"}
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/grafana/d/x"
    assert "httponly" in response.headers["set-cookie"].lower()


def test_wrong_password_is_rejected(client: TestClient) -> None:
    response = client.post("/auth/login", data={"username": "admin", "password": "nope"})

    assert response.status_code == 401
    assert "Invalid username or password" in response.text


def test_verify_without_token_is_unauthorized(client: TestClient) -> None:
    assert client.get("/auth/verify").status_code == 401


def test_verify_with_garbage_token_is_unauthorized(client: TestClient) -> None:
    response = client.get("/auth/verify", headers={"Authorization": "Bearer not-a-jwt"})

    assert response.status_code == 401


def test_verify_returns_identity_headers_for_gateway(client: TestClient) -> None:
    response = client.get("/auth/verify", headers=_bearer(client, "admin", ADMIN_PASSWORD))

    assert response.status_code == 204
    assert response.headers["X-User"] == "admin"
    assert response.headers["X-Role"] == "admin"
    assert response.headers["X-Grafana-Role"] == "Admin"


def test_admin_creates_viewer_who_cannot_pass_admin_check(client: TestClient) -> None:
    admin = _bearer(client, "admin", ADMIN_PASSWORD)
    created = client.post(
        "/auth/users", json={"username": "toto", "password": "wolff-1234", "role": "viewer"}, headers=admin
    )
    viewer = _bearer(client, "toto", "wolff-1234")

    assert created.status_code == 201
    assert client.get("/auth/verify", headers=viewer).status_code == 204
    assert client.get("/auth/verify?role=admin", headers=viewer).status_code == 403
    assert (
        client.post("/auth/users", json={"username": "x" * 5, "password": "p" * 10}, headers=viewer).status_code == 403
    )


def test_duplicate_user_conflicts(client: TestClient) -> None:
    admin = _bearer(client, "admin", ADMIN_PASSWORD)
    payload = {"username": "christian", "password": "horner-1234", "role": "engineer"}

    assert client.post("/auth/users", json=payload, headers=admin).status_code == 201
    assert client.post("/auth/users", json=payload, headers=admin).status_code == 409


def test_service_rejects_unknown_user(settings: AuthSettings) -> None:
    service = build_service(settings, hasher=PasswordHasher(rounds=4))

    with pytest.raises(InvalidCredentials):
        service.login("ghost", "whatever")


def test_role_hierarchy() -> None:
    assert Role.ADMIN.grants(Role.ENGINEER)
    assert Role.ENGINEER.grants(Role.VIEWER)
    assert not Role.VIEWER.grants(Role.ENGINEER)


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("/grafana/", "/grafana/"),
        ("/api/races", "/api/races"),
        ("https://evil.example", "/default"),
        ("//evil.example", "/default"),
        ("/\\evil.example", "/default"),
        (None, "/default"),
    ],
)
def test_safe_redirect_blocks_open_redirects(target: str | None, expected: str) -> None:
    assert safe_redirect(target, "/default") == expected
