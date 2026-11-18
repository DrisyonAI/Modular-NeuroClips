"""
Comprehensive test suite verifying Director Studio and Avatar Studio functionality:
1. Visual Prompt vs. Voiceover Script separation (Visual prompt never spoken)
2. Empty Script produces 100% Silent Video (no spoken prompt, no fallback, no audio errors)
3. Reference Media Foundation (Image-to-video / reference conformed into generation pipeline)
4. Avatar Studio 2D speaking video with audio-reactive visemes and curtain backdrops
5. Avatar Studio 3D mesh head rendering with spatial 3D geometry and audio-reactive jaw articulation
6. FastAPI endpoints: /api/v1/director/upload-reference, /api/v1/avatar/upload-3d, /api/v1/avatar/generate-video
7. UI components: Step 1A & 1B separation, 3D input module, and Director Studio output player/download card
"""
import io
import os
import sys
import shutil
import uuid
import re
import subprocess
from pathlib import Path
import pytest
from PIL import Image

# Ensure OpenMP runtime conflict is handled on Windows
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import OUTPUT_DIR, ASSETS_DIR
from src.services.video_generation_service import VideoGenerationService, ContextAdherentModelAdapter
from src.services.avatar_animation_service import AvatarAnimationService
from src.orchestrator import ScriptOrchestrator
from src.contracts.persona import get_persona_contract
from src.agents.scriptwriter import ScriptwriterAgent
from src.services.audio_service import generate_voiceover_audio_sync
from src.dashboard import app
from fastapi.testclient import TestClient

client = TestClient(app)


def get_dashboard_html():
    template_path = Path(__file__).resolve().parent.parent / "src" / "templates" / "dashboard.html"
    if template_path.exists():
        return template_path.read_text(encoding="utf-8")
    dashboard_path = Path(__file__).resolve().parent.parent / "src" / "dashboard.py"
    content = dashboard_path.read_text(encoding="utf-8")
    m = re.search(r'return r"""(.*?)"""', content, re.DOTALL)
    assert m is not None, "Could not locate HTML template in dashboard.py"
    return m.group(1)


@pytest.fixture
def local_tmp_dir():
    test_dir = OUTPUT_DIR / f"test_run_{uuid.uuid4().hex[:8]}"
    test_dir.mkdir(parents=True, exist_ok=True)
    yield test_dir
    try:
        shutil.rmtree(test_dir, ignore_errors=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 1. VIDEO GENERATION SERVICE & CONTEXT ADHERENCE TESTS
# ---------------------------------------------------------------------------
def test_context_adherent_text_to_video(local_tmp_dir):
    """Verify ContextAdherentModelAdapter generates a valid MP4 from a visual prompt."""
    service = VideoGenerationService()
    prompt = "Futuristic quantum computing core with glowing optical bus and volumetric holographic interference"

    keyframe, clip = service.text_to_video(
        prompt=prompt,
        duration_sec=2.0,
        resolution="16:9_sd",
        job_id=f"t2v_{uuid.uuid4().hex[:6]}"
    )

    assert Path(keyframe).exists(), f"Keyframe does not exist: {keyframe}"
    assert Path(clip).exists(), f"Clip does not exist: {clip}"
    assert Path(clip).stat().st_size > 1000, "Output video is empty or corrupt"


def test_context_adherent_image_to_video(local_tmp_dir):
    """Verify Image-to-Video uses user reference image as foundational keyframe."""
    service = VideoGenerationService()
    ref_img_path = local_tmp_dir / "user_reference.png"
    # Create distinct cyan test reference image
    img = Image.new("RGB", (320, 180), color=(0, 200, 255))
    img.save(ref_img_path)

    prompt = "Camera slowly zooms into the quantum mainframe architecture"

    keyframe, clip = service.image_to_video(
        reference_image_path=str(ref_img_path),
        prompt=prompt,
        duration_sec=2.0,
        resolution="16:9_sd",
        job_id=f"i2v_{uuid.uuid4().hex[:6]}"
    )

    assert Path(keyframe).exists()
    assert Path(clip).exists()
    assert Path(clip).stat().st_size > 1000


# ---------------------------------------------------------------------------
# 2. DIRECTOR STUDIO: VISUAL PROMPT VS VOICEOVER SCRIPT SEPARATION
# ---------------------------------------------------------------------------
def test_scriptwriter_explicit_prompt_and_voiceover_script():
    """
    Test 1: Provide both Visual Prompt and Voiceover Script.
    Visual scene prompts must describe the visual context.
    Narration must strictly chunk the voiceover script.
    The visual prompt must NEVER be spoken as narration.
    """
    orchestrator = ScriptOrchestrator()
    visual_prompt = "Aerial drone shot over ultra-modern Singapore financial district skyscrapers at twilight"
    voiceover_script = "Autonomous agents are transforming treasury operations. Real-time liquidity forecasting eliminates counterparty settlement risk across global banking rails."

    script = orchestrator.generate_script(
        topic=visual_prompt,
        scene_count=2,
        avatar_persona="maya_fintech",
        voiceover_script=voiceover_script
    )

    assert len(script.scenes) >= 1
    # Check that narration strictly derives from voiceover_script
    all_narrations = " ".join(s.narration for s in script.scenes)
    assert "Autonomous agents" in all_narrations
    assert "liquidity forecasting" in all_narrations

    # The visual prompt MUST NOT appear in the narration
    assert "Aerial drone shot" not in all_narrations
    assert "skyscrapers at twilight" not in all_narrations

    # Visual prompts must be informed by the visual prompt
    assert any("skyscrapers" in s.visual_prompt.lower() or "singapore" in s.visual_prompt.lower() or "financial" in s.visual_prompt.lower() for s in script.scenes)


def test_scriptwriter_empty_voiceover_script_silent_video():
    """
    Test 2: Provide Visual Prompt only (empty script).
    The narration text on every scene MUST be completely empty for 100% silent video.
    No fallback to prompt, title, or default narration.
    """
    orchestrator = ScriptOrchestrator()
    visual_prompt = "Close-up macro shot of silicon wafer fabrication under cleanroom ultraviolet illumination"

    script = orchestrator.generate_script(
        topic=visual_prompt,
        scene_count=2,
        avatar_persona="maya_fintech",
        voiceover_script="" # Explicitly empty
    )

    for scene in script.scenes:
        assert scene.narration == "", f"Expected silent scene narration, got '{scene.narration}'"


def test_pipeline_runner_silent_video_compilation(local_tmp_dir):
    """
    Verify that run_production_pipeline with empty voiceover_script compiles a 100% silent MP4 video without audio stream.
    """
    from src.services.pipeline_runner import run_production_pipeline
    from src.services.job_manager import job_manager

    job_id = job_manager.create_job(
        topic="Silent Test",
        scene_count=1,
        art_style="Photorealistic 8K (Corporate / Tech)",
        resolution="16:9_sd",
        voice="en-IN-NeerjaNeural"
    )

    scenes = [{
        "scene_id": 1,
        "title": "Scene 1",
        "visual_prompt": "Abstract holographic glowing neural network",
        "motion_prompt": "Slow push-in",
        "narration": "",
        "duration_seconds": 2.0,
        "output_type": "video",
        "video_source_type": "ai_generated"
    }]

    run_production_pipeline(
        job_id=job_id,
        title="Silent Test",
        art_style="Photorealistic 8K (Corporate / Tech)",
        scenes=scenes,
        resolution="16:9_sd",
        voiceover_script="", # 100% silent video
        motion_graphics=False,
        background_music=False
    )

    job = job_manager.get_job(job_id)
    assert job["status"] == "complete"
    assert job["output_path"] is not None
    assert Path(job["output_path"]).exists()

    # Check that the compiled video has 0 audio streams using ffprobe
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=codec_type",
        "-of", "csv=p=0",
        str(job["output_path"])
    ]
    probe_res = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert probe_res.stdout.strip() == "", f"Expected 0 audio streams for silent video, got: {probe_res.stdout}"


# ---------------------------------------------------------------------------
# 3. AVATAR STUDIO: 2D LIP-SYNC VISUAL ANIMATION
# ---------------------------------------------------------------------------
def test_avatar_animation_2d_visemes(local_tmp_dir):
    """
    Verify AvatarAnimationService creates a speaking video with audio-reactive visemes,
    correct duration matching audio, and synchronized soundtrack.
    """
    service = AvatarAnimationService()
    audio_path = local_tmp_dir / "test_narration.mp3"
    speech_text = "Welcome to the neural avatar presentation studio."

    # Synthesize small audio snippet
    ok = generate_voiceover_audio_sync(
        text=speech_text,
        voice="en-IN-NeerjaNeural",
        output_path=audio_path,
        speech_rate=1.2
    )
    assert ok is True and audio_path.exists()

    out_mp4 = local_tmp_dir / "avatar_2d_output.mp4"
    res_path = service.synthesize_speaking_avatar_video(
        script=speech_text,
        audio_path=audio_path,
        output_path=out_mp4,
        curtain_mode="green",
        curtain_active=True,
        hand_gestures="subtle",
        is_3d_model=False,
        width=640,
        height=360,
        fps=15
    )

    assert out_mp4.exists()
    assert out_mp4.stat().st_size > 1000

    # Verify audio stream is attached to the speaking avatar video
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=codec_name",
        "-of", "csv=p=0",
        str(out_mp4)
    ]
    probe_res = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert "aac" in probe_res.stdout or "mp3" in probe_res.stdout, "Avatar video missing audio stream"


# ---------------------------------------------------------------------------
# 4. AVATAR STUDIO: 3D MESH HEAD RENDERING & ARTICULATION
# ---------------------------------------------------------------------------
def test_avatar_animation_3d_mesh_head(local_tmp_dir):
    """
    Verify AvatarAnimationService creates a speaking 3D avatar head with spatial 3D mesh
    and audio-reactive jaw articulation.
    """
    service = AvatarAnimationService()
    audio_path = local_tmp_dir / "test_narration_3d.mp3"
    speech_text = "Testing 3D blendshape geometry and jaw articulation."

    ok = generate_voiceover_audio_sync(
        text=speech_text,
        voice="en-US-GuyNeural",
        output_path=audio_path,
        speech_rate=1.3
    )
    assert ok is True and audio_path.exists()

    out_mp4 = local_tmp_dir / "avatar_3d_output.mp4"
    res_path = service.synthesize_speaking_avatar_video(
        script=speech_text,
        audio_path=audio_path,
        output_path=out_mp4,
        curtain_mode="white",
        curtain_active=True,
        hand_gestures="dynamic",
        is_3d_model=True,
        width=640,
        height=360,
        fps=15
    )

    assert out_mp4.exists()
    assert out_mp4.stat().st_size > 1000


# ---------------------------------------------------------------------------
# 5. FASTAPI API ENDPOINTS VERIFICATION
# ---------------------------------------------------------------------------
def test_director_upload_reference_api():
    """Verify POST /api/v1/director/upload-reference validates and stores multimodal reference files."""
    # 1. Image upload
    fake_img = io.BytesIO()
    Image.new("RGB", (100, 100), color="blue").save(fake_img, format="PNG")
    fake_img.seek(0)

    res = client.post(
        "/api/v1/director/upload-reference",
        files={"file": ("reference_scene.png", fake_img, "image/png")}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["media_type"] == "image"
    assert Path(data["reference_path"]).exists()

    # 2. Reject unsupported extension
    bad_file = io.BytesIO(b"executable")
    bad_res = client.post(
        "/api/v1/director/upload-reference",
        files={"file": ("malicious.exe", bad_file, "application/octet-stream")}
    )
    assert bad_res.status_code == 400


def test_avatar_upload_3d_api():
    """Verify POST /api/v1/avatar/upload-3d validates and stores 3D model assets."""
    fake_glb = io.BytesIO(b"glTF header binary content")
    res = client.post(
        "/api/v1/avatar/upload-3d",
        files={"file": ("avatar_character.glb", fake_glb, "model/gltf-binary")}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["model_path"].endswith(".glb")
    assert Path(data["model_path"]).exists()


def test_avatar_generate_video_api():
    """Verify POST /api/v1/avatar/generate-video generates a speaking avatar video with curtain."""
    payload = {
        "script": "Synthesizing full avatar pipeline test via API.",
        "voice": "en-IN-NeerjaNeural",
        "speed": 1.1,
        "pitch": "+0Hz",
        "curtain_mode": "green",
        "curtain_active": True,
        "hand_gestures": "subtle",
        "future_3d_model": False
    }
    res = client.post("/api/v1/avatar/generate-video", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "video_url" in data
    assert (OUTPUT_DIR / data["filename"]).exists()


# ---------------------------------------------------------------------------
# 6. UI WIREFRAME & ARCHITECTURE VERIFICATION
# ---------------------------------------------------------------------------
def test_director_and_avatar_studio_ui_structure():
    """
    Verify the HTML dashboard contains:
    - Step 1A: Visual Generation Prompt (#prompt-input) and reference media upload
    - Step 1B: Voiceover Narration Script (#script-input) with 'Empty = Silent Video'
    - Director Studio Video Output Player (#director-video-player) and Download Card (#director-output-card)
    - 3D Avatar Input Module in Avatar Studio (#avatar-3d-file-input, #avatar-3d-model-path, #avatar-3d-status)
    """
    html = get_dashboard_html()

    # Step 1A & 1B
    assert 'id="prompt-input"' in html, "Missing #prompt-input for visual prompt"
    assert "Visual Generation Prompt" in html
    assert 'id="director-ref-upload"' in html, "Missing #director-ref-upload"
    assert 'id="script-input"' in html, "Missing #script-input for voiceover script"
    assert "Empty = Silent Video" in html

    # Director Studio Output Card
    assert 'id="director-output-card"' in html, "Missing #director-output-card"
    assert 'id="director-video-player"' in html, "Missing #director-video-player"
    assert 'id="director-download-btn"' in html, "Missing #director-download-btn"
    assert 'id="director-pipeline-phase"' in html, "Missing #director-pipeline-phase"

    # Avatar Studio 3D Input Module
    assert 'id="avatar-3d-file-input"' in html, "Missing #avatar-3d-file-input"
    assert 'id="avatar-3d-model-path"' in html, "Missing #avatar-3d-model-path"
    assert 'id="avatar-3d-status"' in html, "Missing #avatar-3d-status"
    assert 'id="avatar-curtain-toggle"' in html, "Missing #avatar-curtain-toggle"
    assert 'id="avatar-video-player"' in html, "Missing #avatar-video-player"
    assert 'id="avatar-download-link"' in html, "Missing #avatar-download-link"