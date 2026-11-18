"""Server-side session auth: hashing, signed sessions, throttling and the HTTP gate."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.services import auth
from src.services.auth_routes import install_auth

SECRET = "x" * 40
PASSWORD = "correct-horse-battery"


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("NEUROCLIPS_AUTH_DISABLED", "0")
    monkeypatch.setenv("NEUROCLIPS_SESSION_SECRET", SECRET)
    monkeypatch.setenv("NEUROCLIPS_ADMIN_USER", "director")
    monkeypatch.setenv("NEUROCLIPS_ADMIN_PASSWORD_HASH", auth.hash_password(PASSWORD, iterations=1000))
    monkeypatch.setattr(auth, "login_throttle", auth.LoginThrottle())
    import src.services.auth_routes as routes
    monkeypatch.setattr(routes, "login_throttle", auth.login_throttle)


@pytest.fixture
def client(enabled):
    app = FastAPI()
    install_auth(app)

    @app.get("/")
    async def home():
        return {"page": "dashboard"}

    @app.get("/api/v1/secret")
    async def secret():
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return TestClient(app)


def test_hash_roundtrip():
    encoded = auth.hash_password("abc123", iterations=1000)
    assert auth.verify_password("abc123", encoded)
    assert not auth.verify_password("wrong", encoded)
    assert not auth.verify_password("abc123", "garbage")


def test_session_rejects_tamper_and_expiry(enabled):
    token = auth.issue_session("director", now=1000)
    assert auth.read_session(token, now=1001) == "director"
    payload, sig = token.rsplit(".", 1)
    assert auth.read_session(payload + "." + sig[:-1] + ("A" if sig[-1] != "A" else "B"), now=1001) is None
    assert auth.read_session(token, now=1000 + 13 * 3600) is None


def test_fails_closed_without_config(monkeypatch):
    monkeypatch.setenv("NEUROCLIPS_AUTH_DISABLED", "0")
    monkeypatch.delenv("NEUROCLIPS_ADMIN_PASSWORD_HASH", raising=False)
    monkeypatch.delenv("NEUROCLIPS_SESSION_SECRET", raising=False)
    assert not auth.check_credentials("director", "anything")


def test_api_requires_session(client):
    assert client.get("/api/v1/secret").status_code == 401
    assert client.get("/health").status_code == 200


def test_page_redirects_to_login(client):
    res = client.get("/", follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"].startswith("/login?redirect=")


def test_login_flow_sets_httponly_cookie(client):
    bad = client.post("/api/v1/auth/login", json={"username": "director", "password": "nope"})
    assert bad.status_code == 401
    good = client.post("/api/v1/auth/login", json={"username": "Director", "password": PASSWORD})
    assert good.status_code == 200
    assert "httponly" in good.headers["set-cookie"].lower()
    assert client.get("/api/v1/secret").json() == {"ok": True}
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/secret").status_code == 401


def test_login_throttled_after_repeated_failures(client):
    for _ in range(auth.MAX_FAILURES):
        client.post("/api/v1/auth/login", json={"username": "director", "password": "bad"})
    res = client.post("/api/v1/auth/login", json={"username": "director", "password": PASSWORD})
    assert res.status_code == 429


@pytest.mark.parametrize("target,expected", [
    ("/director", "/director"),
    ("//evil.com", "/"),
    ("https://evil.com", "/"),
    ("/\\evil.com", "/"),
    (None, "/"),
])
def test_safe_redirect_target(target, expected):
    assert auth.safe_redirect_target(target) == expected
