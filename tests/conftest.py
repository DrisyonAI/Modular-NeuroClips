"""
Shared pytest setup.

Feature tests exercise endpoints directly, so the session gate is bypassed by
default. tests/test_auth.py turns it back on per test with monkeypatch.
"""
import os

os.environ.setdefault("NEUROCLIPS_AUTH_DISABLED", "1")
