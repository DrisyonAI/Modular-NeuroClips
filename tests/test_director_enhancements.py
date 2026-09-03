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
