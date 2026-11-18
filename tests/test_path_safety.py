"""Path guards on filename-based endpoints and upload size caps."""
import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.config import IDENTITIES_DIR, OUTPUT_DIR
from src.dashboard import app
from src.services.path_safety import (
    read_upload_capped,
    resolve_under_roots,
    resolve_within,
    safe_upload_name,
)

client = TestClient(app)


@pytest.mark.parametrize("name", ["..", ".", "../x", "a/b", "a\\b", "", "x\x00y"])
def test_resolve_within_rejects(tmp_path, name):
    with pytest.raises(HTTPException):
        resolve_within(tmp_path, name)


def test_resolve_within_accepts_child(tmp_path):
    assert resolve_within(tmp_path, "clip.mp4") == (tmp_path / "clip.mp4").resolve()


def test_resolve_under_roots(tmp_path):
    inner = tmp_path / "docs" / "deck.pptx"
    assert resolve_under_roots(str(inner), [tmp_path]) == inner.resolve()
    with pytest.raises(HTTPException) as exc:
        resolve_under_roots(str(tmp_path / ".." / "outside.pptx"), [tmp_path])
    assert exc.value.status_code == 403


def test_safe_upload_name_strips_path_and_checks_suffix():
    name = safe_upload_name("../../etc/evil name.pptx", [".pptx"])
    assert "/" not in name and ".." not in name and name.endswith(".pptx")
    with pytest.raises(HTTPException):
        safe_upload_name("run.sh", [".pptx"])


class _FakeUpload:
    def __init__(self, size):
        self._left = size

    async def read(self, n=-1):
        if self._left <= 0:
            return b""
        take = min(n, self._left)
        self._left -= take
        return b"x" * take


def test_read_upload_capped():
    assert len(asyncio.run(read_upload_capped(_FakeUpload(10), 100))) == 10
    with pytest.raises(HTTPException) as exc:
        asyncio.run(read_upload_capped(_FakeUpload(3 * 1024 * 1024), 1024 * 1024))
    assert exc.value.status_code == 413


def test_gallery_delete_cannot_escape_output_dir():
    sentinel = OUTPUT_DIR.parent / "sentinel_do_not_delete.txt"
    sentinel.write_text("keep")
    try:
        res = client.delete("/api/v1/gallery/..%5Csentinel_do_not_delete.txt")
        assert res.status_code in (400, 404)
        assert sentinel.exists()
    finally:
        sentinel.unlink(missing_ok=True)


def test_identity_save_rejects_empty_name():
    res = client.post("/api/v1/identity/save", json={
        "name": "../..", "avatar_persona": "maya", "avatar_layout": "pip",
        "preferred_voice": "v", "speech_rate": 1.0,
    })
    assert res.status_code == 400
    assert not (IDENTITIES_DIR / ".json").exists()
