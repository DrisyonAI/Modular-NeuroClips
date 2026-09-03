"""
Exercise scorm_upload logic with pytest test cases and CLI runner compatibility.
"""
import sys
import types
import zipfile
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
import pytest

# Add src to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Stub fastapi / starlette only if they are not installed
try:
    import fastapi
    from fastapi import HTTPException
except ImportError:
    fastapi = types.ModuleType("fastapi")

    class HTTPException(Exception):
        def __init__(self, status_code=400, detail=""):
            self.status_code = status_code
            self.detail = detail
            super().__init__(f"{status_code}: {detail}")

    fastapi.HTTPException = HTTPException
    fastapi.File = lambda *a, **k: None
    fastapi.Form = lambda *a, **k: None

    class UploadFile:
        pass

    fastapi.UploadFile = UploadFile
    sys.modules["fastapi"] = fastapi

try:
    import starlette.concurrency
except ImportError:
    sc = types.ModuleType("starlette.concurrency")
    sc.run_in_threadpool = None
    starlette = types.ModuleType("starlette")
    starlette.concurrency = sc
    sys.modules["starlette"] = starlette
    sys.modules["starlette.concurrency"] = sc

import scorm_upload as su


def test_extract_videos_from_zip_normal(tmp_path):
    """1. Normal zip with nested dirs + non-video files extracts only videos and flattens."""
    z1 = tmp_path / "normal.zip"
    with zipfile.ZipFile(z1, "w") as zf:
        zf.writestr("intro.mp4", b"\x00" * 2048)
        zf.writestr("nested/deep/lesson2.mov", b"\x00" * 2048)
        zf.writestr("notes.txt", b"ignore me")
        zf.writestr("thumb.png", b"\x89PNG")
    out1 = tmp_path / "out1"
    out1.mkdir()
    vids = su._extract_videos_from_zip(z1, out1)
    names = sorted(v.name for v in vids)
    assert names == ["intro.mp4", "lesson2.mov"]
    assert not (out1 / "notes.txt").exists()
    assert all(v.parent == out1.resolve() or v.parent == out1 for v in vids)


def test_zip_slip_prevention(tmp_path):
    """2. Zip-slip traversal entry must not escape destination folder."""
    z2 = tmp_path / "slip.zip"
    with zipfile.ZipFile(z2, "w") as zf:
        zf.writestr("../../escaped.mp4", b"\x00" * 2048)
    out2 = tmp_path / "out2"
    out2.mkdir()
    escaped_target = out2.parent.parent / "escaped.mp4"
    try:
        su._extract_videos_from_zip(z2, out2)
    except HTTPException:
        pass
    assert not escaped_target.exists()


def test_colliding_basenames_deduplication(tmp_path):
    """3. Colliding basenames in subdirectories get unique names."""
    z3 = tmp_path / "collide.zip"
    with zipfile.ZipFile(z3, "w") as zf:
        zf.writestr("a/clip.mp4", b"\x00" * 2048)
        zf.writestr("b/clip.mp4", b"\x11" * 2048)
        zf.writestr("c/clip.mp4", b"\x22" * 2048)
    out3 = tmp_path / "out3"
    out3.mkdir()
    v3 = su._extract_videos_from_zip(z3, out3)
    n3 = sorted(v.name for v in v3)
    assert len(set(n3)) == 3
    assert len(n3) == 3


def test_empty_zip_rejected(tmp_path):
    """4. Archive with no videos is rejected with 400."""
    z4 = tmp_path / "novid.zip"
    with zipfile.ZipFile(z4, "w") as zf:
        zf.writestr("readme.txt", b"nothing here")
    out4 = tmp_path / "out4"
    out4.mkdir()
    with pytest.raises(HTTPException) as exc_info:
        su._extract_videos_from_zip(z4, out4)
    assert exc_info.value.status_code == 400


def test_corrupt_zip_rejected(tmp_path):
    """5. Corrupt archive rejected with 400."""
    z5 = tmp_path / "bad.zip"
    z5.write_bytes(b"this is not a zip file at all")
    out5 = tmp_path / "out5"
    out5.mkdir()
    with pytest.raises(HTTPException) as exc_info:
        su._extract_videos_from_zip(z5, out5)
    assert exc_info.value.status_code == 400


def test_oversized_archive_rejected(tmp_path):
    """6. Declared-size bomb is refused before extracting."""
    orig = su.MAX_UNPACKED_BYTES
    su.MAX_UNPACKED_BYTES = 4096
    try:
        z6 = tmp_path / "bomb.zip"
        with zipfile.ZipFile(z6, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("big.mp4", b"\x00" * (64 * 1024))
        out6 = tmp_path / "out6"
        out6.mkdir()
        with pytest.raises(HTTPException) as exc_info:
            su._extract_videos_from_zip(z6, out6)
        assert exc_info.value.status_code == 413
    finally:
        su.MAX_UNPACKED_BYTES = orig


def test_manifest_xml_validity():
    """7. Manifest is well-formed XML and escapes user input."""
    man = su._build_manifest(
        "FIN_M1", 'Course & "Quotes" <hi>', "Module 1: Intro", "1.2", ["a.mp4", "b & c.mp4"]
    )
    root = ET.fromstring(man)
    assert root.tag.endswith("manifest")

    man2004 = su._build_manifest("FIN_M1", "Course", "Module", "2004", ["a.mp4"])
    root2004 = ET.fromstring(man2004)
    assert "2004" in man2004


def test_playlist_player_html():
    """8. Playlist player embeds the list, escapes title, and reports LMS completion."""
    html = su._playlist_player_html(["a.mp4", "b.mp4"], 'C&o <x>', "Mod", "Topic", None)
    assert '"a.mp4"' in html and '"b.mp4"' in html
    assert "C&amp;o" in html and "<x>" not in html
    assert "completion_status" in html and "LMSSetValue" in html


def test_identifier_sanitizing():
    """9. Identifier and filename sanitization."""
    assert su._safe_id("../../evil id!", "X") == "evilid"
    assert su._safe_id("", "COURSE") == "COURSE"
    assert su._unique_name("../../etc/passwd.mp4", set()) == "passwd.mp4"


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        test_extract_videos_from_zip_normal(p)
        test_zip_slip_prevention(p)
        test_colliding_basenames_deduplication(p)
        test_empty_zip_rejected(p)
        test_corrupt_zip_rejected(p)
        test_oversized_archive_rejected(p)
    test_manifest_xml_validity()
    test_playlist_player_html()
    test_identifier_sanitizing()
    print("ALL SCORM UPLOAD TESTS PASSED.")
