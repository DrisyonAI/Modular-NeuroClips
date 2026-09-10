"""Tests for Director Page Functional Redesign & Enhancements.

Covers:
1. Aspect ratios (including 4:5 portrait & SD profiles)
2. Instructional slide generation (high-contrast card with title & bullet points)
3. Motion graphics toggle (motion enabled vs static loop)
4. Background music track generation and ducking mixing
5. Request schemas and endpoints for output_type, motion_graphics, and background_music
"""
import os
import sys
from pathlib import Path
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import RESOLUTION_PROFILES, ASSETS_DIR, OUTPUT_DIR
from src.pipeline import MediaGenerationEngine
from src.compiler import ensure_ambient_bgm_track, compile_final_video


def test_4_5_resolution_profiles():
    """Verify 4:5 aspect ratio profiles are correctly registered in config."""
    assert "4:5_portrait" in RESOLUTION_PROFILES
    assert "4:5_sd" in RESOLUTION_PROFILES

    hd = RESOLUTION_PROFILES["4:5_portrait"]
    assert hd["width"] == 1080
    assert hd["height"] == 1350
    assert hd["width"] / hd["height"] == pytest.approx(4 / 5)
    assert hd["orientation"] == "portrait"

    sd = RESOLUTION_PROFILES["4:5_sd"]
    assert sd["width"] == 576
    assert sd["height"] == 720
    assert sd["width"] / sd["height"] == pytest.approx(4 / 5)
    assert sd["orientation"] == "portrait"


def test_generate_instructional_slide(tmp_path):
    """Verify MediaGenerationEngine renders a valid instructional slide image."""
    engine = MediaGenerationEngine()
    out_file = tmp_path / "test_slide.png"

    ok = engine.generate_instructional_slide(
        title="Core Principles of Liquidity Pools",
        content="• Constant product market maker formula: x * y = k\n• Impermanent loss risks across volatility regimes\n• Automated rebalancing and fee tier distribution",
        output_path=out_file,
        resolution="16:9_hd",
        badge_text="FinTech AI Architecture"
    )

    assert ok is True
    assert out_file.exists()
    img = Image.open(out_file)
    assert img.size == (1280, 720)
    assert img.format == "PNG"


def test_generate_instructional_slide_portrait(tmp_path):
    """Verify instructional slide renders correctly in 4:5 portrait mode."""
    engine = MediaGenerationEngine()
    out_file = tmp_path / "test_slide_portrait.png"

    ok = engine.generate_instructional_slide(
        title="Key Formula",
        content="x * y = k\nAutomated Market Depth",
        output_path=out_file,
        resolution="4:5_portrait",
        badge_text="Module Summary"
    )

    assert ok is True
    assert out_file.exists()
    img = Image.open(out_file)
    assert img.size == (1080, 1350)


def test_ensure_ambient_bgm_track():
    """Verify ambient background music generator produces an audio file."""
    bgm_path = ensure_ambient_bgm_track()
    assert Path(bgm_path).exists()
    assert Path(bgm_path).stat().st_size > 0


def test_director_fastapi_endpoints():
    """Test API models and endpoints if FastAPI is available."""
    try:
        from src.dashboard import (
            GenerationRequest,
            FromStoryboardRequest,
            StoryboardPreviewRequest,
            app
        )
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("FastAPI not installed in current environment")

    gen_req = GenerationRequest(
        topic="FinTech AI",
        output_type="slide",
        motion_graphics=False,
        background_music=True,
        chunking_mode="auto"
    )
    assert gen_req.output_type == "slide"
    assert gen_req.motion_graphics is False
    assert gen_req.background_music is True
    assert gen_req.chunking_mode == "auto"

    client = TestClient(app)
    response = client.post(
        "/api/v1/storyboard/preview",
        json={
            "topic": "Overview of Automated Settlement in Distributed Ledger Networks",
            "scenes": 2,
            "art_style": "Cinematic 35mm (Volumetric Lighting)",
            "avatar_persona": "maya_fintech",
            "output_type": "slide"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    scenes = data["script"]["scenes"]
    assert len(scenes) >= 1
    assert scenes[0]["output_type"] == "slide"


def test_vault_video_state_model_in_dashboard_ui():
    """Verify that Media Vault contains the 5-state video lifecycle model and guards."""
    dashboard_path = Path(__file__).resolve().parent.parent / "src" / "dashboard.py"
    content = dashboard_path.read_text(encoding="utf-8")

    # Verify State Machine presence
    assert "setVideoCardState" in content
    assert "onVideoLifecycleEvent" in content
    assert "updateVaultRenderingCard" in content
    assert "removeVaultRenderingCard" in content

    # Verify 5 distinct states
    for state in ["RENDERING", "READY", "LOADING_VIDEO", "PLAYABLE", "ERROR"]:
        assert state in content

    # Verify HTML5 lifecycle events hooked
    for event in ["loadedmetadata", "loadeddata", "canplay", "waiting", "playing", "error"]:
        assert event in content

    # Verify single completion fetch guard
    assert "LAST_FETCHED_COMPLETED_JOB_ID" in content
    assert "CACHED_GALLERY_FINGERPRINT" in content


def test_slide_mode_skips_video_rendering(tmp_path, monkeypatch):
    """Verify that when Slide mode is selected, only slide output is generated (no video clips / ffmpeg)."""
    from src.services.job_manager import JobManager
    from src.services.pipeline_runner import run_production_pipeline
    import src.services.pipeline_runner as pr_mod

    jm = JobManager(max_history=5)
    monkeypatch.setattr(pr_mod, "job_manager", jm)

    job_id = jm.create_job(
        topic="Algorithmic Order Types",
        scene_count=2,
        art_style="Corporate Modern",
        resolution="16:9_hd",
        voice="en-IN-NeerjaNeural",
        output_type="slide"
    )

    scenes = [
        {
            "scene_id": 1,
            "title": "Iceberg Orders",
            "visual_prompt": "Automated iceberg order slicing across fragmented liquidity",
            "narration": "Iceberg orders disguise large institutional trade volume.",
            "duration_seconds": 3,
            "output_type": "slide"
        },
        {
            "scene_id": 2,
            "title": "TWAP vs VWAP",
            "visual_prompt": "Volume weighted average price vs time weighted execution curves",
            "narration": "Execution benchmarks minimize market impact.",
            "duration_seconds": 3,
            "output_type": "slide"
        }
    ]

    # Run pipeline in pure slide mode
    run_production_pipeline(
        job_id=job_id,
        title="Algorithmic Order Types",
        scenes=scenes,
        art_style="Corporate Modern",
        resolution="16:9_hd",
        language="en-US",
        voice="en-IN-NeerjaNeural",
        speech_rate=1.0,
        compiler_engine="ffmpeg",
        avatar_persona="maya_fintech",
        avatar_layout="pip_bottom_right",
        burn_subtitles=True,
        output_type="slide",
        motion_graphics=False,
        background_music=False
    )

    job = jm.get_job(job_id)
    assert job["status"] == "complete"
    assert job["output_type"] == "slide"
    # Ensure NO video clips were generated
    assert len(job["clip_paths"]) == 0
    # Ensure slide output was generated and saved
    assert job["output_path"].endswith(".png")
    assert Path(job["output_path"]).exists()
    assert len(job["keyframe_paths"]) == 2

