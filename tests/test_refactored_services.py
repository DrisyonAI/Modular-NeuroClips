"""
Unit and integration tests for refactored services and multi-agent contracts.
"""
import pytest
from pathlib import Path
from src.services.job_manager import JobManager, MILESTONES
from src.services.telemetry import get_system_telemetry
from src.services.audio_service import (
    translate_narration_text,
    resolve_video_path,
)
from src.contracts.persona import get_persona_contract, PERSONA_CATALOG
from src.pipeline import MediaGenerationEngine
from src.config import get_resolution_dimensions


def test_job_manager_lifecycle():
    jm = JobManager(max_history=5)
    assert jm.pipeline_state["status"] == "Idle"

    job_id = jm.create_job(
        topic="FinTech AI Risk Management",
        scene_count=3,
        art_style="Photorealistic 8K",
        resolution="16:9_hd",
        voice="en-IN-NeerjaNeural"
    )
    assert job_id is not None
    assert jm.active_job_id == job_id
    assert jm.pipeline_state["status"] == "Generating Script"

    # Test milestone progression
    jm.log_milestone(job_id, "keyframes", "Generating keyframes", 45, "Keyframe log")
    job = jm.get_job(job_id)
    assert job["current_milestone"] == "keyframes"
    assert job["progress_percent"] == 45
    assert any("Keyframe log" in log for log in job["logs"])

    # Test completion
    jm.complete_job(job_id, "output/final.mp4")
    assert job["status"] == "complete"
    assert job["output_path"] == "output/final.mp4"
    assert jm.pipeline_state["status"] == "Complete"

    # Test reset
    jm.reset_pipeline()
    assert jm.pipeline_state["status"] == "Idle"
    assert jm.active_job_id is None


def test_telemetry_service():
    metrics = get_system_telemetry()
    assert "gpu" in metrics
    assert "system" in metrics
    assert "timestamp" in metrics
    assert "cpu_percent" in metrics["system"]
    assert "available" in metrics["gpu"]


def test_audio_service_translation_and_paths(tmp_path):
    # en-US returns untouched
    assert translate_narration_text("Hello World", "en-US") == "Hello World"
    # Empty string
    assert translate_narration_text("", "es-ES") == ""

    # Path resolution on nonexistent path
    assert resolve_video_path("") is None
    assert resolve_video_path(None) is None

    # Real file resolution
    sample_file = tmp_path / "test.mp4"
    sample_file.touch()
    assert resolve_video_path(str(sample_file)) == str(sample_file)


def test_resolution_profile_dimensions():
    assert get_resolution_dimensions("16:9_hd") == (1280, 720)
    assert get_resolution_dimensions("16:9_fhd") == (1920, 1080)
    assert get_resolution_dimensions("9:16_vertical") == (720, 1280)
    assert get_resolution_dimensions("1:1_square") == (720, 720)
    assert get_resolution_dimensions("800x600") == (800, 600)
    assert get_resolution_dimensions("invalid") == (1280, 720)


def test_media_engine_methods_and_fallbacks(tmp_path):
    engine = MediaGenerationEngine(output_dir=tmp_path)
    placeholder_file = tmp_path / "test_card.png"

    # Test procedural placeholder card generation
    created = engine._create_placeholder_image(
        prompt="FinTech AI Risk and Autonomous Execution",
        output_path=placeholder_file,
        resolution="16:9_hd",
        title="TEST CARD"
    )
    assert created is True
    assert placeholder_file.exists()
    assert placeholder_file.stat().st_size > 500

    # Test unified generate_image
    gen_file = tmp_path / "gen_image.png"
    success = engine.generate_image(
        prompt="Algorithmic Trading Models",
        output_path=gen_file,
        resolution="16:9_hd"
    )
    assert success is True
    assert gen_file.exists()


def test_persona_catalog_contracts():
    assert "maya_fintech" in PERSONA_CATALOG
    persona = get_persona_contract("maya_fintech")
    assert persona.persona_id == "maya_fintech"
    assert persona.canonical_voice == "en-IN-NeerjaNeural"
    assert len(persona.visual_continuity_anchor) > 10
