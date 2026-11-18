"""Batch slide routes: one definition each, UI response contract, path guards."""
import pytest
from fastapi.testclient import TestClient

import src.dashboard as dashboard
from src.dashboard import app

client = TestClient(app)


class _FakeResult:
    total_slides = 2
    successful_slides = 2
    failed_slides = 0
    output_directory = "render_output/batch_slides/M01"
    manifest_file = "batch_manifest.json"
    generated_files = [{"file": "M1_T1_L1_Slide1.mp3"}, {"file": "M1_T1_L1_Slide2.mp3"}]


def test_each_batch_route_registered_once():
    paths = [getattr(r, "path", "") for r in app.routes]
    assert paths.count("/api/v1/voice/batch-slides") == 1
    assert paths.count("/api/v1/voice/batch-slides-upload") == 1


def test_upload_returns_ui_contract(monkeypatch):
    seen = {}

    def fake_run(source, *args):
        seen["source"] = source
        return _FakeResult()

    monkeypatch.setattr(dashboard, "_run_slide_batch", fake_run)
    res = client.post(
        "/api/v1/voice/batch-slides-upload",
        files={"file": ("../../evil deck.pptx", b"PK\x03\x04fake", "application/octet-stream")},
        data={"module_num": "1", "skip_existing": "true"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert len(body["files"]) == 2
    # Uploaded name is sanitised and the temp file stays inside temp_uploads
    assert seen["source"].parent.name == "temp_uploads"
    assert ".." not in seen["source"].name
    assert not seen["source"].exists()


def test_upload_rejects_other_types():
    res = client.post(
        "/api/v1/voice/batch-slides-upload",
        files={"file": ("notes.sh", b"echo hi", "text/plain")},
    )
    assert res.status_code == 400


@pytest.mark.parametrize("bad", ["/etc/passwd.xlsx", "../../../../etc/hosts.pptx"])
def test_server_path_outside_app_is_refused(bad):
    res = client.post("/api/v1/voice/batch-slides", json={"excel_path": bad})
    assert res.status_code == 403
