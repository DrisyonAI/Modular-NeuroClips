"""
Server-side session authentication for the Studio control plane.

Stdlib only: PBKDF2 password hashes and HMAC-signed session cookies.

Environment:
  NEUROCLIPS_ADMIN_USER           login id (default "director")
  NEUROCLIPS_ADMIN_PASSWORD_HASH  output of `python -m src.services.auth hash`
  NEUROCLIPS_SESSION_SECRET       random string, >= 32 chars
  NEUROCLIPS_SESSION_TTL_HOURS    session lifetime (default 12)
  NEUROCLIPS_AUTH_DISABLED        "1" to bypass auth (local dev / tests only)

Fails closed: if the hash or secret is missing, no login can succeed.
"""
import base64
import getpass
import hashlib
import hmac
import json
import os
import secrets
import sys
import threading
import time
from typing import Dict, List, Optional

SESSION_COOKIE = "nc_session"
PBKDF2_ITERATIONS = 310_000
MAX_FAILURES = 5
FAILURE_WINDOW_SECONDS = 300

PUBLIC_PATHS = frozenset({
    "/login",
    "/signin",
    "/health",
    "/favicon.ico",
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
})


def auth_disabled() -> bool:
    return os.getenv("NEUROCLIPS_AUTH_DISABLED", "").lower() in ("1", "true", "yes")


def _admin_user() -> str:
    return os.getenv("NEUROCLIPS_ADMIN_USER", "director")


def _session_secret() -> Optional[bytes]:
    secret = os.getenv("NEUROCLIPS_SESSION_SECRET", "")
    return secret.encode("utf-8") if len(secret) >= 32 else None


def _session_ttl_seconds() -> int:
    try:
        return int(float(os.getenv("NEUROCLIPS_SESSION_TTL_HOURS", "12")) * 3600)
    except ValueError:
        return 12 * 3600


def auth_configured() -> bool:
    return bool(os.getenv("NEUROCLIPS_ADMIN_PASSWORD_HASH")) and _session_secret() is not None


# --------------------------------------------------------------------------
# Password hashing
# --------------------------------------------------------------------------
def hash_password(password: str, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    # ':' separator, not '$': docker compose and shells interpolate '$' in env files.
    return f"pbkdf2_sha256:{iterations}:{salt}:{digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, iterations, salt, expected = encoded.split(":", 3)
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def check_credentials(username: str, password: str) -> bool:
    encoded = os.getenv("NEUROCLIPS_ADMIN_PASSWORD_HASH", "")
    if not encoded or _session_secret() is None:
        return False
    user_ok = hmac.compare_digest(username.strip().lower(), _admin_user().strip().lower())
    pass_ok = verify_password(password, encoded)
    return user_ok and pass_ok


# --------------------------------------------------------------------------
# Signed session tokens
# --------------------------------------------------------------------------
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def issue_session(username: str, now: Optional[float] = None) -> str:
    secret = _session_secret()
    if secret is None:
        raise RuntimeError("NEUROCLIPS_SESSION_SECRET is missing or shorter than 32 characters")
    issued = int(now if now is not None else time.time())
    payload = _b64(json.dumps(
        {"u": username, "exp": issued + _session_ttl_seconds()}, separators=(",", ":")
    ).encode("utf-8"))
    sig = _b64(hmac.new(secret, payload.encode("ascii"), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_session(token: Optional[str], now: Optional[float] = None) -> Optional[str]:
    """Returns the username for a valid, unexpired token, else None."""
    secret = _session_secret()
    if not token or secret is None or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    expected = _b64(hmac.new(secret, payload.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        data = json.loads(_unb64(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(data.get("exp", 0)) < int(now if now is not None else time.time()):
        return None
    return data.get("u")


# --------------------------------------------------------------------------
# Login throttling (per client IP, in-process)
# --------------------------------------------------------------------------
class LoginThrottle:
    def __init__(self, max_failures: int = MAX_FAILURES, window: int = FAILURE_WINDOW_SECONDS):
        self._max = max_failures
        self._window = window
        self._failures: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> List[float]:
        return [t for t in self._failures.get(key, []) if now - t < self._window]

    def is_blocked(self, key: str, now: Optional[float] = None) -> bool:
        now = now if now is not None else time.time()
        with self._lock:
            recent = self._recent(key, now)
            self._failures = {**self._failures, key: recent}
            return len(recent) >= self._max

    def record_failure(self, key: str, now: Optional[float] = None) -> None:
        now = now if now is not None else time.time()
        with self._lock:
            self._failures = {**self._failures, key: [*self._recent(key, now), now]}

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures = {k: v for k, v in self._failures.items() if k != key}


login_throttle = LoginThrottle()


def is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS


def safe_redirect_target(target: Optional[str]) -> str:
    """Only allow same-origin relative paths to prevent open redirects."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return "/"
    return target


def _cli(argv: List[str]) -> int:
    if len(argv) >= 1 and argv[0] == "hash":
        pw = getpass.getpass("Admin password: ")
        if len(pw) < 12:
            print("Password must be at least 12 characters.", file=sys.stderr)
            return 1
        print(hash_password(pw))
        return 0
    if len(argv) >= 1 and argv[0] == "secret":
        print(secrets.token_urlsafe(48))
        return 0
    print("usage: python -m src.services.auth [hash|secret]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
