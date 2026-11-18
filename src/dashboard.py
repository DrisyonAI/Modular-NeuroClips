import os
import re
import subprocess
import urllib.request
import urllib.parse
import time
import json
import uuid
import zipfile
import asyncio
import threading
from pathlib import Path
from typing import Dict, List, Any, Optional, Union
from fastapi import FastAPI, BackgroundTasks, HTTPException, Query, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.config import (
    OUTPUT_DIR, CURRICULUM_OUTPUT_DIR, EXPORTS_DIR, IDENTITIES_DIR, ASSETS_DIR,
    ART_STYLE_PRESETS, RESOLUTION_PROFILES, VOICE_PROFILES,
    AVATAR_PROFILES, AVATAR_LAYOUT_MODES, LANGUAGE_PROFILES,
    DASHBOARD_HOST, DASHBOARD_PORT
)
from src.orchestrator import ScriptOrchestrator, VideoScript, VideoScene
from src.pipeline import MediaGenerationEngine, VRAMGuard
from src.compiler import compile_final_video, generate_srt_subtitles
from src.quiz_engine import QuizEngine
from src.scorm_packager import SCORMPackager, SCORMPackageRequest, SCORMModuleModel, SCORMLessonModel
from src.scorm_upload import install_scorm_upload

quiz_engine = QuizEngine()

app = FastAPI(title="Modular-NeuroClips Studio & VPS Control Plane", version="2.6.0")

app.mount("/static_renders", StaticFiles(directory=str(OUTPUT_DIR)), name="static_renders")
app.mount("/static_curriculum", StaticFiles(directory=str(CURRICULUM_OUTPUT_DIR)), name="static_curriculum")
app.mount("/static_exports", StaticFiles(directory=str(EXPORTS_DIR)), name="static_exports")
app.mount("/static_assets", StaticFiles(directory=str(ASSETS_DIR)), name="static_assets")

# Build a SCORM package from an uploaded video or a .zip of videos.
install_scorm_upload(app, output_dir=OUTPUT_DIR, exports_dir=EXPORTS_DIR,
                     quiz_engine=quiz_engine)


from src.services.telemetry import get_system_telemetry, GPU_AVAILABLE
from src.services.audio_service import (
    generate_voiceover_audio_sync,
    convert_audio_format,
    translate_narration_text,
    resolve_video_path,
)
from src.services.job_manager import job_manager, MILESTONES
from src.services.pipeline_runner import run_production_pipeline

# Backward-compatible state proxies
JOBS_DB: Dict[str, Dict[str, Any]] = job_manager.jobs
ACTIVE_JOB_ID: Optional[str] = job_manager.active_job_id
PIPELINE_STATE: Dict[str, Any] = job_manager.pipeline_state


def create_tracked_job(
    topic: str,
    scene_count: int,
    art_style: str,
    resolution: str,
    voice: str,
    engine_type: str = "ffmpeg",
    output_type: str = "video",
) -> str:
    global ACTIVE_JOB_ID
    job_id = job_manager.create_job(topic, scene_count, art_style, resolution, voice, engine_type, output_type=output_type)
    ACTIVE_JOB_ID = job_id
    return job_id


def log_job_milestone(
    job_id: str,
    milestone_id: str,
    step_msg: str,
    progress: int,
    log_text: Optional[str] = None,
):
    job_manager.log_milestone(job_id, milestone_id, step_msg, progress, log_text)


def execute_tracked_generation(
    job_id: str,
    topic: str,
    scene_count: int,
    art_style: str,
    resolution: str,
    language: str = "en-US",
    voice: str = "en-IN-NeerjaNeural",
    speech_rate: float = 1.0,
    compiler_engine: str = "ffmpeg",
    avatar_persona: str = "maya_fintech",
    avatar_layout: str = "pip_bottom_right",
    burn_subtitles: bool = True,
    auto_clean: bool = False,
    intro_video_url: Optional[str] = None,
    outro_video_url: Optional[str] = None,
    pitch: str = "+0Hz",
    volume: str = "+0%",
    voice_provider: str = "edge_tts",
    elevenlabs_api_key: Optional[str] = None,
    elevenlabs_voice_id: Optional[str] = None,
    stability: float = 0.75,
    similarity_boost: float = 0.75,
    output_type: str = "video",
    motion_graphics: bool = True,
    background_music: bool = False,
    chunking_mode: str = "auto",
    voiceover_script: Optional[str] = None,
    reference_media_url: Optional[str] = None,
):
    job = job_manager.get_job(job_id)
    if not job:
        return

    orchestrator = ScriptOrchestrator()
    try:
        job_manager.log_milestone(
            job_id,
            "scripting",
            "Director composing visual screenplay...",
            15,
            f"Distilling visual scene prompts from user content ({resolution}, {art_style})",
        )
        t0 = time.time()
        script = orchestrator.generate_script(
            topic=topic,
            scene_count=scene_count,
            art_style=art_style,
            avatar_persona=avatar_persona,
            voiceover_script=voiceover_script,
        )
        latency = time.time() - t0
        job["script"] = script.model_dump() if hasattr(script, "model_dump") else script.dict()
        job["total_scenes"] = len(script.scenes)
        job_manager.pipeline_state["model_load_latency"] = latency
        job_manager.pipeline_state["total_scenes"] = len(script.scenes)
        job_manager.log_milestone(
            job_id,
            "scripting",
            f"Script ready ({len(script.scenes)} scenes, {latency:.2f}s)",
            30,
            f"Directorial screenplay composed: '{script.title}'",
        )

        scenes_dicts = [
            {
                "scene_id": sc.scene_id,
                "visual_prompt": sc.visual_prompt,
                "motion_prompt": sc.motion_prompt,
                "narration": getattr(sc, "narration", "") if getattr(sc, "narration", "") is not None else "",
                "duration_seconds": sc.duration_seconds,
                "video_source_type": getattr(sc, "video_source_type", "ai_generated"),
                "video_source_url": getattr(sc, "video_source_url", ""),
                "output_type": getattr(sc, "output_type", output_type),
                "title": getattr(sc, "title", f"Scene {sc.scene_id}"),
            }
            for sc in script.scenes
        ]

        run_production_pipeline(
            job_id=job_id,
            title=script.title,
            art_style=script.art_style_preset,
            scenes=scenes_dicts,
            resolution=resolution,
            language=language,
            voice=voice,
            speech_rate=speech_rate,
            compiler_engine=compiler_engine,
            avatar_persona=avatar_persona,
            avatar_layout=avatar_layout,
            burn_subtitles=burn_subtitles,
            auto_clean=auto_clean,
            intro_video_url=intro_video_url,
            outro_video_url=outro_video_url,
            pitch=pitch,
            volume=volume,
            voice_provider=voice_provider,
            elevenlabs_api_key=elevenlabs_api_key,
            elevenlabs_voice_id=elevenlabs_voice_id,
            stability=stability,
            similarity_boost=similarity_boost,
            topic=topic,
            output_type=output_type,
            motion_graphics=motion_graphics,
            background_music=background_music,
            voiceover_script=voiceover_script,
            reference_media_url=reference_media_url,
        )
    except Exception as exc:
        job_manager.fail_job(job_id, str(exc))
        VRAMGuard.cleanup()

# -------------------------------------------------------------
# REST API Endpoints
# -------------------------------------------------------------
class GenerationRequest(BaseModel):
    topic: str
    visual_prompt: Optional[str] = None
    voiceover_script: Optional[str] = None
    reference_media_url: Optional[str] = None
    scenes: int = 3
    art_style: str = "Cinematic 35mm (Volumetric Lighting)"
    resolution: str = "16:9_hd"
    language: str = "en-US"
    voice: str = "en-IN-NeerjaNeural"
    speech_rate: float = 1.0
    compiler_engine: str = "ffmpeg"
    avatar_persona: str = "maya_fintech"
    avatar_layout: str = "pip_bottom_right"
    burn_subtitles: bool = True
    auto_clean: bool = False
    intro_video_url: Optional[str] = None
    outro_video_url: Optional[str] = None
    pitch: Optional[str] = "+0Hz"
    volume: Optional[str] = "+0%"
    voice_provider: Optional[str] = "edge_tts"
    elevenlabs_api_key: Optional[str] = None
    elevenlabs_voice_id: Optional[str] = None
    stability: Optional[float] = 0.75
    similarity_boost: Optional[float] = 0.75
    output_type: Optional[str] = "video"
    motion_graphics: Optional[bool] = True
    background_music: Optional[bool] = False
    chunking_mode: Optional[str] = "auto"
    speaker_script: Optional[str] = None
    trainee_reading_material: Optional[str] = None
    visuals_recommended: Optional[str] = None
    avatar_onscreen_pct: Optional[int] = 50
    est_runtime_min: Optional[float] = 2.0
    spoken_wpm: Optional[int] = 140

@app.post("/api/v1/generate")
async def trigger_generation_api(req: GenerationRequest, background_tasks: BackgroundTasks):
    if PIPELINE_STATE["status"] not in ["Idle", "Complete", "Failed", "Restarted"]:
        return JSONResponse(status_code=409, content={"status": "busy", "message": "Another generation job is currently running."})
        
    job_id = create_tracked_job(
        topic=req.topic,
        scene_count=req.scenes,
        art_style=req.art_style,
        resolution=req.resolution,
        voice=req.voice,
        engine_type=req.compiler_engine,
        output_type=req.output_type or "video"
    )
    
    job = JOBS_DB[job_id]
    word_count = len(req.topic.split())
    effective_wpm = (req.spoken_wpm or 140) * (req.speech_rate or 1.0)
    spoken_min = round(word_count / effective_wpm, 2)
    runtime_gap = round(spoken_min - (req.est_runtime_min or 2.0), 2)
    
    job["curriculum_meta"] = {
        "speaker_script": req.speaker_script or req.topic,
        "trainee_reading_material": req.trainee_reading_material or "Standard FinTech AI Module Guide",
        "visuals_recommended": req.visuals_recommended or f"Visuals: {req.art_style}",
        "shots_scenes_count": req.scenes,
        "avatar_persona": req.avatar_persona,
        "avatar_layout": req.avatar_layout,
        "avatar_onscreen_pct": req.avatar_onscreen_pct or 50,
        "est_runtime_min": req.est_runtime_min or 2.0,
        "speech_rate": req.speech_rate or 1.0,
        "compiler_engine": req.compiler_engine or "ffmpeg",
        "burn_subtitles": req.burn_subtitles,
        "auto_clean": req.auto_clean,
        "output_type": req.output_type or "video",
        "motion_graphics": req.motion_graphics if req.motion_graphics is not None else True,
        "background_music": req.background_music if req.background_music is not None else False,
        "asset_status": "Synthesizing",
        "script_words": word_count,
        "spoken_min": spoken_min,
        "gap_vs_runtime_min": runtime_gap
    }
    
    v_topic = req.visual_prompt or req.topic
    vo_script = req.voiceover_script if req.voiceover_script is not None else None

    background_tasks.add_task(
        execute_tracked_generation,
        job_id=job_id,
        topic=v_topic,
        scene_count=req.scenes,
        art_style=req.art_style,
        resolution=req.resolution,
        language=req.language,
        voice=req.voice,
        speech_rate=req.speech_rate,
        compiler_engine=req.compiler_engine,
        avatar_persona=req.avatar_persona,
        avatar_layout=req.avatar_layout,
        burn_subtitles=req.burn_subtitles,
        auto_clean=req.auto_clean,
        intro_video_url=req.intro_video_url,
        outro_video_url=req.outro_video_url,
        pitch=req.pitch or "+0Hz",
        volume=req.volume or "+0%",
        voice_provider=req.voice_provider or "edge_tts",
        elevenlabs_api_key=req.elevenlabs_api_key,
        elevenlabs_voice_id=req.elevenlabs_voice_id,
        stability=req.stability or 0.75,
        similarity_boost=req.similarity_boost or 0.75,
        output_type=req.output_type or "video",
        motion_graphics=req.motion_graphics if req.motion_graphics is not None else True,
        background_music=req.background_music if req.background_music is not None else False,
        chunking_mode=req.chunking_mode or "auto",
        voiceover_script=vo_script,
        reference_media_url=req.reference_media_url
    )
    
    return {"status": "started", "job_id": job_id, "topic": v_topic, "scenes": req.scenes, "meta": job["curriculum_meta"]}

class StoryboardPreviewRequest(BaseModel):
    topic: str
    scenes: int = 3
    art_style: str = "Cinematic 35mm (Volumetric Lighting)"
    avatar_persona: str = "maya_fintech"
    output_type: Optional[str] = "video"
    chunking_mode: Optional[str] = "auto"

@app.post("/api/v1/storyboard/preview")
async def preview_storyboard_api(req: StoryboardPreviewRequest):
    orchestrator = ScriptOrchestrator()
    script = orchestrator.generate_script(
        topic=req.topic,
        scene_count=req.scenes,
        art_style=req.art_style,
        avatar_persona=req.avatar_persona
    )
    script_dict = script.model_dump() if hasattr(script, "model_dump") else script.dict()
    for sc in script_dict.get("scenes", []):
        if "output_type" not in sc:
            sc["output_type"] = req.output_type or "video"
    return {"status": "ok", "script": script_dict}

class FromStoryboardRequest(BaseModel):
    title: str
    art_style: str
    resolution: str = "16:9_hd"
    language: str = "en-US"
    voice: str = "en-IN-NeerjaNeural"
    speech_rate: float = 1.0
    compiler_engine: str = "ffmpeg"
    avatar_persona: str = "maya_fintech"
    avatar_layout: str = "pip_bottom_right"
    burn_subtitles: bool = True
    auto_clean: bool = False
    intro_video_url: Optional[str] = None
    outro_video_url: Optional[str] = None
    pitch: Optional[str] = "+0Hz"
    volume: Optional[str] = "+0%"
    voice_provider: Optional[str] = "edge_tts"
    elevenlabs_api_key: Optional[str] = None
    elevenlabs_voice_id: Optional[str] = None
    stability: Optional[float] = 0.75
    similarity_boost: Optional[float] = 0.75
    output_type: Optional[str] = "video"
    motion_graphics: Optional[bool] = True
    background_music: Optional[bool] = False
    scenes: List[Dict[str, Any]]

@app.post("/api/v1/generate/from-storyboard")
async def generate_from_storyboard_api(req: FromStoryboardRequest, background_tasks: BackgroundTasks):
    if PIPELINE_STATE["status"] not in ["Idle", "Complete", "Failed", "Restarted"]:
        return JSONResponse(status_code=409, content={"status": "busy", "message": "Another generation job is currently running."})

    full_narration = " ".join([s.get("narration", "") for s in req.scenes])
    
    job_id = create_tracked_job(
        topic=full_narration or req.title,
        scene_count=len(req.scenes),
        art_style=req.art_style,
        resolution=req.resolution,
        voice=req.voice,
        engine_type=req.compiler_engine,
        output_type=req.output_type or "video"
    )

    def _run_custom_storyboard():
        job = job_manager.get_job(job_id)
        if not job:
            return
        job_manager.log_milestone(
            job_id,
            "scripting",
            "Ingesting refined storyboard scenes...",
            20,
            f"Screenplay: '{req.title}' ({len(req.scenes)} scenes)",
        )
        job["script"] = {"title": req.title, "art_style_preset": req.art_style, "scenes": req.scenes}
        job["total_scenes"] = len(req.scenes)

        run_production_pipeline(
            job_id=job_id,
            title=req.title,
            art_style=req.art_style,
            scenes=req.scenes,
            resolution=req.resolution,
            language=req.language,
            voice=req.voice,
            speech_rate=req.speech_rate,
            compiler_engine=req.compiler_engine,
            avatar_persona=req.avatar_persona,
            avatar_layout=req.avatar_layout,
            burn_subtitles=req.burn_subtitles,
            auto_clean=req.auto_clean,
            intro_video_url=req.intro_video_url,
            outro_video_url=req.outro_video_url,
            pitch=req.pitch or "+0Hz",
            volume=req.volume or "+0%",
            voice_provider=req.voice_provider or "edge_tts",
            elevenlabs_api_key=req.elevenlabs_api_key,
            elevenlabs_voice_id=req.elevenlabs_voice_id,
            stability=req.stability or 0.75,
            similarity_boost=req.similarity_boost or 0.75,
            topic=full_narration or req.title,
            output_type=req.output_type or "video",
            motion_graphics=req.motion_graphics if req.motion_graphics is not None else True,
            background_music=req.background_music if req.background_music is not None else False,
            voiceover_script=(full_narration if full_narration.strip() else ""),
        )

    background_tasks.add_task(_run_custom_storyboard)
    return {"status": "started", "job_id": job_id, "title": req.title, "scenes_count": len(req.scenes)}

class VoiceAuditionRequest(BaseModel):
    text: str = "Welcome to Modular-NeuroClips. Auditioning neural voice director prosody and natural pacing."
    voice: str = "en-IN-NeerjaNeural"
    speech_rate: float = 1.0
    pitch: str = "+0Hz"
    volume: str = "+0%"
    voice_provider: str = "edge_tts"
    elevenlabs_api_key: Optional[str] = None
    elevenlabs_voice_id: Optional[str] = "21m00Tcm4TlvDq8ikWAM"
    stability: float = 0.75
    similarity_boost: float = 0.75

@app.post("/api/v1/voice-director/audition")
async def audition_voice_director_api(req: VoiceAuditionRequest):
    audition_file = OUTPUT_DIR / f"audition_{uuid.uuid4().hex[:6]}.mp3"
    success = generate_voiceover_audio_sync(
        text=req.text,
        voice=req.voice,
        speech_rate=req.speech_rate,
        output_path=audition_file,
        pitch=req.pitch,
        volume=req.volume,
        voice_provider=req.voice_provider,
        elevenlabs_api_key=req.elevenlabs_api_key,
        elevenlabs_voice_id=req.elevenlabs_voice_id,
        stability=req.stability,
        similarity_boost=req.similarity_boost
    )
    if success and audition_file.exists():
        return {
            "status": "ok",
            "audio_url": f"/static_renders/{audition_file.name}",
            "provider": req.voice_provider,
            "duration_est": round(len(req.text.split()) / (140 * req.speech_rate) * 60, 1)
        }
    raise HTTPException(status_code=500, detail="Voice audition synthesis failed. Please check voice settings or ElevenLabs API credentials.")

class VoiceExportRequest(BaseModel):
    text: str
    voice: str = "en-IN-NeerjaNeural"
    speech_rate: float = 1.0
    pitch: str = "+0Hz"
    volume: str = "+0%"
    format: str = "mp3"  # mp3, wav, m4a, ogg, flac
    voice_provider: str = "edge_tts"
    elevenlabs_api_key: Optional[str] = None
    elevenlabs_voice_id: Optional[str] = "21m00Tcm4TlvDq8ikWAM"
    stability: float = 0.75
    similarity_boost: float = 0.75

@app.post("/api/v1/voice/export")
async def export_voiceover_api(req: VoiceExportRequest):
    """Generates standalone studio-quality voiceover audio in MP3, WAV, M4A, OGG, or FLAC with companion subtitles."""
    clean_text = req.text.strip()
    if not clean_text:
        raise HTTPException(status_code=400, detail="Text content is required for voice export.")

    base_id = uuid.uuid4().hex[:8]
    raw_mp3 = OUTPUT_DIR / f"raw_voice_{base_id}.mp3"
    
    success = generate_voiceover_audio_sync(
        text=clean_text,
        voice=req.voice,
        speech_rate=req.speech_rate,
        output_path=raw_mp3,
        pitch=req.pitch,
        volume=req.volume,
        voice_provider=req.voice_provider,
        elevenlabs_api_key=req.elevenlabs_api_key,
        elevenlabs_voice_id=req.elevenlabs_voice_id,
        stability=req.stability,
        similarity_boost=req.similarity_boost
    )
    if not success or not raw_mp3.exists():
        raise HTTPException(status_code=500, detail="Voice synthesis failed. Please check voice configuration.")

    target_fmt = req.format.lower().replace(".", "").strip()
    final_audio = OUTPUT_DIR / f"voice_master_{base_id}.{target_fmt}"
    convert_ok = convert_audio_format(raw_mp3, target_fmt, final_audio)
    if not convert_ok:
        final_audio = raw_mp3
        target_fmt = "mp3"

    # Generate companion subtitle file
    words = clean_text.split()
    est_sec = max(round(len(words) / (140 * req.speech_rate) * 60, 1), 3.0)
    srt_path = OUTPUT_DIR / f"subtitles_{base_id}.srt"
    scenes_dummy = [{"scene_id": 1, "narration": clean_text, "duration_seconds": est_sec}]
    generate_srt_subtitles(scenes_dummy, srt_path)

    return {
        "status": "ok",
        "audio_url": f"/static_renders/{final_audio.name}",
        "filename": final_audio.name,
        "format": target_fmt.upper(),
        "size_mb": round(final_audio.stat().st_size / (1024 ** 2), 2),
        "duration_seconds": est_sec,
        "subtitles_url": f"/static_renders/{srt_path.name}" if srt_path.exists() else None
    }

@app.post("/api/v1/script/upload-document")
async def upload_script_document(file: UploadFile = File(...)):
    """Ingests TXT, Markdown, SRT, VTT, or JSON script documents and returns cleaned narration text."""
    contents = await file.read()
    try:
        raw_text = contents.decode("utf-8")
    except UnicodeDecodeError:
        raw_text = contents.decode("latin-1", errors="ignore")

    # Clean VTT / SRT timestamps if subtitle file
    if file.filename.endswith((".srt", ".vtt")):
        lines = raw_text.splitlines()
        clean_lines = []
        for line in lines:
            line = line.strip()
            if not line or line.isdigit() or "-->" in line or line.startswith("WEBVTT"):
                continue
            clean_lines.append(line)
        clean_text = " ".join(clean_lines)
    else:
        clean_text = raw_text.strip()

    word_count = len(clean_text.split())
    suggested_scenes = min(max(word_count // 35, 2), 16)

    return {
        "status": "ok",
        "filename": file.filename,
        "content": clean_text,
        "word_count": word_count,
        "suggested_scenes": suggested_scenes
    }

@app.post("/api/v1/assets/upload-video")
async def upload_video_asset(file: UploadFile = File(...), tag: str = Query("general")):
    """Uploads pre-recorded videos, screen recordings, B-roll, or intro/outro bumpers."""
    ext = Path(file.filename).suffix.lower()
    if ext not in [".mp4", ".mov", ".webm", ".mkv"]:
        raise HTTPException(status_code=400, detail="Invalid video format. Supported: MP4, MOV, WebM, MKV.")

    asset_id = str(uuid.uuid4())[:8]
    clean_name = f"asset_{asset_id}_{Path(file.filename).name.replace(' ', '_')}"
    target_path = ASSETS_DIR / clean_name
    
    contents = await file.read()
    with open(target_path, "wb") as f:
        f.write(contents)

    # Extract video thumbnail
    thumb_name = f"{target_path.stem}_thumb.png"
    thumb_path = ASSETS_DIR / thumb_name
    engine = MediaGenerationEngine()
    engine.extract_video_thumbnail(str(target_path), thumb_path)

    # Probe duration if possible
    duration = 5.0
    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(target_path)]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode == 0 and res.stdout.strip():
            duration = round(float(res.stdout.strip()), 1)
    except Exception:
        pass

    return {
        "status": "ok",
        "filename": clean_name,
        "video_url": f"/static_assets/{clean_name}",
        "thumbnail_url": f"/static_assets/{thumb_name}",
        "duration_seconds": duration,
        "size_mb": round(len(contents) / (1024 ** 2), 2),
        "tag": tag
    }

@app.get("/api/v1/assets/videos")
async def list_video_assets():
    """Lists all reusable video clips, screen recordings, and bumper assets."""
    assets = []
    for f in ASSETS_DIR.glob("*.*"):
        if f.suffix.lower() in [".mp4", ".mov", ".webm", ".mkv"]:
            thumb = ASSETS_DIR / f"{f.stem}_thumb.png"
            assets.append({
                "filename": f.name,
                "video_url": f"/static_assets/{f.name}",
                "thumbnail_url": f"/static_assets/{thumb.name}" if thumb.exists() else None,
                "size_mb": round(f.stat().st_size / (1024 ** 2), 2),
                "created_at": f.stat().st_mtime
            })
    assets.sort(key=lambda x: x["created_at"], reverse=True)
    return {"status": "ok", "assets": assets}

@app.delete("/api/v1/assets/videos/{filename}")
async def delete_video_asset(filename: str):
    """Deletes an uploaded video asset and its thumbnail."""
    p = ASSETS_DIR / filename
    if p.exists():
        p.unlink(missing_ok=True)
        thumb = ASSETS_DIR / f"{p.stem}_thumb.png"
        thumb.unlink(missing_ok=True)
        return {"status": "ok", "message": f"Asset {filename} deleted."}
    raise HTTPException(status_code=404, detail="Asset not found")

@app.post("/api/v1/avatar/upload")
async def upload_custom_avatar(file: UploadFile = File(...)):
    custom_avatar_path = OUTPUT_DIR / "custom_avatar.png"
    contents = await file.read()
    with open(custom_avatar_path, "wb") as f:
        f.write(contents)
    return {"status": "ok", "message": "Avatar uploaded successfully", "avatar_url": "/static_renders/custom_avatar.png"}

@app.post("/api/v1/director/upload-reference")
async def upload_director_reference_media(file: UploadFile = File(...)):
    """
    Uploads multimodal reference media (image or video) for Director Studio.
    """
    valid_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".mp4", ".mov", ".webm", ".mkv"}
    ext = Path(file.filename).suffix.lower()
    if ext not in valid_exts:
        raise HTTPException(status_code=400, detail=f"Unsupported format {ext}. Allowed: {', '.join(valid_exts)}")

    uid = uuid.uuid4().hex[:8]
    out_filename = f"director_ref_{uid}{ext}"
    out_path = OUTPUT_DIR / out_filename
    contents = await file.read()
    with open(out_path, "wb") as f:
        f.write(contents)

    media_type = "video" if ext in {".mp4", ".mov", ".webm", ".mkv"} else "image"
    return {
        "status": "ok",
        "message": f"Reference {media_type} uploaded successfully",
        "reference_url": f"/static_renders/{out_filename}",
        "reference_path": str(out_path),
        "media_type": media_type,
        "filename": file.filename
    }

@app.post("/api/v1/avatar/upload-3d")
async def upload_avatar_3d_model(file: UploadFile = File(...)):
    """
    Uploads a 3D avatar mesh model (.glb, .gltf, .obj, .fbx, .zip).
    """
    valid_exts = {".glb", ".gltf", ".obj", ".fbx", ".zip"}
    ext = Path(file.filename).suffix.lower()
    if ext not in valid_exts:
        raise HTTPException(status_code=400, detail=f"Unsupported 3D format {ext}. Allowed: {', '.join(valid_exts)}")

    uid = uuid.uuid4().hex[:8]
    out_filename = f"avatar_3d_{uid}{ext}"
    out_path = OUTPUT_DIR / out_filename
    contents = await file.read()
    with open(out_path, "wb") as f:
        f.write(contents)

    return {
        "status": "ok",
        "message": "3D Avatar Model uploaded successfully",
        "model_url": f"/static_renders/{out_filename}",
        "model_path": str(out_path),
        "filename": file.filename
    }

class VoiceScriptExpandRequest(BaseModel):
    prompt: str
    persona: Optional[str] = "maya_fintech"
    scenes_count: Optional[int] = 3

@app.post("/api/v1/voice/expand-prompt")
async def expand_prompt_to_voice_script(req: VoiceScriptExpandRequest):
    """
    Expands a raw prompt/topic into a complete spoken voiceover script with directorial prosody cues using ScriptwriterAgent.
    """
    try:
        from src.agents.scriptwriter import ScriptwriterAgent
        agent = ScriptwriterAgent()
        script_contract = agent.generate_script(
            prompt=req.prompt,
            persona_id=req.persona or "maya_fintech",
            scene_count=req.scenes_count or 3
        )
        combined_text = "\n\n".join(
            f"{s.narration_text}" for s in script_contract.scenes
        )
        return {
            "status": "ok",
            "expanded_script": combined_text,
            "title": script_contract.title,
            "scenes_count": len(script_contract.scenes),
            "total_words": sum(s.word_count for s in script_contract.scenes)
        }
    except Exception as e:
        expanded = f"In this session on {req.prompt}, [pause 500ms] we examine the core architecture and fundamental principles. [emphasis] Let's break down the primary mechanisms."
        return {
            "status": "ok",
            "expanded_script": expanded,
            "title": req.prompt,
            "scenes_count": 1,
            "total_words": len(expanded.split())
        }

@app.post("/api/v1/tts/preview")
async def preview_tts_voice_api(voice: str = Query("en-IN-NeerjaNeural"), rate: float = Query(1.0)):
    preview_file = OUTPUT_DIR / f"preview_{voice.replace(':', '_')}.mp3"
    sample_text = "Welcome to Modular-NeuroClips. Auditioning neural voice narration."
    rate_str = f"{int((rate - 1.0) * 100):+d}%"
    try:
        import edge_tts
        communicate = edge_tts.Communicate(sample_text, voice, rate=rate_str)
        await communicate.save(str(preview_file))
        return {"status": "ok", "audio_url": f"/static_renders/{preview_file.name}", "voice": voice}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Voice preview failed: {str(e)}")

# -------------------------------------------------------------------------
# CUSTOM VOICE CLONING & UNIVERSAL DOCUMENT SPEECH APIS
# -------------------------------------------------------------------------
from fastapi import Form
from src.agents.voice_cloner import VoiceCloner
from src.document_parser import DocumentParser
from src.contracts.persona import (
    PERSONA_CATALOG,
    PersonaIdentityContract,
    GenderEnum,
    RegionLocaleEnum,
    get_persona_contract,
    load_custom_personas,
    delete_custom_persona_contract
)
from src.contracts.script_contract import ScriptContract, ScriptScene
from src.agents.voice_director import VoiceDirectorAgent

VOICES_STORAGE_DIR = ASSETS_DIR / "voices"
voice_cloner = VoiceCloner(VOICES_STORAGE_DIR)

@app.get("/api/v1/voice/personas")
async def list_all_personas_api():
    """Lists all canonical and user-cloned personas available for narration."""
    load_custom_personas()
    result = []
    for pid, p in PERSONA_CATALOG.items():
        loc_str = p.target_locale.value if hasattr(p.target_locale, "value") else str(p.target_locale)
        gen_str = p.gender.value if hasattr(p.gender, "value") else str(p.gender)
        result.append({
            "persona_id": p.persona_id,
            "display_name": p.display_name,
            "gender": gen_str,
            "target_locale": loc_str,
            "locale": loc_str,
            "industry_domain": p.industry_domain,
            "canonical_voice": p.canonical_voice,
            "elevenlabs_voice_id": p.elevenlabs_voice_id,
            "reference_sample_url": f"/static_assets/voices/{p.persona_id}_sample.wav" if (ASSETS_DIR / "voices" / f"{p.persona_id}_sample.wav").exists() else None,
            "is_custom": p.demographic_ethnicity == "User Cloned" or pid not in ["maya_fintech", "alex_ai", "elena_compliance", "david_trainer", "rajesh_cloud"]
        })
    return {"status": "ok", "count": len(result), "personas": result}

@app.delete("/api/v1/voice/personas/{persona_id}")
async def delete_persona_api(persona_id: str):
    """Deletes a custom cloned voice persona from the library."""
    if persona_id in ["maya_fintech", "alex_ai", "elena_compliance", "david_trainer", "rajesh_cloud"]:
        raise HTTPException(status_code=400, detail="Cannot delete certified canonical personas.")
    deleted = delete_custom_persona_contract(persona_id)
    if deleted:
        return {"status": "ok", "message": f"Persona '{persona_id}' deleted successfully."}
    raise HTTPException(status_code=404, detail="Persona not found in custom library.")

@app.post("/api/v1/voice/clone")
async def clone_user_voice_api(
    audio_file: Optional[UploadFile] = File(None),
    sample_file: Optional[UploadFile] = File(None),
    display_name: str = Form(...),
    gender: str = Form("female"),
    target_locale: Optional[str] = Form(None),
    locale: Optional[str] = Form(None),
    elevenlabs_api_key: Optional[str] = Form(None)
):
    """
    Ingests in-browser recorded audio or audio file upload (.mp3, .ogg, .wav), normalizes via FFmpeg,
    registers voice with ElevenLabs or local profile, and creates an immutable custom persona.
    """
    upload = audio_file or sample_file
    if not upload:
        raise HTTPException(status_code=400, detail="No audio sample file provided.")

    loc_val = target_locale or locale or "en-IN"

    temp_dir = OUTPUT_DIR / "temp_voice_uploads"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_raw = temp_dir / f"raw_{uuid.uuid4().hex}_{upload.filename}"

    try:
        content = await upload.read()
        temp_raw.write_bytes(content)

        gender_enum = GenderEnum.FEMALE if gender.lower() == "female" else (
            GenderEnum.MALE if gender.lower() == "male" else GenderEnum.NON_BINARY
        )
        locale_enum = RegionLocaleEnum.EN_IN
        for loc in RegionLocaleEnum:
            if loc.value == loc_val:
                locale_enum = loc
                break

        persona = voice_cloner.register_user_voice(
            display_name=display_name,
            raw_audio_path=temp_raw,
            gender=gender_enum,
            target_locale=locale_enum,
            elevenlabs_api_key=elevenlabs_api_key
        )

        return {
            "status": "ok",
            "message": f"Voice cloned and persona '{persona.display_name}' registered successfully.",
            "persona": {
                "persona_id": persona.persona_id,
                "display_name": persona.display_name,
                "gender": persona.gender.value,
                "target_locale": persona.target_locale.value,
                "locale": persona.target_locale.value,
                "canonical_voice": persona.canonical_voice,
                "elevenlabs_voice_id": persona.elevenlabs_voice_id,
                "is_custom": True
            }
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Voice cloning failed: {str(e)}")
    finally:
        if temp_raw.exists():
            try:
                temp_raw.unlink()
            except Exception:
                pass

@app.post("/api/v1/voice/synthesize-file")
@app.post("/api/v1/voice/document-to-speech")
async def synthesize_document_speech_api(
    document_file: Optional[UploadFile] = File(None),
    file: Optional[UploadFile] = File(None),
    persona_id: Optional[str] = Form(None),
    voice: Optional[str] = Form(None),
    speech_rate: float = Form(1.0),
    pitch: str = Form("+0Hz"),
    export_scorm: Optional[bool] = Form(None),
    package_scorm: Optional[bool] = Form(None),
    elevenlabs_api_key: Optional[str] = Form(None)
):
    """
    Ingests .txt, .md, .docx, or .pdf, decomposes into pedagogical scenes,
    applies FinTech pronunciation lexicon and SSML, and synthesizes master audio + SRT subtitles.
    Optionally packages as an ADL SCORM 1.2 e-learning zip.
    """
    doc_upload = document_file or file
    if not doc_upload:
        raise HTTPException(status_code=400, detail="No document file provided.")

    pid = persona_id or voice or "maya_fintech"
    do_scorm = True if (export_scorm or package_scorm) else False

    temp_dir = OUTPUT_DIR / "temp_doc_uploads"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_doc = temp_dir / f"doc_{uuid.uuid4().hex}_{doc_upload.filename}"

    try:
        content = await doc_upload.read()
        temp_doc.write_bytes(content)

        # 1. Parse document into pedagogical scenes
        parse_result = DocumentParser.parse_file(temp_doc, target_words_per_scene=60, max_scenes=40)
        if not parse_result.scenes:
            raise HTTPException(status_code=400, detail="Document contains no readable text.")

        # 2. Build ScriptContract for Voice Director
        script_scenes = [
            ScriptScene(
                scene_id=sc.scene_id,
                title=sc.title,
                visual_description=f"Educational slide illustrating {sc.title}",
                motion_prompt="Subtle camera tracking over bullet points",
                narration=sc.narration,
                estimated_duration_sec=float(sc.estimated_duration_sec)
            )
            for sc in parse_result.scenes
        ]

        script_contract = ScriptContract(
            course_title=parse_result.document_title,
            persona_id=pid,
            target_locale=RegionLocaleEnum.EN_IN,
            art_style_preset="Photorealistic 8K",
            total_word_count=parse_result.total_words,
            estimated_total_runtime_sec=sum(s.estimated_duration_sec for s in script_scenes),
            scenes=script_scenes
        )

        # 3. Resolve Persona & Synthesize
        persona = get_persona_contract(pid)
        voice_director = VoiceDirectorAgent(output_dir=OUTPUT_DIR)

        engine_to_use = "elevenlabs" if elevenlabs_api_key and elevenlabs_api_key.strip() else "edge_tts"
        voice_contract = voice_director.synthesize_voice_contract(
            script=script_contract,
            persona=persona,
            speech_rate=speech_rate,
            pitch=pitch,
            engine=engine_to_use,
            elevenlabs_api_key=elevenlabs_api_key,
            target_lufs=-14.0
        )

        master_filename = Path(voice_contract.master_audio_path).name
        srt_filename = Path(voice_contract.subtitles_srt_path).name if voice_contract.subtitles_srt_path else None

        scorm_url = None
        if do_scorm:
            # Package directly into SCORM 1.2 zip
            packager = SCORMPackager(
                course_id=f"DOC_{uuid.uuid4().hex[:6].upper()}",
                course_title=parse_result.document_title,
                course_description=f"Generated from {doc_upload.filename} with voice {persona.display_name}",
                version="1.2"
            )
            packager.add_module(1, "Main Lecture", "Decomposed audio narration")
            for sc in script_scenes:
                packager.add_lesson(
                    module_id=1,
                    lesson_id=sc.scene_id,
                    lesson_title=sc.visual_description[:40],
                    topic="Document Audio",
                    description=sc.narration[:100],
                    video_path=voice_contract.master_audio_path,
                    audio_path=voice_contract.master_audio_path,
                    srt_path=voice_contract.subtitles_srt_path,
                    runtime_seconds=float(sc.estimated_duration_sec)
                )
            out_zip = packager.export_zip()
            scorm_url = f"/static_exports/{out_zip.name}"

        return {
            "status": "success",
            "document_title": parse_result.document_title,
            "persona_used": persona.display_name,
            "total_scenes": parse_result.total_scenes,
            "total_words": parse_result.total_words,
            "total_duration_sec": voice_contract.total_audio_duration_sec,
            "normalized_lufs": voice_contract.normalized_lufs,
            "master_audio_url": f"/static_renders/{master_filename}",
            "subtitles_srt_url": f"/static_renders/{srt_filename}" if srt_filename else None,
            "scorm_download_url": scorm_url
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Document speech synthesis failed: {str(e)}")
    finally:
        if temp_doc.exists():
            try:
                temp_doc.unlink()
            except Exception:
                pass

# -------------------------------------------------------------------------
# BATCH SLIDE AUDIO PROCESSING (M{m}_T{t}_L{l}_Slide{s}.mp3)
# -------------------------------------------------------------------------
from src.agents.slide_batch_processor import SlideBatchProcessor, SlideBatchItem

@app.post("/api/v1/voice/batch-slides")
async def batch_process_slides_endpoint(
    deck_path: Optional[str] = Form(None),
    excel_path: Optional[str] = Form(None),
    module_num: Optional[int] = Form(None),
    persona_id: str = Form("maya_fintech"),
    speech_rate: float = Form(1.0),
    pitch: str = Form("+0Hz"),
    target_lufs: float = Form(-14.0),
    slide_numbering: str = Form("deck_absolute"),  # "deck_absolute" or "lesson_relative"
    limit_slides: Optional[int] = Form(None)
):
    """
    Batch processes slide decks (.pptx) or Excel course maps (.xlsx) into audio files
    following the standard naming convention: M{m}_T{t}_L{l}_Slide{s}.mp3
    """
    processor = SlideBatchProcessor(output_dir=OUTPUT_DIR / "batch_slides")
    items = []

    try:
        if deck_path:
            p = Path(deck_path)
            if not p.exists():
                raise HTTPException(status_code=404, detail=f"Slide deck file not found: {deck_path}")
            items = processor.parse_pptx_deck(p, module_num=module_num, slide_numbering=slide_numbering)
        elif excel_path:
            p = Path(excel_path)
            if not p.exists():
                raise HTTPException(status_code=404, detail=f"Excel course map not found: {excel_path}")
            items = processor.parse_excel_course_map(p)
        else:
            raise HTTPException(status_code=400, detail="Must supply either deck_path or excel_path")

        if not items:
            raise HTTPException(status_code=400, detail="No valid slide narration items could be parsed.")

        if limit_slides and limit_slides > 0:
            items = items[:limit_slides]

        result = processor.process_batch(
            items=items,
            persona_id=persona_id,
            speech_rate=speech_rate,
            pitch=pitch,
            target_lufs=target_lufs
        )

        return {
            "status": "success",
            "total_slides": result.total_slides,
            "successful_slides": result.successful_slides,
            "failed_slides": result.failed_slides,
            "output_directory": result.output_directory,
            "manifest_url": f"/static_renders/batch_slides/batch_manifest.json",
            "generated_files": result.generated_files
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch slide processing failed: {str(e)}")

@app.post("/api/v1/voice/batch-slides-upload")
async def batch_process_slides_upload_endpoint(
    file: UploadFile = File(...),
    module_num: Optional[int] = Form(None),
    persona_id: str = Form("maya_fintech"),
    speech_rate: float = Form(1.0),
    pitch: str = Form("+0Hz"),
    target_lufs: float = Form(-14.0),
    slide_numbering: str = Form("deck_absolute"),
    limit_slides: Optional[int] = Form(None)
):
    """
    Accepts uploaded .pptx or .xlsx, extracts slide narration, and synthesizes M{m}_T{t}_L{l}_Slide{s}.mp3.
    """
    temp_dir = OUTPUT_DIR / "temp_batch_uploads"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_file = temp_dir / f"batch_{uuid.uuid4().hex}_{file.filename}"

    try:
        content = await file.read()
        temp_file.write_bytes(content)

        processor = SlideBatchProcessor(output_dir=OUTPUT_DIR / "batch_slides")
        if temp_file.suffix.lower() == ".pptx":
            items = processor.parse_pptx_deck(temp_file, module_num=module_num, slide_numbering=slide_numbering)
        elif temp_file.suffix.lower() == ".xlsx":
            items = processor.parse_excel_course_map(temp_file)
        else:
            raise HTTPException(status_code=400, detail="Uploaded file must be .pptx or .xlsx")

        if not items:
            raise HTTPException(status_code=400, detail="No readable slides or narration found in file.")

        if limit_slides and limit_slides > 0:
            items = items[:limit_slides]

        result = processor.process_batch(
            items=items,
            persona_id=persona_id,
            speech_rate=speech_rate,
            pitch=pitch,
            target_lufs=target_lufs
        )

        return {
            "status": "success",
            "filename": file.filename,
            "total_slides": result.total_slides,
            "successful_slides": result.successful_slides,
            "failed_slides": result.failed_slides,
            "output_directory": result.output_directory,
            "manifest_url": f"/static_renders/batch_slides/batch_manifest.json",
            "generated_files": result.generated_files
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload batch slide processing failed: {str(e)}")
    finally:
        if temp_file.exists():
            try:
                temp_file.unlink()
            except Exception:
                pass

@app.post("/api/v1/scorm/package")
async def create_custom_scorm_package(req: SCORMPackageRequest):
    """
    Generates a full ADL SCORM 1.2 or 2004 e-learning package (.zip)
    from structured Course Title, Modules, Lessons, Topics, and attached media.
    """
    packager = SCORMPackager(
        course_id=req.course_id,
        course_title=req.course_title,
        course_description=req.course_description or "",
        version=req.version
    )

    for mod in req.modules:
        packager.add_module(
            module_id=mod.module_id,
            module_title=mod.module_title,
            description=mod.description or ""
        )
        for ls in mod.lessons:
            # Resolve video/audio/srt if relative or job id provided
            resolved_vid = resolve_video_path(ls.video_path)
            packager.add_lesson(
                module_id=mod.module_id,
                lesson_id=ls.lesson_id,
                lesson_title=ls.lesson_title,
                topic=ls.topic or "",
                description=ls.description or "",
                video_path=resolved_vid,
                srt_path=ls.srt_path,
                audio_path=ls.audio_path,
                runtime_seconds=ls.runtime_seconds or 0.0
            )

    output_zip = packager.export_zip()

    return {
        "status": "ok",
        "package_name": output_zip.name,
        "download_url": f"/static_exports/{output_zip.name}",
        "version": req.version,
        "size_mb": round(output_zip.stat().st_size / (1024 ** 2), 2),
        "total_modules": len(req.modules),
        "total_lessons": sum(len(m.lessons) for m in req.modules)
    }

@app.get("/api/v1/quiz/modules")
async def get_quiz_modules_api():
    """Lists all available course modules and question bank statistics from Nipuna curriculum."""
    return {"status": "ok", "modules": [s.model_dump() for s in quiz_engine.get_modules_summary()]}

@app.get("/api/v1/quiz/module/{module_id}")
async def get_quiz_module_questions_api(module_id: int):
    """Returns question bank items for a specific module."""
    questions = quiz_engine.get_module_questions(module_id)
    return {"status": "ok", "module_id": module_id, "questions": [q.model_dump() for q in questions]}

@app.post("/api/v1/scorm/export/{filename}")
async def export_scorm_package(
    filename: str,
    module_id: int = Query(1),
    course_title: Optional[str] = Query(None),
    scorm_version: str = Query("1.2")
):
    """
    1-click SCORM exporter bundling the rendered video with the module's interactive 32-question assessment from Nipuna curriculum.
    """
    video_path = OUTPUT_DIR / filename
    if not video_path.exists():
        video_path = ASSETS_DIR / filename
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video file not found")
        
    c_title = course_title or video_path.stem.replace('_', ' ').title()
    package_name = f"SCORM_{video_path.stem}_Module{module_id}.zip"
    zip_path = EXPORTS_DIR / package_name
    
    questions = quiz_engine.get_module_questions(module_id)
    
    packager = SCORMPackager(
        course_id=f"Course_{video_path.stem}",
        course_title=f"{c_title} • Interactive Lecture & Assessment",
        course_description=f"Interactive lecture and knowledge assessment for {c_title}",
        version=scorm_version
    )
    packager.add_module(
        module_id=f"module_{module_id}",
        module_title=f"Module {module_id}: {c_title}",
        description=""
    )
    packager.add_lesson(
        module_id=f"module_{module_id}",
        lesson_id=f"lesson_{module_id}_1",
        lesson_title=f"{c_title} Video Lecture & Knowledge Check",
        topic=c_title,
        video_path=str(video_path)
    )
    packager.export_zip(zip_path)
        
    return {
        "status": "ok",
        "package_name": package_name,
        "download_url": f"/static_exports/{package_name}",
        "size_mb": round(zip_path.stat().st_size / (1024 ** 2), 2),
        "module_id": module_id,
        "questions_count": len(questions)
    }

class CustomSCORMBuildRequest(BaseModel):
    course_title: str
    course_id: Optional[str] = "FINTECH_AGENTS_M1"
    module_title: Optional[str] = None
    module_id: Optional[int] = 1
    module_number: Optional[Union[int, str]] = None
    module_name: Optional[str] = None
    module_description: Optional[str] = "Core concepts of autonomous AI agents and foundational architecture"
    lesson_title: Optional[str] = None
    lesson_number: Optional[str] = None
    lesson_name: Optional[str] = None
    lesson_id: Optional[str] = "L101"
    topic: Optional[str] = None
    pass_percentage: Optional[int] = 70
    scorm_version: Optional[str] = "1.2"
    video_filename: Optional[str] = None
    intro_video_filename: Optional[str] = None

@app.post("/api/v1/scorm/custom-build")
async def custom_scorm_build_api(req: CustomSCORMBuildRequest):
    """
    Builds a custom SCORM 1.2 / 2004 e-learning package with dynamic metadata (module number, module name,
    lesson number, lesson name), intro background video, media attachment, and 2-3 question understanding check.
    """
    safe_course_id = "".join(c for c in (req.course_id or "COURSE") if c.isalnum() or c in ('_', '-')).strip() or "COURSE"
    safe_lesson_id = "".join(c for c in (req.lesson_id or "L1") if c.isalnum() or c in ('_', '-')).strip() or "L1"
    package_name = f"SCORM_{safe_course_id}_{safe_lesson_id}_{int(time.time())}.zip"
    zip_path = EXPORTS_DIR / package_name
    
    m_num = str(req.module_number).strip() if req.module_number is not None and str(req.module_number).strip() else (str(req.module_id) if req.module_id else "1")
    m_name = (req.module_name or "").strip()
    if not m_name:
        if req.module_title:
            m_name = re.sub(r"^Module\s*\d+\s*:\s*", "", req.module_title).strip() or req.module_title
        else:
            m_name = f"Module {m_num}"

    final_module_title = f"Module {m_num}: {m_name}" if (m_num and not m_name.startswith(f"Module {m_num}")) else m_name
    
    l_num = str(req.lesson_number).strip() if req.lesson_number is not None and str(req.lesson_number).strip() else f"{m_num}.1"
    raw_lesson_name = (req.lesson_name or req.lesson_title or req.topic or f"Lesson {l_num}").strip()
    clean_l_name = re.sub(r"^(Lesson\s*)?\d+(\.\d+)?\s*[:\-]?\s*", "", raw_lesson_name).strip() or raw_lesson_name
    final_lesson_title = f"{l_num} {clean_l_name}"

    q_mod_id = int(m_num) if str(m_num).isdigit() else (req.module_id or 1)
    questions = quiz_engine.get_module_questions(q_mod_id)
    
    video_file = None
    if req.video_filename:
        v1 = OUTPUT_DIR / req.video_filename
        v2 = ASSETS_DIR / req.video_filename
        if v1.exists():
            video_file = v1
        elif v2.exists():
            video_file = v2

    packager = SCORMPackager(
        course_id=safe_course_id,
        course_title=req.course_title,
        course_description=req.module_description or f"Curriculum module: {final_module_title}",
        version=req.scorm_version or "1.2",
        intro_video_path=req.intro_video_filename
    )
    packager.add_module(
        module_id=f"module_{m_num}",
        module_title=final_module_title,
        description=req.module_description or "",
        module_number=m_num,
        module_name=m_name
    )
    packager.add_lesson(
        module_id=f"module_{m_num}",
        lesson_id=safe_lesson_id,
        lesson_title=final_lesson_title,
        topic=req.topic or clean_l_name,
        video_path=str(video_file) if video_file else None,
        lesson_number=l_num,
        lesson_name=clean_l_name
    )
    packager.export_zip(zip_path)

    return {
        "status": "ok",
        "package_name": package_name,
        "download_url": f"/static_exports/{package_name}",
        "size_mb": round(zip_path.stat().st_size / (1024 ** 2), 2),
        "course_title": req.course_title,
        "module_id": q_mod_id,
        "module_number": m_num,
        "module_name": m_name,
        "module_title": final_module_title,
        "lesson_number": l_num,
        "lesson_name": clean_l_name,
        "lesson_title": final_lesson_title,
        "lesson_id": req.lesson_id,
        "topic": req.topic or clean_l_name,
        "questions_count": min(len(questions), 3),
        "scorm_version": req.scorm_version
    }


class ScenarioGenerateRequest(BaseModel):
    topic: str
    domain: Optional[str] = "FinTech & Enterprise Risk"
    presenter_persona: Optional[str] = "srinivas_cloud"
    depth: Optional[int] = 2


@app.post("/api/v1/scenario/generate")
async def generate_scenario_api(req: ScenarioGenerateRequest):
    """Generates an adaptive NeuroBranch™ branching scenario decision DAG."""
    try:
        from src.scenario_orchestrator import ScenarioOrchestrator
        orchestrator = ScenarioOrchestrator()
        dag = orchestrator.generate_scenario_dag(
            topic=req.topic,
            domain=req.domain or "FinTech & Enterprise Risk",
            presenter_persona=req.presenter_persona or "srinivas_cloud",
            depth=req.depth or 2,
        )
        return {
            "status": "ok",
            "scenario": dag.model_dump() if hasattr(dag, "model_dump") else dag.dict()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate scenario: {e}")


class ScenarioExportRequest(BaseModel):
    scenario_dag: Dict[str, Any]
    pass_percentage: Optional[int] = 70


@app.post("/api/v1/scenario/export-scorm")
async def export_scenario_scorm_api(req: ScenarioExportRequest):
    """Exports a generated scenario DAG into a ready-to-deploy SCORM 1.2 / 2004 ZIP package."""
    try:
        from src.contracts.scenario_contract import ScenarioDAGContract
        from src.scorm_packager import SCORMPackager

        dag = ScenarioDAGContract(**req.scenario_dag)
        errors = dag.validate_graph_integrity()
        if errors:
            raise HTTPException(status_code=400, detail=f"Invalid DAG: {'; '.join(errors)}")

        packager = SCORMPackager(course_id=dag.scenario_id, course_title=dag.title)
        zip_path = packager.export_scenario_zip(dag, pass_percentage=req.pass_percentage or 70)

        return {
            "status": "ok",
            "package_name": zip_path.name,
            "download_url": f"/static_exports/{zip_path.name}",
            "size_mb": round(zip_path.stat().st_size / (1024 ** 2), 2),
            "title": dag.title,
            "total_nodes": len(dag.nodes)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to export SCORM simulation: {e}")


@app.get("/api/v1/scorm/packages")
async def list_scorm_packages():
    """Lists all available SCORM zip packages in the exports directory."""
    packages = []
    if EXPORTS_DIR.exists():
        for f in EXPORTS_DIR.glob("*.zip"):
            packages.append({
                "filename": f.name,
                "download_url": f"/static_exports/{f.name}",
                "size_mb": round(f.stat().st_size / (1024 ** 2), 2),
                "created_at": f.stat().st_mtime
            })
    packages.sort(key=lambda x: x["created_at"], reverse=True)
    return {"packages": packages}
class BatchSlideAudioRequest(BaseModel):
    deck_path: Optional[str] = None
    excel_path: Optional[str] = None
    module_num: Optional[int] = 1
    persona_id: Optional[str] = "maya_fintech"
    speech_rate: Optional[float] = 1.0
    slide_numbering: Optional[str] = "lesson_relative"
    skip_existing: Optional[bool] = True


@app.post("/api/v1/voice/batch-slides")
async def batch_slides_api(req: BatchSlideAudioRequest):
    """
    Generates batch audio files adhering strictly to M{m}_T{t}_L{l}_Slide{s}.mp3
    from a presentation deck (.pptx) or an Excel course map (.xlsx).
    """
    try:
        from src.agents.slide_batch_processor import SlideBatchProcessor
        out_sub = f"M{req.module_num:02d}" if req.module_num else "batch_output"
        processor = SlideBatchProcessor(output_dir=OUTPUT_DIR / "batch_slides" / out_sub)

        if req.deck_path:
            p_deck = Path(req.deck_path)
            if not p_deck.exists():
                raise HTTPException(status_code=404, detail=f"Deck file not found: {req.deck_path}")
            items = processor.parse_pptx_deck(p_deck, module_num=req.module_num, slide_numbering=req.slide_numbering)
        elif req.excel_path:
            p_excel = Path(req.excel_path)
            if not p_excel.exists():
                raise HTTPException(status_code=404, detail=f"Excel file not found: {req.excel_path}")
            items = processor.parse_excel_course_map(p_excel)
        else:
            raise HTTPException(status_code=400, detail="Either deck_path or excel_path must be provided.")

        result = processor.process_batch(
            items,
            persona_id=req.persona_id or "maya_fintech",
            speech_rate=req.speech_rate or 1.0,
            skip_existing=req.skip_existing
        )
        return {
            "status": "ok",
            "total_slides": result.total_slides,
            "successful_slides": result.successful_slides,
            "failed_slides": result.failed_slides,
            "manifest_file": result.manifest_file,
            "files": result.generated_files
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/voice/batch-slides-upload")
async def batch_slides_upload_api(
    file: UploadFile = File(...),
    module_num: int = Form(1),
    persona_id: str = Form("maya_fintech"),
    speech_rate: float = Form(1.0),
    slide_numbering: str = Form("lesson_relative"),
    skip_existing: bool = Form(True)
):
    """
    Accepts uploaded .pptx or .xlsx file and generates M{m}_T{t}_L{l}_Slide{s}.mp3 files in batch.
    """
    try:
        from src.agents.slide_batch_processor import SlideBatchProcessor
        filename = file.filename
        ext = Path(filename).suffix.lower()
        if ext not in [".pptx", ".xlsx"]:
            raise HTTPException(status_code=400, detail="Only .pptx and .xlsx files are supported.")

        temp_dir = OUTPUT_DIR / "temp_uploads"
        temp_dir.mkdir(parents=True, exist_ok=True)
        saved_file = temp_dir / filename
        with open(saved_file, "wb") as f:
            f.write(await file.read())

        out_sub = f"M{module_num:02d}"
        processor = SlideBatchProcessor(output_dir=OUTPUT_DIR / "batch_slides" / out_sub)

        if ext == ".pptx":
            items = processor.parse_pptx_deck(saved_file, module_num=module_num, slide_numbering=slide_numbering)
        else:
            items = processor.parse_excel_course_map(saved_file)

        result = processor.process_batch(
            items,
            persona_id=persona_id,
            speech_rate=speech_rate,
            skip_existing=skip_existing
        )

        return {
            "status": "ok",
            "filename": filename,
            "total_slides": result.total_slides,
            "successful_slides": result.successful_slides,
            "failed_slides": result.failed_slides,
            "manifest_file": result.manifest_file,
            "files": result.generated_files
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------------------
# SCORM Cloud API v2 Integration (Feature 1)
# -------------------------------------------------------------
@app.post("/api/v1/scorm/deploy-cloud")
async def deploy_scorm_cloud_api(req: Dict[str, Any]):
    """
    Dispatches a packaged SCORM zip package directly to SCORM Cloud API v2.
    """
    try:
        from src.scorm_cloud_client import SCORMCloudClient
        course_id = req.get("course_id", "COURSE_01")
        pkg_name = req.get("package_filename") or req.get("zip_path")
        if not pkg_name:
            raise HTTPException(status_code=400, detail="package_filename or zip_path is required.")

        p_zip = EXPORTS_DIR / pkg_name
        if not p_zip.exists():
            p_zip = Path(pkg_name)
        if not p_zip.exists():
            raise HTTPException(status_code=404, detail=f"SCORM package not found: {pkg_name}")

        client = SCORMCloudClient(
            app_id=req.get("scorm_app_id"),
            secret_key=req.get("scorm_secret_key")
        )
        res = client.import_course_package(course_id, p_zip)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/scorm/cloud-job/{job_id}")
async def get_scorm_cloud_job_api(job_id: str):
    """Checks import status of a SCORM Cloud asynchronous job."""
    try:
        from src.scorm_cloud_client import SCORMCloudClient
        client = SCORMCloudClient()
        return client.get_job_status(job_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------------------
# Curriculum Batch Video Synthesis Pipeline (Feature 3)
# -------------------------------------------------------------
@app.post("/api/v1/batch/curriculum")
async def batch_curriculum_api(req: Dict[str, Any]):
    """
    Queues and executes an end-to-end curriculum video synthesis batch from Excel course maps.
    """
    try:
        from src.curriculum_batch_runner import CurriculumBatchRunner, CurriculumBatchRequest
        runner = CurriculumBatchRunner()
        batch_req = CurriculumBatchRequest(
            excel_path=req.get("excel_path"),
            course_id=req.get("course_id", "FINTECH_AGENTS_15HR"),
            course_title=req.get("course_title", "AI Agents in FinTech Course"),
            module_id=req.get("module_id"),
            persona_id=req.get("persona_id", "maya_fintech"),
            resolution=req.get("resolution", "16:9_hd"),
            speech_rate=req.get("speech_rate", 1.0)
        )
        return runner.enqueue_curriculum(batch_req)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/batch/curriculum/status/{course_id}")
async def batch_curriculum_status_api(course_id: str):
    """Returns live completion status of a curriculum batch production job."""
    try:
        from src.curriculum_batch_runner import CurriculumBatchRunner
        runner = CurriculumBatchRunner()
        return runner.get_course_status(course_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



class IdentitySaveRequest(BaseModel):
    name: str
    avatar_persona: str
    avatar_layout: str
    preferred_voice: str
    speech_rate: float
    continuity_anchor: Optional[str] = None

@app.post("/api/v1/identity/save")
async def save_identity_profile(req: IdentitySaveRequest):
    safe_name = "".join(c for c in req.name if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
    file_path = IDENTITIES_DIR / f"{safe_name}.json"
    payload = {
        "name": req.name,
        "avatar_persona": req.avatar_persona,
        "avatar_layout": req.avatar_layout,
        "preferred_voice": req.preferred_voice,
        "speech_rate": req.speech_rate,
        "continuity_anchor": req.continuity_anchor,
        "updated_at": time.time()
    }
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return {"status": "ok", "message": f"Identity '{req.name}' saved successfully."}

@app.get("/api/v1/identity/list")
async def list_identities():
    profiles = []
    if IDENTITIES_DIR.exists():
        for f in IDENTITIES_DIR.glob("*.json"):
            try:
                with open(f, "r", encoding="utf-8") as file:
                    profiles.append(json.load(file))
            except Exception:
                pass
    return {"identities": profiles}

@app.get("/api/v1/identity/load/{name}")
async def load_identity_profile(name: str):
    safe_name = name.replace(' ', '_')
    file_path = IDENTITIES_DIR / f"{safe_name}.json"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Identity not found")
    with open(file_path, "r", encoding="utf-8") as f:
        return {"status": "ok", "identity": json.load(f)}

@app.post("/api/v1/jobs/restart")
async def restart_pipeline_api():
    global ACTIVE_JOB_ID
    VRAMGuard.cleanup()
    PIPELINE_STATE["status"] = "Idle"
    PIPELINE_STATE["current_step"] = "Pipeline reset & ready"
    PIPELINE_STATE["progress_percent"] = 0
    PIPELINE_STATE["current_milestone"] = "init"
    PIPELINE_STATE["last_error"] = None
    ACTIVE_JOB_ID = None
    return {"status": "ok", "message": "Pipeline successfully restarted and ready for fresh jobs."}

@app.get("/api/v1/jobs/active")
async def get_active_job_api():
    if ACTIVE_JOB_ID and ACTIVE_JOB_ID in JOBS_DB:
        return JOBS_DB[ACTIVE_JOB_ID]
    return {
        "job_id": None,
        "status": PIPELINE_STATE["status"],
        "current_milestone": PIPELINE_STATE.get("current_milestone", "init"),
        "current_step": PIPELINE_STATE["current_step"],
        "progress_percent": PIPELINE_STATE.get("progress_percent", 0),
        "milestones": {m["id"]: "pending" for m in MILESTONES},
        "logs": []
    }

@app.get("/api/v1/gallery")
async def list_gallery_videos(session_job_id: Optional[str] = None):
    videos = []
    if OUTPUT_DIR.exists():
        # 1. Rendered MP4 Videos
        for file in sorted(OUTPUT_DIR.glob("*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True):
            if session_job_id and session_job_id not in file.name:
                continue
                
            stat = file.stat()
            audio_url = None
            audio_filename = None
            srt_url = None
            srt_filename = None

            parts = file.stem.split("_")
            if len(parts) >= 2 and parts[0] == "prod":
                potential_job_id = parts[1]
                potential_audio = OUTPUT_DIR / f"audio_{potential_job_id}.mp3"
                if potential_audio.exists():
                    audio_url = f"/static_renders/{potential_audio.name}"
                    audio_filename = potential_audio.name
                
                potential_srt = OUTPUT_DIR / f"subtitles_{potential_job_id}.srt"
                if potential_srt.exists():
                    srt_url = f"/static_renders/{potential_srt.name}"
                    srt_filename = potential_srt.name
            
            videos.append({
                "media_type": "video",
                "filename": file.name,
                "url": f"/static_renders/{file.name}",
                "audio_url": audio_url,
                "audio_filename": audio_filename,
                "srt_url": srt_url,
                "srt_filename": srt_filename,
                "size_mb": round(stat.st_size / (1024 ** 2), 2),
                "created_at": stat.st_mtime,
                "time_str": time.strftime('%Y-%m-%d %H:%M', time.localtime(stat.st_mtime))
            })

        # 2. Rendered Instructional Slides
        slide_patterns = ["slide_*.png", "*_slide.png"]
        seen_slides = set()
        for pat in slide_patterns:
            for file in OUTPUT_DIR.glob(pat):
                if file.name in seen_slides:
                    continue
                seen_slides.add(file.name)
                if session_job_id and session_job_id not in file.name:
                    continue

                stat = file.stat()
                audio_url = None
                audio_filename = None
                srt_url = None
                srt_filename = None

                # Check if audio/subtitles match job ID
                parts = file.stem.split("_")
                for p in parts:
                    if len(p) == 8:
                        potential_audio = OUTPUT_DIR / f"audio_{p}.mp3"
                        if potential_audio.exists():
                            audio_url = f"/static_renders/{potential_audio.name}"
                            audio_filename = potential_audio.name
                        potential_srt = OUTPUT_DIR / f"subtitles_{p}.srt"
                        if potential_srt.exists():
                            srt_url = f"/static_renders/{potential_srt.name}"
                            srt_filename = potential_srt.name
                        break

                videos.append({
                    "media_type": "slide",
                    "filename": file.name,
                    "url": f"/static_renders/{file.name}",
                    "audio_url": audio_url,
                    "audio_filename": audio_filename,
                    "srt_url": srt_url,
                    "srt_filename": srt_filename,
                    "size_mb": round(stat.st_size / (1024 ** 2), 2),
                    "created_at": stat.st_mtime,
                    "time_str": time.strftime('%Y-%m-%d %H:%M', time.localtime(stat.st_mtime))
                })

        # Sort all production media by mtime descending
        videos.sort(key=lambda x: x["created_at"], reverse=True)

    return {"videos": videos}

@app.post("/api/v1/gallery/clear")
async def clear_gallery_api():
    deleted_count = 0
    if OUTPUT_DIR.exists():
        for f in list(OUTPUT_DIR.glob("*.mp4")) + list(OUTPUT_DIR.glob("*.png")) + list(OUTPUT_DIR.glob("*.mp3")) + list(OUTPUT_DIR.glob("*.srt")) + list(OUTPUT_DIR.glob("*.txt")):
            try:
                f.unlink(missing_ok=True)
                deleted_count += 1
            except Exception:
                pass
    return {"status": "ok", "deleted_count": deleted_count, "message": f"Successfully cleared {deleted_count} files from gallery."}

@app.delete("/api/v1/gallery/{filename}")
async def delete_gallery_item_api(filename: str):
    target = OUTPUT_DIR / filename
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
        
    try:
        target.unlink(missing_ok=True)
        parts = target.stem.split("_")
        if len(parts) >= 2 and parts[0] == "prod":
            matching_audio = OUTPUT_DIR / f"audio_{parts[1]}.mp3"
            matching_audio.unlink(missing_ok=True)
            matching_srt = OUTPUT_DIR / f"subtitles_{parts[1]}.srt"
            matching_srt.unlink(missing_ok=True)
            
        return {"status": "ok", "message": f"Deleted {filename}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/config/presets")
async def get_presets():
    return {
        "art_styles": ART_STYLE_PRESETS,
        "resolutions": RESOLUTION_PROFILES,
        "languages": LANGUAGE_PROFILES,
        "voices": VOICE_PROFILES,
        "avatars": AVATAR_PROFILES,
        "avatar_layouts": AVATAR_LAYOUT_MODES,
        "milestones": MILESTONES
    }

@app.post("/api/v1/telemetry/purge-vram")
async def purge_vram_api():
    VRAMGuard.cleanup()
    return {"status": "ok", "message": "VRAM and garbage collector purged successfully."}

@app.get("/metrics/stream")
@app.get("/api/v1/telemetry/stream")
async def sse_metrics():
    async def event_generator():
        while True:
            active_job = JOBS_DB.get(ACTIVE_JOB_ID) if ACTIVE_JOB_ID else None
            payload = {
                "telemetry": get_system_telemetry(),
                "state": PIPELINE_STATE,
                "active_job": active_job,
                "milestones": MILESTONES,
                "timestamp": time.time()
            }
            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(0.8)
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/health")
async def health_check():
    return {"status": "ok", "gpu_available": GPU_AVAILABLE, "timestamp": time.time()}


# -------------------------------------------------------------
# Google Stitch Wireframe APIs: Avatar Video & SCORM Framework
# -------------------------------------------------------------
class AvatarVideoGenerateRequest(BaseModel):
    script: str
    voice: Optional[str] = "en-IN-NeerjaNeural"
    speed: Optional[float] = 1.0
    pitch: Optional[str] = "+0Hz"
    curtain_mode: Optional[str] = "green" # "green" | "white" | "studio"
    curtain_active: Optional[bool] = True
    hand_gestures: Optional[str] = "subtle" # "subtle" | "explanatory" | "dynamic" | "executive"
    avatar_persona: Optional[str] = "maya_fintech"
    avatar_image_url: Optional[str] = None
    future_3d_model: Optional[bool] = False
    model_3d_path: Optional[str] = None

@app.post("/api/v1/avatar/generate-video")
async def generate_avatar_video_api(req: AvatarVideoGenerateRequest):
    """
    Synthesizes an avatar presenter video matching the wireframe:
    - Custom speech script via neural Edge-TTS
    - Audio-reactive lip-sync visemes and natural kinematics
    - 3D mesh head rendering with jaw articulation if 3D model active
    - Green Screen / White Studio Curtain backdrop
    - Hand gesture choreography and avatar positioning
    """
    clean_script = (req.script or "").strip()
    if not clean_script:
        raise HTTPException(status_code=400, detail="Script narration is required for avatar video.")

    vid_id = uuid.uuid4().hex[:8]
    audio_filename = f"avatar_speech_{vid_id}.mp3"
    audio_path = OUTPUT_DIR / audio_filename

    # 1. Generate Voiceover Audio
    voice = req.voice or "en-IN-NeerjaNeural"
    speed = float(req.speed or 1.0)
    pitch = req.pitch or "+0Hz"

    ok = generate_voiceover_audio_sync(
        text=clean_script,
        voice=voice,
        speech_rate=speed,
        output_path=audio_path,
        pitch=pitch,
        volume="+0%",
        voice_provider="edge_tts"
    )
    if not ok or not audio_path.exists():
        raise HTTPException(status_code=500, detail="Failed to synthesize avatar voiceover narration.")

    # 2. Probe audio duration
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
            capture_output=True, text=True, check=True
        )
        duration = float(probe.stdout.strip() or 4.0)
    except Exception:
        duration = max(3.0, len(clean_script.split()) / 2.3)

    # 3. Locate or create avatar portrait image
    avatar_img_path = OUTPUT_DIR / "custom_avatar.png"
    if not avatar_img_path.exists():
        try:
            from PIL import Image, ImageDraw
            img = Image.new("RGBA", (500, 500), (15, 23, 42, 255))
            d = ImageDraw.Draw(img)
            d.ellipse([160, 80, 340, 260], fill=(56, 189, 248, 255))
            d.ellipse([100, 260, 400, 520], fill=(99, 102, 241, 255))
            img.save(avatar_img_path)
        except Exception:
            pass

    # 4. Determine Curtain Color
    curtain_active = req.curtain_active if req.curtain_active is not None else True
    curtain_mode = (req.curtain_mode or "green").lower()
    if curtain_active and curtain_mode == "green":
        bg_color = "0x00FF00"
    elif curtain_active and curtain_mode == "white":
        bg_color = "0xFFFFFF"
    else:
        bg_color = "0x090D16"

    # 5. Hand gestures positioning & framing
    gesture = (req.hand_gestures or "subtle").lower()
    if gesture == "explanatory":
        overlay_filter = "[1:v]scale=460:460:force_original_aspect_ratio=decrease[av];[0:v][av]overlay=90:(H-h)-20[v_out]"
    elif gesture == "dynamic":
        overlay_filter = "[1:v]scale=500:500:force_original_aspect_ratio=decrease[av];[0:v][av]overlay=(W-w)/2:(H-h)-15[v_out]"
    elif gesture == "executive":
        overlay_filter = "[1:v]scale=470:470:force_original_aspect_ratio=decrease[av];[0:v][av]overlay=(W-w)/2:(H-h)-30[v_out]"
    else:
        overlay_filter = "[1:v]scale=480:480:force_original_aspect_ratio=decrease[av];[0:v][av]overlay=(W-w)/2:(H-h)-25[v_out]"

    output_filename = f"avatar_video_{vid_id}.mp4"
    output_path = OUTPUT_DIR / output_filename

    # 6. Audio-Reactive Viseme Speaking Synthesis
    is_3d = bool(req.future_3d_model or req.model_3d_path)
    try:
        from src.services.avatar_animation_service import AvatarAnimationService
        anim_service = AvatarAnimationService()
        anim_service.synthesize_speaking_avatar_video(
            script=clean_script,
            audio_path=audio_path,
            output_path=output_path,
            avatar_image_path=str(avatar_img_path) if avatar_img_path.exists() else None,
            is_3d_model=is_3d,
            curtain_mode=curtain_mode,
            curtain_active=curtain_active,
            hand_gestures=gesture,
            width=1280,
            height=720,
            fps=25
        )
    except Exception as exc:
        print(f"[Avatar Animation Service Warning] Fallback to FFmpeg compositing ({exc})")
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c={bg_color}:s=1280x720:d={duration}",
            "-loop", "1", "-i", str(avatar_img_path.resolve()),
            "-i", str(audio_path.resolve()),
            "-filter_complex", overlay_filter,
            "-map", "[v_out]",
            "-map", "2:a",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-t", str(duration),
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(output_path)
        ]
        res = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
        if res.returncode != 0 or not output_path.exists():
            raise HTTPException(status_code=500, detail=f"FFmpeg compositing failed: {res.stderr[-300:]}")

    return {
        "status": "ok",
        "message": "Avatar video synthesized successfully",
        "video_url": f"/static_renders/{output_filename}",
        "filename": output_filename,
        "duration": round(duration, 2),
        "curtain_mode": curtain_mode if curtain_active else "studio_dark",
        "hand_gestures": gesture,
        "future_3d_model": is_3d
    }

class SCORMFrameworkBuildRequest(BaseModel):
    edu_category: Optional[str] = "Edu FinTech"
    frame_template: Optional[str] = "microlearning"
    course_title: Optional[str] = "AI Agents in FinTech: Autonomous Execution"
    context_text: Optional[str] = ""
    selected_videos: Optional[List[str]] = Field(default_factory=list)
    module_id: Optional[int] = 1
    pass_percentage: Optional[int] = 70
    scorm_version: Optional[str] = "1.2"

@app.post("/api/v1/scorm/framework-build")
async def scorm_framework_build_api(req: SCORMFrameworkBuildRequest):
    """
    Builds a complete SCORM 1.2 / 2004 e-learning package mapping context & videos into a pre-built frame:
    - [Edu] category tagging
    - Pre-built frame selection
    - Pasted curriculum context
    - Video assets mapping & .zip download
    """
    safe_course_id = re.sub(r'[^a-zA-Z0-9_]', '', (req.course_title or "COURSE").replace(" ", "_"))[:30] or "COURSE"
    package_name = f"SCORM_{req.frame_template}_{safe_course_id}_{int(time.time())}.zip"
    zip_path = EXPORTS_DIR / package_name

    questions = quiz_engine.get_module_questions(req.module_id or 1)

    video_file = None
    target_vid_name = ""
    if req.selected_videos and len(req.selected_videos) > 0:
        target_vid_name = req.selected_videos[0]
        v1 = OUTPUT_DIR / target_vid_name
        v2 = ASSETS_DIR / target_vid_name
        if v1.exists():
            video_file = v1
        elif v2.exists():
            video_file = v2

    esc_title = (req.course_title or "Edu Course").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    manifest_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="{safe_course_id}" version="{req.scorm_version or '1.2'}" xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2" xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2">
  <organizations default="org_{safe_course_id}">
    <organization identifier="org_{safe_course_id}">
      <title>{esc_title} [{req.edu_category or 'Edu'}]</title>
      <item identifier="item_framework_1" identifierref="res_{safe_course_id}">
        <title>{esc_title} — {req.frame_template.title()} Frame</title>
      </item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="res_{safe_course_id}" type="webcontent" adlcp:scormtype="sco" href="index.html">
      <file href="index.html"/>
      {f'<file href="{target_vid_name}"/>' if video_file else ''}
    </resource>
  </resources>
</manifest>
"""

    player_html = quiz_engine.generate_interactive_scorm_html(
        video_filename=target_vid_name if video_file else "",
        module_id=req.module_id or 1,
        pass_percentage=req.pass_percentage or 70
    )

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("imsmanifest.xml", manifest_xml)
        zf.writestr("index.html", player_html)
        if req.context_text:
            zf.writestr("curriculum_context.txt", req.context_text)
        if video_file and video_file.exists():
            zf.write(video_file, arcname=target_vid_name)

    return {
        "status": "ok",
        "package_name": package_name,
        "download_url": f"/static_exports/{package_name}",
        "size_mb": round(zip_path.stat().st_size / (1024 ** 2), 2),
        "edu_category": req.edu_category,
        "frame_template": req.frame_template,
        "course_title": req.course_title,
        "questions_count": len(questions),
        "video_mapped": target_vid_name if video_file else "None (Text Assessment Mode)"
    }

@app.api_route("/director", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def serve_director_route():
    return await serve_dashboard()

@app.api_route("/avatar", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def serve_avatar_route():
    return await serve_dashboard()

@app.api_route("/scorm", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def serve_scorm_route():
    return await serve_dashboard()

@app.api_route("/login", methods=["GET", "POST", "HEAD"], response_class=HTMLResponse)
@app.api_route("/signin", methods=["GET", "POST", "HEAD"], response_class=HTMLResponse)
async def serve_login_route():
    return await serve_login_page()


# -------------------------------------------------------------
# Web UI Portal Interface with SCORM & Visual Storyboard
# -------------------------------------------------------------
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
_DASHBOARD_HTML_CACHE: Optional[str] = None
_LOGIN_HTML_CACHE: Optional[str] = None


def get_dashboard_html() -> str:
    """Loads and caches the dashboard HTML template from src/templates/dashboard.html."""
    global _DASHBOARD_HTML_CACHE
    if _DASHBOARD_HTML_CACHE is None:
        template_path = TEMPLATES_DIR / "dashboard.html"
        _DASHBOARD_HTML_CACHE = template_path.read_text(encoding="utf-8")
    return _DASHBOARD_HTML_CACHE


def get_login_html() -> str:
    """Loads and caches the login HTML template from src/templates/login.html."""
    global _LOGIN_HTML_CACHE
    if _LOGIN_HTML_CACHE is None:
        template_path = TEMPLATES_DIR / "login.html"
        _LOGIN_HTML_CACHE = template_path.read_text(encoding="utf-8")
    return _LOGIN_HTML_CACHE


@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def serve_dashboard():
    return get_dashboard_html()


async def serve_login_page():
    return get_login_html()
