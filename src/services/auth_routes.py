"""
Wires session auth into the FastAPI app: a gate middleware plus
/api/v1/auth/login, /api/v1/auth/logout and /api/v1/auth/me.
"""
import logging
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from src.services.auth import (
    SESSION_COOKIE,
    auth_configured,
    auth_disabled,
    check_credentials,
    is_public_path,
    issue_session,
    login_throttle,
    read_session,
    safe_redirect_target,
    _session_ttl_seconds,
)

logger = logging.getLogger(__name__)


class LoginRequest(BaseModel):
    username: str
    password: str
    redirect: str = "/"


def _client_key(request: Request) -> str:
    # Last hop is the address our own reverse proxy saw; earlier entries are client-supplied.
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _is_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "") == "https"


def _wants_json(path: str) -> bool:
    return path.startswith("/api/") or path.startswith("/metrics")


def install_auth(app: FastAPI) -> None:
    if auth_disabled():
        logger.warning("NEUROCLIPS_AUTH_DISABLED is set: the control plane is UNAUTHENTICATED.")
    elif not auth_configured():
        logger.warning(
            "Auth is not configured (NEUROCLIPS_ADMIN_PASSWORD_HASH / NEUROCLIPS_SESSION_SECRET). "
            "All protected routes will reject requests."
        )

    @app.middleware("http")
    async def session_gate(request: Request, call_next):
        path = request.url.path
        if auth_disabled() or is_public_path(path):
            return await call_next(request)
        if read_session(request.cookies.get(SESSION_COOKIE)):
            return await call_next(request)
        if _wants_json(path):
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        target = quote(path + (f"?{request.url.query}" if request.url.query else ""), safe="")
        return RedirectResponse(f"/login?redirect={target}", status_code=303)

    @app.post("/api/v1/auth/login")
    async def auth_login(req: LoginRequest, request: Request):
        key = _client_key(request)
        if login_throttle.is_blocked(key):
            return JSONResponse({"detail": "Too many attempts. Try again in a few minutes."}, status_code=429)
        if not check_credentials(req.username, req.password):
            login_throttle.record_failure(key)
            return JSONResponse({"detail": "Invalid credentials"}, status_code=401)
        login_throttle.reset(key)
        response = JSONResponse({"status": "ok", "redirect": safe_redirect_target(req.redirect)})
        response.set_cookie(
            SESSION_COOKIE,
            issue_session(req.username.strip().lower()),
            max_age=_session_ttl_seconds(),
            httponly=True,
            secure=_is_https(request),
            samesite="lax",
            path="/",
        )
        return response

    @app.post("/api/v1/auth/logout")
    async def auth_logout():
        response = JSONResponse({"status": "ok"})
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    @app.get("/api/v1/auth/me")
    async def auth_me(request: Request):
        user = "local-dev" if auth_disabled() else read_session(request.cookies.get(SESSION_COOKIE))
        return {"user": user}
