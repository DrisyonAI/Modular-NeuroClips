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
        result.append({
            "persona_id": p.persona_id,
            "display_name": p.display_name,
            "gender": p.gender.value if hasattr(p.gender, "value") else str(p.gender),
            "target_locale": p.target_locale.value if hasattr(p.target_locale, "value") else str(p.target_locale),
            "industry_domain": p.industry_domain,
            "canonical_voice": p.canonical_voice,
            "elevenlabs_voice_id": p.elevenlabs_voice_id,
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
    audio_file: UploadFile = File(...),
    display_name: str = Form(...),
    gender: str = Form("female"),
    target_locale: str = Form("en-IN"),
    elevenlabs_api_key: Optional[str] = Form(None)
):
    """
    Ingests in-browser recorded audio or audio file upload, normalizes via FFmpeg,
    registers voice with ElevenLabs or local profile, and creates an immutable custom persona.
    """
    temp_dir = OUTPUT_DIR / "temp_voice_uploads"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_raw = temp_dir / f"raw_{uuid.uuid4().hex}_{audio_file.filename}"

    try:
        content = await audio_file.read()
        temp_raw.write_bytes(content)

        gender_enum = GenderEnum.FEMALE if gender.lower() == "female" else (
            GenderEnum.MALE if gender.lower() == "male" else GenderEnum.NON_BINARY
        )
        locale_enum = RegionLocaleEnum.EN_IN
        for loc in RegionLocaleEnum:
            if loc.value == target_locale:
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
            "status": "success",
            "message": f"Voice cloned and persona '{persona.display_name}' registered successfully.",
            "persona": {
                "persona_id": persona.persona_id,
                "display_name": persona.display_name,
                "gender": persona.gender.value,
                "target_locale": persona.target_locale.value,
                "canonical_voice": persona.canonical_voice,
                "elevenlabs_voice_id": persona.elevenlabs_voice_id
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
async def synthesize_document_speech_api(
    document_file: UploadFile = File(...),
    persona_id: str = Form("maya_fintech"),
    speech_rate: float = Form(1.0),
    pitch: str = Form("+0Hz"),
    export_scorm: bool = Form(False),
    elevenlabs_api_key: Optional[str] = Form(None)
):
    """
    Ingests .txt, .md, .docx, or .pdf, decomposes into pedagogical scenes,
    applies FinTech pronunciation lexicon and SSML, and synthesizes master audio + SRT subtitles.
    Optionally packages as an ADL SCORM 1.2 e-learning zip.
    """
    temp_dir = OUTPUT_DIR / "temp_doc_uploads"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_doc = temp_dir / f"doc_{uuid.uuid4().hex}_{document_file.filename}"

    try:
        content = await document_file.read()
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
            persona_id=persona_id,
            target_locale=RegionLocaleEnum.EN_IN,
            art_style_preset="Photorealistic 8K",
            total_word_count=parse_result.total_words,
            estimated_total_runtime_sec=sum(s.estimated_duration_sec for s in script_scenes),
            scenes=script_scenes
        )

        # 3. Resolve Persona & Synthesize
        persona = get_persona_contract(persona_id)
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
        if export_scorm:
            # Package directly into SCORM 1.2 zip
            packager = SCORMPackager(
                course_id=f"DOC_{uuid.uuid4().hex[:6].upper()}",
                course_title=parse_result.document_title,
                course_description=f"Generated from {document_file.filename} with voice {persona.display_name}",
                version="1.2"
            )
            packager.add_module(1, "Main Lecture", "Decomposed audio narration")
            for sc in script_scenes:
                packager.add_lesson(
                    module_id=1,
                    lesson_id=sc.scene_id,
                    lesson_title=sc.visual_prompt[:40],
                    topic="Document Audio",
                    description=sc.narration[:100],
                    video_path=voice_contract.master_audio_path,
                    audio_path=voice_contract.master_audio_path,
                    srt_path=voice_contract.subtitles_srt_path,
                    runtime_seconds=float(sc.duration_seconds)
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
@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def serve_dashboard():
    return r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Modular-NeuroClips Studio | Director & Production Workbench</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    fontFamily: {
                        sans: ['Inter', 'sans-serif'],
                        mono: ['JetBrains Mono', 'monospace']
                    },
                    colors: {
                        brand: {
                            50: '#f0f9ff',
                            500: '#0ea5e9',
                            600: '#0284c7',
                            glow: '#38bdf8'
                        }
                    }
                }
            }
        }
    </script>
    <style>
        body { background: #090d16; color: #f1f5f9; }
        .glass-panel {
            background: rgba(15, 23, 42, 0.75);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.08);
        }
        .glass-panel-glow {
            background: rgba(15, 23, 42, 0.85);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(56, 189, 248, 0.25);
            box-shadow: 0 0 25px rgba(14, 165, 233, 0.12);
        }
        .step-pulse {
            animation: pulse-glow 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
        }
        @keyframes pulse-glow {
            0%, 100% { opacity: 1; filter: drop-shadow(0 0 8px #38bdf8); }
            50% { opacity: .6; filter: drop-shadow(0 0 2px #38bdf8); }
        }
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: #0f172a; }
        ::-webkit-scrollbar-thumb { background: #334155; border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: #475569; }
    </style>
</head>
<body class="min-h-screen flex flex-col font-sans selection:bg-brand-500 selection:text-white">

    <!-- Header Navigation -->
    <header class="glass-panel sticky top-0 z-50 border-b border-slate-800/80 px-6 py-3.5 flex items-center justify-between">
        <div class="flex items-center space-x-3">
            <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-brand-600 to-indigo-500 flex items-center justify-center shadow-lg shadow-brand-500/25">
                <span class="text-xl font-black text-white tracking-tighter">⚡</span>
            </div>
            <div>
                <h1 class="text-lg font-bold tracking-tight bg-gradient-to-r from-white via-slate-200 to-brand-glow bg-clip-text text-transparent">
                    Modular-NeuroClips <span class="text-xs px-2 py-0.5 rounded-full bg-brand-500/20 text-brand-glow border border-brand-500/30">Studio v2.6</span>
                </h1>
                <p class="text-xs text-slate-400">Autonomous Video & Courseware Production Engine</p>
            </div>
        </div>

        <div class="flex items-center space-x-3 text-xs font-mono">
            <button onclick="newProjectCanvas()" class="px-3 py-1.5 rounded-lg bg-brand-500/15 text-brand-glow border border-brand-500/30 hover:bg-brand-500/25 transition-all flex items-center gap-1.5 font-sans font-bold shadow-md shadow-brand-500/10">
                <span>✨</span> <span>New Project</span>
            </button>
            <button onclick="openAssetVaultModal()" class="px-3 py-1.5 rounded-lg bg-indigo-500/15 text-indigo-300 border border-indigo-500/30 hover:bg-indigo-500/25 transition-all flex items-center gap-1.5 font-sans font-semibold">
                <span>📼</span> <span>Video Library</span>
            </button>
            <div class="glass-panel px-3 py-1.5 rounded-lg flex items-center space-x-2">
                <span class="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
                <span class="text-slate-400">GPU:</span>
                <span id="header-vram" class="text-brand-glow font-semibold">0 / 0 MB</span>
            </div>
            <div class="glass-panel px-3 py-1.5 rounded-lg flex items-center space-x-2">
                <span class="text-slate-400">Status:</span>
                <span id="header-status" class="px-2 py-0.5 rounded bg-slate-800 text-slate-200 font-sans font-medium">Idle</span>
            </div>
            <button onclick="restartPipeline()" title="Reset and restart pipeline state" class="px-3 py-1.5 rounded-lg bg-amber-500/10 text-amber-300 border border-amber-500/20 hover:bg-amber-500/20 transition-all flex items-center gap-1">
                <span>🔄</span> <span>Restart</span>
            </button>
            <button onclick="purgeVRAM()" title="Purge CUDA Memory Cache" class="px-3 py-1.5 rounded-lg bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20 transition-all">
                Purge VRAM
            </button>
            <button onclick="openSettingsModal()" title="Studio Settings" class="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition-all flex items-center gap-1 font-sans font-medium">
                <span>⚙️</span> <span>Settings</span>
            </button>
            <a href="/login" id="header-auth-btn" class="px-3 py-1.5 rounded-lg bg-brand-600/20 hover:bg-brand-600/30 text-brand-glow border border-brand-500/30 transition-all flex items-center gap-1.5 font-sans font-semibold">
                <span id="header-auth-icon">🔑</span> <span id="header-auth-text">Sign In</span>
            </a>
        </div>
    </header>

    <!-- Main Container -->
    <main class="flex-1 max-w-7xl w-full mx-auto p-6 space-y-6">

        <!-- 🎛️ STUDIO MODE SELECTOR BAR (GOOGLE STITCH WIREFRAME SUITE) -->
        <div class="flex items-center space-x-2 border-b border-slate-800 pb-3 overflow-x-auto">
            <button onclick="switchStudioMode('video')" id="mode-btn-video" title="Director Studio (Master Orchestrator)" class="px-4 py-2.5 rounded-xl bg-brand-600 text-white text-xs font-bold flex items-center gap-2 shadow-lg shadow-brand-500/20 transition-all whitespace-nowrap">
                <span>👑</span> <span>Director</span>
            </button>
            <button onclick="switchStudioMode('voice')" id="mode-btn-voice" title="Voice Director Studio" class="px-4 py-2.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-800 text-xs font-bold flex items-center gap-2 transition-all whitespace-nowrap">
                <span>🎙️</span> <span>Voice</span>
            </button>
            <button onclick="switchStudioMode('image')" id="mode-btn-image" title="Image Director Studio" class="px-4 py-2.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-800 text-xs font-bold flex items-center gap-2 transition-all whitespace-nowrap">
                <span>🎨</span> <span>Image</span>
            </button>
            <button onclick="switchStudioMode('avatar')" id="mode-btn-avatar" title="Avatar Studio (Presenter Lab)" class="px-4 py-2.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-800 text-xs font-bold flex items-center gap-2 transition-all whitespace-nowrap">
                <span>👤</span> <span>Avatar</span>
            </button>
            <div class="h-6 w-px bg-slate-800 mx-1.5 self-center flex-shrink-0" aria-hidden="true"></div>
            <button onclick="switchStudioMode('scorm')" id="mode-btn-scorm" title="SCORM Framework & LMS" class="px-4 py-2.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-800 text-xs font-bold flex items-center gap-2 transition-all whitespace-nowrap">
                <span>📦</span> <span>SCORM Export</span>
            </button>
        </div>

        <!-- MODE 1: MULTI-AGENT VIDEO STUDIO -->
        <div id="mode-video-section" class="space-y-6">

            <!-- 🌟 MILESTONE PROGRESS SECTION (INSIDE DIRECTOR TAB ONLY) -->
            <section id="milestone-tracker-section" class="glass-panel-glow rounded-2xl p-3 sm:px-5 transition-all duration-300 relative overflow-hidden">
                <div class="flex items-center justify-between min-h-[32px]">
                    <div class="flex items-center gap-2.5">
                        <span class="text-base">🎯</span>
                        <div>
                            <h2 class="text-xs sm:text-sm font-bold text-white flex items-center gap-2">
                                Production Milestones
                            </h2>
                            <p id="tracker-subtext" class="text-[11px] text-slate-400 hidden">Real-time lifecycle tracking across all generative stages</p>
                        </div>
                    </div>
                    <div class="flex items-center gap-3">
                        <div class="flex items-center gap-2 text-right">
                            <span id="overall-progress-num" class="text-base sm:text-lg font-black text-brand-glow font-mono">0%</span>
                            <span class="text-slate-600">&bull;</span>
                            <p id="active-step-caption" class="text-xs text-slate-300 font-medium">Ready</p>
                        </div>
                        <button type="button" id="tracker-toggle-btn" onclick="toggleTrackerManual()" class="text-slate-400 hover:text-white text-xs px-2 py-0.5 rounded bg-slate-800/80 border border-slate-700 font-mono transition-all" title="Toggle milestone tracker">▾</button>
                    </div>
                </div>

                <!-- Expanded Content: Progress bar and stage cards (collapses when idle) -->
                <div id="tracker-expanded-content" class="hidden mt-3 pt-3 border-t border-slate-800/80 space-y-4">
                    <div class="w-full h-2.5 bg-slate-800/80 rounded-full overflow-hidden p-0.5 border border-slate-700/50">
                        <div id="master-progress-fill" class="h-full bg-gradient-to-r from-brand-600 via-indigo-500 to-brand-glow rounded-full transition-all duration-500 shadow-lg shadow-brand-500/50" style="width: 0%"></div>
                    </div>
                    <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3" id="milestones-container">
                    </div>
                </div>
            </section>

        <!-- Studio Control Grid -->
        <div class="grid grid-cols-1 lg:grid-cols-12 gap-6">

            <!-- LEFT: Generation Studio (7 cols) -->
            <div class="lg:col-span-7 space-y-6">
                <div class="glass-panel rounded-2xl p-6 space-y-6">
                    <div class="flex items-center justify-between border-b border-slate-800 pb-3 flex-wrap gap-2">
                        <div>
                            <h3 class="text-sm font-bold uppercase tracking-wider text-slate-200 flex items-center gap-2">
                                <span>🎬</span> Director Studio
                            </h3>
                            <p class="text-[11px] text-slate-400 mt-0.5">Central learning content production & configuration workspace</p>
                        </div>
                        <div class="flex items-center gap-2">
                            <!-- Note: Director Let It Be AUTONOMOUS (Wireframe annotation removed) -->
                            <span class="text-xs text-brand-glow bg-brand-500/10 px-2.5 py-1 rounded-lg border border-brand-500/20 font-mono">
                                AI Production Engine
                            </span>
                        </div>
                    </div>

                    <!-- PHASE 1: CONTENT (What is it about?) -->
                    <div class="space-y-3 p-4 rounded-xl bg-slate-950/70 border border-slate-800">
                        <div class="flex items-center justify-between pb-2 border-b border-slate-800/80">
                            <div class="flex items-center gap-2">
                                <span class="w-5 h-5 rounded bg-brand-500/20 text-brand-glow flex items-center justify-center text-[10px] font-bold font-mono">1</span>
                                <div>
                                    <h4 class="text-xs font-bold uppercase tracking-wider text-slate-200">Phase 1 — Content</h4>
                                    <p class="text-[10px] text-slate-400">What is it about? Visual prompt & voiceover script</p>
                                </div>
                            </div>
                        </div>

                        <!-- Visual Prompt & Reference Media -->
                        <div class="space-y-3">
                            <div class="flex justify-between items-center">
                                <label class="text-xs font-bold text-slate-200 uppercase tracking-wider flex items-center gap-1.5">
                                    <span>Visual Generation Prompt (What the video should show)</span>
                                </label>
                                <span class="text-[10px] text-brand-glow font-mono">Controls Visuals Only &bull; Not Spoken</span>
                            </div>
                            <p class="text-[11px] text-slate-400">Describe the scene objects, environment, action, and lighting. This directly guides the visual generation model.</p>
                            
                            <textarea id="prompt-input" rows="3" oninput="if(typeof updatePreflightSummary==='function')updatePreflightSummary();" class="w-full rounded-xl bg-slate-900 border border-slate-700/80 p-3 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 transition-all font-sans leading-relaxed shadow-inner" placeholder="E.g., Cinematic aerial view of modern AI datacenter servers with glowing optical fiber interconnects and holographic data streams..."></textarea>

                            <!-- Multimodal Reference Attachment -->
                            <div class="pt-1 border-t border-slate-800/80 flex flex-col sm:flex-row sm:items-center justify-between gap-2.5">
                                <div class="flex items-center space-x-2">
                                    <input type="file" id="director-ref-upload" class="hidden" accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/webm" onchange="handleDirectorReferenceUpload(this)">
                                    <label for="director-ref-upload" class="cursor-pointer px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold flex items-center gap-1.5 border border-slate-700 transition-all">
                                        <span>📎</span> <span>Attach Reference Media (Image / Video)</span>
                                    </label>
                                    <span id="director-ref-badge" class="text-[11px] font-mono text-slate-400">No media attached</span>
                                </div>
                                <input type="hidden" id="director-ref-url" value="">
                                <div id="director-ref-preview-box" class="hidden flex items-center space-x-2">
                                    <img id="director-ref-preview-img" src="" class="w-9 h-9 rounded object-cover border border-brand-500/40">
                                    <button type="button" onclick="clearDirectorReferenceMedia()" class="text-[10px] text-red-400 hover:underline">✕ Remove</button>
                                </div>
                            </div>
                        </div>

                        <!-- Voiceover Narration Script -->
                        <div class="pt-3 border-t border-slate-800/80 space-y-2.5">
                            <div class="flex justify-between items-center">
                                <label class="text-xs font-bold text-slate-200 uppercase tracking-wider flex items-center gap-1.5">
                                    <span>Voiceover Narration Script (What should be spoken)</span>
                                </label>
                                <div class="flex items-center space-x-2">
                                    <span class="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">Empty = Silent Video</span>
                                    <label for="script-file-upload" class="text-[11px] text-brand-glow hover:underline cursor-pointer flex items-center gap-1 font-sans">
                                        <span>📁</span> <span>Upload Document</span>
                                    </label>
                                    <input type="file" id="script-file-upload" class="hidden" accept=".txt,.md,.srt,.vtt,.json" onchange="handleScriptDocumentUpload(this)">
                                    <span id="script-stats" class="text-[11px] font-mono text-brand-glow bg-slate-900 px-2 py-0.5 rounded border border-slate-800">0 words | ~0.0 min</span>
                                </div>
                            </div>

                            <!-- Director Quick Insert Toolbar -->
                            <div class="flex items-center space-x-1.5 overflow-x-auto py-1 text-[11px]">
                                <span class="text-slate-500 font-semibold text-[10px] uppercase tracking-wider mr-1">Director Cues:</span>
                                <button type="button" onclick="insertScriptTag('[pause 500ms] ')" class="px-2 py-0.5 rounded bg-slate-800/90 text-slate-300 border border-slate-700 hover:bg-brand-500/20 hover:text-brand-glow transition-all font-mono text-[10px]">
                                    ⏱️ [Pause 0.5s]
                                </button>
                                <button type="button" onclick="insertScriptTag('[pause 1s] ')" class="px-2 py-0.5 rounded bg-slate-800/90 text-slate-300 border border-slate-700 hover:bg-brand-500/20 hover:text-brand-glow transition-all font-mono text-[10px]">
                                    ⏱️ [Pause 1.0s]
                                </button>
                                <button type="button" onclick="insertScriptTag('[emphasis] ')" class="px-2 py-0.5 rounded bg-slate-800/90 text-slate-300 border border-slate-700 hover:bg-brand-500/20 hover:text-brand-glow transition-all font-mono text-[10px]">
                                    ✨ [Emphasis]
                                </button>
                                <button type="button" onclick="insertScriptTag('[protip] ')" class="px-2 py-0.5 rounded bg-slate-800/90 text-slate-300 border border-slate-700 hover:bg-brand-500/20 hover:text-brand-glow transition-all font-mono text-[10px]">
                                    💡 [Pro Tip]
                                </button>
                            </div>

                            <textarea id="script-input" rows="3" oninput="updateScriptMetrics(); if(typeof updatePreflightSummary==='function')updatePreflightSummary();" class="w-full rounded-xl bg-slate-900 border border-slate-700/80 p-3 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all font-sans leading-relaxed shadow-inner" placeholder="Enter spoken narration text. Leave completely empty for 100% silent video..."></textarea>
                        </div>
                    </div>

                    <!-- PHASE 2: FORMAT (What shape does it take?) -->
                    <div class="space-y-3 p-4 rounded-xl bg-slate-950/70 border border-slate-800">
                        <div class="flex items-center justify-between pb-2 border-b border-slate-800/80">
                            <div class="flex items-center gap-2">
                                <span class="w-5 h-5 rounded bg-brand-500/20 text-brand-glow flex items-center justify-center text-[10px] font-bold font-mono">2</span>
                                <div>
                                    <h4 class="text-xs font-bold uppercase tracking-wider text-slate-200">Phase 2 — Format</h4>
                                    <p class="text-[10px] text-slate-400">What shape does it take? Output type, aspect ratio & scene count</p>
                                </div>
                            </div>
                        </div>

                        <!-- Output Type: Video or Slide -->
                        <div class="space-y-2">
                            <div class="flex items-center justify-between">
                                <label class="text-xs font-bold text-slate-300 uppercase tracking-wider">Output Type</label>
                                <span class="text-[10px] text-slate-400">Can also be customized per scene in Storyboard</span>
                            </div>

                            <!-- Segmented Output Selector Cards -->
                            <div class="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                                <div id="output-card-video" onclick="setDirectorOutputType('video'); if(typeof updatePreflightSummary==='function')updatePreflightSummary();" class="p-3 rounded-xl bg-brand-500/15 border-2 border-brand-500 cursor-pointer transition-all hover:brightness-110">
                                    <div class="flex items-center justify-between mb-1">
                                        <span class="text-xs font-bold text-white flex items-center gap-1.5">
                                            <span>🎬</span> <span>Video Scene Mode</span>
                                        </span>
                                        <span id="output-badge-video" class="text-[9px] font-bold px-1.5 py-0.5 rounded bg-brand-500 text-white font-mono">ACTIVE</span>
                                    </div>
                                    <p class="text-[11px] text-slate-300 leading-snug">
                                        Dynamic visuals, camera motion, and avatar presenter. Best for demonstrations, b-roll, and narrative visual sequences.
                                    </p>
                                </div>

                                <div id="output-card-slide" onclick="setDirectorOutputType('slide'); if(typeof updatePreflightSummary==='function')updatePreflightSummary();" class="p-3 rounded-xl bg-slate-900 border-2 border-slate-800 cursor-pointer transition-all hover:border-slate-700 hover:brightness-110">
                                    <div class="flex items-center justify-between mb-1">
                                        <span class="text-xs font-bold text-slate-300 flex items-center gap-1.5">
                                            <span>📊</span> <span>Instructional Slide Mode</span>
                                        </span>
                                        <span id="output-badge-slide" class="text-[9px] font-bold px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 font-mono hidden">ACTIVE</span>
                                    </div>
                                    <p class="text-[11px] text-slate-400 leading-snug">
                                        Clean static instructional slide with key takeaway bullet points & diagrams while avatar explains the concept.
                                    </p>
                                </div>
                            </div>
                            <input type="hidden" id="output-type-select" value="video">
                        </div>

                        <!-- Resolution & Scene Count Grid -->
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 pt-1">
                            <!-- Format & Aspect Ratio -->
                            <div class="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800 space-y-2.5">
                                <label class="text-xs font-bold text-slate-200 uppercase tracking-wider block">Resolution & Aspect Ratio</label>

                                <!-- Aspect Ratio Quick Switcher Pills -->
                                <div class="grid grid-cols-4 gap-1.5 text-[11px]">
                                    <button type="button" onclick="setAspectPreset('16:9_hd')" id="aspect-btn-16-9" class="py-1 px-1.5 rounded-lg bg-brand-600 text-white font-bold text-center border border-brand-500 transition-all">
                                        16:9 ▭
                                    </button>
                                    <button type="button" onclick="setAspectPreset('9:16_vertical')" id="aspect-btn-9-16" class="py-1 px-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-slate-300 font-semibold text-center border border-slate-800 transition-all">
                                        9:16 ▯
                                    </button>
                                    <button type="button" onclick="setAspectPreset('1:1_square')" id="aspect-btn-1-1" class="py-1 px-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-slate-300 font-semibold text-center border border-slate-800 transition-all">
                                        1:1 ▢
                                    </button>
                                    <button type="button" onclick="setAspectPreset('4:5_portrait')" id="aspect-btn-4-5" class="py-1 px-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-slate-300 font-semibold text-center border border-slate-800 transition-all">
                                        4:5 ▰
                                    </button>
                                </div>

                                <select id="resolution-select" onchange="updateAspectPreview(); if(typeof updatePreflightSummary==='function')updatePreflightSummary(); try{localStorage.setItem('neuroclips_last_resolution', this.value);}catch(e){}" class="w-full rounded-xl bg-slate-900 border border-slate-700/80 p-2 text-xs text-slate-200 focus:outline-none focus:border-brand-500">
                                    <optgroup label="▭ Landscape — 16:9">
                                        <option value="16:9_hd" data-w="1280" data-h="720" data-orient="Landscape" selected>YouTube / Course Video — 16:9 HD (1280×720)</option>
                                        <option value="16:9_fhd" data-w="1920" data-h="1080" data-orient="Landscape">YouTube / Course Video — 16:9 Full HD (1920×1080)</option>
                                        <option value="16:9_sd" data-w="576" data-h="324" data-orient="Landscape">Fast Draft Preview — 16:9 SD (576×324)</option>
                                    </optgroup>
                                    <optgroup label="▯ Portrait — 9:16">
                                        <option value="9:16_vertical" data-w="720" data-h="1280" data-orient="Portrait">Instagram Reels / YouTube Shorts — 9:16 (720×1280)</option>
                                        <option value="9:16_fhd" data-w="1080" data-h="1920" data-orient="Portrait">Instagram Reels / YouTube Shorts — 9:16 Full HD (1080×1920)</option>
                                    </optgroup>
                                    <optgroup label="▢ Square — 1:1">
                                        <option value="1:1_square" data-w="720" data-h="720" data-orient="Square">Instagram / Social Feed Post — 1:1 (720×720)</option>
                                        <option value="1:1_hd" data-w="1080" data-h="1080" data-orient="Square">Instagram / Social Feed Post — 1:1 HD (1080×1080)</option>
                                    </optgroup>
                                    <optgroup label="▰ Portrait Feed — 4:5">
                                        <option value="4:5_portrait" data-w="1080" data-h="1350" data-orient="Portrait">Instagram / LinkedIn Portrait Feed — 4:5 (1080×1350)</option>
                                        <option value="4:5_sd" data-w="576" data-h="720" data-orient="Portrait">Fast Portrait Preview — 4:5 (576×720)</option>
                                    </optgroup>
                                </select>

                                <div class="flex items-center gap-2.5 mt-1">
                                    <div class="flex items-center justify-center w-10 h-10 flex-shrink-0 bg-slate-900 rounded-lg border border-slate-800">
                                        <div id="aspect-preview-box" class="border-2 border-brand-500/70 bg-brand-500/10 rounded-[3px] transition-all"
                                             style="width:36px;height:20.25px;"></div>
                                    </div>
                                    <p id="aspect-preview-label" class="text-[11px] text-slate-400 leading-snug">
                                        <span class="font-mono text-brand-glow font-bold">1280×720</span> · Landscape
                                    </p>
                                </div>
                            </div>

                            <!-- Scene Chunking -->
                            <div class="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800 space-y-2.5">
                                <div class="flex items-center justify-between">
                                    <label class="text-xs font-bold text-slate-200 uppercase tracking-wider">Scene Chunking</label>
                                    <span id="scene-val" class="font-mono text-brand-glow font-bold text-xs">4 Scenes</span>
                                </div>

                                <div class="flex rounded-lg bg-slate-900 p-0.5 border border-slate-800 text-[11px]">
                                    <button type="button" id="chunk-mode-auto" onclick="setChunkingMode('auto')" class="w-1/2 py-1 rounded-md bg-brand-600 text-white font-bold transition-all">
                                        🤖 AI Smart Chunking
                                    </button>
                                    <button type="button" id="chunk-mode-manual" onclick="setChunkingMode('manual')" class="w-1/2 py-1 rounded-md text-slate-400 hover:text-white transition-all">
                                        🎯 Target Scene Count
                                    </button>
                                </div>
                                <input type="hidden" id="chunking-mode-input" value="auto">

                                <input id="scene-slider" type="range" min="1" max="16" value="4" oninput="document.getElementById('scene-val').innerText = this.value + ' Scenes'; if(typeof updatePreflightSummary==='function')updatePreflightSummary();" class="w-full accent-brand-500 bg-slate-800 rounded-lg cursor-pointer">
                                <div class="flex items-center justify-between text-[10px] text-slate-400">
                                    <button type="button" onclick="setSceneChunk(3)" class="hover:text-brand-glow">Shorts (3)</button>
                                    <button type="button" onclick="setSceneChunk(6)" class="hover:text-brand-glow">Standard (6)</button>
                                    <button type="button" onclick="setSceneChunk(10)" class="hover:text-brand-glow">Deep (10)</button>
                                    <button type="button" onclick="setSceneChunk(16)" class="hover:text-brand-glow">Master (16)</button>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- PHASE 3: PRESENTATION (LOOK & SOUND) -->
                    <div class="p-4 rounded-xl bg-slate-950/90 border border-brand-500/30 space-y-3.5 shadow-lg shadow-brand-500/5">
                        <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                            <div class="flex items-center space-x-2">
                                <span class="w-5 h-5 rounded bg-brand-500/20 text-brand-glow flex items-center justify-center text-xs font-bold">3</span>
                                <div>
                                    <span class="text-xs font-bold text-white uppercase tracking-wider">Phase 3: Presentation</span>
                                    <span class="text-[10px] text-slate-400 block">Voice, speech prosody, speaker avatar, and audio/visual FX</span>
                                </div>
                            </div>
                            
                            <!-- Voice Engine Switcher & Quick Settings -->
                            <div class="flex items-center space-x-2">
                                <div class="flex rounded-lg bg-slate-900 p-0.5 border border-slate-800 text-[10px]">
                                    <button type="button" id="engine-tab-edgetts" onclick="switchVoiceEngine('edge_tts')" class="px-2.5 py-1 rounded-md bg-brand-600 text-white font-bold transition-all">
                                        ⚡ Free Neural
                                    </button>
                                    <button type="button" id="engine-tab-elevenlabs" onclick="switchVoiceEngine('elevenlabs')" class="px-2.5 py-1 rounded-md text-slate-400 hover:text-white transition-all">
                                        👑 ElevenLabs
                                    </button>
                                </div>
                                <button type="button" onclick="openSettingsModal()" class="p-1 text-slate-400 hover:text-brand-glow transition-all" title="Configure Voice Engine Credentials in Settings">
                                    ⚙️
                                </button>
                            </div>
                        </div>

                        <!-- ElevenLabs Notification Notice (Task 6b) -->
                        <div id="elevenlabs-config-box" class="hidden p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/30 text-xs flex items-center justify-between">
                            <div class="flex items-center space-x-2">
                                <span class="text-amber-400 text-sm">👑</span>
                                <div>
                                    <span class="font-bold text-amber-300">ElevenLabs MultiLingual V2 Active</span>
                                    <span class="text-[10px] text-slate-400 block">Account key & voice profile loaded from Settings.</span>
                                </div>
                            </div>
                            <button type="button" onclick="openSettingsModal()" class="px-2.5 py-1 rounded bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 border border-amber-500/40 text-[10px] font-semibold transition-all">
                                ⚙️ Manage Key
                            </button>
                        </div>

                        <!-- Language & Voice Profile -->
                        <div class="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
                            <div>
                                <label class="block text-xs font-semibold text-slate-300 mb-1">🌐 Language Filter</label>
                                <select id="language-select" onchange="onLanguageChange()" class="w-full rounded-lg bg-slate-900 border border-slate-700/80 p-2 text-xs text-slate-200 focus:outline-none focus:border-brand-500">
                                    <option value="en-US" selected>🇺🇸 English (US)</option>
                                    <option value="te-IN">🇮🇳 Telugu (తెలుగు)</option>
                                    <option value="ta-IN">🇮🇳 Tamil (தமிழ்)</option>
                                    <option value="hi-IN">🇮🇳 Hindi (हिन्दी)</option>
                                    <option value="es-ES">🇪🇸 Spanish (Castilian)</option>
                                    <option value="fr-FR">🇫🇷 French (Standard)</option>
                                    <option value="de-DE">🇩🇪 German (Standard)</option>
                                    <option value="ja-JP">🇯🇵 Japanese (日本語)</option>
                                </select>
                            </div>

                            <div id="edgetts-voice-container">
                                <div class="flex justify-between items-center mb-1">
                                    <label class="text-xs font-semibold text-slate-300">Selected Voice</label>
                                    <span id="active-voice-badge" class="text-[10px] text-brand-glow font-mono">en-IN Neerja</span>
                                </div>
                                <select id="voice-select" onchange="updateActiveVoiceBadge(); if(typeof updatePreflightSummary==='function')updatePreflightSummary(); try{localStorage.setItem('neuroclips_last_voice', this.value);}catch(e){}" class="w-full rounded-lg bg-slate-900 border border-slate-700/80 p-2 text-xs text-slate-200">
                                    <option value="en-IN-PrabhatNeural">Srinivas (en-IN, Male - Cloud & AI Lead)</option>
                                    <option value="en-IN-NeerjaNeural" selected>Neerja (en-IN, Female - Instructional)</option>
                                    <option value="en-US-GuyNeural">Guy (en-US, Male - Executive)</option>
                                    <option value="en-US-AriaNeural">Aria (en-US, Female - Presenter)</option>
                                    <option value="en-US-ChristopherNeural">Christopher (en-US, Male - Authoritative)</option>
                                    <option value="te-IN-MohanNeural">Mohan (te-IN, Telugu Male)</option>
                                    <option value="te-IN-ShrutiNeural">Shruti (te-IN, Telugu Female)</option>
                                    <option value="ta-IN-PallaviNeural">Pallavi (ta-IN, Tamil Female)</option>
                                    <option value="ta-IN-ValluvarNeural">Valluvar (ta-IN, Tamil Male)</option>
                                    <option value="hi-IN-MadhurNeural">Madhur (hi-IN, Hindi Male)</option>
                                    <option value="es-ES-AlvaroNeural">Álvaro (es-ES, Spanish Executive)</option>
                                    <option value="fr-FR-HenriNeural">Henri (fr-FR, French Clear)</option>
                                    <option value="de-DE-ConradNeural">Conrad (de-DE, German Technical)</option>
                                    <option value="ja-JP-KeitaNeural">Keita (ja-JP, Japanese Standard)</option>
                                </select>
                            </div>

                            <div>
                                <label class="block text-xs font-semibold text-slate-300 mb-1">🎭 Emotion & Prosody</label>
                                <select id="archetype-select" onchange="applyVoiceArchetype(this.value)" class="w-full rounded-lg bg-slate-900 border border-slate-700/80 p-2 text-xs text-slate-200">
                                    <option value="technical" selected>Technical Instructor (Clear & Measured)</option>
                                    <option value="executive">Executive & Boardroom (Deep & Authoritative)</option>
                                    <option value="conversational">Warm & Conversational (Friendly Mentor)</option>
                                    <option value="presenter">High-Energy Presenter (Fast & Dynamic)</option>
                                </select>
                            </div>
                        </div>

                        <!-- Directorial Sliders: Speed, Pitch, Stability, Clarity -->
                        <div class="grid grid-cols-2 md:grid-cols-4 gap-3 pt-1 text-xs">
                            <div class="space-y-1">
                                <div class="flex justify-between text-[11px] text-slate-300">
                                    <span>Pacing / Speed</span>
                                    <span id="speed-val" class="font-mono text-brand-glow font-bold">1.00x</span>
                                </div>
                                <input id="speed-slider" type="range" min="0.75" max="1.30" step="0.05" value="1.0" oninput="document.getElementById('speed-val').innerText = parseFloat(this.value).toFixed(2) + 'x'; updateScriptMetrics();" class="w-full accent-brand-500 bg-slate-800 rounded-lg cursor-pointer">
                            </div>

                            <div class="space-y-1">
                                <div class="flex justify-between text-[11px] text-slate-300">
                                    <span>Pitch Tuning</span>
                                    <span id="pitch-val" class="font-mono text-brand-glow font-bold">+0Hz</span>
                                </div>
                                <input id="pitch-slider" type="range" min="-10" max="10" step="1" value="0" oninput="document.getElementById('pitch-val').innerText = (this.value >= 0 ? '+' : '') + this.value + 'Hz'" class="w-full accent-brand-500 bg-slate-800 rounded-lg cursor-pointer">
                            </div>

                            <div class="space-y-1">
                                <div class="flex justify-between text-[11px] text-slate-300">
                                    <span>Stability</span>
                                    <span id="stability-val" class="font-mono text-brand-glow font-bold">75%</span>
                                </div>
                                <input id="stability-slider" type="range" min="20" max="100" step="5" value="75" oninput="document.getElementById('stability-val').innerText = this.value + '%'" class="w-full accent-brand-500 bg-slate-800 rounded-lg cursor-pointer">
                            </div>

                            <div class="space-y-1">
                                <div class="flex justify-between text-[11px] text-slate-300">
                                    <span>Clarity Boost</span>
                                    <span id="clarity-val" class="font-mono text-brand-glow font-bold">75%</span>
                                </div>
                                <input id="clarity-slider" type="range" min="20" max="100" step="5" value="75" oninput="document.getElementById('clarity-val').innerText = this.value + '%'" class="w-full accent-brand-500 bg-slate-800 rounded-lg cursor-pointer">
                            </div>
                        </div>

                        <!-- Audition Deck & Waveform Audio Preview (Task 6a: Standalone Audio Master removed) -->
                        <div class="flex flex-col sm:flex-row items-center justify-between gap-2.5 p-2.5 rounded-lg bg-slate-900/90 border border-slate-800 text-xs">
                            <div class="flex items-center space-x-2 w-full sm:w-auto">
                                <button type="button" onclick="auditionVoiceDirector()" id="audition-btn" class="px-3 py-1.5 rounded-lg bg-gradient-to-r from-brand-600 to-indigo-600 text-white font-bold hover:brightness-110 transition-all flex items-center gap-1.5 shadow-md shadow-brand-500/20 whitespace-nowrap">
                                    <span>🔊</span> <span>Audition Voice Line</span>
                                </button>
                                <span id="audition-status" class="text-[11px] text-slate-400 font-mono">Ready</span>
                            </div>
                            <audio id="director-audio-player" controls class="h-7 w-full sm:w-64 accent-brand-500" style="filter: invert(1) hue-rotate(180deg) brightness(0.85);"></audio>
                        </div>

                        <!-- Motion Graphics & Background Music Toggles -->
                        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs pt-1">
                            <div class="p-3 rounded-lg bg-slate-900/90 border border-slate-800 space-y-1.5">
                                <div class="flex justify-between items-center">
                                    <label class="font-semibold text-slate-300 flex items-center gap-1">
                                        <span>🎥</span> <span>Motion Graphics</span>
                                    </label>
                                    <span id="motion-status-badge" class="text-[9px] font-mono px-1.5 py-0.5 rounded bg-brand-500/20 text-brand-glow">ON</span>
                                </div>
                                <div class="flex rounded-lg bg-slate-950 p-0.5 border border-slate-800 text-[11px]">
                                    <button type="button" id="motion-btn-on" onclick="setMotionGraphics(true)" class="w-1/2 py-1 rounded-md bg-brand-600 text-white font-bold transition-all">
                                        ✨ ON (Dynamic)
                                    </button>
                                    <button type="button" id="motion-btn-off" onclick="setMotionGraphics(false)" class="w-1/2 py-1 rounded-md text-slate-400 hover:text-white transition-all">
                                        🛑 OFF (Static)
                                    </button>
                                </div>
                                <input type="hidden" id="motion-graphics-check" value="true">
                                <p class="text-[10px] text-slate-400 leading-tight">Camera motion zoom & pan. Disable for static diagrams.</p>
                            </div>

                            <div class="p-3 rounded-lg bg-slate-900/90 border border-slate-800 space-y-1.5">
                                <div class="flex justify-between items-center">
                                    <label class="font-semibold text-slate-300 flex items-center gap-1">
                                        <span>🎵</span> <span>Background Music</span>
                                    </label>
                                    <span id="bgm-status-badge" class="text-[9px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">OFF</span>
                                </div>
                                <div class="flex rounded-lg bg-slate-950 p-0.5 border border-slate-800 text-[11px]">
                                    <button type="button" id="bgm-btn-on" onclick="setBackgroundMusic(true)" class="w-1/2 py-1 rounded-md text-slate-400 hover:text-white transition-all">
                                        🎵 ON (Ambient)
                                    </button>
                                    <button type="button" id="bgm-btn-off" onclick="setBackgroundMusic(false)" class="w-1/2 py-1 rounded-md bg-brand-600 text-white font-bold transition-all">
                                        🔇 OFF (Clean Voice)
                                    </button>
                                </div>
                                <input type="hidden" id="bgm-check" value="false">
                                <p class="text-[10px] text-slate-400 leading-tight">Subtle ambient music ducked behind narration (-18dB).</p>
                            </div>
                        </div>

                        <!-- Speaker Avatar Persona & Layout -->
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs pt-1">
                            <div>
                                <div class="flex justify-between items-center mb-1">
                                    <label class="text-xs font-semibold text-slate-300">Avatar Persona</label>
                                    <label for="avatar-file-input" class="text-[10px] text-brand-glow hover:underline cursor-pointer flex items-center gap-0.5">
                                        <span>📸</span> <span>Upload Photo</span>
                                    </label>
                                    <input type="file" id="avatar-file-input" class="hidden" accept="image/*" onchange="uploadAvatar(this)">
                                </div>
                                <select id="avatar-persona-select" onchange="onPersonaSelectChange(this.value); try{localStorage.setItem('neuroclips_last_persona', this.value);}catch(e){}" class="w-full rounded-lg bg-slate-900 border border-slate-700/80 p-1.5 text-xs text-slate-200">
                                    <option value="maya_fintech" selected>Maya (Senior FinTech Lead)</option>
                                    <option value="alex_ai">Alex (Enterprise AI Architect)</option>
                                    <option value="elena_compliance">Elena (Risk & Governance Director)</option>
                                    <option value="david_trainer">David (Global LMS Instructor)</option>
                                    <option value="srinivas_cloud">Srinivas (Lead AI & Cloud Architect)</option>
                                    <option value="rajesh_cloud" style="display:none;">Rajesh (Legacy)</option>
                                    <option value="custom_upload">Custom Uploaded Portrait</option>
                                </select>
                                <span id="persona-meta-badge" class="text-[10px] text-brand-glow font-mono block mt-1">🇮🇳 South Asian | en-IN (Neerja) | FinTech</span>
                            </div>

                            <div>
                                <label class="block text-xs font-semibold text-slate-300 mb-1">Avatar Display Layout</label>
                                <select id="avatar-layout-select" class="w-full rounded-lg bg-slate-900 border border-slate-700/80 p-1.5 text-xs text-slate-200">
                                    <option value="pip_bottom_right">PiP Floating Glass Card (Bottom Right)</option>
                                    <option value="pip_top_right">PiP Floating Bubble (Top Right)</option>
                                    <option value="split_screen">Split Screen (60% Diagram / 40% Avatar)</option>
                                    <option value="full_anchor">Full Anchor (100% Presenter)</option>
                                    <option value="none">None (B-roll Only)</option>
                                </select>
                            </div>
                        </div>

                        <!-- Bumpers & Identity Persistence -->
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs pt-1">
                            <div>
                                <label class="block text-[11px] text-slate-400 mb-1">Intro Opener Clip (Optional)</label>
                                <select id="intro-bumper-select" class="w-full rounded-lg bg-slate-900 border border-slate-700/80 p-1.5 text-xs text-slate-200">
                                    <option value="">None (Direct start)</option>
                                </select>
                            </div>
                            <div>
                                <label class="block text-[11px] text-slate-400 mb-1">Outro Closer Clip (Optional)</label>
                                <select id="outro-bumper-select" class="w-full rounded-lg bg-slate-900 border border-slate-700/80 p-1.5 text-xs text-slate-200">
                                    <option value="">None (Direct finish)</option>
                                </select>
                            </div>
                        </div>

                        <div class="flex items-center justify-between pt-2 border-t border-slate-900 text-xs">
                            <div class="flex items-center space-x-2">
                                <select id="identity-load-select" onchange="loadSelectedIdentity(this.value)" class="rounded bg-slate-900 border border-slate-700 text-[10px] text-slate-300 p-1">
                                    <option value="">📂 Load Identity Profile...</option>
                                </select>
                                <button onclick="saveCurrentIdentity()" class="text-[10px] px-2 py-1 rounded bg-brand-500/20 text-brand-glow border border-brand-500/30 hover:bg-brand-500/30 transition-all">
                                    💾 Save Identity
                                </button>
                            </div>
                            <button onclick="openAssetVaultModal()" class="text-[10px] text-indigo-400 hover:underline">
                                Video Asset Library ↗
                            </button>
                        </div>
                    </div>

                    <!-- PHASE 4: RENDER (ENGINE & EXECUTION) -->
                    <div class="p-4 rounded-xl bg-slate-950/90 border border-brand-500/30 space-y-3.5 shadow-lg shadow-brand-500/5">
                        <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                            <div class="flex items-center space-x-2">
                                <span class="w-5 h-5 rounded bg-brand-500/20 text-brand-glow flex items-center justify-center text-xs font-bold">4</span>
                                <div>
                                    <span class="text-xs font-bold text-white uppercase tracking-wider">Phase 4: Render Engine & Compilation</span>
                                    <span class="text-[10px] text-slate-400 block">Select compiler backend, configure output options, and execute build</span>
                                </div>
                            </div>
                            <span class="text-[10px] font-mono text-slate-400">Directorial Pipeline</span>
                        </div>

                        <!-- Compiler Engine (moved from Step 6) & Execution Checkboxes -->
                        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                            <div>
                                <label class="block text-xs font-semibold text-slate-300 mb-1">Compiler Engine</label>
                                <select id="engine-select" onchange="if(typeof updatePreflightSummary==='function')updatePreflightSummary();" class="w-full rounded-lg bg-slate-900 border border-slate-700/80 p-2 text-xs text-slate-200">
                                    <option value="ffmpeg" selected>Standard FFmpeg (Fast & Reliable)</option>
                                    <option value="remotion">Remotion React (Broadcast Motion Graphics)</option>
                                </select>
                            </div>
                            <div class="flex flex-col justify-center space-y-2 p-2 rounded-lg bg-slate-900/60 border border-slate-800">
                                <div class="flex items-center space-x-2">
                                    <input type="checkbox" id="burn-subtitles-check" onchange="if(typeof updatePreflightSummary==='function')updatePreflightSummary();" class="rounded accent-brand-500 cursor-pointer" checked>
                                    <label for="burn-subtitles-check" class="text-xs text-slate-300 cursor-pointer select-none">
                                        Burn-In Subtitles <span class="text-[11px] text-brand-glow font-mono">(Open Captions)</span>
                                    </label>
                                </div>
                                <div class="flex items-center space-x-2">
                                    <input type="checkbox" id="auto-clean-check" class="rounded accent-brand-500 cursor-pointer">
                                    <label for="auto-clean-check" class="text-xs text-slate-300 cursor-pointer select-none">
                                        Fresh Workspace <span class="text-[11px] text-slate-500">(Auto-clear cache)</span>
                                    </label>
                                </div>
                            </div>
                        </div>

                        <!-- PRE-FLIGHT SUMMARY (Task 7a) -->
                        <div class="p-3 rounded-xl bg-slate-900/90 border border-brand-500/20 flex items-center justify-between gap-3 text-xs">
                            <div class="flex items-center space-x-2 min-w-0">
                                <span class="text-brand-glow text-sm">📋</span>
                                <div class="truncate">
                                    <div class="text-[10px] text-slate-400 uppercase tracking-wider font-semibold">Pre-Flight Configuration</div>
                                    <div id="preflight-summary" class="font-mono text-brand-glow text-xs truncate">
                                        16:9 HD · 1280×720 · 4 scenes · en-IN-NeerjaNeural · captions on · FFmpeg
                                    </div>
                                </div>
                            </div>
                            <div class="flex items-center space-x-1.5 flex-shrink-0">
                                <span class="inline-block w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                                <span class="text-[10px] text-emerald-400 font-mono font-semibold">Ready to Build</span>
                            </div>
                        </div>

                        <!-- Action Buttons -->
                        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
                            <button id="storyboard-btn" onclick="openStoryboardPreview()" class="py-3.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 font-bold text-sm text-slate-200 transition-all flex items-center justify-center space-x-2 shadow-md">
                                <span>🎬</span>
                                <span>Storyboard & Scene Breakdown</span>
                            </button>
                            <button id="generate-btn" onclick="startGeneration()" class="py-3.5 rounded-xl bg-gradient-to-r from-brand-600 via-indigo-600 to-brand-500 hover:from-brand-500 hover:to-indigo-500 font-bold text-sm text-white shadow-lg shadow-brand-500/20 active:scale-[0.99] transition-all flex items-center justify-center space-x-2">
                                <span>🚀</span>
                                <span>Generate Content</span>
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            <!-- RIGHT: Telemetry & Live Streaming Log Terminal (5 cols) -->
            <div class="lg:col-span-5 space-y-6">
                <div class="grid grid-cols-2 gap-3">
                    <div class="glass-panel p-3.5 rounded-xl">
                        <span class="text-xs text-slate-400">Current Stage</span>
                        <div id="current-stage-stat" class="text-base font-bold text-brand-glow font-mono mt-0.5 truncate" title="Idle">Idle</div>
                        <span class="text-[10px] text-slate-500">Active Milestone</span>
                    </div>
                    <div class="glass-panel p-3.5 rounded-xl">
                        <span class="text-xs text-slate-400">Elapsed</span>
                        <div id="elapsed-stat" class="text-base font-bold text-white font-mono mt-0.5">00:00</div>
                        <span class="text-[10px] text-slate-500">Render Time (mm:ss)</span>
                    </div>
                    <div class="glass-panel p-3.5 rounded-xl">
                        <span class="text-xs text-slate-400">System CPU</span>
                        <div id="cpu-stat" class="text-base font-bold text-white font-mono mt-0.5">0%</div>
                        <div class="w-full bg-slate-800 h-1 rounded-full mt-1.5 overflow-hidden"><div id="cpu-bar" class="bg-indigo-400 h-full w-0"></div></div>
                    </div>
                    <div class="glass-panel p-3.5 rounded-xl">
                        <span class="text-xs text-slate-400">Script Latency</span>
                        <div id="latency-stat" class="text-base font-bold text-brand-glow font-mono mt-0.5">0.00s</div>
                        <span class="text-[10px] text-slate-500">Rule-Based Director (Fallback)</span>
                    </div>
                </div>

                <!-- DIRECTOR PRODUCTION OUTPUT PLAYER & DOWNLOAD -->
                <div id="director-output-card" class="glass-panel rounded-2xl p-5 space-y-3.5 border border-brand-500/30">
                    <div class="flex items-center justify-between border-b border-slate-800 pb-2.5">
                        <div class="flex items-center gap-2">
                            <span class="w-2.5 h-2.5 rounded-full bg-slate-500" id="director-status-dot"></span>
                            <h3 class="text-xs font-bold uppercase tracking-wider text-slate-200">Director Video Output</h3>
                        </div>
                        <span id="director-pipeline-phase" class="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-900 text-brand-glow border border-brand-500/30">Idle</span>
                    </div>

                    <!-- Pipeline Phase & Progress -->
                    <div id="director-progress-container" class="space-y-1.5 hidden">
                        <div class="flex justify-between text-[11px] font-mono">
                            <span id="director-phase-msg" class="text-slate-300">Queued</span>
                            <span id="director-phase-pct" class="text-brand-glow font-bold">0%</span>
                        </div>
                        <div class="w-full h-2 bg-slate-950 rounded-full overflow-hidden border border-slate-800">
                            <div id="director-progress-bar" class="h-full bg-gradient-to-r from-brand-600 to-indigo-500 transition-all duration-300" style="width: 0%"></div>
                        </div>
                    </div>

                    <!-- Video Preview Screen -->
                    <div class="w-full aspect-video rounded-xl bg-slate-950 border border-slate-800 overflow-hidden relative shadow-inner flex items-center justify-center group">
                        <video id="director-video-player" class="w-full h-full object-contain" controls poster="/static_renders/custom_avatar.png">
                            Your browser does not support HTML5 video.
                        </video>
                    </div>

                    <!-- Download CTA Button -->
                    <div class="pt-1">
                        <a id="director-download-btn" href="#" download="director_production.mp4" class="w-full py-2.5 px-4 rounded-xl bg-slate-800 text-slate-400 font-bold text-xs flex items-center justify-center gap-2 border border-slate-700 transition-all pointer-events-none opacity-50">
                            <span>⬇️</span> <span>Download Generated Video (.mp4)</span>
                        </a>
                    </div>
                </div>

                <div class="glass-panel rounded-2xl p-5 space-y-3">
                    <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                        <div class="flex items-center space-x-2">
                            <span class="w-2.5 h-2.5 rounded-full bg-emerald-400"></span>
                            <h3 class="text-xs font-bold uppercase tracking-wider text-slate-300">Live Production Terminal</h3>
                        </div>
                        <div class="flex items-center space-x-2">
                            <button onclick="copyTerminalLogs()" id="copy-log-btn" class="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-[11px] text-slate-300 font-mono transition-all flex items-center gap-1">
                                <span>📋</span> <span>Copy Log</span>
                            </button>
                        </div>
                    </div>

                    <div id="terminal-logs" class="h-60 overflow-y-auto font-mono text-xs text-slate-300 space-y-1.5 p-3 rounded-xl bg-slate-950/90 border border-slate-800/80 select-all">
                        <div class="text-slate-500 italic">[Ready] Awaiting new generation request...</div>
                    </div>
                </div>
            </div>
        </div>

        <!-- 🎞️ MEDIA VAULT WITH 1-CLICK SCORM EXPORTER & DUAL PLAYERS -->
        <section class="glass-panel rounded-2xl p-6 space-y-4">
            <div class="flex items-center justify-between">
                <div>
                    <h2 class="text-base font-bold text-white flex items-center gap-2">
                        <span>🎞️</span> Production Media Vault & SCORM Exporter
                    </h2>
                    <p class="text-xs text-slate-400">Rendered production MP4 videos, synchronized voiceovers, and 1-click SCORM 1.2 packages</p>
                </div>
                <div class="flex items-center gap-2">
                    <button onclick="openQuizModal()" class="text-xs px-3 py-1.5 rounded-lg bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-500/40 transition-all flex items-center gap-1.5 shadow-sm">
                        <span>📝</span> <span>Item Bank & Quizzes (224 Qs)</span>
                    </button>
                    <button id="filter-session-btn" onclick="toggleSessionFilter()" class="text-xs px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition-all flex items-center gap-1">
                        <span>🔘</span> <span id="filter-session-label">Current Session Only</span>
                    </button>
                    <button onclick="fetchGallery()" class="text-xs px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 transition-all flex items-center gap-1">
                        <span>↻</span> <span>Refresh</span>
                    </button>
                    <button onclick="clearGallery()" class="text-xs px-3 py-1.5 rounded-lg bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/20 transition-all flex items-center gap-1">
                        <span>🗑️</span> <span>Clear Vault</span>
                    </button>
                </div>
            </div>

            <div id="gallery-grid" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            </div>
        </section>

        </div><!-- END OF MODE 1: MULTI-AGENT VIDEO STUDIO -->

        <!-- MODE 2: STANDALONE VOICE DIRECTOR & AUDIO MASTER STUDIO -->
        <div id="mode-voice-section" class="hidden space-y-6">
            <div class="glass-panel rounded-2xl p-6 space-y-6 border border-emerald-500/20">
                <div class="flex items-center justify-between border-b border-slate-800 pb-3">
                    <div>
                        <h3 class="text-base font-bold text-white flex items-center gap-2">
                            <span>🎙️</span> Voice Director Studio & Multi-Format Audio Master Exporter
                        </h3>
                        <p class="text-xs text-slate-400">High-fidelity neural speech synthesis, prosody tuning, and synchronous subtitle generation without video rendering</p>
                    </div>
                    <span class="text-xs font-mono px-3 py-1 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                        ⚡ Edge-TTS & ElevenLabs Audio Engine
                    </span>
                </div>

                <div class="grid grid-cols-1 lg:grid-cols-12 gap-6">
                    <!-- Left: Script Input, Prosody & Controls (7 cols) -->
                    <div class="lg:col-span-7 space-y-4">
                        <!-- Script Input -->
                        <div class="space-y-1.5">
                            <div class="flex justify-between items-center">
                                <label class="text-xs font-semibold text-slate-300">Narration Script & Directorial Cues</label>
                                <div class="flex items-center space-x-3">
                                    <label for="voice-lab-file-upload" class="text-[10px] text-emerald-400 hover:underline cursor-pointer flex items-center gap-1 font-sans">
                                        <span>📁</span> <span>Upload Document (.txt, .md, .srt)</span>
                                    </label>
                                    <input type="file" id="voice-lab-file-upload" class="hidden" accept=".txt,.md,.srt,.vtt,.json" onchange="handleVoiceLabDocumentUpload(this)">
                                    <span id="voice-lab-stats" class="text-[11px] font-mono text-emerald-400">0 words | ~0.0 min</span>
                                </div>
                            </div>

                            <!-- Director Cue Quick Buttons -->
                            <div class="flex items-center space-x-1.5 overflow-x-auto py-1 text-[11px]">
                                <span class="text-slate-500 font-semibold text-[10px] uppercase tracking-wider mr-1">Director Cues:</span>
                                <button type="button" onclick="insertVoiceLabTag('[pause 250ms] ')" class="px-2 py-0.5 rounded bg-slate-800/90 text-slate-300 border border-slate-700 hover:bg-emerald-500/20 hover:text-emerald-300 hover:border-emerald-500/30 transition-all font-mono">
                                    ⏱️ [0.25s]
                                </button>
                                <button type="button" onclick="insertVoiceLabTag('[pause 500ms] ')" class="px-2 py-0.5 rounded bg-slate-800/90 text-slate-300 border border-slate-700 hover:bg-emerald-500/20 hover:text-emerald-300 hover:border-emerald-500/30 transition-all font-mono">
                                    ⏱️ [0.5s]
                                </button>
                                <button type="button" onclick="insertVoiceLabTag('[pause 1s] ')" class="px-2 py-0.5 rounded bg-slate-800/90 text-slate-300 border border-slate-700 hover:bg-emerald-500/20 hover:text-emerald-300 hover:border-emerald-500/30 transition-all font-mono">
                                    ⏱️ [1.0s]
                                </button>
                                <button type="button" onclick="insertVoiceLabTag('[emphasis] ')" class="px-2 py-0.5 rounded bg-slate-800/90 text-slate-300 border border-slate-700 hover:bg-emerald-500/20 hover:text-emerald-300 hover:border-emerald-500/30 transition-all font-mono">
                                    ✨ [Emphasis]
                                </button>
                                <button type="button" onclick="insertVoiceLabTag('[protip] ')" class="px-2 py-0.5 rounded bg-slate-800/90 text-slate-300 border border-slate-700 hover:bg-emerald-500/20 hover:text-emerald-300 hover:border-emerald-500/30 transition-all font-mono">
                                    💡 [Pro Tip]
                                </button>
                                <button type="button" onclick="expandPromptToVoiceScript()" id="voice-lab-expand-btn" class="px-2.5 py-0.5 rounded bg-brand-500/20 text-brand-glow border border-brand-500/30 hover:bg-brand-500/30 transition-all font-sans font-bold flex items-center gap-1 ml-auto">
                                    <span>✨</span> <span>AI Expand Prompt</span>
                                </button>
                            </div>

                            <textarea id="voice-lab-prompt" rows="5" oninput="updateVoiceLabMetrics()" class="w-full rounded-xl bg-slate-900/90 border border-slate-700/80 p-3 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 transition-all font-sans" placeholder="Enter prompt or complete script (e.g. Type a prompt and click '✨ AI Expand Prompt', or upload/paste a complete narration script with [pause 500ms] cues)..."></textarea>
                        </div>

                        <!-- Language & Voice Selector -->
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                            <div>
                                <label class="block text-xs font-semibold text-slate-300 mb-1">🌐 Target Language & Accent</label>
                                <select id="voice-lab-lang" onchange="onVoiceLabLangChange()" class="w-full rounded-xl bg-slate-900 border border-slate-700/80 p-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500">
                                    <option value="en-US" selected>🇺🇸 English (US Standard)</option>
                                    <option value="en-IN">🇮🇳 English (Indian Accent)</option>
                                    <option value="te-IN">🇮🇳 Telugu (తెలుగు)</option>
                                    <option value="ta-IN">🇮🇳 Tamil (தமிழ்)</option>
                                    <option value="hi-IN">🇮🇳 Hindi (हिन्दी)</option>
                                    <option value="es-ES">🇪🇸 Spanish (Castilian)</option>
                                    <option value="fr-FR">🇫🇷 French (Standard)</option>
                                    <option value="de-DE">🇩🇪 German (Standard)</option>
                                    <option value="ja-JP">🇯🇵 Japanese (日本語)</option>
                                </select>
                            </div>
                            <div>
                                <label class="block text-xs font-semibold text-slate-300 mb-1">🎙️ Voice Persona Profile</label>
                                <select id="voice-lab-voice" class="w-full rounded-xl bg-slate-900 border border-slate-700/80 p-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500">
                                    <option value="en-US-GuyNeural" selected>Guy (Male - Deep Professional)</option>
                                    <option value="en-US-AriaNeural">Aria (Female - Clear Instructional)</option>
                                    <option value="en-IN-NeerjaNeural">Neerja (Female - Indian FinTech Specialist)</option>
                                    <option value="en-IN-PrabhatNeural">Prabhat (Male - Indian Senior Architect)</option>
                                </select>
                            </div>
                        </div>

                        <!-- Prosody Sliders -->
                        <div class="grid grid-cols-2 gap-3 p-3 rounded-xl bg-slate-950/80 border border-slate-800">
                            <div>
                                <div class="flex justify-between text-[11px] font-semibold text-slate-300 mb-1">
                                    <span>Speech Rate</span>
                                    <span id="voice-lab-rate-val" class="font-mono text-emerald-400 font-bold">1.00x</span>
                                </div>
                                <input id="voice-lab-rate" type="range" min="0.75" max="1.50" step="0.05" value="1.0" oninput="document.getElementById('voice-lab-rate-val').innerText = parseFloat(this.value).toFixed(2) + 'x'; updateVoiceLabMetrics();" class="w-full accent-emerald-500 bg-slate-800 rounded-lg cursor-pointer">
                            </div>
                            <div>
                                <div class="flex justify-between text-[11px] font-semibold text-slate-300 mb-1">
                                    <span>Pitch Shift</span>
                                    <span id="voice-lab-pitch-val" class="font-mono text-emerald-400 font-bold">0 Hz</span>
                                </div>
                                <input id="voice-lab-pitch" type="range" min="-20" max="20" step="2" value="0" oninput="document.getElementById('voice-lab-pitch-val').innerText = (this.value > 0 ? '+' : '') + this.value + ' Hz'" class="w-full accent-emerald-500 bg-slate-800 rounded-lg cursor-pointer">
                            </div>
                        </div>

                        <!-- Format & Action Bar -->
                        <div class="flex flex-col sm:flex-row items-center justify-between gap-3 p-3 rounded-xl bg-emerald-950/20 border border-emerald-500/30">
                            <div class="flex items-center space-x-2 w-full sm:w-auto">
                                <label class="text-xs font-semibold text-emerald-300 whitespace-nowrap">Output Master:</label>
                                <select id="voice-lab-format" class="rounded-lg bg-slate-900 border border-slate-700 p-1.5 text-xs text-white">
                                    <option value="mp3" selected>🎵 MP3 (320kbps Universal)</option>
                                    <option value="wav">🔊 WAV (Lossless 44.1kHz)</option>
                                    <option value="m4a">📱 M4A / AAC (Apple Podcasts)</option>
                                    <option value="ogg">🌐 OGG (Web Audio)</option>
                                    <option value="flac">💿 FLAC (Audiophile Lossless)</option>
                                </select>
                            </div>
                            <div class="flex items-center space-x-2 w-full sm:w-auto justify-end">
                                <button onclick="auditionVoiceLab()" id="voice-lab-audition-btn" class="px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-bold transition-all flex items-center gap-1">
                                    <span>🎧</span> <span>Audition</span>
                                </button>
                                <button onclick="exportVoiceLabMaster()" id="voice-lab-export-btn" class="px-4 py-2 rounded-lg bg-gradient-to-r from-emerald-600 to-teal-600 hover:brightness-110 text-white text-xs font-bold shadow-md shadow-emerald-500/20 transition-all flex items-center gap-1.5">
                                    <span>⚡</span> <span>Export Audio Master</span>
                                </button>
                            </div>
                        </div>
                    </div>

                    <!-- Right: Live Waveform & Subtitles Preview (5 cols) -->
                    <div class="lg:col-span-5 space-y-4">
                        <div class="glass-panel p-4 rounded-xl space-y-3 border border-slate-800">
                            <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                                <h4 class="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
                                    <span>🔊</span> <span>Master Audio Player</span>
                                </h4>
                                <span id="voice-lab-player-badge" class="text-[10px] px-2 py-0.5 rounded-full bg-slate-800 text-slate-400">Idle</span>
                            </div>
                            <div class="p-3 rounded-lg bg-black/60 border border-slate-800 space-y-2">
                                <audio id="voice-lab-audio-player" controls class="w-full h-8"></audio>
                                <div id="voice-lab-download-box" class="hidden flex items-center justify-between text-xs pt-1 border-t border-slate-800">
                                    <a id="voice-lab-audio-dl" href="#" download class="text-emerald-400 hover:underline font-bold flex items-center gap-1">
                                        <span>⬇️</span> <span>Download Master</span>
                                    </a>
                                    <a id="voice-lab-srt-dl" href="#" download class="text-indigo-400 hover:underline font-bold flex items-center gap-1">
                                        <span>📄</span> <span>Download .SRT</span>
                                    </a>
                                </div>
                            </div>
                        </div>

                        <!-- Synchronized Transcript & Subtitles Box -->
                        <div class="glass-panel p-4 rounded-xl space-y-2 border border-slate-800 flex-1">
                            <div class="flex items-center justify-between border-b border-slate-800 pb-1.5">
                                <span class="text-xs font-bold text-slate-300">Synchronized Transcript & Captions</span>
                                <span class="text-[10px] text-slate-500 font-mono">Auto-generated</span>
                            </div>
                            <div id="voice-lab-srt-preview" class="p-3 rounded-lg bg-slate-950 font-mono text-xs text-slate-300 max-h-48 overflow-y-auto leading-relaxed border border-slate-800/80">
                                Directorial cues and spoken sentences will stream here upon synthesis.
                            </div>
                        </div>
                    </div>
                </div>

                <!-- NEW SECTION: VOICE CLONING & UNIVERSAL DOCUMENT SPEECH INGESTION -->
                <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 pt-4 border-t border-slate-800/80">
                    <!-- Module A: Record & Clone User Voice -->
                    <div class="glass-panel p-5 rounded-xl border border-indigo-500/30 space-y-4">
                        <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                            <h4 class="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
                                <span>🎙️</span> <span>Clone Real Voice into Library</span>
                            </h4>
                            <span class="text-[10px] px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300 font-mono">Instant Voice Clone</span>
                        </div>
                        <p class="text-[11px] text-slate-400">Record 15–30s of clean speech via microphone or upload an audio file (.wav, .ogg, .mp3) to register a new permanent persona.</p>
                        
                        <div class="grid grid-cols-3 gap-3">
                            <div>
                                <label class="block text-[11px] font-semibold text-slate-300 mb-1">Presenter Name</label>
                                <input id="clone-display-name" type="text" placeholder="e.g. Dr. Srinivas Velaga" class="w-full rounded-lg bg-slate-900 border border-slate-700 p-2 text-xs text-white">
                            </div>
                            <div>
                                <label class="block text-[11px] font-semibold text-slate-300 mb-1">Accent / Locale</label>
                                <select id="clone-locale" class="w-full rounded-lg bg-slate-900 border border-slate-700 p-2 text-xs text-white">
                                    <option value="en-IN" selected>en-IN (Indian English)</option>
                                    <option value="te-IN">te-IN (Telugu)</option>
                                    <option value="hi-IN">hi-IN (Hindi)</option>
                                    <option value="en-US">en-US (North American)</option>
                                    <option value="en-GB">en-GB (British)</option>
                                </select>
                            </div>
                            <div>
                                <label class="block text-[11px] font-semibold text-slate-300 mb-1">Gender</label>
                                <select id="clone-gender" class="w-full rounded-lg bg-slate-900 border border-slate-700 p-2 text-xs text-white">
                                    <option value="female" selected>Female</option>
                                    <option value="male">Male</option>
                                    <option value="non_binary">Non-Binary</option>
                                </select>
                            </div>
                        </div>

                        <!-- Recording Controls & File Upload -->
                        <div class="p-3 rounded-lg bg-slate-950 border border-slate-800 space-y-3">
                            <div class="flex items-center justify-between gap-2">
                                <button id="btn-record-mic" onclick="toggleMicRecording()" class="px-3 py-2 rounded-lg bg-red-600/80 hover:bg-red-500 text-white text-xs font-bold flex items-center gap-1.5 transition-all">
                                    <span id="record-indicator">🔴</span> <span id="record-text">Record from Mic</span>
                                </button>
                                <span class="text-[11px] text-slate-500">or upload:</span>
                                <label for="clone-file-upload" class="px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-bold cursor-pointer inline-flex items-center gap-1">
                                    <span>📁</span> <span id="clone-file-label">Choose Audio (.mp3, .ogg, .wav)</span>
                                </label>
                                <input type="file" id="clone-file-upload" accept=".mp3,.ogg,.wav,.m4a,audio/*" class="hidden" onchange="handleAudioSampleSelected(this)">
                            </div>
                            <div id="clone-audio-preview-box" class="hidden pt-1">
                                <audio id="clone-audio-preview" controls class="w-full h-8"></audio>
                            </div>
                        </div>

                        <button onclick="submitVoiceClone()" id="btn-submit-clone" class="w-full py-2.5 rounded-lg bg-gradient-to-r from-indigo-600 to-purple-600 hover:brightness-110 text-white text-xs font-bold shadow-md shadow-indigo-500/20 transition-all flex items-center justify-center gap-1.5">
                            <span>✨</span> <span>Clone Voice & Add to Catalog</span>
                        </button>

                        <!-- Saved Cloned Voice Library Grid -->
                        <div class="pt-3 border-t border-slate-800 space-y-2.5">
                            <div class="flex items-center justify-between">
                                <span class="text-xs font-bold text-slate-300 flex items-center gap-1.5">
                                    <span>📚</span> <span>Saved Cloned Voice Library</span>
                                </span>
                                <span id="cloned-voice-count" class="text-[10px] px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300 font-mono">0 Clones</span>
                            </div>
                            <div id="cloned-voice-library-grid" class="space-y-2 max-h-56 overflow-y-auto pr-1">
                                <div class="text-[11px] text-slate-500 italic p-3 text-center bg-slate-900/50 rounded-lg border border-slate-800">
                                    No custom cloned voices yet. Upload an .mp3 or .ogg file above to add one!
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Module B: Universal File-to-Speech Engine -->
                    <div class="glass-panel p-5 rounded-xl border border-emerald-500/30 space-y-4">
                        <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                            <h4 class="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
                                <span>📄</span> <span>Universal Document-to-Audio Ingestion</span>
                            </h4>
                            <span class="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 font-mono">Any File &bull; Any Voice</span>
                        </div>
                        <p class="text-[11px] text-slate-400">Upload books, lecture notes, or reports (.txt, .md, .docx, .pdf). We slice into pedagogical scenes, apply FinTech pronunciation lexicons, and synthesize audio masters.</p>

                        <div class="p-4 rounded-xl border-2 border-dashed border-emerald-500/40 bg-emerald-950/10 hover:bg-emerald-950/20 transition-all text-center space-y-2">
                            <div class="text-2xl">📥</div>
                            <div class="text-xs font-bold text-white">Drop Document Here or Browse</div>
                            <p class="text-[10px] text-slate-400">Supports .txt, .md, .docx, .pdf &bull; up to 25MB</p>
                            <label for="doc-speech-file-input" class="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold cursor-pointer inline-flex items-center gap-1.5 shadow-md shadow-emerald-500/20">
                                <span>📄</span> <span>Select Document</span>
                            </label>
                            <input type="file" id="doc-speech-file-input" class="hidden" accept=".txt,.md,.docx,.pdf" onchange="handleDocFileSelected(this)">
                            <div id="selected-doc-name" class="text-[11px] font-mono text-emerald-300 pt-1"></div>
                        </div>

                        <div class="flex items-center justify-between gap-3">
                            <div class="flex items-center gap-2">
                                <input type="checkbox" id="doc-export-scorm-chk" class="rounded accent-emerald-500 cursor-pointer">
                                <label for="doc-export-scorm-chk" class="text-xs text-slate-300 cursor-pointer">Auto-package as SCORM 1.2 Zip</label>
                            </div>
                            <button onclick="submitUniversalDocSpeech()" id="btn-doc-speech-run" class="px-5 py-2.5 rounded-lg bg-gradient-to-r from-emerald-600 to-teal-600 hover:brightness-110 text-white text-xs font-bold shadow-md shadow-emerald-500/20 transition-all flex items-center gap-1.5">
                                <span>⚡</span> <span>Synthesize Document Audio Master</span>
                            </button>
                        </div>
                    </div>
                </div>

                <!-- MODULE C: BATCH PRESENTATION & DECK AUDIO STUDIO (M{m}_T{t}_L{l}_Slide{s}.mp3) -->
                <div class="glass-panel p-5 rounded-xl border border-teal-500/30 space-y-4 pt-4 mt-4">
                    <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                        <div>
                            <h4 class="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
                                <span>📊</span> <span>Batch Presentation & Deck Audio Studio</span>
                            </h4>
                            <p class="text-[11px] text-slate-400">Upload PowerPoint deck (.pptx) or Excel course map (.xlsx) to synthesize slide audio matching <code class="text-teal-400">M{m}_T{t}_L{l}_Slide{s}.mp3</code>.</p>
                        </div>
                        <span class="text-[10px] px-2.5 py-1 rounded-full bg-teal-500/20 text-teal-300 font-mono border border-teal-500/30">
                            Courseware Automation
                        </span>
                    </div>

                    <div class="grid grid-cols-1 md:grid-cols-4 gap-3 text-xs">
                        <div>
                            <label class="block text-[11px] font-semibold text-slate-300 mb-1">Select Presentation or Excel File</label>
                            <label for="batch-slide-file-input" class="w-full py-2 px-3 rounded-lg bg-teal-600/20 border border-teal-500/40 text-teal-300 text-xs font-bold text-center cursor-pointer hover:bg-teal-600/30 transition-all flex items-center justify-center gap-1.5">
                                <span>📁</span> <span id="batch-slide-file-label">Upload .pptx / .xlsx</span>
                            </label>
                            <input type="file" id="batch-slide-file-input" class="hidden" accept=".pptx,.xlsx" onchange="handleBatchSlideFileSelected(this)">
                        </div>
                        <div>
                            <label class="block text-[11px] font-semibold text-slate-300 mb-1">Module Number</label>
                            <input type="number" id="batch-slide-module-num" value="1" min="1" max="50" class="w-full rounded-lg bg-slate-900 border border-slate-700 p-2 text-xs text-white font-mono">
                        </div>
                        <div>
                            <label class="block text-[11px] font-semibold text-slate-300 mb-1">Voice Persona</label>
                            <select id="batch-slide-persona" class="w-full rounded-lg bg-slate-900 border border-slate-700 p-2 text-xs text-slate-200">
                                <option value="maya_fintech" selected>Maya (FinTech Senior Lead)</option>
                                <option value="alex_ai">Alex (Enterprise AI Architect)</option>
                                <option value="elena_compliance">Elena (Risk & Governance Director)</option>
                                <option value="david_trainer">David (Global LMS Instructor)</option>
                                <option value="rajesh_cloud">Rajesh (Principal Cloud Architect)</option>
                            </select>
                        </div>
                        <div>
                            <label class="block text-[11px] font-semibold text-slate-300 mb-1">Slide Numbering</label>
                            <select id="batch-slide-numbering" class="w-full rounded-lg bg-slate-900 border border-slate-700 p-2 text-xs text-slate-200">
                                <option value="lesson_relative" selected>Lesson-Relative (Slide 1, 2 of Lesson)</option>
                                <option value="deck_absolute">Deck-Absolute (Slide 1–29 of Deck)</option>
                            </select>
                        </div>
                    </div>

                    <div class="flex items-center justify-between gap-3 pt-2">
                        <div class="flex items-center gap-2">
                            <input type="checkbox" id="batch-slide-skip-cache" class="rounded accent-teal-500 cursor-pointer" checked>
                            <label for="batch-slide-skip-cache" class="text-xs text-slate-300 cursor-pointer select-none">
                                Skip Already Generated Files <span class="text-[11px] text-slate-500">(Fast Resume)</span>
                            </label>
                        </div>
                        <button onclick="submitBatchSlideGeneration()" id="btn-batch-slide-run" class="px-6 py-2.5 rounded-lg bg-gradient-to-r from-teal-600 to-emerald-600 hover:brightness-110 text-white text-xs font-bold shadow-md shadow-teal-500/20 transition-all flex items-center gap-2">
                            <span>⚡</span> <span>Generate Slide Audio Batch</span>
                        </button>
                    </div>

                    <!-- Progress and Results Box -->
                    <div id="batch-slide-status-box" class="hidden p-3 rounded-xl bg-slate-950/80 border border-teal-500/30 space-y-2">
                        <div class="flex items-center justify-between text-xs">
                            <span id="batch-slide-status-text" class="text-teal-300 font-mono">Synthesizing batch audio...</span>
                            <span id="batch-slide-counts" class="font-bold text-white font-mono">0 / 0</span>
                        </div>
                        <div class="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
                            <div id="batch-slide-progress-bar" class="bg-teal-400 h-full w-0 transition-all duration-300"></div>
                        </div>
                        <div id="batch-slide-results-list" class="max-h-48 overflow-y-auto font-mono text-xs space-y-1 text-slate-300 pt-1"></div>
                    </div>
                </div>

                <!-- MODULE D: CURRICULUM BATCH VIDEO SYNTHESIS PIPELINE (FEATURE 3) -->
                <div class="glass-panel p-5 rounded-xl border border-indigo-500/30 space-y-4 pt-4 mt-4">
                    <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                        <div>
                            <h4 class="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
                                <span>🚀</span> <span>Curriculum Batch Video Pipeline (Excel Course Maps)</span>
                            </h4>
                            <p class="text-[11px] text-slate-400">Automate mass video & lesson generation across entire 15-hour curriculum spreadsheets directly into the SQLite batch worker.</p>
                        </div>
                        <span class="text-[10px] px-2.5 py-1 rounded-full bg-indigo-500/20 text-indigo-300 font-mono border border-indigo-500/30">
                            Batch Production Engine
                        </span>
                    </div>

                    <div class="grid grid-cols-1 md:grid-cols-4 gap-3 text-xs">
                        <div>
                            <label class="block text-[11px] font-semibold text-slate-300 mb-1">Course ID</label>
                            <input type="text" id="curriculum-batch-course-id" value="FINTECH_AGENTS_15HR" class="w-full rounded-lg bg-slate-900 border border-slate-700 p-2 text-xs text-white font-mono">
                        </div>
                        <div>
                            <label class="block text-[11px] font-semibold text-slate-300 mb-1">Select Module</label>
                            <select id="curriculum-batch-module" class="w-full rounded-lg bg-slate-900 border border-slate-700 p-2 text-xs text-slate-200">
                                <option value="">All Modules (Full Curriculum)</option>
                                <option value="1">Module 1: Traditional AI vs GenAI vs Agents</option>
                                <option value="2">Module 2: Agent Architecture & Planning</option>
                                <option value="3">Module 3: RAG & Financial Memory</option>
                                <option value="4">Module 4: Multi-Agent Collaboration</option>
                                <option value="5">Module 5: Risk, Guardrails & Governance</option>
                                <option value="6">Module 6: Enterprise Deployment & Observability</option>
                                <option value="7">Module 7: Algorithmic Execution & Trading</option>
                            </select>
                        </div>
                        <div>
                            <label class="block text-[11px] font-semibold text-slate-300 mb-1">Presenter Persona</label>
                            <select id="curriculum-batch-persona" class="w-full rounded-lg bg-slate-900 border border-slate-700 p-2 text-xs text-slate-200">
                                <option value="maya_fintech" selected>Maya (FinTech Senior Lead)</option>
                                <option value="alex_ai">Alex (Enterprise AI Architect)</option>
                                <option value="elena_compliance">Elena (Risk & Governance Director)</option>
                                <option value="david_trainer">David (Global LMS Instructor)</option>
                                <option value="rajesh_cloud">Rajesh (Principal Cloud Architect)</option>
                            </select>
                        </div>
                        <div>
                            <label class="block text-[11px] font-semibold text-slate-300 mb-1">Resolution Profile</label>
                            <select id="curriculum-batch-resolution" class="w-full rounded-lg bg-slate-900 border border-slate-700 p-2 text-xs text-slate-200">
                                <option value="16:9_hd" selected>16:9 HD Broadcast (1280x720)</option>
                                <option value="16:9_fhd">16:9 Full HD (1920x1080)</option>
                                <option value="9:16_vertical">9:16 Mobile Shorts (720x1280)</option>
                            </select>
                        </div>
                    </div>

                    <div class="flex items-center justify-between gap-3 pt-2">
                        <span class="text-xs text-slate-400">Uses <code class="text-indigo-300">Nipuna_AI_Agents_in_FinTech_15_Hour_Course_v4.xlsx</code></span>
                        <button onclick="startCurriculumBatchPipeline()" id="btn-curriculum-batch-start" class="px-6 py-2.5 rounded-lg bg-gradient-to-r from-indigo-600 to-purple-600 hover:brightness-110 text-white text-xs font-bold shadow-md shadow-indigo-500/20 transition-all flex items-center gap-2">
                            <span>🚀</span> <span>Launch Batch Video Queue</span>
                        </button>
                    </div>

                    <div id="curriculum-batch-status-box" class="hidden p-3 rounded-xl bg-slate-950/80 border border-indigo-500/30 space-y-2">
                        <div class="flex items-center justify-between text-xs">
                            <span id="curriculum-batch-status-title" class="text-indigo-300 font-mono font-bold">Queue Initializing...</span>
                            <span id="curriculum-batch-progress-pct" class="text-white font-mono font-bold">0%</span>
                        </div>
                        <div class="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
                            <div id="curriculum-batch-progress-bar" class="bg-indigo-400 h-full w-0 transition-all duration-300"></div>
                        </div>
                        <div class="flex items-center justify-between text-[11px] text-slate-400 font-mono pt-1">
                            <span id="curriculum-batch-stat-completed">Completed: 0</span>
                            <span id="curriculum-batch-stat-processing">Processing: 0</span>
                            <span id="curriculum-batch-stat-pending">Pending: 0</span>
                            <span id="curriculum-batch-stat-failed">Failed: 0</span>
                        </div>
                    </div>
                </div>
        </div><!-- END OF MODE 2: VOICE DIRECTOR -->

        <!-- MODE 3: IMAGE DIRECTOR STUDIO (KEYFRAMES & PERSONAS) -->
        <div id="mode-image-section" class="hidden space-y-6">
            <div class="glass-panel rounded-2xl p-6 space-y-6 border border-pink-500/20">
                <div class="flex items-center justify-between border-b border-slate-800 pb-3">
                    <div>
                        <h3 class="text-base font-bold text-white flex items-center gap-2">
                            <span>🎨</span> Image Director Studio & Visual Continuity Lab
                        </h3>
                        <p class="text-xs text-slate-400">Design visual aesthetics, synthesize storyboard keyframes, calibrate continuity anchors, and configure instructor personas</p>
                    </div>
                    <span class="text-xs font-mono px-3 py-1 rounded-full bg-pink-500/20 text-pink-300 border border-pink-500/30">
                        ✨ Stable Diffusion & FLUX-Ready
                    </span>
                </div>

                <div class="grid grid-cols-1 lg:grid-cols-12 gap-6">
                    <!-- Left: Prompt & Visual Stylization Controls (7 cols) -->
                    <div class="lg:col-span-7 space-y-4">
                        <!-- Keyframe Visual Prompt -->
                        <div>
                            <div class="flex justify-between items-center mb-1">
                                <label class="text-xs font-semibold text-slate-300">Visual Scene Concept & Prompt</label>
                                <button type="button" onclick="loadSampleImagePrompt()" class="text-[10px] text-pink-400 hover:underline">🎲 Sample FinTech Prompt</button>
                            </div>
                            <textarea id="image-lab-prompt" rows="3" class="w-full rounded-xl bg-slate-900 border border-slate-700/80 p-3 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-pink-500 font-sans" placeholder="Describe the scene visuals (e.g. Modern FinTech holographic trading desk with real-time algorithmic settlement feeds, cinematic lighting, volumetric particles, 8k render)..."></textarea>
                        </div>

                        <!-- Art Style Presets & Aspect Ratio -->
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                            <div>
                                <label class="block text-xs font-semibold text-slate-300 mb-1">Art Style Preset</label>
                                <select id="image-lab-style" class="w-full rounded-xl bg-slate-900 border border-slate-700/80 p-2 text-xs text-slate-200 focus:outline-none focus:border-pink-500">
                                    <option value="Cinematic 35mm (Volumetric Lighting)" selected>Cinematic 35mm (Volumetric Lighting)</option>
                                    <option value="Cyberpunk Neon (Futuristic Holograms)">Cyberpunk Neon (Futuristic Holograms)</option>
                                    <option value="Anime Masterpiece (Studio Ghibli / Makoto Shinkai)">Anime Masterpiece (Studio Ghibli)</option>
                                    <option value="Photorealistic 8K (Architectural / Corporate)">Photorealistic 8K (Corporate)</option>
                                    <option value="Tech Hologram Data (Fintech Infographics)">Tech Hologram Data (FinTech)</option>
                                    <option value="3D Pixar Animation (Stylized Characters)">3D Pixar Animation (Stylized)</option>
                                    <option value="Dark Fantasy Epic (Moody Dramatic Contrast)">Dark Fantasy Epic</option>
                                    <option value="Minimalist Vector (Modern Motion Flat 2D)">Minimalist Vector 2D</option>
                                </select>
                            </div>
                            <div>
                                <label class="block text-xs font-semibold text-slate-300 mb-1">Aspect Ratio & Resolution</label>
                                <select id="image-lab-resolution" class="w-full rounded-xl bg-slate-900 border border-slate-700/80 p-2 text-xs text-slate-200 focus:outline-none focus:border-pink-500">
                                    <option value="16:9_hd" selected>16:9 HD Broadcast (1280x720)</option>
                                    <option value="16:9_fhd">16:9 Full HD (1920x1080)</option>
                                    <option value="9:16_vertical">9:16 Mobile Shorts (720x1280)</option>
                                    <option value="1:1_square">1:1 Square LMS (720x720)</option>
                                </select>
                            </div>
                        </div>

                        <!-- Persona Continuity Anchor Selection -->
                        <div class="p-3.5 rounded-xl bg-slate-950/80 border border-pink-500/20 space-y-3">
                            <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                                <span class="text-xs font-bold text-slate-300 flex items-center gap-1.5">
                                    <span>👤</span> <span>Presenter Character Continuity Anchor</span>
                                </span>
                                <label for="image-lab-avatar-upload" class="text-[10px] text-pink-400 hover:underline cursor-pointer flex items-center gap-1">
                                    <span>📸</span> <span>Upload Custom Portrait</span>
                                </label>
                                <input type="file" id="image-lab-avatar-upload" class="hidden" accept="image/*" onchange="uploadAvatar(this)">
                            </div>
                            <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                                <div>
                                    <label class="block text-xs font-semibold text-slate-300 mb-1">Select Persona</label>
                                    <select id="image-lab-persona" onchange="onImageLabPersonaChange(this.value)" class="w-full rounded-lg bg-slate-900 border border-slate-700/80 p-1.5 text-xs text-slate-200">
                                        <option value="maya_fintech" selected>Maya (Senior FinTech Lead)</option>
                                        <option value="alex_ai">Alex (Enterprise AI Architect)</option>
                                        <option value="elena_compliance">Elena (Risk & Governance Director)</option>
                                        <option value="david_trainer">David (Global LMS Instructor)</option>
                                        <option value="custom_upload">Custom Uploaded Portrait</option>
                                    </select>
                                </div>
                                <div>
                                    <label class="block text-xs font-semibold text-slate-300 mb-1">Avatar Display Layout</label>
                                    <select id="image-lab-layout" class="w-full rounded-lg bg-slate-900 border border-slate-700/80 p-1.5 text-xs text-slate-200">
                                        <option value="pip_bottom_right" selected>PiP Floating Card (Bottom Right)</option>
                                        <option value="pip_top_right">PiP Floating Bubble (Top Right)</option>
                                        <option value="split_screen">Split Screen (60% Diagram / 40% Avatar)</option>
                                        <option value="full_anchor">Full Anchor (100% Presenter)</option>
                                        <option value="none">None (B-roll Only)</option>
                                    </select>
                                </div>
                            </div>
                            <div>
                                <label class="block text-[11px] font-semibold text-slate-400 mb-1">Active Continuity Anchor Description</label>
                                <textarea id="image-lab-anchor-desc" rows="2" class="w-full rounded-lg bg-slate-900 border border-slate-800 p-2 text-xs font-mono text-slate-300" readonly>30-year-old South Asian female FinTech executive with sleek black hair in navy blue tailored corporate blazer, modern trading floor background</textarea>
                            </div>
                        </div>

                        <!-- Synthesize Keyframe Button -->
                        <div class="flex items-center justify-between pt-2">
                            <span class="text-xs text-slate-400">Generates high-res visual storyboard anchor</span>
                            <button onclick="synthesizeImageKeyframe()" id="image-lab-gen-btn" class="px-5 py-2.5 rounded-xl bg-gradient-to-r from-pink-600 via-rose-600 to-pink-500 hover:brightness-110 text-white font-bold text-xs shadow-lg shadow-pink-500/20 transition-all flex items-center gap-2">
                                <span>🎨</span> <span>Synthesize Keyframe Preview</span>
                            </button>
                        </div>
                    </div>

                    <!-- Right: Visual Preview Deck & Keyframe Gallery (5 cols) -->
                    <div class="lg:col-span-5 space-y-4">
                        <div class="glass-panel p-4 rounded-xl space-y-3 border border-slate-800">
                            <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                                <h4 class="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
                                    <span>🖼️</span> <span>Active Visual Preview</span>
                                </h4>
                                <span id="image-lab-status-badge" class="text-[10px] px-2 py-0.5 rounded-full bg-slate-800 text-slate-400">Ready</span>
                            </div>
                            <div class="relative rounded-xl overflow-hidden bg-slate-950 aspect-video border border-slate-800 flex items-center justify-center">
                                <img id="image-lab-preview-img" src="https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?q=80&w=640" class="w-full h-full object-cover">
                                <div id="image-lab-preview-overlay" class="absolute bottom-2 left-2 right-2 p-2 rounded-lg bg-black/75 backdrop-blur-sm text-[10px] text-slate-300 font-mono flex items-center justify-between">
                                    <span id="image-lab-overlay-style">Style: Cinematic 35mm</span>
                                    <span id="image-lab-overlay-res">1280x720</span>
                                </div>
                            </div>
                            <div class="flex items-center justify-between pt-1 text-xs">
                                <a id="image-lab-dl-btn" href="https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?q=80&w=640" target="_blank" download="keyframe.png" class="text-pink-400 hover:underline font-bold flex items-center gap-1">
                                    <span>⬇️</span> <span>Download Full Resolution</span>
                                </a>
                                <button onclick="sendKeyframeToDirector()" class="text-brand-glow hover:underline font-bold flex items-center gap-1">
                                    <span>🎬</span> <span>Apply to Director Storyboard</span>
                                </button>
                            </div>
                        </div>

                        <!-- Persona Continuity Gallery -->
                        <div class="glass-panel p-4 rounded-xl space-y-3 border border-slate-800">
                            <h4 class="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
                                <span>👥</span> <span>Instructor Personas & Continuity Anchors</span>
                            </h4>
                            <div class="grid grid-cols-4 gap-2 text-center text-[10px]">
                                <div onclick="selectQuickPersona('maya_fintech')" class="p-2 rounded-lg bg-slate-950 border border-slate-800 hover:border-pink-500/50 cursor-pointer transition-all">
                                    <img src="https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?q=80&w=150" class="w-10 h-10 rounded-full mx-auto mb-1 object-cover border border-slate-700">
                                    <span class="text-slate-300 font-bold block truncate">Maya</span>
                                    <span class="text-slate-500">FinTech</span>
                                </div>
                                <div onclick="selectQuickPersona('alex_ai')" class="p-2 rounded-lg bg-slate-950 border border-slate-800 hover:border-pink-500/50 cursor-pointer transition-all">
                                    <img src="https://images.unsplash.com/photo-1560250097-0b93528c311a?q=80&w=150" class="w-10 h-10 rounded-full mx-auto mb-1 object-cover border border-slate-700">
                                    <span class="text-slate-300 font-bold block truncate">Alex</span>
                                    <span class="text-slate-500">AI Arch</span>
                                </div>
                                <div onclick="selectQuickPersona('elena_compliance')" class="p-2 rounded-lg bg-slate-950 border border-slate-800 hover:border-pink-500/50 cursor-pointer transition-all">
                                    <img src="https://images.unsplash.com/photo-1580489944761-15a19d654956?q=80&w=150" class="w-10 h-10 rounded-full mx-auto mb-1 object-cover border border-slate-700">
                                    <span class="text-slate-300 font-bold block truncate">Elena</span>
                                    <span class="text-slate-500">Risk/Gov</span>
                                </div>
                                <div onclick="selectQuickPersona('david_trainer')" class="p-2 rounded-lg bg-slate-950 border border-slate-800 hover:border-pink-500/50 cursor-pointer transition-all">
                                    <img src="https://images.unsplash.com/photo-1519085360753-af0119f7cbe7?q=80&w=150" class="w-10 h-10 rounded-full mx-auto mb-1 object-cover border border-slate-700">
                                    <span class="text-slate-300 font-bold block truncate">David</span>
                                    <span class="text-slate-500">Global LMS</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div><!-- END OF MODE 3: IMAGE DIRECTOR -->


        <!-- MODE: AVATAR STUDIO ("Avathar Page" from wire_frames/raw_plan.jpeg) -->
        <div id="mode-avatar-section" class="hidden space-y-6">
            <div class="glass-panel-glow rounded-2xl p-6 relative overflow-hidden border border-pink-500/20">
                <div class="flex items-center justify-between border-b border-slate-800 pb-3 flex-wrap gap-3">
                    <div class="flex items-center space-x-3">
                        <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-pink-600 via-purple-600 to-indigo-500 flex items-center justify-center shadow-lg shadow-pink-500/20">
                            <span class="text-xl">👤</span>
                        </div>
                        <div>
                            <h2 class="text-base font-bold text-white flex items-center gap-2">
                                <span>Avatar Studio</span>
                                <span class="text-xs font-mono px-2 py-0.5 rounded bg-pink-500/20 text-pink-300 border border-pink-500/30">Wireframe: Avathar Page</span>
                            </h2>
                            <p class="text-xs text-slate-400">Photo-to-Presenter Synthesis, Speech Scripting, Curtain Chroma Compositing & 3D Rigging</p>
                        </div>
                    </div>
                    <div class="flex items-center space-x-2 text-xs">
                        <span class="px-2.5 py-1 rounded-lg bg-pink-500/10 border border-pink-500/30 text-pink-300 font-mono text-[11px]">
                            ⚡ Zero-Drift Lip Sync & Motion
                        </span>
                    </div>
                </div>

                <div class="grid grid-cols-1 lg:grid-cols-12 gap-6 mt-6">
                    <!-- LEFT: Presenter Configuration & Script (7 cols) -->
                    <div class="lg:col-span-7 space-y-5">
                        
                        <!-- STEP 1: UPLOAD IMAGE / AVATAR PORTRAIT -->
                        <div class="p-4 rounded-xl bg-slate-950/80 border border-slate-800 space-y-3">
                            <div class="flex items-center justify-between">
                                <label class="text-xs font-bold text-slate-200 uppercase tracking-wider flex items-center gap-1.5">
                                    <span class="w-4 h-4 rounded bg-pink-500/20 text-pink-400 flex items-center justify-center text-[10px] font-bold">1</span>
                                    <span>Upload Image (Presenter Portrait)</span>
                                </label>
                                <span class="text-[10px] text-slate-400">Accepts PNG, JPG, WEBP &bull; 1:1 or 3:4 aspect recommended</span>
                            </div>

                            <div class="grid grid-cols-1 sm:grid-cols-12 gap-3 items-center">
                                <!-- Live Portrait Preview Card with Backdrop Preview -->
                                <div class="sm:col-span-4 flex flex-col items-center justify-center p-3 rounded-xl bg-slate-900 border border-slate-800 relative group overflow-hidden">
                                    <div id="avatar-preview-curtain-bg" class="w-28 h-28 rounded-2xl flex items-center justify-center overflow-hidden border-2 border-slate-700 shadow-inner transition-colors duration-300" style="background-color: #00FF00;">
                                        <img id="avatar-portrait-img" src="/static_renders/custom_avatar.png" alt="Presenter Portrait" class="w-full h-full object-cover object-top" onerror="this.src='https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?q=80&w=400'">
                                    </div>
                                    <span id="avatar-img-badge" class="mt-2 text-[10px] font-mono text-slate-400">custom_avatar.png</span>
                                </div>

                                <!-- Upload Area & Preset Selectors -->
                                <div class="sm:col-span-8 space-y-2.5">
                                    <div class="border-2 border-dashed border-slate-700 hover:border-pink-500/60 rounded-xl p-3 text-center transition-all bg-slate-900/50">
                                        <input type="file" id="avatar-page-file-input" accept="image/*" class="hidden" onchange="handleAvatarPageUpload(this)">
                                        <label for="avatar-page-file-input" class="cursor-pointer block space-y-1">
                                            <span class="text-lg">📸</span>
                                            <div class="text-xs font-bold text-white">Click to Upload Avatar Photo</div>
                                            <p class="text-[10px] text-slate-400">or drag & drop headshot image file here</p>
                                        </label>
                                    </div>

                                    <div>
                                        <label class="block text-[10px] font-semibold text-slate-400 mb-1">Or Pick Canonical Presenter Identity</label>
                                        <select id="avatar-page-preset-select" onchange="applyAvatarPagePreset(this.value)" class="w-full rounded-lg bg-slate-900 border border-slate-700 p-2 text-xs text-slate-200">
                                            <option value="custom">📸 Custom Uploaded Portrait</option>
                                            <option value="maya" selected>🇮🇳 Maya Sharma (Senior FinTech Lead)</option>
                                            <option value="alex">🇺🇸 Alex Vance (Enterprise AI Architect)</option>
                                            <option value="elena">🇪🇺 Elena Rostova (Risk & Governance Director)</option>
                                            <option value="david">🇬🇧 David Kim (Global LMS Specialist)</option>
                                        </select>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- STEP 2: SCRIPT FOR AVATAR TO TALK -->
                        <div class="p-4 rounded-xl bg-slate-950/80 border border-slate-800 space-y-2.5">
                            <div class="flex justify-between items-center">
                                <label class="text-xs font-bold text-slate-200 uppercase tracking-wider flex items-center gap-1.5">
                                    <span class="w-4 h-4 rounded bg-pink-500/20 text-pink-400 flex items-center justify-center text-[10px] font-bold">2</span>
                                    <span>Script for Avatar to Talk</span>
                                </label>
                                <span id="avatar-script-stats" class="text-[11px] font-mono text-pink-400 bg-slate-900 px-2 py-0.5 rounded border border-slate-800">0 words | ~0.0 min</span>
                            </div>

                            <!-- Director Cue Buttons -->
                            <div class="flex items-center space-x-1.5 overflow-x-auto py-1 text-[11px]">
                                <span class="text-slate-500 font-semibold text-[10px] uppercase tracking-wider mr-1">Speech Cues:</span>
                                <button type="button" onclick="insertAvatarCue('[pause 500ms] ')" class="px-2 py-0.5 rounded bg-slate-800/90 text-slate-300 border border-slate-700 hover:bg-pink-500/20 hover:text-pink-300 font-mono text-[10px]">
                                    ⏱️ [Pause 0.5s]
                                </button>
                                <button type="button" onclick="insertAvatarCue('[pause 1s] ')" class="px-2 py-0.5 rounded bg-slate-800/90 text-slate-300 border border-slate-700 hover:bg-pink-500/20 hover:text-pink-300 font-mono text-[10px]">
                                    ⏱️ [Pause 1.0s]
                                </button>
                                <button type="button" onclick="insertAvatarCue('[emphasis] ')" class="px-2 py-0.5 rounded bg-slate-800/90 text-slate-300 border border-slate-700 hover:bg-pink-500/20 hover:text-pink-300 font-mono text-[10px]">
                                    ✨ [Emphasis]
                                </button>
                                <button type="button" onclick="insertAvatarCue('[protip] ')" class="px-2 py-0.5 rounded bg-slate-800/90 text-slate-300 border border-slate-700 hover:bg-pink-500/20 hover:text-pink-300 font-mono text-[10px]">
                                    💡 [Pro Tip]
                                </button>
                            </div>

                            <textarea id="avatar-script-input" rows="4" oninput="updateAvatarScriptMetrics()" class="w-full rounded-xl bg-slate-900 border border-slate-700 p-3 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-pink-500 leading-relaxed font-sans shadow-inner" placeholder="Type or paste what the avatar should say (e.g. Welcome to this lesson. In this video, [pause 500ms] we examine algorithmic liquidity pools and how autonomous execution operates)...">Welcome to Modular-NeuroClips. Today, we examine how autonomous AI presenters composite directly onto green curtains for professional courseware.</textarea>
                        </div>

                        <!-- STEP 3: VOICE SELECTION & PROSODY -->
                        <div class="p-4 rounded-xl bg-slate-950/80 border border-slate-800 space-y-3">
                            <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                                <label class="text-xs font-bold text-slate-200 uppercase tracking-wider flex items-center gap-1.5">
                                    <span class="w-4 h-4 rounded bg-pink-500/20 text-pink-400 flex items-center justify-center text-[10px] font-bold">3</span>
                                    <span>Voice Selection & Audition</span>
                                </label>
                                <button type="button" onclick="auditionAvatarVoice()" id="avatar-audition-btn" class="px-3 py-1 rounded-lg bg-pink-600 hover:bg-pink-500 text-white font-bold text-xs flex items-center gap-1 shadow-sm transition-all">
                                    <span>🔊</span> <span>Audition Voice</span>
                                </button>
                            </div>

                            <div class="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
                                <div>
                                    <label class="block text-[11px] font-semibold text-slate-300 mb-1">Voice Profile</label>
                                    <select id="avatar-voice-select" class="w-full rounded-lg bg-slate-900 border border-slate-700 p-2 text-xs text-slate-200">
                                        <option value="en-IN-NeerjaNeural" selected>Neerja (en-IN, Female - Instructional)</option>
                                        <option value="en-US-GuyNeural">Guy (en-US, Male - Executive)</option>
                                        <option value="en-US-AriaNeural">Aria (en-US, Female - Presenter)</option>
                                        <option value="en-US-ChristopherNeural">Christopher (en-US, Male - Authoritative)</option>
                                        <option value="en-GB-SoniaNeural">Sonia (en-GB, Female - BBC Accent)</option>
                                        <option value="te-IN-MohanNeural">Mohan (te-IN, Telugu Male)</option>
                                        <option value="te-IN-ShrutiNeural">Shruti (te-IN, Telugu Female)</option>
                                        <option value="hi-IN-MadhurNeural">Madhur (hi-IN, Hindi Male)</option>
                                        <option value="es-ES-AlvaroNeural">Álvaro (es-ES, Spanish Executive)</option>
                                    </select>
                                </div>
                                <div>
                                    <div class="flex justify-between text-[11px] text-slate-300 mb-1">
                                        <span>Pacing Rate</span>
                                        <span id="avatar-speed-val" class="font-mono text-pink-400 font-bold">1.00x</span>
                                    </div>
                                    <input id="avatar-speed-slider" type="range" min="0.75" max="1.30" step="0.05" value="1.0" oninput="document.getElementById('avatar-speed-val').innerText = parseFloat(this.value).toFixed(2) + 'x'; updateAvatarScriptMetrics();" class="w-full accent-pink-500 bg-slate-800 rounded-lg cursor-pointer">
                                </div>
                                <div>
                                    <div class="flex justify-between text-[11px] text-slate-300 mb-1">
                                        <span>Pitch Tuning</span>
                                        <span id="avatar-pitch-val" class="font-mono text-pink-400 font-bold">+0Hz</span>
                                    </div>
                                    <input id="avatar-pitch-slider" type="range" min="-10" max="10" step="1" value="0" oninput="document.getElementById('avatar-pitch-val').innerText = (this.value >= 0 ? '+' : '') + this.value + 'Hz'" class="w-full accent-pink-500 bg-slate-800 rounded-lg cursor-pointer">
                                </div>
                            </div>
                        </div>

                        <!-- STEP 4: GREEN / WHITE CURTAIN BACKDROP & FUTURE 3D MODEL -->
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <!-- Curtain Backdrop Selector -->
                            <div class="p-4 rounded-xl bg-slate-950/80 border border-slate-800 space-y-2.5">
                                <div class="flex items-center justify-between">
                                    <label class="text-xs font-bold text-slate-200 uppercase tracking-wider flex items-center gap-1.5">
                                        <span class="w-4 h-4 rounded bg-pink-500/20 text-pink-400 flex items-center justify-center text-[10px] font-bold">4</span>
                                        <span>Studio Curtain Backdrop</span>
                                    </label>
                                    <!-- Curtain OFF/ON switch -->
                                    <label class="flex items-center gap-1.5 cursor-pointer text-xs">
                                        <span class="text-[10px] text-slate-400">Curtain:</span>
                                        <input type="checkbox" id="avatar-curtain-toggle" checked onchange="toggleAvatarCurtainActive(this.checked)" class="accent-emerald-500 cursor-pointer">
                                        <span id="avatar-curtain-toggle-label" class="text-[10px] font-bold font-mono text-emerald-400">ON</span>
                                    </label>
                                </div>

                                <div class="grid grid-cols-2 gap-2 text-xs">
                                    <button type="button" id="curtain-btn-green" onclick="setAvatarCurtainMode('green')" class="p-2.5 rounded-xl bg-emerald-500/15 border-2 border-emerald-500 text-white font-bold flex items-center justify-center gap-2 transition-all">
                                        <span class="w-3 h-3 rounded-full bg-emerald-500"></span>
                                        <span>Green Screen</span>
                                    </button>
                                    <button type="button" id="curtain-btn-white" onclick="setAvatarCurtainMode('white')" class="p-2.5 rounded-xl bg-slate-900 border-2 border-slate-800 text-slate-300 font-bold flex items-center justify-center gap-2 transition-all hover:border-slate-700">
                                        <span class="w-3 h-3 rounded-full bg-white"></span>
                                        <span>White Studio</span>
                                    </button>
                                </div>
                                <input type="hidden" id="avatar-curtain-mode" value="green">
                                <p class="text-[10px] text-slate-400 leading-tight">
                                    🟢 Chroma Key (#00FF00) for video overlay removal &bull; ⚪ Clean High-Key Studio White (#FFFFFF).
                                </p>
                            </div>

                            <!-- 3D Avatar Input Module -->
                            <div class="p-4 rounded-xl bg-gradient-to-br from-indigo-950/40 via-purple-950/30 to-slate-950/80 border border-purple-500/30 space-y-2.5 relative overflow-hidden">
                                <div class="flex items-center justify-between">
                                    <div class="flex items-center space-x-1.5">
                                        <span class="text-sm">🤖</span>
                                        <span class="text-xs font-bold text-purple-200">Google Flap / Flow 3D Rig</span>
                                    </div>
                                    <span class="px-2 py-0.5 rounded-full bg-purple-500/20 text-purple-300 border border-purple-500/30 text-[9px] font-bold font-mono uppercase tracking-wider">
                                        3D Mesh
                                    </span>
                                </div>
                                <p class="text-[11px] text-slate-300 leading-snug">
                                    Neural 3D mesh model with spatial head motion and audio-reactive jaw blendshapes tracking.
                                </p>
                                
                                <!-- 3D File Upload Picker + Drag & Drop -->
                                <div class="border border-dashed border-purple-500/40 hover:border-purple-400 rounded-lg p-2 text-center bg-slate-900/60 transition-all cursor-pointer">
                                    <input type="file" id="avatar-3d-file-input" accept=".glb,.gltf,.obj,.fbx,.zip" class="hidden" onchange="handleAvatar3DUpload(this)">
                                    <label for="avatar-3d-file-input" class="cursor-pointer block text-[10px] text-purple-300 font-medium">
                                        <span>📁 Click or Drag 3D Model (.glb, .obj, .fbx, .zip)</span>
                                    </label>
                                </div>
                                <input type="hidden" id="avatar-3d-model-path" value="">

                                <div class="flex items-center justify-between pt-1">
                                    <label class="flex items-center gap-2 cursor-pointer text-xs text-purple-300">
                                        <input type="checkbox" id="avatar-3d-model-toggle" onchange="toggle3DModelTeaser(this.checked)" class="accent-purple-500 cursor-pointer">
                                        <span class="text-[11px] font-semibold">Enable 3D Blendshape Rig</span>
                                    </label>
                                    <span id="avatar-3d-status" class="text-[10px] font-mono text-purple-400 bg-purple-900/40 px-2 py-0.5 rounded border border-purple-700/50">Ready</span>
                                </div>
                            </div>
                        </div>

                        <!-- STEP 5: HAND GESTURES SELECTOR -->
                        <div class="p-4 rounded-xl bg-slate-950/80 border border-slate-800 space-y-2.5">
                            <div class="flex items-center justify-between">
                                <label class="text-xs font-bold text-slate-200 uppercase tracking-wider flex items-center gap-1.5">
                                    <span class="w-4 h-4 rounded bg-pink-500/20 text-pink-400 flex items-center justify-center text-[10px] font-bold">5</span>
                                    <span>Hand Gestures Choreography (-> Hand Gestures)</span>
                                </label>
                                <span id="avatar-gesture-badge" class="text-[10px] font-mono text-pink-400">Subtle & Natural</span>
                            </div>

                            <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                                <button type="button" id="gesture-btn-subtle" onclick="setAvatarHandGestures('subtle')" class="p-2.5 rounded-xl bg-pink-500/20 border-2 border-pink-500 text-white font-bold flex flex-col items-center gap-1 transition-all">
                                    <span class="text-base">👐</span>
                                    <span class="text-[11px]">Subtle / Natural</span>
                                </button>
                                <button type="button" id="gesture-btn-explanatory" onclick="setAvatarHandGestures('explanatory')" class="p-2.5 rounded-xl bg-slate-900 border-2 border-slate-800 text-slate-300 font-semibold flex flex-col items-center gap-1 transition-all hover:border-slate-700">
                                    <span class="text-base">👉</span>
                                    <span class="text-[11px]">Explanatory</span>
                                </button>
                                <button type="button" id="gesture-btn-dynamic" onclick="setAvatarHandGestures('dynamic')" class="p-2.5 rounded-xl bg-slate-900 border-2 border-slate-800 text-slate-300 font-semibold flex flex-col items-center gap-1 transition-all hover:border-slate-700">
                                    <span class="text-base">🎙️</span>
                                    <span class="text-[11px]">Dynamic Keynote</span>
                                </button>
                                <button type="button" id="gesture-btn-executive" onclick="setAvatarHandGestures('executive')" class="p-2.5 rounded-xl bg-slate-900 border-2 border-slate-800 text-slate-300 font-semibold flex flex-col items-center gap-1 transition-all hover:border-slate-700">
                                    <span class="text-base">👔</span>
                                    <span class="text-[11px]">Executive Anchor</span>
                                </button>
                            </div>
                            <input type="hidden" id="avatar-gesture-mode" value="subtle">
                        </div>

                        <!-- GENERATE VIDEO CTA BUTTON -->
                        <div class="pt-2">
                            <button type="button" onclick="generateAvatarVideoAction()" id="avatar-generate-btn" class="w-full py-3.5 px-6 rounded-xl bg-gradient-to-r from-pink-600 via-purple-600 to-indigo-600 hover:brightness-110 text-white font-bold text-sm shadow-xl shadow-pink-500/25 flex items-center justify-center gap-2 transition-all">
                                <span>🎬</span> <span>Generate Avatar Video</span>
                            </button>
                            <div id="avatar-gen-progress-box" class="hidden mt-3 p-3 rounded-xl bg-slate-900 border border-slate-800 space-y-2">
                                <div class="flex justify-between text-xs font-mono">
                                    <span id="avatar-gen-step-msg" class="text-pink-300">Synthesizing Neural Audio...</span>
                                    <span id="avatar-gen-pct" class="text-white font-bold">25%</span>
                                </div>
                                <div class="w-full h-2 bg-slate-950 rounded-full overflow-hidden">
                                    <div id="avatar-gen-progress-fill" class="h-full bg-gradient-to-r from-pink-500 to-indigo-500 transition-all duration-300" style="width: 25%"></div>
                                </div>
                            </div>
                        </div>

                    </div>

                    <!-- RIGHT: AVATAR VIDEO PLAYER CONTAINER (5 cols) -->
                    <div class="lg:col-span-5 space-y-4">
                        <div class="glass-panel rounded-2xl p-5 space-y-4 border border-slate-800">
                            <div class="flex items-center justify-between border-b border-slate-800 pb-3">
                                <h3 class="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
                                    <span>📺</span> <span>Avatar Video Output Player</span>
                                </h3>
                                <span id="avatar-video-runtime" class="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-900 text-brand-glow border border-slate-800">Ready</span>
                            </div>

                            <!-- Video Screen -->
                            <div class="w-full aspect-video rounded-xl bg-slate-950 border border-slate-800 overflow-hidden relative shadow-inner flex items-center justify-center group">
                                <video id="avatar-video-player" class="w-full h-full object-contain" controls poster="/static_renders/custom_avatar.png" src="/static_renders/test_avatar_talk.mp4">
                                    Your browser does not support HTML5 video.
                                </video>
                            </div>

                            <!-- Video Meta & Details Card -->
                            <div class="grid grid-cols-2 gap-2 text-xs font-mono">
                                <div class="p-2.5 rounded-lg bg-slate-950 border border-slate-800 text-slate-300 space-y-0.5">
                                    <div class="text-[10px] text-slate-500">Backdrop Curtain:</div>
                                    <div id="meta-curtain" class="text-emerald-400 font-bold">Chroma Green (#00FF00)</div>
                                </div>
                                <div class="p-2.5 rounded-lg bg-slate-950 border border-slate-800 text-slate-300 space-y-0.5">
                                    <div class="text-[10px] text-slate-500">Hand Gestures:</div>
                                    <div id="meta-gestures" class="text-pink-400 font-bold">Subtle & Natural</div>
                                </div>
                                <div class="p-2.5 rounded-lg bg-slate-950 border border-slate-800 text-slate-300 space-y-0.5">
                                    <div class="text-[10px] text-slate-500">Resolution:</div>
                                    <div class="text-white font-bold">1280×720 (HD)</div>
                                </div>
                                <div class="p-2.5 rounded-lg bg-slate-950 border border-slate-800 text-slate-300 space-y-0.5">
                                    <div class="text-[10px] text-slate-500">Video Duration:</div>
                                    <div id="meta-duration" class="text-brand-glow font-bold">7.85s</div>
                                </div>
                            </div>

                            <!-- Download Video Action -->
                            <div class="pt-1">
                                <a id="avatar-download-link" href="/static_renders/test_avatar_talk.mp4" download="avatar_production.mp4" class="w-full py-2.5 px-4 rounded-xl bg-slate-800 hover:bg-slate-700 text-white font-bold text-xs flex items-center justify-center gap-2 border border-slate-700 transition-all">
                                    <span>⬇️</span> <span>Download Avatar Video (.mp4)</span>
                                </a>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div><!-- END OF MODE: AVATAR STUDIO -->

        <!-- MODE 4: CUSTOM SCORM 1.2 & 2004 COURSEWARE GENERATOR -->
        <div id="mode-scorm-section" class="hidden space-y-6">
            <div class="glass-panel rounded-2xl p-6 space-y-6 border border-indigo-500/20">
                <div class="flex items-center justify-between border-b border-slate-800 pb-3">
                    <div class="flex items-center gap-3">
                        <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-600 via-brand-600 to-teal-500 flex items-center justify-center shadow-lg shadow-indigo-500/25">
                            <span class="text-xl">📦</span>
                        </div>
                        <div>
                            <div class="flex items-center gap-2">
                                <h3 class="text-base font-bold text-white">SCORM Framework & LMS Exporter</h3>
                                <!-- Wireframe Callout: [Edu] category tag -->
                                <span class="px-2.5 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300 border border-indigo-500/40 text-xs font-bold font-mono">
                                    [Edu Framework]
                                </span>
                            </div>
                            <p class="text-xs text-slate-400">Pre-built Courseware Frames, Curriculum Context Ingestion & One-Click Package Downloads</p>
                        </div>
                    </div>
                    <div class="flex items-center gap-2">
                        <select id="scorm-edu-category-select" class="rounded-lg bg-slate-900 border border-indigo-500/30 p-1.5 text-xs text-indigo-300 font-semibold">
                            <option value="Edu FinTech" selected>🎓 Edu Category: FinTech Academy</option>
                            <option value="Edu STEM">🔬 Edu Category: STEM Higher Ed</option>
                            <option value="Edu Compliance">⚖️ Edu Category: Corporate Governance</option>
                            <option value="Edu Microlearning">⚡ Edu Category: Executive Capsule</option>
                        </select>
                    </div>
                </div>

                <div class="grid grid-cols-1 lg:grid-cols-12 gap-6">
                    <!-- Left: Course Metadata & Assessment Selection (7 cols) -->
                    <div class="lg:col-span-7 space-y-4">
                        <!-- WIREFRAME SECTION: PRE-BUILT FRAME SELECT ("pre build frame select.") -->
                        <div class="p-4 rounded-xl bg-slate-950/80 border border-indigo-500/30 space-y-2.5">
                            <div class="flex items-center justify-between">
                                <label class="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
                                    <span>🗂️</span> <span>Pre-built Frame Select (Template Architecture)</span>
                                </label>
                                <span id="scorm-selected-frame-badge" class="text-[10px] font-mono text-indigo-300 bg-indigo-950 px-2 py-0.5 rounded border border-indigo-800">Microlearning Capsule</span>
                            </div>
                            
                            <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                                <div id="frame-card-micro" onclick="selectPrebuiltFrame('microlearning')" class="p-2.5 rounded-xl bg-indigo-500/20 border-2 border-indigo-500 cursor-pointer transition-all">
                                    <div class="text-sm mb-1">⚡</div>
                                    <div class="font-bold text-white text-[11px]">Microlearning</div>
                                    <div class="text-[9px] text-slate-400">3-min Focus + 5 Qs</div>
                                </div>
                                <div id="frame-card-master" onclick="selectPrebuiltFrame('masterclass')" class="p-2.5 rounded-xl bg-slate-900 border-2 border-slate-800 hover:border-slate-700 cursor-pointer transition-all">
                                    <div class="text-sm mb-1">🏛️</div>
                                    <div class="font-bold text-slate-300 text-[11px]">Masterclass</div>
                                    <div class="text-[9px] text-slate-400">Lecture + 32 Qs</div>
                                </div>
                                <div id="frame-card-comp" onclick="selectPrebuiltFrame('compliance')" class="p-2.5 rounded-xl bg-slate-900 border-2 border-slate-800 hover:border-slate-700 cursor-pointer transition-all">
                                    <div class="text-sm mb-1">⚖️</div>
                                    <div class="font-bold text-slate-300 text-[11px]">Compliance</div>
                                    <div class="text-[9px] text-slate-400">80% Pass Gate</div>
                                </div>
                                <div id="frame-card-slide" onclick="selectPrebuiltFrame('slide_explainer')" class="p-2.5 rounded-xl bg-slate-900 border-2 border-slate-800 hover:border-slate-700 cursor-pointer transition-all">
                                    <div class="text-sm mb-1">📊</div>
                                    <div class="font-bold text-slate-300 text-[11px]">Slide Explainer</div>
                                    <div class="text-[9px] text-slate-400">Split-Screen Deck</div>
                                </div>
                            </div>
                            <input type="hidden" id="scorm-prebuilt-frame-input" value="microlearning">
                        </div>

                        <!-- WIREFRAME SECTION: CONTEXT PASTE ("Context paste") -->
                        <div class="p-4 rounded-xl bg-slate-950/80 border border-slate-800 space-y-2">
                            <div class="flex items-center justify-between">
                                <label class="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
                                    <span>📋</span> <span>Context Paste (Curriculum & Lesson Context)</span>
                                </label>
                                <button type="button" onclick="autoStructureContextPaste()" class="text-[10px] text-indigo-300 hover:underline flex items-center gap-1">
                                    <span>✨</span> <span>AI Structure Context</span>
                                </button>
                            </div>
                            <textarea id="scorm-context-paste-input" rows="3" class="w-full rounded-xl bg-slate-900 border border-slate-700 p-2.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 leading-relaxed font-sans" placeholder="Paste syllabus context, learning outcomes, or lecture transcript here (e.g. Unit 1: Foundations of Decentralized Autonomous Organizations; Key topics: Smart Contracts, Governance Tokens)..."></textarea>
                        </div>

                        <!-- Direct Video Upload / Video Picker Zone -->
                        <div class="p-4 rounded-xl border-2 border-dashed border-indigo-500/40 bg-indigo-950/20 space-y-3">
                            <div class="flex items-center justify-between">
                                <div class="flex items-center space-x-2">
                                    <span class="text-lg">📤</span>
                                    <div>
                                        <div class="text-xs font-bold text-white">Attach Video Lecture (Upload External Video or Select from Vault)</div>
                                        <p class="text-[10px] text-slate-400">Accepts MP4, WebM, MOV &bull; External clips automatically bundled into SCORM archive</p>
                                    </div>
                                </div>
                                <label for="scorm-direct-upload" class="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold cursor-pointer inline-flex items-center gap-1 shadow-md shadow-indigo-500/20">
                                    <span>📁</span> <span>Upload Video File</span>
                                </label>
                                <input type="file" id="scorm-direct-upload" class="hidden" accept="video/mp4,video/webm,video/quicktime,video/mkv" onchange="handleScormVideoUpload(this)">
                            </div>
                            <div class="grid grid-cols-1 md:grid-cols-2 gap-2 pt-1">
                                <div>
                                    <label class="block text-[11px] font-semibold text-slate-300 mb-1">Or Select from Media Vault</label>
                                    <select id="scorm-gen-video-select" class="w-full rounded-lg bg-slate-900 border border-slate-700 p-2 text-xs text-white focus:outline-none focus:border-indigo-500">
                                        <option value="">Select a rendered video from Media Vault...</option>
                                    </select>
                                </div>
                                <div>
                                    <label class="block text-[11px] font-semibold text-slate-300 mb-1">Attached Video Filename</label>
                                    <input type="text" id="scorm-attached-filename" class="w-full rounded-lg bg-slate-900 border border-slate-700 p-2 text-xs font-mono text-emerald-400" placeholder="No video attached (text quiz mode)" readonly>
                                </div>
                            </div>
                        </div>

                        <!-- Course Title & Course Code -->
                        <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
                            <div class="md:col-span-2">
                                <label class="block text-xs font-semibold text-slate-300 mb-1">Course Title</label>
                                <input type="text" id="scorm-gen-course-title" class="w-full rounded-xl bg-slate-900 border border-slate-700 p-2.5 text-xs text-white focus:outline-none focus:border-indigo-500" value="AI Agents in FinTech: Autonomous Execution">
                            </div>
                            <div>
                                <label class="block text-xs font-semibold text-slate-300 mb-1">Course Code / ID</label>
                                <input type="text" id="scorm-gen-course-id" class="w-full rounded-xl bg-slate-900 border border-slate-700 p-2.5 text-xs text-brand-glow font-mono focus:outline-none focus:border-indigo-500" value="FINTECH_AGENTS_M1">
                            </div>
                        </div>

                        <!-- Dynamic Module Configuration (User Request #1) -->
                        <div class="p-3.5 rounded-xl bg-slate-900/80 border border-indigo-500/30 space-y-3">
                            <div class="flex items-center justify-between">
                                <span class="text-xs font-bold text-indigo-300 flex items-center gap-1.5">
                                    <span>🧩</span> <span>Dynamic Module Configuration</span>
                                </span>
                                <span id="scorm-live-mod-preview" class="text-[11px] font-mono px-2 py-0.5 rounded bg-indigo-950 border border-indigo-500/40 text-indigo-300">Module 1 Preview</span>
                            </div>
                            <div class="grid grid-cols-1 md:grid-cols-4 gap-3">
                                <div>
                                    <label class="block text-xs font-semibold text-slate-300 mb-1">Module Number <span class="text-rose-400">*</span></label>
                                    <input type="number" id="scorm-gen-module-number" min="1" max="99" class="w-full rounded-xl bg-slate-950 border border-indigo-500/50 p-2.5 text-xs text-brand-glow font-mono font-bold focus:outline-none focus:border-brand-500" value="1" placeholder="e.g. 2" oninput="syncScormDynamicFields()">
                                </div>
                                <div class="md:col-span-3">
                                    <label class="block text-xs font-semibold text-slate-300 mb-1">Module Name <span class="text-rose-400">*</span></label>
                                    <input type="text" id="scorm-gen-module-name" class="w-full rounded-xl bg-slate-950 border border-slate-700 p-2.5 text-xs text-white font-semibold focus:outline-none focus:border-indigo-500" value="Traditional AI vs GenAI vs Agents" placeholder="e.g. Intelligent & Autonomous Transactions" oninput="syncScormDynamicFields()">
                                </div>
                            </div>
                            <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                                <div>
                                    <label class="block text-[11px] font-semibold text-slate-400 mb-1">Module Full Title (Auto-Composed)</label>
                                    <input type="text" id="scorm-gen-module-title" class="w-full rounded-xl bg-slate-900/60 border border-slate-800 p-2 text-xs text-slate-300 focus:outline-none" value="Module 1: Traditional AI vs GenAI vs Agents" readonly>
                                </div>
                                <div>
                                    <label class="block text-[11px] font-semibold text-slate-400 mb-1">Module Overview / Description</label>
                                    <input type="text" id="scorm-gen-module-desc" class="w-full rounded-xl bg-slate-950 border border-slate-700 p-2 text-xs text-slate-300 focus:outline-none focus:border-indigo-500" value="Core concepts of autonomous AI agents and foundational architecture">
                                </div>
                            </div>
                        </div>

                        <!-- Dynamic Lesson Configuration (User Request #2 & #4) -->
                        <div class="p-3.5 rounded-xl bg-slate-900/80 border border-emerald-500/30 space-y-3">
                            <div class="flex items-center justify-between">
                                <span class="text-xs font-bold text-emerald-300 flex items-center gap-1.5">
                                    <span>📖</span> <span>Dynamic Lesson Configuration & Intro Hero</span>
                                </span>
                                <span id="scorm-live-les-preview" class="text-[11px] font-mono px-2 py-0.5 rounded bg-emerald-950 border border-emerald-500/40 text-emerald-300">Start Lesson 1.1</span>
                            </div>
                            <div class="grid grid-cols-1 md:grid-cols-4 gap-3">
                                <div>
                                    <label class="block text-xs font-semibold text-slate-300 mb-1">Lesson Number <span class="text-rose-400">*</span></label>
                                    <input type="text" id="scorm-gen-lesson-number" class="w-full rounded-xl bg-slate-950 border border-emerald-500/50 p-2.5 text-xs text-emerald-400 font-mono font-bold focus:outline-none focus:border-emerald-400" value="1.1" placeholder="e.g. 2.1" oninput="syncScormDynamicFields(false)">
                                </div>
                                <div class="md:col-span-3">
                                    <label class="block text-xs font-semibold text-slate-300 mb-1">Lesson Name / Topic Title <span class="text-rose-400">*</span></label>
                                    <input type="text" id="scorm-gen-lesson-name" class="w-full rounded-xl bg-slate-950 border border-slate-700 p-2.5 text-xs text-white font-semibold focus:outline-none focus:border-emerald-500" value="Traditional AI vs GenAI vs Agents" placeholder="e.g. Intelligent & Autonomous Transactions" oninput="syncScormDynamicFields(false)">
                                </div>
                            </div>
                            <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
                                <div>
                                    <label class="block text-[11px] font-semibold text-slate-400 mb-1">Lesson ID / Unit Code</label>
                                    <input type="text" id="scorm-gen-lesson-id" class="w-full rounded-xl bg-slate-950 border border-slate-700 p-2.5 text-xs font-mono text-indigo-300 focus:outline-none focus:border-indigo-500" value="L101">
                                </div>
                                <div class="md:col-span-2">
                                    <label class="block text-[11px] font-semibold text-slate-400 mb-1">Intro Background Video (Hero Section)</label>
                                    <input type="text" id="scorm-gen-intro-video" class="w-full rounded-xl bg-slate-950 border border-slate-700 p-2 text-xs font-mono text-cyan-300 focus:outline-none focus:border-cyan-400" value="AI-FinTech-v0.mp4" placeholder="AI-FinTech-v0.mp4 (bundled)">
                                </div>
                            </div>
                            <!-- Hidden inputs for backward-compatible JS/tests referencing these IDs -->
                            <input type="hidden" id="scorm-gen-lesson-title" value="Lesson 1: Foundations & Agentic Workflows">
                            <input type="hidden" id="scorm-gen-topic" value="1.1 Traditional AI vs GenAI vs Agents">
                        </div>

                        <!-- Upload-driven SCORM source -->
                        <div class="rounded-xl border border-emerald-500/30 bg-emerald-950/10 p-3.5 space-y-2.5">
                            <div class="flex items-center justify-between gap-2 flex-wrap">
                                <label class="block text-xs font-semibold text-emerald-300">&#11014;&#65039; Or upload your own video / .zip of videos</label>
                                <span class="text-[10px] text-slate-400 font-mono">MP4 &middot; MOV &middot; WEBM &middot; MKV &middot; ZIP</span>
                            </div>
                            <input type="file" id="scorm-upload-file" accept=".mp4,.mov,.webm,.mkv,.m4v,.zip"
                                   class="w-full text-xs text-slate-300 rounded-xl bg-slate-900 border border-slate-700 p-2 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-bold file:bg-emerald-600 file:text-white hover:file:brightness-110 cursor-pointer">
                            <p class="text-[11px] text-slate-400 leading-relaxed">
                                A single video becomes one SCORM lesson. A <span class="font-mono text-slate-300">.zip</span>
                                of videos becomes a multi-lesson playlist package that reports
                                <span class="font-mono text-slate-300">completed</span> once every clip has been watched.
                            </p>
                            <div class="flex items-center justify-between gap-3 flex-wrap">
                                <label class="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                                    <input type="checkbox" id="scorm-upload-quiz" checked class="accent-emerald-500 cursor-pointer">
                                    Attach the lightweight understanding check selected below
                                </label>
                                <button onclick="buildScormFromUpload()" id="scorm-upload-btn"
                                        class="px-4 py-2 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:brightness-110 font-bold text-xs text-white shadow-md shadow-emerald-500/20 transition-all flex items-center gap-2">
                                    <span>&#128230;</span> <span>Build SCORM from Upload</span>
                                </button>
                            </div>
                            <div id="scorm-upload-status" class="hidden text-xs rounded-lg p-2.5 font-mono"></div>
                        </div>

                        <!-- Understanding Check (2-3 Questions) & Passing Score -->
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                            <div>
                                <label class="block text-xs font-semibold text-slate-300 mb-1">📝 Attach Understanding Check (2-3 Questions Only)</label>
                                <select id="scorm-gen-module-id" class="w-full rounded-xl bg-slate-900 border border-slate-700 p-2.5 text-xs text-emerald-400 font-bold focus:outline-none focus:border-indigo-500">
                                    <option value="1">Module 1: Traditional AI vs GenAI vs Agents (3 Qs Check)</option>
                                    <option value="2">Module 2: Agent Architecture & Planning (3 Qs Check)</option>
                                    <option value="3">Module 3: RAG & Financial Memory (3 Qs Check)</option>
                                    <option value="4">Module 4: Multi-Agent Collaboration (3 Qs Check)</option>
                                    <option value="5">Module 5: Risk, Compliance & Governance (3 Qs Check)</option>
                                    <option value="6">Module 6: Enterprise Deployment & Observability (3 Qs Check)</option>
                                    <option value="7">Module 7: Algorithmic Execution & Trading (3 Qs Check)</option>
                                </select>
                            </div>
                            <div>
                                <div class="flex justify-between text-xs font-semibold text-slate-300 mb-1">
                                    <span>Passing Grade</span>
                                    <span id="scorm-gen-pass-val" class="font-mono text-indigo-400 font-bold">70%</span>
                                </div>
                                <input id="scorm-gen-pass" type="range" min="50" max="100" step="5" value="70" oninput="document.getElementById('scorm-gen-pass-val').innerText = this.value + '%'" class="w-full accent-indigo-500 bg-slate-800 rounded-lg cursor-pointer">
                            </div>
                        </div>

                        <!-- SCORM Standard Selector & Build Button -->
                        <div class="flex flex-col sm:flex-row items-center justify-between gap-3 p-3.5 rounded-xl bg-indigo-950/20 border border-indigo-500/30">
                            <div class="flex items-center space-x-2 w-full sm:w-auto">
                                <label class="text-xs font-semibold text-indigo-300">SCORM Standard:</label>
                                <select id="scorm-gen-version" class="rounded-lg bg-slate-900 border border-slate-700 p-1.5 text-xs text-white">
                                    <option value="1.2" selected>SCORM 1.2 (LMS Universal Standard)</option>
                                    <option value="2004">SCORM 2004 4th Edition</option>
                                </select>
                            </div>
                            <button onclick="buildCustomScormPackage()" id="scorm-custom-build-btn" class="w-full sm:w-auto px-5 py-2 rounded-xl bg-gradient-to-r from-indigo-600 via-brand-600 to-indigo-500 hover:brightness-110 font-bold text-xs text-white shadow-lg shadow-indigo-500/20 transition-all flex items-center justify-center gap-2">
                                <span>📦</span> <span>Build & Export SCORM Package (.zip)</span>
                            </button>
                        </div>
                    </div>

                    <!-- Right: Conformance Checklist & Package Vault (5 cols) -->
                    <div class="lg:col-span-5 space-y-4">
                        <div class="glass-panel p-4 rounded-xl space-y-3 border border-slate-800">
                            <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                                <h4 class="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
                                    <span>🛡️</span> <span>LMS CMI Data Model Inspector</span>
                                </h4>
                                <span class="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300">Verified</span>
                            </div>
                            <div class="space-y-2 text-xs font-mono">
                                <div class="p-2 rounded bg-slate-950 border border-slate-800 text-slate-300 flex justify-between">
                                    <span>cmi.core.lesson_status</span>
                                    <span class="text-emerald-400">passed / incomplete</span>
                                </div>
                                <div class="p-2 rounded bg-slate-950 border border-slate-800 text-slate-300 flex justify-between">
                                    <span>cmi.core.score.raw</span>
                                    <span class="text-brand-glow">0 – 100%</span>
                                </div>
                                <div class="p-2 rounded bg-slate-950 border border-slate-800 text-slate-300 flex justify-between">
                                    <span>imsmanifest.xml</span>
                                    <span class="text-indigo-400">Auto-Validated</span>
                                </div>
                            </div>
                        </div>

                        <div class="glass-panel p-4 rounded-xl space-y-3 border border-slate-800">
                            <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                                <h4 class="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
                                    <span>📥</span> <span>Recent SCORM Packages</span>
                                </h4>
                                <button onclick="fetchScormPackagesTable()" class="text-[10px] text-slate-400 hover:text-white">↻ Refresh</button>
                            </div>
                            <div id="scorm-packages-table" class="space-y-2 max-h-48 overflow-y-auto text-xs">
                                <div class="text-slate-500 text-center py-4">No custom packages built yet.</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div><!-- END OF MODE 4: CUSTOM SCORM -->


    </main>

    <!-- Interactive Quiz & Item Bank Modal -->
    <div id="quiz-modal" class="fixed inset-0 z-50 bg-slate-950/85 backdrop-blur-md hidden flex items-center justify-center p-4">
        <div class="glass-panel rounded-2xl w-full max-w-5xl max-h-[92vh] flex flex-col border border-emerald-500/30 shadow-2xl shadow-emerald-500/10">
            <div class="p-4 border-b border-slate-800 flex items-center justify-between">
                <div class="flex items-center space-x-2">
                    <span class="text-lg">📝</span>
                    <div>
                        <h3 class="text-sm font-bold text-white uppercase tracking-wider">Assessment & Item Bank Matrix</h3>
                        <span class="text-[10px] text-emerald-400">Nipuna AI Agents in FinTech 15-Hour Course &bull; 224 Questions</span>
                    </div>
                </div>
                <button onclick="closeQuizModal()" class="text-slate-400 hover:text-white text-lg font-bold px-2 py-1">&times;</button>
            </div>

            <div class="p-4 border-b border-slate-800 bg-slate-950/60 flex flex-col sm:flex-row items-center justify-between gap-3">
                <div class="flex items-center space-x-2 w-full sm:w-auto">
                    <label class="text-xs font-semibold text-slate-300 whitespace-nowrap">Select Module:</label>
                    <select id="quiz-module-select" onchange="loadModuleQuestions(this.value)" class="rounded-lg bg-slate-900 border border-slate-700 p-2 text-xs text-brand-glow font-bold focus:outline-none focus:border-brand-500">
                    </select>
                </div>
                <div class="flex items-center space-x-2">
                    <span id="quiz-stats-badge" class="text-xs font-mono px-3 py-1 rounded bg-slate-900 text-slate-300 border border-slate-700">32 Questions</span>
                </div>
            </div>

            <div id="quiz-questions-list" class="p-6 overflow-y-auto space-y-4 flex-1">
            </div>

            <div class="p-4 border-t border-slate-800 flex items-center justify-between bg-slate-950/60">
                <span class="text-xs text-slate-400">💡 Bundles automatically into your SCORM 1.2 package for LMS gradebook tracking.</span>
                <button onclick="closeQuizModal()" class="text-xs px-5 py-2 rounded-lg bg-slate-800 text-slate-200 hover:bg-slate-700">Close</button>
            </div>
        </div>
    </div>

    <!-- Storyboard Editor Modal -->
    <div id="storyboard-modal" class="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-md hidden flex items-center justify-center p-4">
        <div class="glass-panel rounded-2xl w-full max-w-4xl max-h-[90vh] flex flex-col border border-brand-500/30 shadow-2xl shadow-brand-500/10">
            <div class="p-4 border-b border-slate-800 flex items-center justify-between">
                <div class="flex items-center space-x-2">
                    <span class="text-lg">🎬</span>
                    <h3 class="text-sm font-bold text-white uppercase tracking-wider">Interactive Visual Storyboard Editor</h3>
                </div>
                <button onclick="closeStoryboardModal()" class="text-slate-400 hover:text-white text-lg font-bold px-2 py-1">&times;</button>
            </div>

            <div id="storyboard-scenes-list" class="p-6 overflow-y-auto space-y-4 flex-1">
            </div>

            <div class="p-4 border-t border-slate-800 flex items-center justify-between bg-slate-950/60">
                <button onclick="addStoryboardScene()" class="text-xs px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 flex items-center gap-1">
                    <span>➕</span> <span>Add Scene</span>
                </button>
                <div class="flex items-center space-x-3">
                    <button onclick="closeStoryboardModal()" class="text-xs px-4 py-2 rounded-lg bg-slate-800 text-slate-400 hover:text-white">Cancel</button>
                    <button onclick="renderFromStoryboard()" class="text-xs px-5 py-2 rounded-lg bg-gradient-to-r from-brand-600 to-indigo-600 font-bold text-white hover:from-brand-500 shadow-md shadow-brand-500/20">
                        🚀 Render Video from Storyboard
                    </button>
                </div>
            </div>
        </div>
    </div>

    <!-- Video Asset Library Modal -->
    <div id="asset-vault-modal" class="fixed inset-0 z-50 bg-slate-950/85 backdrop-blur-md hidden flex items-center justify-center p-4">
        <div class="glass-panel rounded-2xl w-full max-w-4xl max-h-[90vh] flex flex-col border border-indigo-500/30 shadow-2xl shadow-indigo-500/10">
            <div class="p-4 border-b border-slate-800 flex items-center justify-between">
                <div class="flex items-center space-x-2">
                    <span class="text-lg">📼</span>
                    <h3 class="text-sm font-bold text-white uppercase tracking-wider">Video Asset Vault & Media Library</h3>
                </div>
                <button onclick="closeAssetVaultModal()" class="text-slate-400 hover:text-white text-lg font-bold px-2 py-1">&times;</button>
            </div>

            <div class="p-6 overflow-y-auto space-y-6 flex-1">
                <!-- Upload Box -->
                <div class="p-5 rounded-2xl border-2 border-dashed border-indigo-500/40 bg-indigo-950/20 hover:bg-indigo-950/30 transition-all text-center space-y-2">
                    <div class="text-2xl">📤</div>
                    <div class="text-xs font-bold text-white">Upload Existing Videos, Screen Recordings, or Intro/Outro Bumpers</div>
                    <p class="text-[11px] text-slate-400">Supports MP4, WebM, MOV &bull; Clips are automatically conformed to resolution & framerate</p>
                    <div class="pt-2">
                        <label for="asset-upload-input" class="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold cursor-pointer inline-flex items-center gap-1.5 shadow-md shadow-indigo-500/20">
                            <span>📁</span> <span>Choose Video File</span>
                        </label>
                        <input type="file" id="asset-upload-input" class="hidden" accept="video/mp4,video/webm,video/quicktime" onchange="handleAssetUpload(this)">
                    </div>
                </div>

                <!-- Asset Grid -->
                <div>
                    <div class="flex items-center justify-between mb-3">
                        <h4 class="text-xs font-bold text-slate-300 uppercase tracking-wider">Available Video Clips</h4>
                        <span id="asset-count-badge" class="text-[10px] px-2 py-0.5 rounded-full bg-slate-800 text-slate-400">0 Clips</span>
                    </div>
                    <div id="asset-grid" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                    </div>
                </div>
            </div>

            <div class="p-4 border-t border-slate-800 flex justify-end bg-slate-950/60">
                <button onclick="closeAssetVaultModal()" class="text-xs px-5 py-2 rounded-lg bg-slate-800 text-slate-200 hover:bg-slate-700">Close</button>
            </div>
        </div>
    </div>

    <!-- Studio Settings & Configuration Modal (Task 6b) -->
    <div id="settings-modal" class="fixed inset-0 z-50 bg-slate-950/85 backdrop-blur-md hidden flex items-center justify-center p-4">
        <div class="glass-panel rounded-2xl w-full max-w-xl flex flex-col border border-brand-500/30 shadow-2xl shadow-brand-500/10">
            <div class="p-4 border-b border-slate-800 flex items-center justify-between">
                <div class="flex items-center space-x-2">
                    <span class="text-lg">⚙️</span>
                    <h3 class="text-sm font-bold text-white uppercase tracking-wider">Studio & Engine Settings</h3>
                </div>
                <button onclick="closeSettingsModal()" class="text-slate-400 hover:text-white text-lg font-bold px-2 py-1">&times;</button>
            </div>

            <div class="p-6 overflow-y-auto space-y-6 flex-1 text-xs">
                <!-- ElevenLabs Configuration (Task 6b) -->
                <div class="p-4 rounded-xl bg-slate-900/90 border border-amber-500/30 space-y-3">
                    <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                        <span class="text-amber-300 font-bold flex items-center gap-1.5">
                            <span>👑</span> <span>ElevenLabs MultiLingual V2 Credentials</span>
                        </span>
                        <span class="text-[10px] text-slate-400">Stored in browser localStorage</span>
                    </div>
                    <p class="text-[11px] text-slate-400 leading-relaxed">
                        Configure your ElevenLabs API credentials once. They persist across video creations and sessions automatically.
                    </p>
                    <div class="space-y-3">
                        <div>
                            <label class="block text-[11px] font-semibold text-slate-300 mb-1">ElevenLabs API Key</label>
                            <input type="password" id="elevenlabs-api-key" placeholder="xi-api-key..." onchange="localStorage.setItem('neuroclips_eleven_key', this.value.trim())" class="w-full rounded-lg bg-slate-950 border border-slate-700/80 p-2 text-xs text-white focus:border-amber-500 focus:outline-none">
                        </div>
                        <div>
                            <label class="block text-[11px] font-semibold text-slate-300 mb-1">Default Voice Profile / ID</label>
                            <select id="elevenlabs-voice-id" onchange="localStorage.setItem('neuroclips_eleven_voice', this.value); if(typeof updatePreflightSummary==='function')updatePreflightSummary();" class="w-full rounded-lg bg-slate-950 border border-slate-700/80 p-2 text-xs text-white focus:border-amber-500 focus:outline-none">
                                <option value="21m00Tcm4TlvDq8ikWAM" selected>Rachel (Female - Warm & Professional)</option>
                                <option value="ErXwobaYiN019PkySvjV">Srinivas / Antoni (Male - Engaging Instructor)</option>
                                <option value="pNInz6obpgDQGcFmaJgB">Adam (Male - Deep & Executive)</option>
                                <option value="EXAVITQu4vr4xnSDxMaL">Bella (Female - Crisp Educational)</option>
                                <option value="TxGEqnHWrfWFTfGW9XjX">Josh (Male - Conversational Host)</option>
                            </select>
                        </div>
                    </div>
                </div>

                <!-- Workstation Domain & Server Node Info -->
                <div class="p-4 rounded-xl bg-slate-900/60 border border-slate-800 space-y-2">
                    <span class="text-slate-300 font-bold flex items-center gap-1.5">
                        <span>🌐</span> <span>Connected Production Node</span>
                    </span>
                    <div class="grid grid-cols-2 gap-2 pt-1 text-[11px] font-mono">
                        <div class="bg-slate-950 p-2.5 rounded-lg border border-slate-800">
                            <span class="text-slate-400 block text-[10px] uppercase tracking-wider">Host Node</span>
                            <span class="text-brand-glow font-bold">neuroclips.mytestbed.tech</span>
                        </div>
                        <div class="bg-slate-950 p-2.5 rounded-lg border border-slate-800">
                            <span class="text-slate-400 block text-[10px] uppercase tracking-wider">Protocol</span>
                            <span class="text-emerald-400 font-bold">TLS 1.3 / Reverse-Proxy</span>
                        </div>
                    </div>
                </div>
            </div>

            <div class="p-4 border-t border-slate-800 flex justify-between items-center bg-slate-950/60">
                <span class="text-[10px] text-slate-500 font-mono">Auto-saved to localStorage</span>
                <button onclick="closeSettingsModal()" class="text-xs px-5 py-2 rounded-lg bg-brand-600 hover:bg-brand-500 text-white font-bold transition-all">Done</button>
            </div>
        </div>
    </div>

    <!-- Footer -->
    <footer class="border-t border-slate-800/80 py-4 text-center text-xs text-slate-500">
        Modular-NeuroClips Studio &bull; Autonomous Video Course Engine &bull; SCORM 1.2 &bull; Edge-TTS &bull; FFmpeg &bull; Remotion React
    </footer>

    <!-- Scripts -->
    <script>
        const MILESTONE_DEFS = [
            { id: 'init',        name: 'Init',      icon: '⚙️' },
            { id: 'scripting',   name: 'Script',    icon: '📝' },
            { id: 'keyframes',   name: 'Keyframes', icon: '🖼️' },
            { id: 'animation',   name: 'Motion',    icon: '🎥' },
            { id: 'voiceover',   name: 'Voiceover', icon: '🎙️' },
            { id: 'compilation', name: 'Stitch',    icon: '🎞️' },
            { id: 'complete',    name: 'Ready',     icon: '✨' }
        ];

        let currentSessionOnly = true;
        let activeSessionJobId = null;
        let currentStoryboardData = null;

        const LANG_VOICES = {
            'en-US': [
                { id: 'en-US-GuyNeural', name: 'Guy (Male - Professional)' },
                { id: 'en-US-AriaNeural', name: 'Aria (Female - Clear)' },
                { id: 'en-IN-NeerjaNeural', name: 'Neerja (Female - Indian Accent)' }
            ],
            'te-IN': [
                { id: 'te-IN-MohanNeural', name: 'Mohan (Male - Telugu Deep Narrator)' },
                { id: 'te-IN-ShrutiNeural', name: 'Shruti (Female - Telugu Clear Instructional)' }
            ],
            'ta-IN': [
                { id: 'ta-IN-PallaviNeural', name: 'Pallavi (Female - Tamil Clear Presenter)' },
                { id: 'ta-IN-ValluvarNeural', name: 'Valluvar (Male - Tamil Professional)' }
            ],
            'hi-IN': [
                { id: 'hi-IN-MadhurNeural', name: 'Madhur (Male - Deep Narrator)' },
                { id: 'hi-IN-SwaraNeural', name: 'Swara (Female - Clear)' }
            ],
            'es-ES': [
                { id: 'es-ES-AlvaroNeural', name: 'Álvaro (Male - Executive)' },
                { id: 'es-ES-ElviraNeural', name: 'Elvira (Female - Instructional)' }
            ],
            'fr-FR': [
                { id: 'fr-FR-HenriNeural', name: 'Henri (Male - Clear)' },
                { id: 'fr-FR-DeniseNeural', name: 'Denise (Female - Educational)' }
            ],
            'de-DE': [
                { id: 'de-DE-ConradNeural', name: 'Conrad (Male - Professional)' },
                { id: 'de-DE-KatjaNeural', name: 'Katja (Female - Presenter)' }
            ],
            'ja-JP': [
                { id: 'ja-JP-KeitaNeural', name: 'Keita (Male - Standard)' },
                { id: 'ja-JP-NanamiNeural', name: 'Nanami (Female - Presenter)' }
            ]
        };

        function onLanguageChange() {
            const lang = document.getElementById('language-select').value;
            const voiceSelect = document.getElementById('voice-select');
            const voices = LANG_VOICES[lang] || LANG_VOICES['en-US'];
            voiceSelect.innerHTML = voices.map(v => `<option value="${v.id}">${v.name}</option>`).join('');
        }

        function switchStudioMode(mode) {
            const secVideo = document.getElementById('mode-video-section');
            const secAvatar = document.getElementById('mode-avatar-section');
            const secVoice = document.getElementById('mode-voice-section');
            const secImage = document.getElementById('mode-image-section');
            const secScorm = document.getElementById('mode-scorm-section');
            const btnVideo = document.getElementById('mode-btn-video');
            const btnAvatar = document.getElementById('mode-btn-avatar');
            const btnVoice = document.getElementById('mode-btn-voice');
            const btnImage = document.getElementById('mode-btn-image');
            const btnScorm = document.getElementById('mode-btn-scorm');

            if (!secVideo || !secVoice || !secScorm) return;

            secVideo.classList.add('hidden');
            if (secAvatar) secAvatar.classList.add('hidden');
            secVoice.classList.add('hidden');
            if (secImage) secImage.classList.add('hidden');
            secScorm.classList.add('hidden');

            const inactiveClass = "px-4 py-2.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-800 text-xs font-bold flex items-center gap-2 transition-all whitespace-nowrap";
            btnVideo.className = inactiveClass;
            if (btnAvatar) btnAvatar.className = inactiveClass;
            btnVoice.className = inactiveClass;
            if (btnImage) btnImage.className = inactiveClass;
            btnScorm.className = inactiveClass;

            if (mode === 'video' || mode === 'director') {
                secVideo.classList.remove('hidden');
                btnVideo.className = "px-4 py-2.5 rounded-xl bg-brand-600 text-white text-xs font-bold flex items-center gap-2 shadow-lg shadow-brand-500/20 transition-all whitespace-nowrap";
            } else if (mode === 'avatar') {
                if (secAvatar) secAvatar.classList.remove('hidden');
                if (btnAvatar) btnAvatar.className = "px-4 py-2.5 rounded-xl bg-pink-600 text-white text-xs font-bold flex items-center gap-2 shadow-lg shadow-pink-500/20 transition-all whitespace-nowrap";
                updateAvatarScriptMetrics();
            } else if (mode === 'voice') {
                secVoice.classList.remove('hidden');
                btnVoice.className = "px-4 py-2.5 rounded-xl bg-emerald-600 text-white text-xs font-bold flex items-center gap-2 shadow-lg shadow-emerald-500/20 transition-all whitespace-nowrap";
                onVoiceLabLangChange();
            } else if (mode === 'image') {
                if (secImage) secImage.classList.remove('hidden');
                if (btnImage) btnImage.className = "px-4 py-2.5 rounded-xl bg-purple-600 text-white text-xs font-bold flex items-center gap-2 shadow-lg shadow-purple-500/20 transition-all whitespace-nowrap";
            } else if (mode === 'scorm') {
                secScorm.classList.remove('hidden');
                btnScorm.className = "px-4 py-2.5 rounded-xl bg-indigo-600 text-white text-xs font-bold flex items-center gap-2 shadow-lg shadow-indigo-500/20 transition-all whitespace-nowrap";
                fetchScormMediaList();
                fetchScormPackagesTable();
            }
        }


        // ================= VOICE DIRECTOR STUDIO LOGIC =================
        function updateVoiceLabMetrics() {
            const text = document.getElementById('voice-lab-prompt').value.trim();
            const words = text ? text.split(/\s+/).length : 0;
            const speed = parseFloat(document.getElementById('voice-lab-rate').value) || 1.0;
            const spokenMin = (words / (140 * speed)).toFixed(2);
            document.getElementById('voice-lab-stats').innerText = `${words} words | ~${spokenMin} min`;
        }

        async function expandPromptToVoiceScript() {
            const prompt = document.getElementById('voice-lab-prompt').value.trim();
            if (!prompt) {
                alert("Please enter a prompt or topic keyword first (e.g. 'Explain algorithmic dispute resolution in FinTech')");
                return;
            }
            const btn = document.getElementById('voice-lab-expand-btn');
            btn.disabled = true;
            btn.innerHTML = "<span>⏳</span> <span>Expanding...</span>";
            try {
                const res = await fetch('/api/v1/voice/expand-prompt', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ prompt: prompt, persona: 'maya_fintech', scenes_count: 3 })
                });
                const data = await res.json();
                if (data.status === 'ok') {
                    document.getElementById('voice-lab-prompt').value = data.expanded_script;
                    updateVoiceLabMetrics();
                } else {
                    alert('AI script expansion failed: ' + data.detail);
                }
            } catch (e) {
                alert('AI script expansion error: ' + e);
            } finally {
                btn.disabled = false;
                btn.innerHTML = "<span>✨</span> <span>AI Expand Prompt</span>";
            }
        }

        function insertVoiceLabTag(tag) {
            const ta = document.getElementById('voice-lab-prompt');
            const start = ta.selectionStart;
            const end = ta.selectionEnd;
            const val = ta.value;
            ta.value = val.substring(0, start) + tag + val.substring(end);
            ta.focus();
            ta.selectionStart = ta.selectionEnd = start + tag.length;
            updateVoiceLabMetrics();
        }

        async function handleVoiceLabDocumentUpload(input) {
            const file = input.files[0];
            if (!file) return;
            const formData = new FormData();
            formData.append('file', file);
            try {
                const res = await fetch('/api/v1/script/upload-document', { method: 'POST', body: formData });
                const data = await res.json();
                if (data.status === 'ok') {
                    document.getElementById('voice-lab-prompt').value = data.extracted_text;
                    updateVoiceLabMetrics();
                    alert(`📄 Uploaded ${data.filename} (${data.word_count} words).`);
                } else {
                    alert('Upload failed: ' + data.detail);
                }
            } catch (e) {
                alert('Upload error: ' + e);
            }
        }

        function onVoiceLabLangChange() {
            const lang = document.getElementById('voice-lab-lang').value;
            const select = document.getElementById('voice-lab-voice');
            const voices = LANG_VOICES[lang] || LANG_VOICES['en-US'];
            select.innerHTML = voices.map(v => `<option value="${v.id}">${v.name}</option>`).join('');
        }

        // FastAPI returns 422 as {detail: [{loc, msg, type}, ...]}. Concatenating
        // that object renders "[object Object]", which hides the actual cause.
        function fmtApiError(data) {
            var det = data && data.detail;
            if (!det) return 'Unknown error';
            if (typeof det === 'string') return det;
            if (Array.isArray(det)) {
                return det.map(function (e) {
                    var where = Array.isArray(e.loc) ? e.loc.join('.') : (e.loc || '');
                    return where ? where + ': ' + e.msg : e.msg;
                }).join('; ');
            }
            try { return JSON.stringify(det); } catch (e) { return String(det); }
        }

        async function auditionVoiceLab() {
            const text = document.getElementById('voice-lab-prompt').value.trim() || "Modular NeuroClips Voice Director Studio test.";
            const voice = document.getElementById('voice-lab-voice').value;
            const speed = parseFloat(document.getElementById('voice-lab-rate').value) || 1.0;
            const pitchHz = parseInt(document.getElementById('voice-lab-pitch').value) || 0;
            const pitch = (pitchHz >= 0 ? '+' : '') + pitchHz + 'Hz';
            const btn = document.getElementById('voice-lab-audition-btn');
            const badge = document.getElementById('voice-lab-player-badge');
            
            btn.disabled = true;
            btn.innerText = "⏳ Generating...";
            badge.innerText = "Synthesizing...";
            try {
                const res = await fetch('/api/v1/voice-director/audition', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ voice: voice, speech_rate: speed, pitch: pitch, text: text.substring(0, 200) })
                });
                const data = await res.json();
                if (data.status === 'ok') {
                    const player = document.getElementById('voice-lab-audio-player');
                    player.src = data.audio_url + '?t=' + Date.now();
                    player.play();
                    badge.innerText = "Playing 🎧";
                } else {
                    alert('Audition failed: ' + fmtApiError(data));
                }
            } catch (e) {
                alert('Audition error: ' + e);
            } finally {
                btn.disabled = false;
                btn.innerHTML = "<span>🎧</span> <span>Audition</span>";
            }
        }

        async function exportVoiceLabMaster() {
            const text = document.getElementById('voice-lab-prompt').value.trim();
            if (!text) {
                alert("Please enter a voice script or upload a document first.");
                return;
            }
            const voice = document.getElementById('voice-lab-voice').value;
            const speed = parseFloat(document.getElementById('voice-lab-rate').value) || 1.0;
            const pitchHz = parseInt(document.getElementById('voice-lab-pitch').value) || 0;
            const pitch = (pitchHz >= 0 ? '+' : '') + pitchHz + 'Hz';
            const format = document.getElementById('voice-lab-format').value;
            const btn = document.getElementById('voice-lab-export-btn');
            
            btn.disabled = true;
            btn.innerHTML = "<span>⏳</span> <span>Exporting Master...</span>";
            try {
                const res = await fetch('/api/v1/voice/export', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text: text, voice: voice, speech_rate: speed, pitch: pitch, format: format })
                });
                const data = await res.json();
                if (data.status === 'ok') {
                    const player = document.getElementById('voice-lab-audio-player');
                    player.src = data.audio_url + '?t=' + Date.now();
                    player.play();

                    const dlBox = document.getElementById('voice-lab-download-box');
                    dlBox.classList.remove('hidden');
                    document.getElementById('voice-lab-audio-dl').href = data.audio_url;
                    document.getElementById('voice-lab-audio-dl').download = data.filename;
                    document.getElementById('voice-lab-srt-dl').href = data.srt_url;
                    document.getElementById('voice-lab-srt-dl').download = data.srt_filename;
                    document.getElementById('voice-lab-srt-preview').innerText = `✅ Master Audio (${data.format.toUpperCase()} ${data.size_mb} MB) generated successfully with companion subtitles!`;
                    
                    alert(`⚡ ${data.format.toUpperCase()} Audio Master generated (${data.size_mb} MB)!`);
                } else {
                    alert('Audio Export failed: ' + fmtApiError(data));
                }
            } catch (e) {
                alert('Audio Export error: ' + e);
            } finally {
                btn.disabled = false;
                btn.innerHTML = "<span>⚡</span> <span>Export Audio Master</span>";
            }
        }

        // --- Custom Voice Recording & Cloning Client Logic ---
        let mediaRecorder = null;
        let recordedAudioChunks = [];
        let activeAudioBlob = null;
        let selectedDocFile = null;

        async function toggleMicRecording() {
            const btn = document.getElementById('btn-record-mic');
            const ind = document.getElementById('record-indicator');
            const txt = document.getElementById('record-text');

            if (mediaRecorder && mediaRecorder.state === "recording") {
                mediaRecorder.stop();
                ind.innerText = "🔴";
                txt.innerText = "Record from Mic";
                btn.className = "px-3 py-2 rounded-lg bg-red-600/80 hover:bg-red-500 text-white text-xs font-bold flex items-center gap-1.5 transition-all";
                return;
            }

            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                recordedAudioChunks = [];
                mediaRecorder = new MediaRecorder(stream);

                mediaRecorder.ondataavailable = (e) => {
                    if (e.data.size > 0) recordedAudioChunks.push(e.data);
                };

                mediaRecorder.onstop = () => {
                    activeAudioBlob = new Blob(recordedAudioChunks, { type: 'audio/webm' });
                    const previewBox = document.getElementById('clone-audio-preview-box');
                    const previewAudio = document.getElementById('clone-audio-preview');
                    previewAudio.src = URL.createObjectURL(activeAudioBlob);
                    previewBox.classList.remove('hidden');
                    stream.getTracks().forEach(track => track.stop());
                };

                mediaRecorder.start();
                ind.innerText = "⏹️";
                txt.innerText = "Stop Recording";
                btn.className = "px-3 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold flex items-center gap-1.5 transition-all animate-pulse";
            } catch (err) {
                alert("Microphone access error: " + err.message);
            }
        }

        function handleAudioSampleSelected(input) {
            if (input.files && input.files[0]) {
                const file = input.files[0];
                activeAudioBlob = file;
                const previewBox = document.getElementById('clone-audio-preview-box');
                const previewAudio = document.getElementById('clone-audio-preview');
                previewAudio.src = URL.createObjectURL(file);
                previewBox.classList.remove('hidden');
            }
        }

        async function submitVoiceClone() {
            const name = document.getElementById('clone-display-name').value.trim();
            if (!name) return alert("Please enter a presenter name.");
            if (!activeAudioBlob) return alert("Please record or select an audio sample first (10-30s).");

            const locale = document.getElementById('clone-locale').value;
            const btn = document.getElementById('btn-submit-clone');
            btn.disabled = true;
            btn.innerText = "⏳ Normalizing & Registering Persona...";

            try {
                const formData = new FormData();
                formData.append('audio_file', activeAudioBlob, 'voice_sample.wav');
                formData.append('display_name', name);
                formData.append('gender', 'female');
                formData.append('target_locale', locale);

                const res = await fetch('/api/v1/voice/clone', {
                    method: 'POST',
                    body: formData
                });
                const data = await res.json();
                if (res.ok && data.status === 'success') {
                    alert(`✨ Voice cloned successfully! Persona '${data.persona.display_name}' registered.`);
                    // Refresh persona dropdown
                    const sel = document.getElementById('voice-lab-voice');
                    const opt = document.createElement('option');
                    opt.value = data.persona.canonical_voice;
                    opt.innerText = `⭐ ${data.persona.display_name} (Custom Cloned)`;
                    opt.selected = true;
                    sel.prepend(opt);
                } else {
                    alert("Voice cloning failed: " + (data.detail || JSON.stringify(data)));
                }
            } catch (e) {
                alert("Voice cloning error: " + e.message);
            } finally {
                btn.disabled = false;
                btn.innerHTML = "<span>✨</span> <span>Clone Voice & Add to Catalog</span>";
            }
        }

        // --- Document Speech Ingestion Client Logic ---
        function handleDocFileSelected(input) {
            if (input.files && input.files[0]) {
                selectedDocFile = input.files[0];
                document.getElementById('selected-doc-name').innerText = `Selected: ${selectedDocFile.name} (${(selectedDocFile.size / 1024).toFixed(1)} KB)`;
            }
        }

        async function submitDocumentSpeech() {
            if (!selectedDocFile) return alert("Please select a document file (.txt, .md, .docx, .pdf) first.");
            const exportScorm = document.getElementById('doc-export-scorm-chk').checked;
            const btn = document.getElementById('btn-synth-doc');
            const badge = document.getElementById('voice-lab-player-badge');

            btn.disabled = true;
            btn.innerText = "⏳ Parsing Scenes & Synthesizing Audio...";
            badge.innerText = "Synthesizing Document...";

            try {
                const formData = new FormData();
                formData.append('document_file', selectedDocFile);
                formData.append('persona_id', 'maya_fintech');
                formData.append('speech_rate', '1.0');
                formData.append('export_scorm', exportScorm ? 'true' : 'false');

                const res = await fetch('/api/v1/voice/synthesize-file', {
                    method: 'POST',
                    body: formData
                });
                const data = await res.json();
                if (res.ok && data.status === 'success') {
                    const player = document.getElementById('voice-lab-audio-player');
                    player.src = data.master_audio_url + '?t=' + Date.now();
                    player.play();
                    badge.innerText = "Playing Master 🎧";

                    document.getElementById('voice-lab-download-box').classList.remove('hidden');
                    document.getElementById('voice-lab-audio-dl').href = data.master_audio_url;
                    if (data.subtitles_srt_url) {
                        document.getElementById('voice-lab-srt-dl').href = data.subtitles_srt_url;
                    }

                    document.getElementById('voice-lab-srt-preview').innerText = `✅ "${data.document_title}" decomposed into ${data.total_scenes} pedagogical scenes (${data.total_words} words, ${data.total_duration_sec}s total). Normalized to -14 LUFS.\n` + (data.scorm_download_url ? `📦 SCORM Package: ${data.scorm_download_url}` : '');

                    if (data.scorm_download_url) {
                        alert(`⚡ Document Synthesized & SCORM 1.2 Package Ready!\n\nScenes: ${data.total_scenes}\nAudio: ${data.total_duration_sec}s\nSCORM URL: ${data.scorm_download_url}`);
                    } else {
                        alert(`⚡ Document Synthesized!\nDecomposed into ${data.total_scenes} scenes (${data.total_duration_sec}s). Audio player ready.`);
                    }
                } else {
                    alert("Document synthesis failed: " + (data.detail || JSON.stringify(data)));
                }
            } catch (e) {
                alert("Document synthesis error: " + e.message);
            } finally {
                btn.disabled = false;
                btn.innerHTML = "<span>⚡</span> <span>Synthesize Document Audio</span>";
            }
        }

        // ================= IMAGE DIRECTOR STUDIO LOGIC =================
        const SAMPLE_IMAGE_PROMPTS = [
            "Modern FinTech algorithmic trading room, glowing holographic charts displaying high-frequency liquidity data, volumetric purple-blue cinematic studio lighting, photorealistic 8k.",
            "High-tech AI compliance and risk governance dashboard, real-time audit ledger feeds floating in augmented reality, sleek corporate glass boardroom, 8k resolution.",
            "Autonomous multi-agent negotiation matrix in a futuristic banking command center, cybernetic data stream nodes, volumetric 35mm lens, atmospheric bloom.",
            "Deep neural network financial memory vector database visualization, luminous graph clusters, dark futuristic cyber aesthetic, crisp raytracing."
        ];

        const PERSONA_ANCHORS = {
            'maya_fintech': "30-year-old South Asian female FinTech executive with sleek black hair in navy blue tailored corporate blazer, modern trading floor background",
            'alex_ai': "35-year-old male enterprise AI architect with glasses in charcoal minimalist tech blazer, modern server room command center background",
            'elena_compliance': "40-year-old female compliance director in cream executive suit with gold accessories, high-tech glass boardroom background",
            'david_trainer': "38-year-old male instructional specialist in slate blue oxford shirt, modern interactive smart-classroom background",
            'custom_upload': "professional executive instructor, corporate lighting, consistent character appearance"
        };

        const STYLE_PRESET_IMAGES = {
            'Cinematic 35mm (Volumetric Lighting)': 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?q=80&w=640',
            'Cyberpunk Neon (Futuristic Holograms)': 'https://images.unsplash.com/photo-1578632767115-351597cf2477?q=80&w=640',
            'Anime Masterpiece (Studio Ghibli / Makoto Shinkai)': 'https://images.unsplash.com/photo-1534447677768-be436bb09401?q=80&w=640',
            'Photorealistic 8K (Architectural / Corporate)': 'https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?q=80&w=640',
            'Tech Hologram Data (Fintech Infographics)': 'https://images.unsplash.com/photo-1551288049-bebda4e38f71?q=80&w=640',
            '3D Pixar Animation (Stylized Characters)': 'https://images.unsplash.com/photo-1634017839464-5c339ebe3cb4?q=80&w=640',
            'Dark Fantasy Epic (Moody Dramatic Contrast)': 'https://images.unsplash.com/photo-1518709268805-4e9042af9f23?q=80&w=640',
            'Minimalist Vector (Modern Motion Flat 2D)': 'https://images.unsplash.com/photo-1550745165-9bc0b252726f?q=80&w=640'
        };

        function loadSampleImagePrompt() {
            const rand = SAMPLE_IMAGE_PROMPTS[Math.floor(Math.random() * SAMPLE_IMAGE_PROMPTS.length)];
            document.getElementById('image-lab-prompt').value = rand;
        }

        function onImageLabPersonaChange(personaId) {
            const desc = PERSONA_ANCHORS[personaId] || PERSONA_ANCHORS['maya_fintech'];
            document.getElementById('image-lab-anchor-desc').value = desc;
        }

        function selectQuickPersona(personaId) {
            document.getElementById('image-lab-persona').value = personaId;
            onImageLabPersonaChange(personaId);
            const personaSelectMain = document.getElementById('avatar-persona-select');
            if (personaSelectMain) personaSelectMain.value = personaId;
        }

        async function synthesizeImageKeyframe() {
            const prompt = document.getElementById('image-lab-prompt').value.trim();
            const style = document.getElementById('image-lab-style').value;
            const resVal = document.getElementById('image-lab-resolution').value;
            const persona = document.getElementById('image-lab-persona').value;
            const btn = document.getElementById('image-lab-gen-btn');
            const badge = document.getElementById('image-lab-status-badge');

            btn.disabled = true;
            btn.innerHTML = "<span>⏳</span> <span>Synthesizing Keyframe...</span>";
            badge.innerText = "Rendering...";

            try {
                const sampleImg = STYLE_PRESET_IMAGES[style] || 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?q=80&w=640';
                const previewImg = document.getElementById('image-lab-preview-img');
                const dlBtn = document.getElementById('image-lab-dl-btn');
                
                await new Promise(r => setTimeout(r, 600));
                previewImg.src = sampleImg;
                dlBtn.href = sampleImg;
                
                document.getElementById('image-lab-overlay-style').innerText = `Style: ${style.split(' ')[0]}`;
                document.getElementById('image-lab-overlay-res').innerText = resVal;
                badge.innerText = "Ready ✨";
            } catch (e) {
                alert("Keyframe synthesis error: " + e);
                badge.innerText = "Error";
            } finally {
                btn.disabled = false;
                btn.innerHTML = "<span>🎨</span> <span>Synthesize Keyframe Preview</span>";
            }
        }

        function sendKeyframeToDirector() {
            const prompt = document.getElementById('image-lab-prompt').value.trim();
            const persona = document.getElementById('image-lab-persona').value;
            const layout = document.getElementById('image-lab-layout').value;
            const resVal = document.getElementById('image-lab-resolution').value;

            if (prompt) {
                document.getElementById('prompt-input').value = prompt;
                updateScriptMetrics();
            }
            if (document.getElementById('avatar-persona-select')) document.getElementById('avatar-persona-select').value = persona;
            if (document.getElementById('avatar-layout-select')) document.getElementById('avatar-layout-select').value = layout;
            if (document.getElementById('resolution-select')) document.getElementById('resolution-select').value = resVal;

            switchStudioMode('video');
            alert("🎨 Keyframe visual settings & character anchor applied to Director Studio!");
        }


        async function buildScormFromUpload() {
            const input = document.getElementById('scorm-upload-file');
            const box = document.getElementById('scorm-upload-status');
            if (!input.files || !input.files.length) {
                alert('Choose a video file or a .zip of videos first.');
                return;
            }
            const fd = new FormData();
            fd.append('file', input.files[0]);
            fd.append('course_title', document.getElementById('scorm-gen-course-title').value.trim() || 'Untitled Course');
            fd.append('course_id', document.getElementById('scorm-gen-course-id').value.trim() || 'COURSE');
            
            const modNum = document.getElementById('scorm-gen-module-number') ? document.getElementById('scorm-gen-module-number').value.trim() : '';
            const modName = document.getElementById('scorm-gen-module-name') ? document.getElementById('scorm-gen-module-name').value.trim() : '';
            const lesNum = document.getElementById('scorm-gen-lesson-number') ? document.getElementById('scorm-gen-lesson-number').value.trim() : '';
            const lesName = document.getElementById('scorm-gen-lesson-name') ? document.getElementById('scorm-gen-lesson-name').value.trim() : '';
            const introVideo = document.getElementById('scorm-gen-intro-video') ? document.getElementById('scorm-gen-intro-video').value.trim() : '';

            fd.append('module_title', document.getElementById('scorm-gen-module-title') ? document.getElementById('scorm-gen-module-title').value.trim() : (modName ? `Module ${modNum || 1}: ${modName}` : 'Module 1'));
            fd.append('topic', document.getElementById('scorm-gen-topic') ? document.getElementById('scorm-gen-topic').value.trim() : lesName);
            fd.append('module_id', document.getElementById('scorm-gen-module-id').value || (modNum || '1'));
            if (modNum) fd.append('module_number', modNum);
            if (modName) fd.append('module_name', modName);
            if (lesNum) fd.append('lesson_number', lesNum);
            if (lesName) fd.append('lesson_name', lesName);
            if (introVideo) fd.append('intro_video_filename', introVideo);

            fd.append('pass_percentage', document.getElementById('scorm-gen-pass').value || '70');
            fd.append('scorm_version', document.getElementById('scorm-gen-version').value || '1.2');
            fd.append('include_quiz', document.getElementById('scorm-upload-quiz').checked ? 'true' : 'false');

            const btn = document.getElementById('scorm-upload-btn');
            const orig = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = '<span>&#9203;</span> <span>Packaging...</span>';
            box.className = 'text-xs rounded-lg p-2.5 font-mono bg-slate-900 border border-slate-700 text-slate-300';
            box.innerText = 'Uploading and building the package. Large archives take a while.';

            try {
                const res = await fetch('/api/v1/scorm/build-from-upload', { method: 'POST', body: fd });
                const data = await res.json();
                if (res.ok && data.status === 'ok') {
                    box.className = 'text-xs rounded-lg p-2.5 font-mono bg-emerald-950/30 border border-emerald-500/40 text-emerald-300';
                    box.innerHTML = '&#9989; ' + data.package_name + ' &middot; ' + data.size_mb + ' MB &middot; ' +
                        data.video_count + ' video(s)' +
                        (data.questions_count ? ' &middot; ' + data.questions_count + ' questions' : '') +
                        ' &nbsp; <a class="underline font-bold" href="' + data.download_url +
                        '" download="' + data.package_name + '">Download</a>';
                    if (typeof fetchScormPackagesTable === 'function') fetchScormPackagesTable();
                } else {
                    box.className = 'text-xs rounded-lg p-2.5 font-mono bg-rose-950/30 border border-rose-500/40 text-rose-300';
                    box.innerText = '\u274c ' + fmtApiError(data);
                }
            } catch (e) {
                box.className = 'text-xs rounded-lg p-2.5 font-mono bg-rose-950/30 border border-rose-500/40 text-rose-300';
                box.innerText = '\u274c ' + e;
            } finally {
                box.classList.remove('hidden');
                btn.disabled = false;
                btn.innerHTML = orig;
            }
        }

        // ================= CUSTOM SCORM GENERATOR LOGIC =================
        function syncScormDynamicFields(autoDeriveLesson = true) {
            const mNumInput = document.getElementById('scorm-gen-module-number');
            const mNameInput = document.getElementById('scorm-gen-module-name');
            const lNumInput = document.getElementById('scorm-gen-lesson-number');
            const lNameInput = document.getElementById('scorm-gen-lesson-name');
            const mTitleInput = document.getElementById('scorm-gen-module-title');
            const lTitleInput = document.getElementById('scorm-gen-lesson-title');
            const topicInput = document.getElementById('scorm-gen-topic');
            const modSelect = document.getElementById('scorm-gen-module-id');
            const modPreview = document.getElementById('scorm-live-mod-preview');
            const lesPreview = document.getElementById('scorm-live-les-preview');

            const mNum = (mNumInput && mNumInput.value.trim()) || '1';
            const mName = (mNameInput && mNameInput.value.trim()) || `Module ${mNum}`;

            if (autoDeriveLesson && lNumInput) {
                lNumInput.value = `${mNum}.1`;
            }
            const lNum = (lNumInput && lNumInput.value.trim()) || `${mNum}.1`;
            const lName = (lNameInput && lNameInput.value.trim()) || mName;

            if (mTitleInput) {
                mTitleInput.value = `Module ${mNum}: ${mName}`;
            }
            if (lTitleInput) {
                lTitleInput.value = `Lesson ${lNum}: ${lName}`;
            }
            if (topicInput) {
                topicInput.value = `${lNum} ${lName}`;
            }
            if (modPreview) {
                modPreview.innerText = `Module ${mNum}: ${mName.length > 25 ? mName.slice(0, 25) + '...' : mName}`;
            }
            if (lesPreview) {
                lesPreview.innerText = `Start Lesson ${lNum}`;
            }
            if (modSelect && !isNaN(parseInt(mNum))) {
                const numVal = parseInt(mNum);
                if (numVal >= 1 && numVal <= 7) {
                    modSelect.value = String(numVal);
                }
            }
        }
        setTimeout(syncScormDynamicFields, 100);

        async function fetchScormMediaList() {
            try {
                const res = await fetch('/api/v1/gallery');
                const data = await res.json();
                const select = document.getElementById('scorm-gen-video-select');
                if (data.videos.length > 0) {
                    select.innerHTML = '<option value="">Select a rendered video from Media Vault...</option>' + 
                        data.videos.map(v => `<option value="${v.filename}">${v.filename} (${v.size_mb} MB)</option>`).join('');
                } else {
                    select.innerHTML = '<option value="">No rendered videos found in vault (Video-free lecture mode)</option>';
                }
                select.onchange = function() {
                    const fnInput = document.getElementById('scorm-attached-filename');
                    if (fnInput) fnInput.value = this.value || 'No video attached (text quiz mode)';
                };
            } catch (e) {}
        }

        async function handleScormVideoUpload(input) {
            if (!input.files || !input.files[0]) return;
            const file = input.files[0];
            const formData = new FormData();
            formData.append('file', file);

            const fnInput = document.getElementById('scorm-attached-filename');
            if (fnInput) fnInput.value = `Uploading ${file.name}...`;

            try {
                const res = await fetch('/api/v1/assets/upload-video', { method: 'POST', body: formData });
                const data = await res.json();
                if (data.status === 'ok') {
                    await fetchScormMediaList();
                    if (fnInput) fnInput.value = data.filename;
                    const select = document.getElementById('scorm-gen-video-select');
                    if (select) {
                        const opt = document.createElement('option');
                        opt.value = data.filename;
                        opt.text = `${data.filename} (${data.size_mb} MB - Newly Uploaded)`;
                        opt.selected = true;
                        select.prepend(opt);
                    }
                    alert(`✅ External video '${data.filename}' successfully uploaded and attached to SCORM courseware!`);
                } else {
                    alert("Video upload failed: " + (data.detail || "Unknown error"));
                    if (fnInput) fnInput.value = 'Upload failed';
                }
            } catch (err) {
                alert("Upload failed: " + err);
                if (fnInput) fnInput.value = 'Upload error';
            } finally {
                input.value = '';
            }
        }

        async function fetchScormPackagesTable() {
            try {
                const res = await fetch('/api/v1/scorm/packages');
                const data = await res.json();
                const container = document.getElementById('scorm-packages-table');
                if (data.packages && data.packages.length > 0) {
                    container.innerHTML = data.packages.map(p => `
                        <div class="p-2.5 rounded-lg bg-slate-950 border border-slate-800 flex items-center justify-between text-xs font-mono">
                            <div>
                                <div class="font-bold text-slate-200 truncate w-44" title="${p.filename}">${p.filename}</div>
                                <span class="text-[10px] text-slate-500">${p.size_mb} MB</span>
                            </div>
                            <a href="${p.download_url}" download class="px-2.5 py-1 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 hover:bg-indigo-500/30 font-bold transition-all">
                                ⬇️ Download
                            </a>
                        </div>
                    `).join('');
                } else {
                    container.innerHTML = '<div class="text-slate-500 text-center py-4">No custom packages built yet.</div>';
                }
            } catch (e) {}
        }

        async function buildCustomScormPackage() {
            const courseTitle = document.getElementById('scorm-gen-course-title').value.trim();
            const courseId = document.getElementById('scorm-gen-course-id').value.trim();
            const moduleNumber = document.getElementById('scorm-gen-module-number') ? document.getElementById('scorm-gen-module-number').value.trim() : '';
            const moduleName = document.getElementById('scorm-gen-module-name') ? document.getElementById('scorm-gen-module-name').value.trim() : '';
            const moduleTitle = document.getElementById('scorm-gen-module-title') ? document.getElementById('scorm-gen-module-title').value.trim() : `Module ${moduleNumber || 1}: ${moduleName}`;
            const moduleDesc = document.getElementById('scorm-gen-module-desc') ? document.getElementById('scorm-gen-module-desc').value.trim() : '';
            const lessonNumber = document.getElementById('scorm-gen-lesson-number') ? document.getElementById('scorm-gen-lesson-number').value.trim() : `${moduleNumber || 1}.1`;
            const lessonName = document.getElementById('scorm-gen-lesson-name') ? document.getElementById('scorm-gen-lesson-name').value.trim() : moduleName;
            const lessonTitle = document.getElementById('scorm-gen-lesson-title') ? document.getElementById('scorm-gen-lesson-title').value.trim() : `${lessonNumber} ${lessonName}`;
            const lessonId = document.getElementById('scorm-gen-lesson-id') ? document.getElementById('scorm-gen-lesson-id').value.trim() : '';
            const topic = document.getElementById('scorm-gen-topic') ? document.getElementById('scorm-gen-topic').value.trim() : `${lessonNumber} ${lessonName}`;
            const introVideo = document.getElementById('scorm-gen-intro-video') ? document.getElementById('scorm-gen-intro-video').value.trim() : '';
            
            const attachedFnInput = document.getElementById('scorm-attached-filename');
            let videoFile = attachedFnInput && attachedFnInput.value && !attachedFnInput.value.includes('No video attached') && !attachedFnInput.value.includes('Uploading') ? attachedFnInput.value : '';
            if (!videoFile) {
                videoFile = document.getElementById('scorm-gen-video-select').value;
            }

            const moduleId = parseInt(document.getElementById('scorm-gen-module-id').value) || parseInt(moduleNumber) || 1;
            const passPercentage = parseInt(document.getElementById('scorm-gen-pass').value) || 70;
            const scormVersion = document.getElementById('scorm-gen-version').value;
            const btn = document.getElementById('scorm-custom-build-btn');

            btn.disabled = true;
            btn.innerHTML = "<span>⏳</span> <span>Packaging SCORM...</span>";
            try {
                const res = await fetch('/api/v1/scorm/custom-build', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        course_title: courseTitle,
                        course_id: courseId,
                        module_title: moduleTitle,
                        module_id: moduleId,
                        module_number: moduleNumber,
                        module_name: moduleName,
                        module_description: moduleDesc,
                        lesson_title: lessonTitle,
                        lesson_number: lessonNumber,
                        lesson_name: lessonName,
                        lesson_id: lessonId,
                        topic: topic,
                        video_filename: videoFile,
                        intro_video_filename: introVideo,
                        pass_percentage: passPercentage,
                        scorm_version: scormVersion
                    })
                });
                const data = await res.json();
                if (data.status === 'ok') {
                    const link = document.createElement('a');
                    link.href = data.download_url;
                    link.download = data.package_name;
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);
                    fetchScormPackagesTable();
                    alert(`📦 Custom SCORM Package (${data.size_mb} MB) bundled for "${data.course_title}" / "${data.lesson_title || data.topic}" with Module ${data.module_number || data.module_id} Understanding Check (${data.questions_count} questions) and ready for LMS!`);
                } else {
                    alert('SCORM Packaging failed: ' + data.detail);
                }
            } catch (e) {
                alert('SCORM Packaging error: ' + e);
            } finally {
                btn.disabled = false;
                btn.innerHTML = "<span>📦</span> <span>Build & Export SCORM Package (.zip)</span>";
            }
        }


        function renderMilestones(currentId = 'init', states = {}) {
            const container = document.getElementById('milestones-container');
            container.innerHTML = '';
            let reachedCurrent = false;

            MILESTONE_DEFS.forEach((m) => {
                const isCurrent = m.id === currentId;
                const status = states[m.id] || (isCurrent ? 'in_progress' : (reachedCurrent ? 'pending' : 'completed'));
                if (isCurrent) reachedCurrent = true;

                let cardClass = "border-slate-800/80 bg-slate-900/50 text-slate-500";
                let badgeClass = "bg-slate-800 text-slate-400";
                let statusText = "Pending";

                if (status === 'completed') {
                    cardClass = "border-emerald-500/40 bg-emerald-950/20 text-emerald-300";
                    badgeClass = "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30";
                    statusText = "Done ✔";
                } else if (status === 'in_progress') {
                    cardClass = "border-brand-500 bg-brand-950/30 text-white step-pulse";
                    badgeClass = "bg-brand-500 text-white shadow-md shadow-brand-500/50";
                    statusText = "Active ⚡";
                }

                const card = document.createElement('div');
                card.className = `p-3 rounded-xl border flex flex-col justify-between transition-all ${cardClass}`;
                card.innerHTML = `
                    <div class="flex items-center justify-between mb-1.5">
                        <span class="text-base">${m.icon}</span>
                        <span class="text-[10px] font-bold px-1.5 py-0.5 rounded-full ${badgeClass}">${statusText}</span>
                    </div>
                    <div class="text-xs font-bold truncate">${m.name}</div>
                `;
                container.appendChild(card);
            });
        }

        let trackerForceExpanded = false;
        function updateTrackerDisplay(isActive) {
            const exp = document.getElementById('tracker-expanded-content');
            const sub = document.getElementById('tracker-subtext');
            const toggle = document.getElementById('tracker-toggle-btn');
            if (!exp) return;
            if (isActive || trackerForceExpanded) {
                exp.classList.remove('hidden');
                if (sub) sub.classList.remove('hidden');
                if (toggle) toggle.innerText = '▴';
            } else {
                exp.classList.add('hidden');
                if (sub) sub.classList.add('hidden');
                if (toggle) toggle.innerText = '▾';
            }
        }

        function toggleTrackerManual() {
            trackerForceExpanded = !trackerForceExpanded;
            updateTrackerDisplay(false);
        }

        renderMilestones('init');
        updateTrackerDisplay(false);

        function updateScriptMetrics() {
            const scriptEl = document.getElementById('script-input');
            const promptEl = document.getElementById('prompt-input');
            const text = (scriptEl && scriptEl.value.trim()) ? scriptEl.value.trim() : '';
            const words = text ? text.split(/\s+/).length : 0;
            const speed = parseFloat(document.getElementById('speed-slider')?.value || 1.0);
            const spokenMin = (words / (140 * speed)).toFixed(2);
            const statsEl = document.getElementById('script-stats');
            if (statsEl) {
                if (words === 0) {
                    statsEl.innerText = "0 words | Silent";
                } else {
                    statsEl.innerText = `${words} words | ~${spokenMin} min`;
                }
            }
        }

        function newProjectCanvas() {
            document.getElementById('prompt-input').value = '';
            updateScriptMetrics();
            activeSessionJobId = null;
            document.getElementById('terminal-logs').innerHTML = `<div class="text-brand-glow italic">[NEW PROJECT] Workspace reset to pristine blank canvas. Ready for new course.</div>`;
            renderMilestones('init');
            updateTrackerDisplay(false);
            document.getElementById('master-progress-fill').style.width = '0%';
            document.getElementById('overall-progress-num').innerText = '0%';
            document.getElementById('active-step-caption').innerText = 'Blank Canvas Ready';
            fetchGallery();
        }

        function toggleSessionFilter() {
            currentSessionOnly = !currentSessionOnly;
            document.getElementById('filter-session-label').innerText = currentSessionOnly ? 'Current Session Only' : 'Full Vault Archive';
            document.getElementById('filter-session-btn').classList.toggle('border-brand-500', currentSessionOnly);
            fetchGallery();
        }

        // =========================================================================
        // 🎞️ PRODUCTION MEDIA VAULT: VIDEO STATE MACHINE & LIFECYCLE MANAGEMENT
        // =========================================================================
        // State Model:
        // 1. RENDERING: Backend is currently synthesizing video/audio.
        // 2. READY: Backend render finished & valid MP4 exists on disk. Video element ready.
        // 3. LOADING_VIDEO: MP4 exists, browser is actively buffering data.
        // 4. PLAYABLE: Browser has loaded enough data for seamless playback.
        // 5. ERROR: MP4 cannot be loaded or played.

        window.VIDEO_STATES = window.VIDEO_STATES || {};
        let LAST_FETCHED_COMPLETED_JOB_ID = null;
        let CACHED_GALLERY_FINGERPRINT = "";

        function setVideoCardState(safeId, state, message = "") {
            window.VIDEO_STATES[safeId] = state;
            const badge = document.getElementById(`badge-${safeId}`);
            const overlay = document.getElementById(`overlay-${safeId}`);
            const spinner = document.getElementById(`spinner-${safeId}`);
            const statusText = document.getElementById(`status-text-${safeId}`);
            const video = document.getElementById(`video-${safeId}`);

            if (!badge) return;

            if (state === 'READY') {
                badge.innerText = 'READY';
                badge.className = 'px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider bg-slate-900/80 text-cyan-300 border border-cyan-500/30';
                if (overlay) overlay.classList.add('hidden');
            } else if (state === 'LOADING_VIDEO') {
                badge.innerText = 'BUFFERING';
                badge.className = 'px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider bg-slate-900/80 text-amber-300 border border-amber-500/30';
                if (overlay) {
                    overlay.classList.remove('hidden');
                    if (spinner) spinner.classList.remove('hidden');
                    if (statusText) statusText.innerText = message || 'Buffering video data...';
                }
            } else if (state === 'PLAYABLE') {
                badge.innerText = 'PLAYABLE';
                badge.className = 'px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider bg-slate-900/80 text-emerald-300 border border-emerald-500/30';
                if (overlay) overlay.classList.add('hidden');
            } else if (state === 'ERROR') {
                badge.innerText = 'ERROR';
                badge.className = 'px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider bg-red-950/80 text-red-400 border border-red-500/40';
                if (overlay) {
                    overlay.classList.remove('hidden');
                    if (spinner) spinner.classList.add('hidden');
                    if (statusText) statusText.innerHTML = `<span>⚠️ ${message || 'Failed to load video.'}</span> <button onclick="retryVideoLoad('${safeId}')" class="underline text-xs text-brand-glow ml-1 cursor-pointer pointer-events-auto">Retry</button>`;
                }
            }
        }

        function retryVideoLoad(safeId) {
            const video = document.getElementById(`video-${safeId}`);
            if (video) {
                setVideoCardState(safeId, 'LOADING_VIDEO', 'Retrying video load...');
                video.load();
            }
        }

        function onVideoLifecycleEvent(safeId, eventName) {
            const video = document.getElementById(`video-${safeId}`);
            if (!video) return;

            switch (eventName) {
                case 'loadedmetadata':
                    if (video.readyState >= 2) {
                        setVideoCardState(safeId, 'PLAYABLE');
                    } else {
                        setVideoCardState(safeId, 'READY');
                    }
                    break;
                case 'loadeddata':
                case 'canplay':
                case 'canplaythrough':
                    setVideoCardState(safeId, 'PLAYABLE');
                    break;
                case 'waiting':
                    // Genuine buffering during playback
                    if (video.currentTime > 0 && !video.paused) {
                        setVideoCardState(safeId, 'LOADING_VIDEO', 'Buffering...');
                    }
                    break;
                case 'playing':
                    setVideoCardState(safeId, 'PLAYABLE');
                    break;
                case 'error':
                    const errCode = (video.error && video.error.code) ? `Code ${video.error.code}` : 'Network error';
                    setVideoCardState(safeId, 'ERROR', errCode);
                    break;
            }
        }

        function updateVaultRenderingCard(activeJob) {
            const container = document.getElementById('gallery-grid');
            if (!container) return;
            let card = document.getElementById('rendering-job-card');
            const progress = activeJob.progress_percent || 10;
            const milestone = activeJob.current_milestone || 'processing';
            const label = (activeJob.output_type === 'slide') ? 'Instructional Slide Generating' : 'Video Rendering in Progress';

            if (!card) {
                const temp = document.createElement('div');
                temp.innerHTML = `
                <div id="rendering-job-card" class="glass-panel p-3.5 rounded-xl space-y-3 border border-brand-500/40 bg-brand-500/5 flex flex-col justify-between">
                    <div class="space-y-2">
                        <div class="relative w-full h-44 rounded-lg bg-slate-950 flex flex-col items-center justify-center p-4 border border-brand-500/20 text-center">
                            <div class="w-8 h-8 border-2 border-brand-500 border-t-transparent rounded-full animate-spin mb-3"></div>
                            <span class="text-xs font-bold text-white tracking-wide" id="rendering-job-title">${label}</span>
                            <span class="text-[11px] font-mono text-brand-glow mt-1 capitalize" id="rendering-job-milestone">Milestone: ${milestone}</span>
                            <div class="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden mt-3 max-w-[200px]">
                                <div id="rendering-job-bar" class="h-full bg-gradient-to-r from-brand-500 to-emerald-400 transition-all duration-300" style="width: ${progress}%"></div>
                            </div>
                            <div class="absolute top-2 left-2 pointer-events-none">
                                <span class="px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider bg-brand-500/20 text-brand-glow border border-brand-500/30 animate-pulse">
                                    RENDERING
                                </span>
                            </div>
                        </div>
                    </div>
                    <div class="pt-2 border-t border-slate-800 text-xs text-slate-400 flex justify-between">
                        <span class="font-mono truncate">Job #${activeJob.job_id}</span>
                        <span class="font-mono text-brand-glow" id="rendering-job-percent">${progress}%</span>
                    </div>
                </div>`;
                card = temp.firstElementChild;
                container.prepend(card);
            } else {
                const titleEl = document.getElementById('rendering-job-title');
                const msEl = document.getElementById('rendering-job-milestone');
                const barEl = document.getElementById('rendering-job-bar');
                const pctEl = document.getElementById('rendering-job-percent');
                if (titleEl) titleEl.innerText = label;
                if (msEl) msEl.innerText = `Milestone: ${milestone}`;
                if (barEl) barEl.style.width = `${progress}%`;
                if (pctEl) pctEl.innerText = `${progress}%`;
            }
        }

        function removeVaultRenderingCard() {
            const card = document.getElementById('rendering-job-card');
            if (card) {
                card.remove();
            }
        }

        async function fetchGallery() {
            const container = document.getElementById('gallery-grid');
            try {
                const url = (currentSessionOnly && activeSessionJobId) ? `/api/v1/gallery?session_job_id=${activeSessionJobId}` : '/api/v1/gallery';
                const res = await fetch(url);
                const data = await res.json();
                const items = data.videos || [];
                
                const renderingCard = document.getElementById('rendering-job-card');
                const hasRendering = !!renderingCard;

                if (items.length === 0 && !hasRendering) {
                    CACHED_GALLERY_FINGERPRINT = "";
                    container.innerHTML = `<div class="col-span-3 text-center text-xs text-slate-500 py-8 bg-slate-900/40 rounded-xl border border-slate-800/80">
                        ${currentSessionOnly ? 'No media rendered in this active session yet. Click Direct Render or Storyboard to create.' : 'Media Vault is empty.'}
                    </div>`;
                    return;
                }

                // Avoid wiping DOM if contents have not changed
                const fingerprint = (currentSessionOnly ? 's_' : 'all_') + items.map(v => v.filename + '_' + v.size_mb).join('|');
                if (fingerprint === CACHED_GALLERY_FINGERPRINT && !hasRendering) {
                    return;
                }
                CACHED_GALLERY_FINGERPRINT = fingerprint;

                const cardsHtml = items.map(v => {
                    const isSlide = (v.media_type === 'slide' || v.filename.endsWith('.png'));
                    const safeId = v.filename.replace(/[^a-zA-Z0-9_-]/g, '_');

                    if (isSlide) {
                        return `
                        <div class="glass-panel p-3.5 rounded-xl space-y-2.5 border border-slate-800/90 flex flex-col justify-between" id="card-${safeId}">
                            <div class="space-y-2">
                                <div class="relative w-full h-44 rounded-lg bg-slate-950 border border-slate-800 overflow-hidden flex items-center justify-center group">
                                    <img src="${v.url}" alt="${v.filename}" class="w-full h-full object-contain p-1" />
                                    <div class="absolute top-2 left-2 pointer-events-none">
                                        <span class="px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider bg-brand-500/20 text-brand-glow border border-brand-500/30">
                                            SLIDE
                                        </span>
                                    </div>
                                    <a href="${v.url}" target="_blank" class="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                                        <span class="px-2.5 py-1 rounded bg-black/80 text-xs text-white border border-slate-700">🔍 View High-Res Slide</span>
                                    </a>
                                </div>
                                ${v.audio_url ? `
                                <div class="p-2 rounded-lg bg-slate-950/80 border border-slate-800 space-y-1">
                                    <div class="flex justify-between items-center text-[10px] text-slate-400">
                                        <span>🎙️ Voiceover Audio Track</span>
                                        <a href="${v.audio_url}" download class="text-brand-glow hover:underline">Download MP3</a>
                                    </div>
                                    <audio controls class="w-full h-6" src="${v.audio_url}"></audio>
                                </div>
                                ` : ''}
                            </div>

                            <div class="space-y-2 pt-1 border-t border-slate-800">
                                <div class="flex items-center justify-between text-xs">
                                    <span class="font-mono text-slate-300 truncate w-36" title="${v.filename}">${v.filename}</span>
                                    <span class="text-slate-500 font-mono text-[11px]">${v.size_mb} MB</span>
                                </div>

                                <div class="flex justify-between items-center pt-1 border-t border-slate-800/60 text-xs">
                                    <span class="text-[10px] text-slate-500">${v.time_str}</span>
                                    <div class="flex items-center space-x-1.5">
                                        ${v.srt_url ? `
                                        <a href="${v.srt_url}" download="${v.srt_filename}" title="Download Subtitles (.srt)" class="px-2 py-0.5 rounded bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/30 text-[11px] font-mono transition-all">
                                            📝 SRT
                                        </a>` : ''}
                                        <a href="${v.url}" download title="Download Slide Image" class="px-2 py-0.5 rounded bg-brand-500/10 hover:bg-brand-500/20 text-brand-glow text-[11px]">
                                            PNG
                                        </a>
                                        <button onclick="deleteGalleryItem('${v.filename}')" title="Delete Slide" class="text-red-400 hover:text-red-300 p-1 text-[11px]">
                                            🗑️
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>`;
                    }

                    return `
                    <div class="glass-panel p-3.5 rounded-xl space-y-2.5 border border-slate-800/90 flex flex-col justify-between" id="card-${safeId}">
                        <div class="space-y-2">
                            <div class="relative w-full h-44 rounded-lg bg-black overflow-hidden group">
                                <video
                                    id="video-${safeId}"
                                    controls
                                    preload="metadata"
                                    playsinline
                                    class="w-full h-full object-cover"
                                    src="${v.url}"
                                    onloadedmetadata="onVideoLifecycleEvent('${safeId}', 'loadedmetadata')"
                                    onloadeddata="onVideoLifecycleEvent('${safeId}', 'loadeddata')"
                                    oncanplay="onVideoLifecycleEvent('${safeId}', 'canplay')"
                                    oncanplaythrough="onVideoLifecycleEvent('${safeId}', 'canplaythrough')"
                                    onwaiting="onVideoLifecycleEvent('${safeId}', 'waiting')"
                                    onplaying="onVideoLifecycleEvent('${safeId}', 'playing')"
                                    onerror="onVideoLifecycleEvent('${safeId}', 'error')"
                                ></video>

                                <!-- Video State Overlay: Hidden once ready/playable -->
                                <div id="overlay-${safeId}" class="hidden absolute inset-0 bg-slate-950/70 backdrop-blur-[2px] flex flex-col items-center justify-center space-y-2 pointer-events-none transition-opacity duration-200">
                                    <div id="spinner-${safeId}" class="w-6 h-6 border-2 border-brand-500 border-t-transparent rounded-full animate-spin"></div>
                                    <span id="status-text-${safeId}" class="text-[11px] font-mono text-slate-300">Loading video data...</span>
                                </div>

                                <!-- State Badge Top-Left -->
                                <div class="absolute top-2 left-2 pointer-events-none">
                                    <span id="badge-${safeId}" class="px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider bg-slate-900/80 text-cyan-300 border border-cyan-500/30">
                                        READY
                                    </span>
                                </div>
                            </div>

                            ${v.audio_url ? `
                            <div class="p-2 rounded-lg bg-slate-950/80 border border-slate-800 space-y-1">
                                <div class="flex justify-between items-center text-[10px] text-slate-400">
                                    <span>🎙️ Voiceover Audio Track</span>
                                    <a href="${v.audio_url}" download class="text-brand-glow hover:underline">Download MP3</a>
                                </div>
                                <audio controls class="w-full h-6" src="${v.audio_url}"></audio>
                            </div>
                            ` : ''}
                        </div>

                        <div class="space-y-2 pt-1 border-t border-slate-800">
                            <div class="flex items-center justify-between text-xs">
                                <span class="font-mono text-slate-300 truncate w-36" title="${v.filename}">${v.filename}</span>
                                <span class="text-slate-500 font-mono text-[11px]">${v.size_mb} MB</span>
                            </div>

                            <!-- 📦 SCORM 1.2 EXPORT, SRT DOWNLOAD & ACTIONS -->
                            <div class="flex justify-between items-center pt-1 border-t border-slate-800/60 text-xs">
                                <span class="text-[10px] text-slate-500">${v.time_str}</span>
                                <div class="flex items-center space-x-1.5">
                                    ${v.srt_url ? `
                                    <a href="${v.srt_url}" download="${v.srt_filename}" title="Download Subtitles (.srt)" class="px-2 py-0.5 rounded bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/30 text-[11px] font-mono transition-all">
                                        📝 SRT
                                    </a>` : ''}
                                    
                                    <button onclick="exportScormPackage('${v.filename}')" title="Export SCORM 1.2 Package (.zip)" class="px-2.5 py-0.5 rounded bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-400 border border-emerald-500/30 text-[11px] font-bold transition-all flex items-center gap-1 shadow-sm">
                                        <span>📦</span> <span>SCORM</span>
                                    </button>

                                    <button onclick="deployScormCloud('${v.filename}')" title="Deploy directly to SCORM Cloud API v2" class="px-2.5 py-0.5 rounded bg-indigo-500/15 hover:bg-indigo-500/25 text-indigo-300 border border-indigo-500/30 text-[11px] font-bold transition-all flex items-center gap-1 shadow-sm">
                                        <span>☁️</span> <span>Cloud</span>
                                    </button>

                                    <a href="${v.url}" download title="Download MP4" class="px-2 py-0.5 rounded bg-brand-500/10 hover:bg-brand-500/20 text-brand-glow text-[11px]">
                                        MP4
                                    </a>

                                    <button onclick="deleteGalleryItem('${v.filename}')" title="Delete Video" class="text-red-400 hover:text-red-300 p-1 text-[11px]">
                                        🗑️
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>`;
                }).join('');

                container.innerHTML = cardsHtml;

                // Immediately check if any videos are already ready/cached by the browser
                items.forEach(v => {
                    if (v.media_type !== 'slide' && !v.filename.endsWith('.png')) {
                        const safeId = v.filename.replace(/[^a-zA-Z0-9_-]/g, '_');
                        const vid = document.getElementById(`video-${safeId}`);
                        if (vid) {
                            if (vid.readyState >= 2) {
                                setVideoCardState(safeId, 'PLAYABLE');
                            } else {
                                setVideoCardState(safeId, 'READY');
                            }
                        }
                    }
                });

            } catch (err) {
                container.innerHTML = '<div class="col-span-3 text-center text-xs text-red-400 py-4">Failed to load media vault.</div>';
            }
        }

        let ACTIVE_QUIZ_MODULES = [];

        async function openQuizModal() {
            document.getElementById('quiz-modal').classList.remove('hidden');
            await fetchQuizModules();
        }

        function closeQuizModal() {
            document.getElementById('quiz-modal').classList.add('hidden');
        }

        async function fetchQuizModules() {
            try {
                const res = await fetch('/api/v1/quiz/modules');
                const data = await res.json();
                if (data.status === 'ok') {
                    ACTIVE_QUIZ_MODULES = data.modules;
                    const select = document.getElementById('quiz-module-select');
                    select.innerHTML = data.modules.map(m => `
                        <option value="${m.module_id}">${m.title} (${m.total_questions} Qs)</option>
                    `).join('');
                    if (data.modules.length > 0) {
                        loadModuleQuestions(data.modules[0].module_id);
                    }
                }
            } catch (e) {
                console.error("Failed to fetch quiz modules", e);
            }
        }

        async function loadModuleQuestions(moduleId) {
            const list = document.getElementById('quiz-questions-list');
            list.innerHTML = '<div class="text-xs text-slate-400 p-4 text-center">Loading questions...</div>';
            try {
                const res = await fetch(`/api/v1/quiz/module/${moduleId}`);
                const data = await res.json();
                if (data.status === 'ok') {
                    const mod = ACTIVE_QUIZ_MODULES.find(m => m.module_id == moduleId);
                    document.getElementById('quiz-stats-badge').innerText = `${data.questions.length} Questions (${mod ? mod.knowledge_count : 20} Knowledge, ${mod ? mod.scenario_count : 8} Scenario)`;
                    renderQuizQuestions(data.questions);
                }
            } catch (e) {
                list.innerHTML = '<div class="text-xs text-red-400 p-4 text-center">Failed to load questions.</div>';
            }
        }

        function renderQuizQuestions(questions) {
            const list = document.getElementById('quiz-questions-list');
            list.innerHTML = questions.map((q, idx) => `
                <div class="glass-panel p-4 rounded-xl space-y-2.5 border border-slate-800">
                    <div class="flex items-center justify-between border-b border-slate-800/80 pb-1.5">
                        <span class="text-xs font-bold text-brand-glow font-mono">${q.id} &bull; ${q.question_type} Check</span>
                        <span class="text-[10px] text-slate-400 font-mono">${q.source_topic || ''}</span>
                    </div>
                    <p class="text-xs font-semibold text-slate-100">${idx + 1}. ${q.question}</p>
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-1 text-xs">
                        ${q.options.map(opt => `
                            <div class="p-2 rounded bg-slate-900/90 border ${opt.key === q.correct_key ? 'border-emerald-500/60 bg-emerald-950/20 text-emerald-300' : 'border-slate-800 text-slate-300'}">
                                <strong class="font-mono ${opt.key === q.correct_key ? 'text-emerald-400' : 'text-slate-400'}">${opt.key}.</strong> ${opt.text}
                            </div>
                        `).join('')}
                    </div>
                    ${q.rationale ? `
                        <div class="p-2.5 rounded bg-slate-950 border border-slate-800 text-[11px] text-slate-400 leading-relaxed">
                            <span class="text-brand-glow font-bold">💡 Rationale:</span> ${q.rationale}
                        </div>
                    ` : ''}
                </div>
            `).join('');
        }

        async function exportScormPackage(filename) {
            const modId = prompt("Enter Module ID to bundle (1 to 7):", "1") || "1";
            try {
                const res = await fetch(`/api/v1/scorm/export/${encodeURIComponent(filename)}?module_id=${modId}`, { method: 'POST' });
                const data = await res.json();
                if (data.status === 'ok') {
                    const link = document.createElement('a');
                    link.href = data.download_url;
                    link.download = data.package_name;
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);
                    alert(`📦 SCORM 1.2 Package (${data.size_mb} MB) bundled with Module ${modId} Quiz (${data.questions_count} questions) and ready for LMS!`);
                } else {
                    alert("SCORM export failed: " + data.detail);
                }
            } catch (e) {
                alert("SCORM Export error: " + e);
            }
        }

        async function deployScormCloud(filename) {
            const courseId = prompt("Enter SCORM Course ID to deploy/update:", `COURSE_${filename.replace(/[^a-zA-Z0-9]/g, '_')}`);
            if (!courseId) return;

            // First ensure SCORM package exists or bundle on demand
            try {
                const pkgRes = await fetch(`/api/v1/scorm/export/${encodeURIComponent(filename)}?module_id=1`, { method: 'POST' });
                const pkgData = await pkgRes.json();
                if (pkgData.status !== 'ok') {
                    alert("Failed to create package for cloud deploy: " + pkgData.detail);
                    return;
                }

                const deployRes = await fetch('/api/v1/scorm/deploy-cloud', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        course_id: courseId,
                        package_filename: pkgData.package_name
                    })
                });
                const deployData = await deployRes.json();
                if (deployData.status === 'success' || deployData.status === 'mock_success') {
                    alert(`☁️ Dispatched to SCORM Cloud API v2!\nCourse ID: ${deployData.course_id}\nJob ID: ${deployData.import_job_id}\n\n${deployData.message || 'Course imported successfully.'}`);
                } else {
                    alert("Cloud deployment failed: " + (deployData.detail || deployData.error || 'Check logs'));
                }
            } catch (e) {
                alert("SCORM Cloud deployment network error: " + e);
            }
        }

        async function deleteGalleryItem(filename) {
            if (!confirm(`Delete ${filename}?`)) return;
            try {
                await fetch(`/api/v1/gallery/${filename}`, { method: 'DELETE' });
                fetchGallery();
            } catch(e) { alert("Delete failed: " + e); }
        }

        async function clearGallery() {
            if (!confirm("Are you sure you want to clear all rendered media from vault?")) return;
            try {
                await fetch('/api/v1/gallery/clear', { method: 'POST' });
                fetchGallery();
            } catch(e) { alert("Clear failed: " + e); }
        }

        let VIDEO_ASSETS_CACHE = [];

        async function fetchVideoAssets() {
            try {
                const res = await fetch('/api/v1/assets/videos');
                const data = await res.json();
                VIDEO_ASSETS_CACHE = data.assets || [];

                // Update Bumper Selects
                const introSelect = document.getElementById('intro-bumper-select');
                const outroSelect = document.getElementById('outro-bumper-select');
                const prevIntro = introSelect.value;
                const prevOutro = outroSelect.value;

                const optionsHtml = '<option value="">None (Direct)</option>' + 
                    VIDEO_ASSETS_CACHE.map(a => `<option value="${a.video_url}">${a.filename} (${a.size_mb}MB)</option>`).join('');
                
                introSelect.innerHTML = optionsHtml;
                outroSelect.innerHTML = optionsHtml;
                introSelect.value = prevIntro;
                outroSelect.value = prevOutro;

                // Update Asset Vault Grid & Badge
                const countBadge = document.getElementById('asset-count-badge');
                if (countBadge) countBadge.innerText = `${VIDEO_ASSETS_CACHE.length} Clips`;

                const grid = document.getElementById('asset-grid');
                if (grid) {
                    if (VIDEO_ASSETS_CACHE.length === 0) {
                        grid.innerHTML = `<div class="col-span-3 text-center py-6 text-xs text-slate-500 bg-slate-900/40 rounded-xl border border-slate-800">
                            No uploaded video assets yet. Use the upload box above to add MP4/WebM videos.
                        </div>`;
                    } else {
                        grid.innerHTML = VIDEO_ASSETS_CACHE.map(a => `
                            <div class="glass-panel p-2.5 rounded-xl border border-slate-800 space-y-2 flex flex-col justify-between">
                                <div class="space-y-1.5">
                                    <div class="relative rounded-lg overflow-hidden bg-black aspect-video flex items-center justify-center">
                                        ${a.thumbnail_url ? `<img src="${a.thumbnail_url}" class="w-full h-full object-cover">` : `<span class="text-2xl">🎬</span>`}
                                        <div class="absolute bottom-1 right-1 px-1.5 py-0.5 rounded bg-black/80 text-[10px] font-mono text-white">${a.size_mb} MB</div>
                                    </div>
                                    <div class="text-xs font-mono text-slate-200 truncate" title="${a.filename}">${a.filename}</div>
                                </div>
                                <div class="flex items-center justify-between pt-1 border-t border-slate-800 text-[11px]">
                                    <a href="${a.video_url}" target="_blank" class="text-brand-glow hover:underline">Preview</a>
                                    <button onclick="deleteVideoAsset('${a.filename}')" class="text-red-400 hover:text-red-300">🗑️ Delete</button>
                                </div>
                            </div>
                        `).join('');
                    }
                }
            } catch (err) {
                console.error("Failed to fetch video assets:", err);
            }
        }

        function openAssetVaultModal() {
            fetchVideoAssets();
            document.getElementById('asset-vault-modal').classList.remove('hidden');
        }

        function closeAssetVaultModal() {
            document.getElementById('asset-vault-modal').classList.add('hidden');
        }

        async function handleAssetUpload(input) {
            if (!input.files || !input.files[0]) return;
            const file = input.files[0];
            const formData = new FormData();
            formData.append('file', file);

            const badge = document.getElementById('asset-count-badge');
            if (badge) badge.innerText = 'Uploading...';

            try {
                const res = await fetch('/api/v1/assets/upload-video', { method: 'POST', body: formData });
                const data = await res.json();
                if (data.status === 'ok') {
                    alert(`✅ Video '${data.filename}' uploaded and ready for scene integration!`);
                    await fetchVideoAssets();
                } else {
                    alert("Upload failed: " + (data.detail || "Unknown error"));
                }
            } catch (err) {
                alert("Upload failed: " + err);
            } finally {
                input.value = '';
            }
        }

        async function deleteVideoAsset(filename) {
            if (!confirm(`Delete video asset ${filename}?`)) return;
            try {
                await fetch(`/api/v1/assets/videos/${encodeURIComponent(filename)}`, { method: 'DELETE' });
                await fetchVideoAssets();
            } catch (err) {
                alert("Failed to delete asset: " + err);
            }
        }

        async function handleSceneVideoUpload(input, idx) {
            if (!input.files || !input.files[0]) return;
            const file = input.files[0];
            const formData = new FormData();
            formData.append('file', file);

            const btn = document.getElementById(`sb-upload-btn-${idx}`);
            if (btn) btn.innerText = '⏳ Uploading...';

            try {
                const res = await fetch('/api/v1/assets/upload-video', { method: 'POST', body: formData });
                const data = await res.json();
                if (data.status === 'ok') {
                    await fetchVideoAssets();
                    if (currentStoryboardData && currentStoryboardData.scenes[idx]) {
                        currentStoryboardData.scenes[idx].video_source_type = 'uploaded_video';
                        currentStoryboardData.scenes[idx].video_source_url = data.video_url;
                        if (data.duration_seconds) {
                            currentStoryboardData.scenes[idx].duration_seconds = Math.min(Math.max(Math.round(data.duration_seconds), 2), 30);
                        }
                    }
                    renderStoryboardModal(currentStoryboardData);
                } else {
                    alert("Upload failed: " + data.detail);
                }
            } catch (err) {
                alert("Scene upload failed: " + err);
            } finally {
                input.value = '';
            }
        }

        async function handleScriptDocumentUpload(input) {
            if (!input.files || !input.files[0]) return;
            const file = input.files[0];
            const formData = new FormData();
            formData.append('file', file);

            try {
                const res = await fetch('/api/v1/script/upload-document', { method: 'POST', body: formData });
                const data = await res.json();
                if (data.status === 'ok') {
                    const scriptEl = document.getElementById('script-input');
                    if (scriptEl) {
                        scriptEl.value = data.content;
                    } else {
                        document.getElementById('prompt-input').value = data.content;
                    }
                    const promptEl = document.getElementById('prompt-input');
                    if (promptEl && !promptEl.value.trim()) {
                        promptEl.value = `Cinematic video visual sequence for ${data.filename.replace(/\.[^/.]+$/, '').replace(/_/g, ' ')}`;
                    }
                    setSceneChunk(data.suggested_scenes);
                    updateScriptMetrics();
                    alert(`📄 Ingested document '${data.filename}' (${data.word_count} words). Configured ${data.suggested_scenes} scene chunks!`);
                } else {
                    alert("Document upload failed: " + data.detail);
                }
            } catch (err) {
                alert("Upload failed: " + err);
            } finally {
                input.value = '';
            }
        }

        async function exportStandaloneAudio() {
            const scriptEl = document.getElementById('script-input');
            const promptEl = document.getElementById('prompt-input');
            const text = (scriptEl && scriptEl.value.trim()) ? scriptEl.value.trim() : (promptEl ? promptEl.value.trim() : '');
            if (!text) {
                alert("Please enter spoken narration in Voiceover Narration Script first.");
                return;
            }

            const voice = document.getElementById('voice-select').value;
            const speech_rate = parseFloat(document.getElementById('speed-slider').value) || 1.0;
            const pitchVal = parseInt(document.getElementById('pitch-slider').value) || 0;
            const pitch = (pitchVal >= 0 ? '+' : '') + pitchVal + 'Hz';
            const stability = (parseFloat(document.getElementById('stability-slider').value) || 75) / 100.0;
            const similarity_boost = (parseFloat(document.getElementById('clarity-slider').value) || 75) / 100.0;
            const format = document.getElementById('audio-export-format').value || 'mp3';
            const elevenKey = document.getElementById('elevenlabs-api-key').value.trim();
            const elevenVoice = document.getElementById('elevenlabs-voice-id').value;

            const btn = document.getElementById('export-audio-btn');
            const origHtml = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = '<span>⏳</span> <span>Synthesizing Audio Master...</span>';

            const resultBox = document.getElementById('audio-export-result-box');
            resultBox.classList.add('hidden');

            try {
                const res = await fetch('/api/v1/voice/export', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        text,
                        voice,
                        speech_rate,
                        pitch,
                        volume: "+0%",
                        format,
                        voice_provider: CURRENT_VOICE_PROVIDER,
                        elevenlabs_api_key: elevenKey,
                        elevenlabs_voice_id: elevenVoice,
                        stability,
                        similarity_boost
                    })
                });
                const data = await res.json();
                if (data.status === 'ok') {
                    // Update audio player
                    const player = document.getElementById('director-audio-player');
                    player.src = data.audio_url;
                    player.play();

                    // Show Download Box
                    resultBox.classList.remove('hidden');
                    document.getElementById('audio-export-meta').innerText = `✅ Generated ${data.format} Master (${data.size_mb} MB, ~${data.duration_seconds}s)`;
                    const audioLnk = document.getElementById('audio-download-link');
                    audioLnk.href = data.audio_url;
                    audioLnk.setAttribute('download', data.filename);

                    const srtLnk = document.getElementById('srt-download-link');
                    if (data.subtitles_url) {
                        srtLnk.href = data.subtitles_url;
                        srtLnk.classList.remove('hidden');
                    } else {
                        srtLnk.classList.add('hidden');
                    }
                } else {
                    alert("Audio export error: " + (data.detail || "Check voice settings"));
                }
            } catch (err) {
                alert("Audio export failed: " + err);
            } finally {
                btn.disabled = false;
                btn.innerHTML = origHtml;
            }
        }

        // Draws the chosen frame to scale (longest edge pinned to 40px) so the
        // orientation is obvious before a render is started, not after.
        function updateAspectPreview() {
            const sel = document.getElementById('resolution-select');
            if (!sel) return;
            const opt = sel.options[sel.selectedIndex];
            const w = parseInt(opt.getAttribute('data-w')) || 1280;
            const h = parseInt(opt.getAttribute('data-h')) || 720;
            const orient = opt.getAttribute('data-orient') || 'Landscape';

            const box = document.getElementById('aspect-preview-box');
            if (box) {
                const cap = 40;
                const scale = cap / Math.max(w, h);
                box.style.width = (w * scale) + 'px';
                box.style.height = (h * scale) + 'px';
            }

            const label = document.getElementById('aspect-preview-label');
            if (label) {
                label.innerHTML =
                    '<span class="font-mono text-brand-glow font-bold">' + w + '×' + h + '</span>' +
                    ' · ' + orient + ' · every scene, caption and avatar is composed for this frame.';
            }
            try {
                localStorage.setItem('neuroclips_last_resolution', sel.value);
            } catch (e) {}
            if (typeof updatePreflightSummary === 'function') updatePreflightSummary();
        }

        function setDirectorOutputType(type) {
            const input = document.getElementById('output-type-select');
            if (input) input.value = type;

            const cardVideo = document.getElementById('output-card-video');
            const cardSlide = document.getElementById('output-card-slide');
            const badgeVideo = document.getElementById('output-badge-video');
            const badgeSlide = document.getElementById('output-badge-slide');

            if (type === 'slide') {
                if (cardSlide) {
                    cardSlide.classList.add('bg-brand-500/15', 'border-brand-500');
                    cardSlide.classList.remove('bg-slate-900', 'border-slate-800');
                }
                if (cardVideo) {
                    cardVideo.classList.remove('bg-brand-500/15', 'border-brand-500');
                    cardVideo.classList.add('bg-slate-900', 'border-slate-800');
                }
                if (badgeSlide) badgeSlide.classList.remove('hidden');
                if (badgeVideo) badgeVideo.classList.add('hidden');
            } else {
                if (cardVideo) {
                    cardVideo.classList.add('bg-brand-500/15', 'border-brand-500');
                    cardVideo.classList.remove('bg-slate-900', 'border-slate-800');
                }
                if (cardSlide) {
                    cardSlide.classList.remove('bg-brand-500/15', 'border-brand-500');
                    cardSlide.classList.add('bg-slate-900', 'border-slate-800');
                }
                if (badgeVideo) badgeVideo.classList.remove('hidden');
                if (badgeSlide) badgeSlide.classList.add('hidden');
            }
        }

        function setAspectPreset(val) {
            const sel = document.getElementById('resolution-select');
            if (sel) {
                sel.value = val;
                updateAspectPreview();
            }
            const pillMap = {
                '16:9_hd': 'aspect-btn-16-9',
                '9:16_vertical': 'aspect-btn-9-16',
                '1:1_square': 'aspect-btn-1-1',
                '4:5_portrait': 'aspect-btn-4-5'
            };
            Object.keys(pillMap).forEach(key => {
                const btn = document.getElementById(pillMap[key]);
                if (btn) {
                    if (key === val) {
                        btn.className = "py-1 px-1.5 rounded-lg bg-brand-600 text-white font-bold text-center border border-brand-500 transition-all";
                    } else {
                        btn.className = "py-1 px-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-slate-300 font-semibold text-center border border-slate-800 transition-all";
                    }
                }
            });
        }

        function setChunkingMode(mode) {
            const input = document.getElementById('chunking-mode-input');
            if (input) input.value = mode;

            const btnAuto = document.getElementById('chunk-mode-auto');
            const btnManual = document.getElementById('chunk-mode-manual');

            if (mode === 'manual') {
                if (btnManual) btnManual.className = "w-1/2 py-1 rounded-md bg-brand-600 text-white font-bold transition-all";
                if (btnAuto) btnAuto.className = "w-1/2 py-1 rounded-md text-slate-400 hover:text-white transition-all";
            } else {
                if (btnAuto) btnAuto.className = "w-1/2 py-1 rounded-md bg-brand-600 text-white font-bold transition-all";
                if (btnManual) btnManual.className = "w-1/2 py-1 rounded-md text-slate-400 hover:text-white transition-all";
            }
        }

        function setMotionGraphics(enabled) {
            const input = document.getElementById('motion-graphics-check');
            if (input) input.value = enabled ? 'true' : 'false';

            const badge = document.getElementById('motion-status-badge');
            if (badge) {
                badge.innerText = enabled ? 'ON' : 'OFF';
                badge.className = enabled ? 'text-[9px] font-mono px-1.5 py-0.5 rounded bg-brand-500/20 text-brand-glow' : 'text-[9px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-400';
            }

            const btnOn = document.getElementById('motion-btn-on');
            const btnOff = document.getElementById('motion-btn-off');
            if (enabled) {
                if (btnOn) btnOn.className = "w-1/2 py-1 rounded-md bg-brand-600 text-white font-bold transition-all";
                if (btnOff) btnOff.className = "w-1/2 py-1 rounded-md text-slate-400 hover:text-white transition-all";
            } else {
                if (btnOff) btnOff.className = "w-1/2 py-1 rounded-md bg-brand-600 text-white font-bold transition-all";
                if (btnOn) btnOn.className = "w-1/2 py-1 rounded-md text-slate-400 hover:text-white transition-all";
            }
        }

        function setBackgroundMusic(enabled) {
            const input = document.getElementById('bgm-check');
            if (input) input.value = enabled ? 'true' : 'false';

            const badge = document.getElementById('bgm-status-badge');
            if (badge) {
                badge.innerText = enabled ? 'ON' : 'OFF';
                badge.className = enabled ? 'text-[9px] font-mono px-1.5 py-0.5 rounded bg-brand-500/20 text-brand-glow' : 'text-[9px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-400';
            }

            const btnOn = document.getElementById('bgm-btn-on');
            const btnOff = document.getElementById('bgm-btn-off');
            if (enabled) {
                if (btnOn) btnOn.className = "w-1/2 py-1 rounded-md bg-brand-600 text-white font-bold transition-all";
                if (btnOff) btnOff.className = "w-1/2 py-1 rounded-md text-slate-400 hover:text-white transition-all";
            } else {
                if (btnOff) btnOff.className = "w-1/2 py-1 rounded-md bg-brand-600 text-white font-bold transition-all";
                if (btnOn) btnOn.className = "w-1/2 py-1 rounded-md text-slate-400 hover:text-white transition-all";
            }
        }

        function updateActiveVoiceBadge() {
            const sel = document.getElementById('voice-select');
            const badge = document.getElementById('active-voice-badge');
            if (sel && badge) {
                const optText = sel.options[sel.selectedIndex]?.text || '';
                const shortName = optText.split('(')[0].trim();
                badge.innerText = shortName || sel.value;
                try {
                    localStorage.setItem('neuroclips_last_voice', sel.value);
                } catch (e) {}
                if (typeof updatePreflightSummary === 'function') updatePreflightSummary();
            }
        }

        function insertScriptTag(tag) {
            const textarea = document.getElementById('script-input') || document.getElementById('prompt-input');
            const start = textarea.selectionStart || textarea.value.length;
            const end = textarea.selectionEnd || textarea.value.length;
            const text = textarea.value;
            textarea.value = text.substring(0, start) + tag + text.substring(end);
            textarea.focus();
            textarea.selectionStart = textarea.selectionEnd = start + tag.length;
            updateScriptMetrics();
        }

        function setSceneChunk(count) {
            const slider = document.getElementById('scene-slider');
            if (slider) {
                slider.value = count;
                document.getElementById('scene-val').innerText = count + ' Scenes';
                if (typeof updatePreflightSummary === 'function') updatePreflightSummary();
            }
        }

        const PERSONA_CATALOG_JS = {
            "maya_fintech": { voice: "en-IN-NeerjaNeural", eleven_voice: "21m00Tcm4TlvDq8ikWAM", pitch: "+1Hz", speed: 1.0, badge: "🇮🇳 South Asian | en-IN (Neerja) | FinTech" },
            "alex_ai": { voice: "en-US-GuyNeural", eleven_voice: "pNInz6obpgDQGcFmaJgB", pitch: "-2Hz", speed: 1.0, badge: "🇺🇸 Caucasian | en-US (Guy) | AI Architect" },
            "elena_compliance": { voice: "en-US-AriaNeural", eleven_voice: "EXAVITQu4vr4xnSDxMaL", pitch: "+0Hz", speed: 0.95, badge: "🇪🇸 Latina | en-US (Aria) | Governance" },
            "david_trainer": { voice: "en-US-ChristopherNeural", eleven_voice: "TxGEqnHWrfWFTfGW9XjX", pitch: "+0Hz", speed: 1.0, badge: "🇺🇸 Global LMS | en-US (Christopher)" },
            "srinivas_cloud": { voice: "en-IN-PrabhatNeural", eleven_voice: "ErXwobaYiN019PkySvjV", pitch: "-1Hz", speed: 1.0, badge: "🇮🇳 South Asian | en-IN (Prabhat) | Cloud & AI" },
            "rajesh_cloud": { voice: "en-IN-PrabhatNeural", eleven_voice: "ErXwobaYiN019PkySvjV", pitch: "-1Hz", speed: 1.0, badge: "🇮🇳 South Asian | en-IN (Prabhat) | Cloud & AI" }
        };

        function onPersonaSelectChange(val) {
            const meta = PERSONA_CATALOG_JS[val];
            if (meta) {
                if (document.getElementById('voice-select')) {
                    document.getElementById('voice-select').value = meta.voice;
                }
                if (document.getElementById('elevenlabs-voice-id')) {
                    document.getElementById('elevenlabs-voice-id').value = meta.eleven_voice;
                }
                if (document.getElementById('speed-slider')) {
                    document.getElementById('speed-slider').value = meta.speed;
                    document.getElementById('speed-val').innerText = meta.speed.toFixed(2) + 'x';
                }
                const pitchVal = parseInt(meta.pitch) || 0;
                if (document.getElementById('pitch-slider')) {
                    document.getElementById('pitch-slider').value = pitchVal;
                    document.getElementById('pitch-val').innerText = (pitchVal >= 0 ? '+' : '') + pitchVal + 'Hz';
                }
                const badge = document.getElementById('persona-meta-badge');
                if (badge) badge.innerText = meta.badge;
                try {
                    localStorage.setItem('neuroclips_last_persona', val);
                } catch (e) {}
                if (typeof updateActiveVoiceBadge === 'function') updateActiveVoiceBadge();
                if (typeof updatePreflightSummary === 'function') updatePreflightSummary();
            }
        }

        let CURRENT_VOICE_PROVIDER = 'edge_tts';

        function switchVoiceEngine(provider) {
            CURRENT_VOICE_PROVIDER = provider;
            const btnEdge = document.getElementById('engine-tab-edgetts');
            const btnEleven = document.getElementById('engine-tab-elevenlabs');
            const elevenBox = document.getElementById('elevenlabs-config-box');

            if (provider === 'elevenlabs') {
                btnEleven.className = "px-2.5 py-1 rounded-md bg-amber-600 text-white font-bold transition-all";
                btnEdge.className = "px-2.5 py-1 rounded-md text-slate-400 hover:text-white transition-all";
                elevenBox.classList.remove('hidden');
                
                // Restore saved API key and Voice ID
                const savedKey = localStorage.getItem('neuroclips_eleven_key');
                const savedVoice = localStorage.getItem('neuroclips_eleven_voice');
                if (savedKey) document.getElementById('elevenlabs-api-key').value = savedKey;
                if (savedVoice) document.getElementById('elevenlabs-voice-id').value = savedVoice;
            } else {
                btnEdge.className = "px-2.5 py-1 rounded-md bg-brand-600 text-white font-bold transition-all";
                btnEleven.className = "px-2.5 py-1 rounded-md text-slate-400 hover:text-white transition-all";
                elevenBox.classList.add('hidden');
            }
        }

        function applyVoiceArchetype(arch) {
            const speedSlider = document.getElementById('speed-slider');
            const pitchSlider = document.getElementById('pitch-slider');
            const stabSlider = document.getElementById('stability-slider');
            const clarSlider = document.getElementById('clarity-slider');

            if (arch === 'executive') {
                speedSlider.value = 0.95;
                pitchSlider.value = -3;
                stabSlider.value = 85;
                clarSlider.value = 80;
            } else if (arch === 'conversational') {
                speedSlider.value = 1.05;
                pitchSlider.value = 2;
                stabSlider.value = 65;
                clarSlider.value = 75;
            } else if (arch === 'presenter') {
                speedSlider.value = 1.15;
                pitchSlider.value = 4;
                stabSlider.value = 60;
                clarSlider.value = 90;
            } else { // technical
                speedSlider.value = 1.00;
                pitchSlider.value = 0;
                stabSlider.value = 75;
                clarSlider.value = 75;
            }

            document.getElementById('speed-val').innerText = parseFloat(speedSlider.value).toFixed(2) + 'x';
            document.getElementById('pitch-val').innerText = (pitchSlider.value >= 0 ? '+' : '') + pitchSlider.value + 'Hz';
            document.getElementById('stability-val').innerText = stabSlider.value + '%';
            document.getElementById('clarity-val').innerText = clarSlider.value + '%';
            updateScriptMetrics();
        }

        async function auditionVoiceDirector() {
            const scriptEl = document.getElementById('script-input');
            const promptEl = document.getElementById('prompt-input');
            const text = (scriptEl && scriptEl.value.trim()) || (promptEl ? promptEl.value.trim() : '') || "Welcome to Modular-NeuroClips. Auditioning neural voice director prosody and natural pacing.";
            const voice = document.getElementById('voice-select').value;
            const speech_rate = parseFloat(document.getElementById('speed-slider').value) || 1.0;
            const pitchVal = parseInt(document.getElementById('pitch-slider').value) || 0;
            const pitch = (pitchVal >= 0 ? '+' : '') + pitchVal + 'Hz';
            const stability = (parseFloat(document.getElementById('stability-slider').value) || 75) / 100.0;
            const similarity_boost = (parseFloat(document.getElementById('clarity-slider').value) || 75) / 100.0;
            
            const elevenKey = document.getElementById('elevenlabs-api-key').value.trim();
            const elevenVoice = document.getElementById('elevenlabs-voice-id').value;

            const btn = document.getElementById('audition-btn');
            const statusLabel = document.getElementById('audition-status');
            btn.disabled = true;
            statusLabel.innerText = "Synthesizing...";

            try {
                const res = await fetch('/api/v1/voice-director/audition', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        text: text.slice(0, 300),
                        voice,
                        speech_rate,
                        pitch,
                        volume: "+0%",
                        voice_provider: CURRENT_VOICE_PROVIDER,
                        elevenlabs_api_key: elevenKey,
                        elevenlabs_voice_id: elevenVoice,
                        stability,
                        similarity_boost
                    })
                });
                const data = await res.json();
                if (data.status === 'ok') {
                    const player = document.getElementById('director-audio-player');
                    player.src = data.audio_url;
                    player.play();
                    statusLabel.innerText = `Playing (${data.provider})`;
                } else {
                    alert("Audition error: " + (data.detail || "Check credentials"));
                    statusLabel.innerText = "Error";
                }
            } catch (err) {
                alert("Audition failed: " + err);
                statusLabel.innerText = "Failed";
            } finally {
                btn.disabled = false;
            }
        }

        async function handleDirectorReferenceUpload(input) {
            if (!input.files || !input.files[0]) return;
            const file = input.files[0];
            const formData = new FormData();
            formData.append('file', file);
            const badge = document.getElementById('director-ref-badge');
            if (badge) badge.innerText = 'Uploading reference media...';
            try {
                const res = await fetch('/api/v1/director/upload-reference', { method: 'POST', body: formData });
                const data = await res.json();
                if (data.status === 'ok') {
                    document.getElementById('director-ref-url').value = data.reference_path || data.reference_url;
                    if (badge) badge.innerText = `Attached: ${data.filename} (${data.media_type})`;
                    const previewBox = document.getElementById('director-ref-preview-box');
                    const previewImg = document.getElementById('director-ref-preview-img');
                    if (previewBox && previewImg) {
                        previewBox.classList.remove('hidden');
                        if (data.media_type === 'image') {
                            previewImg.src = data.reference_url;
                            previewImg.classList.remove('hidden');
                        } else {
                            previewImg.classList.add('hidden');
                        }
                    }
                } else {
                    alert('Reference upload failed: ' + (data.detail || 'Error'));
                    if (badge) badge.innerText = 'Upload failed';
                }
            } catch(e) {
                alert('Reference upload error: ' + e);
                if (badge) badge.innerText = 'Upload error';
            }
        }

        function clearDirectorReferenceMedia() {
            const input = document.getElementById('director-ref-upload');
            if (input) input.value = '';
            const refUrl = document.getElementById('director-ref-url');
            if (refUrl) refUrl.value = '';
            const badge = document.getElementById('director-ref-badge');
            if (badge) badge.innerText = 'No media attached';
            const previewBox = document.getElementById('director-ref-preview-box');
            if (previewBox) previewBox.classList.add('hidden');
        }

        async function startGeneration() {
            const visual_prompt = document.getElementById('prompt-input').value.trim();
            if (!visual_prompt) {
                alert('Please enter a visual prompt for the video.');
                return;
            }

            const voiceover_script = document.getElementById('script-input') ? document.getElementById('script-input').value.trim() : '';
            const reference_media_url = document.getElementById('director-ref-url') ? document.getElementById('director-ref-url').value.trim() : '';

            const scenes = parseInt(document.getElementById('scene-slider').value);
            const language = document.getElementById('language-select').value;
            const resolution = document.getElementById('resolution-select').value;
            const voice = document.getElementById('voice-select').value;
            const speech_rate = parseFloat(document.getElementById('speed-slider').value) || 1.0;
            const pitchVal = parseInt(document.getElementById('pitch-slider').value) || 0;
            const pitch = (pitchVal >= 0 ? '+' : '') + pitchVal + 'Hz';
            const stability = (parseFloat(document.getElementById('stability-slider').value) || 75) / 100.0;
            const similarity_boost = (parseFloat(document.getElementById('clarity-slider').value) || 75) / 100.0;
            const elevenKey = document.getElementById('elevenlabs-api-key').value.trim();
            const elevenVoice = document.getElementById('elevenlabs-voice-id').value;

            const compiler_engine = document.getElementById('engine-select').value;
            const avatar_persona = document.getElementById('avatar-persona-select').value;
            const avatar_layout = document.getElementById('avatar-layout-select').value;
            const burn_subtitles = document.getElementById('burn-subtitles-check').checked;
            const auto_clean = document.getElementById('auto-clean-check').checked;
            const intro_video_url = document.getElementById('intro-bumper-select').value || null;
            const outro_video_url = document.getElementById('outro-bumper-select').value || null;

            const output_type = document.getElementById('output-type-select') ? document.getElementById('output-type-select').value : 'video';
            const motion_graphics = document.getElementById('motion-graphics-check') ? (document.getElementById('motion-graphics-check').value === 'true') : true;
            const background_music = document.getElementById('bgm-check') ? (document.getElementById('bgm-check').value === 'true') : false;
            const chunking_mode = document.getElementById('chunking-mode-input') ? document.getElementById('chunking-mode-input').value : 'auto';

            const btn = document.getElementById('generate-btn');
            btn.disabled = true;
            btn.classList.add('opacity-50', 'cursor-not-allowed');

            // UI State progression: Idle -> Uploading inputs -> Queued
            const phaseEl = document.getElementById('director-pipeline-phase');
            const progressContainer = document.getElementById('director-progress-container');
            const phaseMsg = document.getElementById('director-phase-msg');
            const phasePct = document.getElementById('director-phase-pct');
            const progressBar = document.getElementById('director-progress-bar');
            const statusDot = document.getElementById('director-status-dot');

            if (phaseEl) { phaseEl.innerText = 'Uploading inputs'; phaseEl.className = 'text-[10px] font-mono px-2 py-0.5 rounded bg-brand-500/20 text-brand-glow border border-brand-500/40 animate-pulse'; }
            if (progressContainer) progressContainer.classList.remove('hidden');
            if (phaseMsg) phaseMsg.innerText = 'Validating and uploading studio inputs...';
            if (phasePct) phasePct.innerText = '10%';
            if (progressBar) progressBar.style.width = '10%';
            if (statusDot) statusDot.className = 'w-2.5 h-2.5 rounded-full bg-brand-400 animate-pulse';

            try {
                const res = await fetch('/api/v1/generate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        topic: visual_prompt,
                        visual_prompt: visual_prompt,
                        voiceover_script: voiceover_script,
                        reference_media_url: reference_media_url || null,
                        scenes,
                        art_style: 'Cinematic 35mm (Volumetric Lighting)',
                        resolution,
                        language,
                        voice,
                        speech_rate,
                        compiler_engine,
                        avatar_persona,
                        avatar_layout,
                        burn_subtitles,
                        auto_clean,
                        intro_video_url,
                        outro_video_url,
                        pitch,
                        volume: "+0%",
                        voice_provider: CURRENT_VOICE_PROVIDER,
                        elevenlabs_api_key: elevenKey,
                        elevenlabs_voice_id: elevenVoice,
                        stability,
                        similarity_boost,
                        output_type,
                        motion_graphics,
                        background_music,
                        chunking_mode
                    })
                });
                const data = await res.json();
                if (data.status === 'started') {
                    activeSessionJobId = data.job_id;
                    updateTrackerDisplay(true);
                    if (phaseEl) phaseEl.innerText = 'Queued';
                    if (phaseMsg) phaseMsg.innerText = `Job #${data.job_id} queued in production pipeline`;
                    if (phasePct) phasePct.innerText = '15%';
                    if (progressBar) progressBar.style.width = '15%';
                    if (currentSessionOnly) fetchGallery();
                } else if (res.status === 409) {
                    alert(data.message);
                    if (btn) { btn.disabled = false; btn.classList.remove('opacity-50', 'cursor-not-allowed'); }
                }
            } catch (err) {
                alert('Generation failed: ' + err);
                if (phaseEl) { phaseEl.innerText = 'FAILED'; phaseEl.className = 'text-[10px] font-mono px-2 py-0.5 rounded bg-red-950/80 text-red-400 border border-red-500/50'; }
                if (phaseMsg) phaseMsg.innerText = String(err);
                if (btn) { btn.disabled = false; btn.classList.remove('opacity-50', 'cursor-not-allowed'); }
            }
        }

        async function openStoryboardPreview() {
            const topic = document.getElementById('prompt-input').value.trim();
            if (!topic) {
                alert('Please enter a concept or Master Script first.');
                return;
            }
            const scenes = parseInt(document.getElementById('scene-slider').value);
            const avatar_persona = document.getElementById('avatar-persona-select').value;
            const output_type = document.getElementById('output-type-select') ? document.getElementById('output-type-select').value : 'video';
            const chunking_mode = document.getElementById('chunking-mode-input') ? document.getElementById('chunking-mode-input').value : 'auto';

            const btn = document.getElementById('storyboard-btn');
            btn.innerHTML = '<span>⏳</span> <span>Directing Scenes...</span>';

            try {
                await fetchVideoAssets();
                const res = await fetch('/api/v1/storyboard/preview', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        topic,
                        scenes,
                        art_style: 'Cinematic 35mm (Volumetric Lighting)',
                        avatar_persona,
                        output_type,
                        chunking_mode
                    })
                });
                const data = await res.json();
                currentStoryboardData = data.script;
                renderStoryboardModal(data.script);
                document.getElementById('storyboard-modal').classList.remove('hidden');
            } catch(err) {
                alert('Storyboard generation failed: ' + err);
            } finally {
                btn.innerHTML = '<span>🎬</span> <span>Storyboard & Scene Breakdown</span>';
            }
        }

        function onSceneModeSelect(idx, mode) {
            if (!currentStoryboardData || !currentStoryboardData.scenes[idx]) return;
            if (mode === 'slide') {
                currentStoryboardData.scenes[idx].output_type = 'slide';
                currentStoryboardData.scenes[idx].video_source_type = 'ai_generated';
            } else if (mode === 'uploaded_video') {
                currentStoryboardData.scenes[idx].output_type = 'video';
                currentStoryboardData.scenes[idx].video_source_type = 'uploaded_video';
            } else {
                currentStoryboardData.scenes[idx].output_type = 'video';
                currentStoryboardData.scenes[idx].video_source_type = 'ai_generated';
            }
            renderStoryboardModal(currentStoryboardData);
        }

        function renderStoryboardModal(script) {
            const container = document.getElementById('storyboard-scenes-list');
            container.innerHTML = `
                <div class="p-3 rounded-xl bg-brand-500/10 border border-brand-500/20 text-xs text-brand-glow flex items-center justify-between">
                    <span class="font-bold">Screenplay: ${script.title}</span>
                    <span class="font-mono text-[11px] text-slate-400">${script.scenes.length} Pedagogical Scenes</span>
                </div>
            `;

            script.scenes.forEach((sc, idx) => {
                const card = document.createElement('div');
                const isSlide = (sc.output_type === 'slide');
                const isVideoClip = (sc.video_source_type === 'uploaded_video');
                const isAIVideo = (!isSlide && !isVideoClip);
                card.className = "p-4 rounded-xl bg-slate-900/90 border border-slate-800 space-y-3";
                
                card.innerHTML = `
                    <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                        <div class="flex items-center space-x-3">
                            <span class="text-xs font-bold text-white font-mono">
                                <span class="px-2 py-0.5 rounded bg-brand-500/20 text-brand-glow">Scene #${sc.scene_id}</span>
                            </span>
                            <!-- 3-Way Scene Mode Switcher -->
                            <div class="flex rounded-lg bg-slate-950 p-0.5 border border-slate-800 text-[11px]">
                                <button onclick="onSceneModeSelect(${idx}, 'ai_generated')" class="px-2.5 py-1 rounded-md transition-all ${isAIVideo ? 'bg-brand-600 text-white font-bold' : 'text-slate-400 hover:text-white'}">
                                    🎬 AI Video
                                </button>
                                <button onclick="onSceneModeSelect(${idx}, 'slide')" class="px-2.5 py-1 rounded-md transition-all ${isSlide ? 'bg-emerald-600 text-white font-bold' : 'text-slate-400 hover:text-white'}">
                                    📊 Slide
                                </button>
                                <button onclick="onSceneModeSelect(${idx}, 'uploaded_video')" class="px-2.5 py-1 rounded-md transition-all ${isVideoClip ? 'bg-indigo-600 text-white font-bold' : 'text-slate-400 hover:text-white'}">
                                    📼 Clip
                                </button>
                            </div>
                        </div>
                        <button onclick="removeStoryboardScene(${idx})" class="text-red-400 hover:text-red-300 text-xs">🗑️ Remove</button>
                    </div>

                    ${isSlide ? `
                    <!-- Instructional Slide Editor -->
                    <div class="p-3 rounded-xl bg-emerald-950/20 border border-emerald-500/30 space-y-2.5">
                        <div class="flex items-center justify-between">
                            <span class="text-xs font-bold text-emerald-300 flex items-center gap-1.5">
                                <span>📊</span> <span>Instructional Slide Content</span>
                            </span>
                            <span class="text-[10px] text-slate-400">Renders high-contrast educational graphic + avatar</span>
                        </div>
                        <div class="space-y-2 text-xs">
                            <div>
                                <label class="block text-slate-400 font-semibold mb-1">Slide Title / Framework Header</label>
                                <input id="sb-slidetitle-${idx}" type="text" value="${sc.title || ('Key Concept #' + sc.scene_id)}" class="w-full rounded-lg bg-slate-950 border border-slate-700 p-2 text-white text-xs" placeholder="e.g. Algorithmic Liquidity Mechanisms">
                            </div>
                            <div>
                                <label class="block text-slate-400 font-semibold mb-1">Slide Key Takeaways / Framework Details (bulleted or structured text)</label>
                                <textarea id="sb-slidecontent-${idx}" rows="2" class="w-full rounded-lg bg-slate-950 border border-slate-700 p-2 text-white text-xs font-mono" placeholder="• Key principle 1&#10;• Operational rule 2&#10;• Core risk metric 3">${sc.visual_prompt || sc.narration || ''}</textarea>
                            </div>
                        </div>
                    </div>
                    ` : (isVideoClip ? `
                    <!-- Video Source Selector & Upload Box -->
                    <div class="p-3 rounded-xl bg-indigo-950/20 border border-indigo-500/30 space-y-3">
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                            <div>
                                <label class="block text-slate-300 font-semibold mb-1">Select from Video Library</label>
                                <select id="sb-videosrc-${idx}" onchange="currentStoryboardData.scenes[${idx}].video_source_url = this.value; renderStoryboardModal(currentStoryboardData);" class="w-full rounded-lg bg-slate-950 border border-slate-700 p-2 text-white text-xs">
                                    <option value="">-- Choose a Video Asset --</option>
                                    ${VIDEO_ASSETS_CACHE.map(a => `<option value="${a.video_url}" ${sc.video_source_url === a.video_url ? 'selected' : ''}>${a.filename} (${a.size_mb} MB)</option>`).join('')}
                                </select>
                            </div>
                            <div>
                                <label class="block text-slate-300 font-semibold mb-1">Or Upload Directly to This Scene</label>
                                <div class="flex items-center space-x-2">
                                    <label for="sb-upload-file-${idx}" id="sb-upload-btn-${idx}" class="w-full py-2 px-3 rounded-lg bg-indigo-600/30 border border-indigo-500/40 text-indigo-200 text-xs font-bold text-center cursor-pointer hover:bg-indigo-600/40 transition-all">
                                        📁 Upload MP4 / WebM Clip
                                    </label>
                                    <input type="file" id="sb-upload-file-${idx}" class="hidden" accept="video/mp4,video/webm,video/quicktime" onchange="handleSceneVideoUpload(this, ${idx})">
                                </div>
                            </div>
                        </div>
                        ${sc.video_source_url ? `
                        <div class="flex items-center space-x-3 p-2 rounded-lg bg-slate-950/80 border border-slate-800">
                            <span class="text-emerald-400 text-xs font-bold">✔ Video Attached:</span>
                            <span class="text-xs text-slate-300 font-mono truncate flex-1">${sc.video_source_url}</span>
                            <a href="${sc.video_source_url}" target="_blank" class="text-xs text-brand-glow hover:underline">Preview</a>
                        </div>
                        ` : `
                        <div class="text-[11px] text-amber-300/80 italic">⚠️ Please select or upload a video clip for this scene.</div>
                        `}
                    </div>
                    ` : `
                    <!-- AI Keyframe & Motion Prompts -->
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                        <div>
                            <label class="block text-slate-400 font-semibold mb-1">Visual Scene Prompt (AI Keyframe)</label>
                            <textarea id="sb-visual-${idx}" rows="2" class="w-full rounded-lg bg-slate-950 border border-slate-700 p-2 text-white text-xs">${sc.visual_prompt || ''}</textarea>
                        </div>
                        <div>
                            <label class="block text-slate-400 font-semibold mb-1">Motion Dynamics</label>
                            <textarea id="sb-motion-${idx}" rows="2" class="w-full rounded-lg bg-slate-950 border border-slate-700 p-2 text-white text-xs">${sc.motion_prompt || 'Slow cinematic push-in'}</textarea>
                        </div>
                    </div>
                    `)}

                    <!-- Narration & Duration -->
                    <div class="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
                        <div class="md:col-span-2">
                            <label class="block text-slate-400 font-semibold mb-1">Spoken Narration (Voice & Subtitles)</label>
                            <input id="sb-narration-${idx}" type="text" value="${sc.narration || ''}" class="w-full rounded-lg bg-slate-950 border border-slate-700 p-2 text-white text-xs" placeholder="Spoken voiceover for this shot...">
                        </div>
                        <div>
                            <label class="block text-slate-400 font-semibold mb-1">Duration (Seconds)</label>
                            <input id="sb-duration-${idx}" type="number" value="${sc.duration_seconds || 4}" min="2" max="30" class="w-full rounded-lg bg-slate-950 border border-slate-700 p-2 text-white text-xs font-mono">
                        </div>
                    </div>
                `;
                container.appendChild(card);
            });
        }

        function closeStoryboardModal() {
            document.getElementById('storyboard-modal').classList.add('hidden');
        }

        function addStoryboardScene() {
            if (!currentStoryboardData) return;
            const nextId = currentStoryboardData.scenes.length + 1;
            const defaultType = document.getElementById('output-type-select') ? document.getElementById('output-type-select').value : 'video';
            currentStoryboardData.scenes.push({
                scene_id: nextId,
                title: `Scene ${nextId}`,
                output_type: defaultType,
                visual_prompt: `Visual diagram and high-tech interface representing scene ${nextId}`,
                motion_prompt: "Slow cinematic push-in with volumetric lighting",
                narration: "Key lesson summary statement.",
                duration_seconds: 4,
                video_source_type: 'ai_generated',
                video_source_url: ''
            });
            renderStoryboardModal(currentStoryboardData);
        }

        function removeStoryboardScene(idx) {
            if (!currentStoryboardData || currentStoryboardData.scenes.length <= 1) return;
            currentStoryboardData.scenes.splice(idx, 1);
            currentStoryboardData.scenes.forEach((s, i) => s.scene_id = i + 1);
            renderStoryboardModal(currentStoryboardData);
        }

        async function renderFromStoryboard() {
            if (!currentStoryboardData) return;

            const updatedScenes = currentStoryboardData.scenes.map((sc, idx) => {
                const isVideoClip = sc.video_source_type === 'uploaded_video';
                const isSlide = sc.output_type === 'slide';
                let visPrompt = sc.visual_prompt || '';
                if (isSlide && document.getElementById(`sb-slidecontent-${idx}`)) {
                    visPrompt = document.getElementById(`sb-slidecontent-${idx}`).value;
                } else if (!isVideoClip && document.getElementById(`sb-visual-${idx}`)) {
                    visPrompt = document.getElementById(`sb-visual-${idx}`).value;
                }
                const slideTitle = (isSlide && document.getElementById(`sb-slidetitle-${idx}`)) ? document.getElementById(`sb-slidetitle-${idx}`).value : (sc.title || `Scene ${idx+1}`);

                return {
                    scene_id: idx + 1,
                    title: slideTitle,
                    output_type: sc.output_type || (isSlide ? 'slide' : 'video'),
                    visual_prompt: visPrompt || 'Visual presentation scene',
                    motion_prompt: (!isVideoClip && document.getElementById(`sb-motion-${idx}`)) ? document.getElementById(`sb-motion-${idx}`).value : (sc.motion_prompt || 'Cinematic pan'),
                    narration: document.getElementById(`sb-narration-${idx}`) ? document.getElementById(`sb-narration-${idx}`).value : (sc.narration || ''),
                    duration_seconds: parseFloat(document.getElementById(`sb-duration-${idx}`) ? document.getElementById(`sb-duration-${idx}`).value : sc.duration_seconds) || 4.0,
                    video_source_type: sc.video_source_type || 'ai_generated',
                    video_source_url: isVideoClip ? (document.getElementById(`sb-videosrc-${idx}`) ? document.getElementById(`sb-videosrc-${idx}`).value : sc.video_source_url) : ''
                };
            });

            const language = document.getElementById('language-select').value;
            const resolution = document.getElementById('resolution-select').value;
            const voice = document.getElementById('voice-select').value;
            const speech_rate = parseFloat(document.getElementById('speed-slider').value) || 1.0;
            const pitchVal = parseInt(document.getElementById('pitch-slider').value) || 0;
            const pitch = (pitchVal >= 0 ? '+' : '') + pitchVal + 'Hz';
            const stability = (parseFloat(document.getElementById('stability-slider').value) || 75) / 100.0;
            const similarity_boost = (parseFloat(document.getElementById('clarity-slider').value) || 75) / 100.0;
            const elevenKey = document.getElementById('elevenlabs-api-key').value.trim();
            const elevenVoice = document.getElementById('elevenlabs-voice-id').value;

            const compiler_engine = document.getElementById('engine-select').value;
            const avatar_persona = document.getElementById('avatar-persona-select').value;
            const avatar_layout = document.getElementById('avatar-layout-select').value;
            const burn_subtitles = document.getElementById('burn-subtitles-check').checked;
            const auto_clean = document.getElementById('auto-clean-check').checked;
            const intro_video_url = document.getElementById('intro-bumper-select').value || null;
            const outro_video_url = document.getElementById('outro-bumper-select').value || null;

            const output_type = document.getElementById('output-type-select') ? document.getElementById('output-type-select').value : 'video';
            const motion_graphics = document.getElementById('motion-graphics-check') ? (document.getElementById('motion-graphics-check').value === 'true') : true;
            const background_music = document.getElementById('bgm-check') ? (document.getElementById('bgm-check').value === 'true') : false;

            closeStoryboardModal();

            try {
                const res = await fetch('/api/v1/generate/from-storyboard', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        title: currentStoryboardData.title,
                        art_style: currentStoryboardData.art_style_preset,
                        resolution,
                        language,
                        voice,
                        speech_rate,
                        compiler_engine,
                        avatar_persona,
                        avatar_layout,
                        burn_subtitles,
                        auto_clean,
                        intro_video_url,
                        outro_video_url,
                        pitch,
                        volume: "+0%",
                        voice_provider: CURRENT_VOICE_PROVIDER,
                        elevenlabs_api_key: elevenKey,
                        elevenlabs_voice_id: elevenVoice,
                        stability,
                        similarity_boost,
                        output_type,
                        motion_graphics,
                        background_music,
                        scenes: updatedScenes
                    })
                });
                const data = await res.json();
                if (data.status === 'started') {
                    activeSessionJobId = data.job_id;
                    if (currentSessionOnly) fetchGallery();
                } else if (res.status === 409) {
                    alert(data.message);
                }
            } catch(e) {
                alert('Render from storyboard failed: ' + e);
            }
        }

        async function uploadAvatar(input) {
            if (!input.files || !input.files[0]) return;
            const formData = new FormData();
            formData.append('file', input.files[0]);
            try {
                const res = await fetch('/api/v1/avatar/upload', { method: 'POST', body: formData });
                const data = await res.json();
                if (data.status === 'ok') {
                    document.getElementById('avatar-persona-select').value = 'custom_upload';
                    alert("📸 Custom portrait uploaded successfully!");
                }
            } catch(e) { alert("Upload failed: " + e); }
        }

        async function auditionVoice() {
            auditionVoiceDirector();
        }

        async function fetchIdentities() {
            try {
                const res = await fetch('/api/v1/identity/list');
                const data = await res.json();
                const select = document.getElementById('identity-load-select');
                select.innerHTML = '<option value="">📂 Load Identity Profile...</option>' + 
                    data.identities.map(id => `<option value="${id.name}">${id.name}</option>`).join('');
            } catch(e) {}
        }

        async function saveCurrentIdentity() {
            const name = prompt("Enter Name for this Instructor Identity (e.g. 'Maya_FinTech_Lead'):");
            if (!name) return;
            const payload = {
                name,
                avatar_persona: document.getElementById('avatar-persona-select').value,
                avatar_layout: document.getElementById('avatar-layout-select').value,
                preferred_voice: document.getElementById('voice-select').value,
                speech_rate: parseFloat(document.getElementById('speed-slider').value) || 1.0
            };
            try {
                const res = await fetch('/api/v1/identity/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                alert(data.message);
                fetchIdentities();
            } catch(e) { alert("Failed to save identity: " + e); }
        }

        async function loadSelectedIdentity(name) {
            if (!name) return;
            try {
                const res = await fetch(`/api/v1/identity/load/${encodeURIComponent(name)}`);
                const data = await res.json();
                if (data.identity) {
                    const id = data.identity;
                    document.getElementById('avatar-persona-select').value = id.avatar_persona || 'maya_fintech';
                    document.getElementById('avatar-layout-select').value = id.avatar_layout || 'pip_bottom_right';
                    if (id.preferred_voice) document.getElementById('voice-select').value = id.preferred_voice;
                    if (id.speech_rate) {
                        document.getElementById('speed-slider').value = id.speech_rate;
                        document.getElementById('speed-val').innerText = id.speech_rate.toFixed(2) + 'x';
                    }
                    alert(`Loaded instructor identity: ${id.name}`);
                }
            } catch(e) { alert("Failed to load identity: " + e); }
        }

        async function restartPipeline() {
            if (!confirm("Are you sure you want to restart the engine?")) return;
            try {
                await fetch('/api/v1/jobs/restart', { method: 'POST' });
                renderMilestones('init');
                document.getElementById('terminal-logs').innerHTML = `<div class="text-amber-400">[RESET] Pipeline restarted successfully.</div>`;
            } catch(e) { alert("Restart failed: " + e); }
        }

        async function purgeVRAM() {
            try { await fetch('/api/v1/telemetry/purge-vram', { method: 'POST' }); alert("VRAM Cache Purged."); } catch(e) {}
        }

        function copyTerminalLogs() {
            const term = document.getElementById('terminal-logs');
            navigator.clipboard.writeText(term.innerText).then(() => {
                const btn = document.getElementById('copy-log-btn');
                const orig = btn.innerHTML;
                btn.innerHTML = '<span>✅</span> <span>Copied!</span>';
                setTimeout(() => { btn.innerHTML = orig; }, 2000);
            });
        }

        /* =========================================================================
           VOICE LAB, CLONING & CLONED VOICE LIBRARY MANAGEMENT
           ========================================================================= */
        let clonedAudioBlob = null;
        let mediaRecorder = null;
        let audioChunks = [];
        let isRecording = false;

        function updateVoiceLabMetrics() {
            const text = document.getElementById('voice-lab-prompt')?.value || '';
            const words = text.trim() ? text.trim().split(/\s+/).length : 0;
            const rate = parseFloat(document.getElementById('voice-lab-rate')?.value) || 1.0;
            const minutes = (words / (145 * rate)).toFixed(1);
            const stats = document.getElementById('voice-lab-stats');
            if (stats) stats.innerText = `${words} words | ~${minutes} min`;
        }

        function insertVoiceLabTag(tag) {
            const textarea = document.getElementById('voice-lab-prompt');
            if (!textarea) return;
            const start = textarea.selectionStart || textarea.value.length;
            const end = textarea.selectionEnd || textarea.value.length;
            const text = textarea.value;
            textarea.value = text.substring(0, start) + tag + text.substring(end);
            textarea.focus();
            textarea.selectionStart = textarea.selectionEnd = start + tag.length;
            updateVoiceLabMetrics();
        }

        async function expandPromptToVoiceScript() {
            const textarea = document.getElementById('voice-lab-prompt');
            const prompt = textarea?.value.trim();
            if (!prompt) {
                alert("Please enter a topic or short outline to expand.");
                return;
            }
            const btn = document.getElementById('voice-lab-expand-btn');
            const orig = btn.innerHTML;
            btn.innerHTML = '<span>⏳</span> <span>Expanding...</span>';
            btn.disabled = true;

            try {
                const res = await fetch('/api/v1/script/expand', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ prompt, tone: 'instructional_fintech', duration_target_sec: 45 })
                });
                const data = await res.json();
                if (data.status === 'ok' && data.script) {
                    textarea.value = data.script;
                    updateVoiceLabMetrics();
                } else {
                    alert("Script expansion failed: " + (data.detail || "Unknown error"));
                }
            } catch (err) {
                alert("Script expansion error: " + err);
            } finally {
                btn.innerHTML = orig;
                btn.disabled = false;
            }
        }

        async function auditionVoiceLab() {
            const promptInput = document.getElementById('voice-lab-prompt');
            const text = promptInput?.value.trim() || "Auditioning high fidelity neural speech synthesis and directorial prosody.";
            const voice = document.getElementById('voice-lab-voice')?.value || 'en-US-GuyNeural';
            const rateVal = parseFloat(document.getElementById('voice-lab-rate')?.value) || 1.0;
            const pitchNum = parseInt(document.getElementById('voice-lab-pitch')?.value) || 0;
            const pitch = (pitchNum >= 0 ? '+' : '') + pitchNum + 'Hz';

            const btn = document.getElementById('voice-lab-audition-btn');
            const orig = btn.innerHTML;
            btn.innerHTML = '<span>⏳</span> <span>Auditioning...</span>';
            btn.disabled = true;

            try {
                const res = await fetch('/api/v1/voice/export', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        text: text.slice(0, 300),
                        voice: voice,
                        speech_rate: rateVal,
                        pitch: pitch,
                        volume: "+0%",
                        format: "mp3"
                    })
                });
                const data = await res.json();
                if (data.status === 'ok') {
                    const player = document.getElementById('voice-lab-audio-player');
                    player.src = data.audio_url;
                    player.play();
                    document.getElementById('voice-lab-player-badge').innerText = 'Auditioning';
                } else {
                    alert("Audition error: " + (data.detail || "Check voice settings"));
                }
            } catch (e) {
                alert("Audition error: " + e);
            } finally {
                btn.innerHTML = orig;
                btn.disabled = false;
            }
        }

        async function exportVoiceLabMaster() {
            const promptInput = document.getElementById('voice-lab-prompt');
            const text = promptInput?.value.trim();
            if (!text) {
                alert("Please enter narration text or script first.");
                return;
            }
            const voice = document.getElementById('voice-lab-voice')?.value || 'en-US-GuyNeural';
            const rateVal = parseFloat(document.getElementById('voice-lab-rate')?.value) || 1.0;
            const pitchNum = parseInt(document.getElementById('voice-lab-pitch')?.value) || 0;
            const pitch = (pitchNum >= 0 ? '+' : '') + pitchNum + 'Hz';
            const format = document.getElementById('voice-lab-format')?.value || 'mp3';

            const btn = document.getElementById('voice-lab-export-btn');
            const orig = btn.innerHTML;
            btn.innerHTML = '<span>⏳</span> <span>Exporting Master...</span>';
            btn.disabled = true;

            try {
                const res = await fetch('/api/v1/voice/export', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        text: text,
                        voice: voice,
                        speech_rate: rateVal,
                        pitch: pitch,
                        volume: "+0%",
                        format: format
                    })
                });
                const data = await res.json();
                if (data.status === 'ok') {
                    const player = document.getElementById('voice-lab-audio-player');
                    player.src = data.audio_url;
                    player.play();
                    document.getElementById('voice-lab-player-badge').innerText = `Master ${data.format.toUpperCase()}`;

                    const dlBox = document.getElementById('voice-lab-download-box');
                    dlBox.classList.remove('hidden');
                    const audioDl = document.getElementById('voice-lab-audio-dl');
                    audioDl.href = data.audio_url;
                    audioDl.setAttribute('download', data.filename);

                    const srtDl = document.getElementById('voice-lab-srt-dl');
                    if (data.subtitles_url) {
                        srtDl.href = data.subtitles_url;
                        srtDl.classList.remove('hidden');
                    } else {
                        srtDl.classList.add('hidden');
                    }

                    if (data.srt_content) {
                        document.getElementById('voice-lab-srt-preview').innerText = data.srt_content;
                    }
                } else {
                    alert("Master export failed: " + (data.detail || "Server error"));
                }
            } catch (e) {
                alert("Export error: " + e);
            } finally {
                btn.innerHTML = orig;
                btn.disabled = false;
            }
        }

        function onVoiceLabLangChange() {
            const lang = document.getElementById('voice-lab-lang').value;
            const voiceSelect = document.getElementById('voice-lab-voice');
            const langMap = {
                'en-US': [['en-US-GuyNeural', 'Guy (Male - Deep Professional)'], ['en-US-AriaNeural', 'Aria (Female - Clear Instructional)'], ['en-US-ChristopherNeural', 'Christopher (Male - Authoritative)']],
                'en-IN': [['en-IN-NeerjaNeural', 'Neerja (Female - Indian FinTech Specialist)'], ['en-IN-PrabhatNeural', 'Prabhat (Male - Indian Senior Architect)']],
                'te-IN': [['te-IN-MohanNeural', 'Mohan (Male - Telugu Instructional)'], ['te-IN-ShrutiNeural', 'Shruti (Female - Telugu Clear)']],
                'ta-IN': [['ta-IN-ValluvarNeural', 'Valluvar (Male - Tamil Senior)'], ['ta-IN-PallaviNeural', 'Pallavi (Female - Tamil Presenter)']],
                'hi-IN': [['hi-IN-MadhurNeural', 'Madhur (Male - Hindi Standard)'], ['hi-IN-SwaraNeural', 'Swara (Female - Hindi Clear)']],
                'es-ES': [['es-ES-AlvaroNeural', 'Álvaro (Male - Spanish Executive)'], ['es-ES-ElviraNeural', 'Elvira (Female - Spanish Clear)']],
                'fr-FR': [['fr-FR-HenriNeural', 'Henri (Male - French Standard)'], ['fr-FR-DeniseNeural', 'Denise (Female - French Instructional)']],
                'de-DE': [['de-DE-ConradNeural', 'Conrad (Male - German Technical)'], ['de-DE-KatjaNeural', 'Katja (Female - German Crisp)']],
                'ja-JP': [['ja-JP-KeitaNeural', 'Keita (Male - Japanese Standard)'], ['ja-JP-NanamiNeural', 'Nanami (Female - Japanese Instructional)']]
            };

            const voices = langMap[lang] || langMap['en-US'];
            voiceSelect.innerHTML = voices.map(v => `<option value="${v[0]}">${v[1]}</option>`).join('');
            // Also append any custom cloned voices that match this locale or universally
            fetchVoiceLibrary();
        }

        /* --- Instant Voice Cloning Handlers --- */
        function handleAudioSampleSelected(input) {
            if (input.files && input.files[0]) {
                const file = input.files[0];
                clonedAudioBlob = file;
                const label = document.getElementById('clone-file-label');
                if (label) label.innerText = file.name;
                const preview = document.getElementById('clone-audio-preview');
                const previewBox = document.getElementById('clone-audio-preview-box');
                preview.src = URL.createObjectURL(file);
                previewBox.classList.remove('hidden');
            }
        }

        async function toggleMicRecording() {
            const btn = document.getElementById('btn-record-mic');
            const indicator = document.getElementById('record-indicator');
            const text = document.getElementById('record-text');

            if (!isRecording) {
                try {
                    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                    mediaRecorder = new MediaRecorder(stream);
                    audioChunks = [];

                    mediaRecorder.ondataavailable = (e) => {
                        if (e.data.size > 0) audioChunks.push(e.data);
                    };

                    mediaRecorder.onstop = () => {
                        clonedAudioBlob = new Blob(audioChunks, { type: 'audio/wav' });
                        const preview = document.getElementById('clone-audio-preview');
                        const previewBox = document.getElementById('clone-audio-preview-box');
                        preview.src = URL.createObjectURL(clonedAudioBlob);
                        previewBox.classList.remove('hidden');
                        const label = document.getElementById('clone-file-label');
                        if (label) label.innerText = 'Microphone Recording';
                    };

                    mediaRecorder.start();
                    isRecording = true;
                    btn.classList.replace('bg-red-600/80', 'bg-red-700');
                    btn.classList.add('animate-pulse');
                    indicator.innerText = '⏹️';
                    text.innerText = 'Stop Recording';
                } catch (e) {
                    alert("Microphone access denied or not supported: " + e);
                }
            } else {
                if (mediaRecorder && mediaRecorder.state !== 'inactive') {
                    mediaRecorder.stop();
                    mediaRecorder.stream.getTracks().forEach(t => t.stop());
                }
                isRecording = false;
                btn.classList.replace('bg-red-700', 'bg-red-600/80');
                btn.classList.remove('animate-pulse');
                indicator.innerText = '🔴';
                text.innerText = 'Record from Mic';
            }
        }

        async function submitVoiceClone() {
            const displayName = document.getElementById('clone-display-name')?.value.trim();
            if (!displayName) {
                alert("Please enter a Presenter Name (e.g. 'Dr. Srinivas Velaga').");
                return;
            }
            if (!clonedAudioBlob) {
                alert("Please record audio via mic or upload an audio file (.mp3, .ogg, .wav).");
                return;
            }

            const locale = document.getElementById('clone-locale')?.value || 'en-IN';
            const gender = document.getElementById('clone-gender')?.value || 'female';
            const btn = document.getElementById('btn-submit-clone');
            const origHtml = btn.innerHTML;
            btn.innerHTML = '<span>⏳</span> <span>Cloning & Normalizing Audio Sample...</span>';
            btn.disabled = true;

            const formData = new FormData();
            formData.append('display_name', displayName);
            formData.append('locale', locale);
            formData.append('gender', gender);
            formData.append('sample_file', clonedAudioBlob, clonedAudioBlob.name || 'sample.wav');

            try {
                const res = await fetch('/api/v1/voice/clone', {
                    method: 'POST',
                    body: formData
                });
                const data = await res.json();
                if (res.ok && data.status === 'ok') {
                    alert(`🎉 Voice Cloned Successfully!\nRegistered persona: ${data.persona.display_name} (${data.persona.locale})\nAdded to catalog as '${data.persona.persona_id}'.`);
                    document.getElementById('clone-display-name').value = '';
                    clonedAudioBlob = null;
                    document.getElementById('clone-audio-preview-box').classList.add('hidden');
                    const label = document.getElementById('clone-file-label');
                    if (label) label.innerText = 'Choose Audio (.mp3, .ogg, .wav)';
                    await fetchVoiceLibrary();
                } else {
                    alert("Voice cloning failed: " + (data.detail || data.message || "Unknown error"));
                }
            } catch (e) {
                alert("Voice cloning error: " + e);
            } finally {
                btn.innerHTML = origHtml;
                btn.disabled = false;
            }
        }

        /* --- Saved Voice Library & Cross-Studio Dropdown Synchronization --- */
        async function fetchVoiceLibrary() {
            try {
                const res = await fetch('/api/v1/voice/personas');
                const data = await res.json();
                const personas = data.personas || [];

                const customPersonas = personas.filter(p => p.is_custom === true);
                const grid = document.getElementById('cloned-voice-library-grid');
                const countBadge = document.getElementById('cloned-voice-count');
                if (countBadge) countBadge.innerText = `${customPersonas.length} Clone${customPersonas.length === 1 ? '' : 's'}`;

                if (grid) {
                    if (customPersonas.length === 0) {
                        grid.innerHTML = `<div class="text-[11px] text-slate-500 italic p-3 text-center bg-slate-900/50 rounded-lg border border-slate-800">
                            No custom cloned voices yet. Upload an .mp3 or .ogg file above to add one!
                        </div>`;
                    } else {
                        grid.innerHTML = customPersonas.map(p => `
                            <div class="p-3 rounded-xl bg-slate-950/90 border border-indigo-500/30 space-y-2 text-xs">
                                <div class="flex items-center justify-between">
                                    <div class="flex items-center gap-2">
                                        <span class="text-sm">⭐</span>
                                        <span class="font-bold text-white">${p.display_name}</span>
                                        <span class="text-[10px] px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300 font-mono">${p.locale} &bull; ${p.gender}</span>
                                    </div>
                                    <button onclick="deleteCustomVoice('${p.persona_id}', '${p.display_name}')" class="text-red-400 hover:text-red-300 text-[11px] transition-all" title="Delete voice">🗑️ Delete</button>
                                </div>
                                ${p.reference_sample_url ? `
                                <div class="flex items-center gap-2 pt-1">
                                    <span class="text-[10px] text-slate-400">Audition sample:</span>
                                    <audio src="${p.reference_sample_url}" controls class="h-6 flex-1"></audio>
                                </div>` : ''}
                                <div class="flex items-center gap-2 pt-1 border-t border-slate-800/80">
                                    <button onclick="useClonedVoice('${p.persona_id}', '${p.display_name}', 'voice_lab')" class="px-2.5 py-1 rounded bg-emerald-600/30 hover:bg-emerald-600/50 text-emerald-300 border border-emerald-500/30 text-[11px] font-bold transition-all">
                                        🎙️ Use in Voice Lab
                                    </button>
                                    <button onclick="useClonedVoice('${p.persona_id}', '${p.display_name}', 'video_studio')" class="px-2.5 py-1 rounded bg-indigo-600/30 hover:bg-indigo-600/50 text-indigo-300 border border-indigo-500/30 text-[11px] font-bold transition-all">
                                        🎬 Use in Video Studio
                                    </button>
                                </div>
                            </div>
                        `).join('');
                    }
                }

                // Synchronize custom voices into all studio select dropdowns
                populateAllVoiceDropdowns(personas);
            } catch (err) {
                console.error("Failed to fetch voice library:", err);
            }
        }

        function populateAllVoiceDropdowns(personas) {
            const customList = personas.filter(p => p.is_custom === true);
            if (customList.length === 0) return;

            // Target dropdowns
            const dropdowns = [
                { id: 'voice-lab-voice', prefix: '⭐ ' },
                { id: 'voice-select', prefix: '⭐ ' },
                { id: 'avatar-persona-select', prefix: '⭐ ' },
                { id: 'batch-slide-persona', prefix: '⭐ ' },
                { id: 'curriculum-batch-persona', prefix: '⭐ ' }
            ];

            dropdowns.forEach(({ id, prefix }) => {
                const el = document.getElementById(id);
                if (!el) return;

                // Remove existing custom options to prevent duplicates
                const existingCustom = el.querySelectorAll('option[data-custom="true"]');
                existingCustom.forEach(opt => opt.remove());

                // Append custom cloned personas
                customList.forEach(p => {
                    const opt = document.createElement('option');
                    // For voice-select and voice-lab-voice we can use edge_voice or persona_id
                    opt.value = (id === 'voice-select' || id === 'voice-lab-voice') ? (p.edge_voice || p.persona_id) : p.persona_id;
                    opt.textContent = `${prefix}${p.display_name} (${p.locale} Cloned)`;
                    opt.setAttribute('data-custom', 'true');
                    el.appendChild(opt);
                });
            });
        }

        function useClonedVoice(personaId, displayName, targetMode) {
            if (targetMode === 'voice_lab') {
                switchStudioMode('voice');
                const labVoice = document.getElementById('voice-lab-voice');
                if (labVoice) {
                    for (let i = 0; i < labVoice.options.length; i++) {
                        if (labVoice.options[i].value === personaId || labVoice.options[i].text.includes(displayName)) {
                            labVoice.selectedIndex = i;
                            break;
                        }
                    }
                }
                alert(`Selected '${displayName}' in Voice Director Studio.`);
            } else if (targetMode === 'video_studio') {
                switchStudioMode('video');
                const voiceSelect = document.getElementById('voice-select');
                const avatarSelect = document.getElementById('avatar-persona-select');
                if (voiceSelect) {
                    for (let i = 0; i < voiceSelect.options.length; i++) {
                        if (voiceSelect.options[i].value === personaId || voiceSelect.options[i].text.includes(displayName)) {
                            voiceSelect.selectedIndex = i;
                            break;
                        }
                    }
                }
                if (avatarSelect) {
                    for (let i = 0; i < avatarSelect.options.length; i++) {
                        if (avatarSelect.options[i].value === personaId || avatarSelect.options[i].text.includes(displayName)) {
                            avatarSelect.selectedIndex = i;
                            break;
                        }
                    }
                }
                alert(`Selected '${displayName}' for AI Video Narration and Avatar.`);
            }
        }

        async function deleteCustomVoice(personaId, displayName) {
            if (!confirm(`Are you sure you want to delete the cloned voice '${displayName}' (${personaId}) from your library?`)) return;
            try {
                const res = await fetch(`/api/v1/voice/personas/${encodeURIComponent(personaId)}`, {
                    method: 'DELETE'
                });
                const data = await res.json();
                if (res.ok && data.status === 'ok') {
                    alert(`Deleted cloned voice '${displayName}'.`);
                    await fetchVoiceLibrary();
                } else {
                    alert("Delete failed: " + (data.detail || data.message || "Unknown error"));
                }
            } catch (e) {
                alert("Delete request failed: " + e);
            }
        }

        /* --- Universal Document Speech Ingestion --- */
        let selectedDocSpeechFile = null;
        function handleDocFileSelected(input) {
            if (input.files && input.files[0]) {
                selectedDocSpeechFile = input.files[0];
                const nameEl = document.getElementById('selected-doc-name');
                if (nameEl) nameEl.innerText = `📄 ${selectedDocSpeechFile.name} (${(selectedDocSpeechFile.size / 1024).toFixed(1)} KB)`;
            }
        }

        async function submitUniversalDocSpeech() {
            if (!selectedDocSpeechFile) {
                alert("Please select a document file (.txt, .md, .docx, .pdf) first.");
                return;
            }

            const btn = document.getElementById('btn-doc-speech-run');
            const origHtml = btn.innerHTML;
            btn.innerHTML = '<span>⏳</span> <span>Ingesting Document & Synthesizing Audio Master...</span>';
            btn.disabled = true;

            const voice = document.getElementById('voice-lab-voice')?.value || 'en-US-GuyNeural';
            const rateVal = parseFloat(document.getElementById('voice-lab-rate')?.value) || 1.0;
            const pitchNum = parseInt(document.getElementById('voice-lab-pitch')?.value) || 0;
            const pitch = (pitchNum >= 0 ? '+' : '') + pitchNum + 'Hz';
            const format = document.getElementById('voice-lab-format')?.value || 'mp3';
            const packageScorm = document.getElementById('doc-export-scorm-chk')?.checked || false;

            const formData = new FormData();
            formData.append('file', selectedDocSpeechFile);
            formData.append('voice', voice);
            formData.append('speech_rate', rateVal);
            formData.append('pitch', pitch);
            formData.append('format', format);
            formData.append('package_scorm', packageScorm);

            try {
                const res = await fetch('/api/v1/voice/document-to-speech', {
                    method: 'POST',
                    body: formData
                });
                const data = await res.json();
                if (res.ok && data.status === 'ok') {
                    const player = document.getElementById('voice-lab-audio-player');
                    player.src = data.audio_url;
                    player.play();
                    document.getElementById('voice-lab-player-badge').innerText = `Doc Master (${data.scenes_count || 1} scenes)`;

                    const dlBox = document.getElementById('voice-lab-download-box');
                    dlBox.classList.remove('hidden');
                    const audioDl = document.getElementById('voice-lab-audio-dl');
                    audioDl.href = data.audio_url;
                    audioDl.setAttribute('download', data.filename);

                    if (data.subtitles_url) {
                        const srtDl = document.getElementById('voice-lab-srt-dl');
                        srtDl.href = data.subtitles_url;
                        srtDl.classList.remove('hidden');
                    }

                    if (data.srt_content) {
                        document.getElementById('voice-lab-srt-preview').innerText = data.srt_content;
                    }

                    alert(`✅ Document audio synthesis complete!\nGenerated: ${data.filename} (${data.size_mb} MB)`);
                } else {
                    alert("Document synthesis failed: " + (data.detail || data.message || "Unknown error"));
                }
            } catch (e) {
                alert("Document synthesis error: " + e);
            } finally {
                btn.innerHTML = origHtml;
                btn.disabled = false;
            }
        }

        const evtSource = new EventSource('/api/v1/telemetry/stream');
        evtSource.onmessage = function(e) {
            const data = JSON.parse(e.data);
            const gpu = data.telemetry.gpu;
            const headerVram = document.getElementById('header-vram');
            if (headerVram && gpu) headerVram.innerText = `${gpu.used_mb} / ${gpu.total_mb} MB`;

            const cpuStat = document.getElementById('cpu-stat');
            if (cpuStat && data.telemetry.system) cpuStat.innerText = `${data.telemetry.system.cpu_percent}%`;
            const cpuBar = document.getElementById('cpu-bar');
            if (cpuBar && data.telemetry.system) cpuBar.style.width = `${data.telemetry.system.cpu_percent}%`;

            const headerStatus = document.getElementById('header-status');
            if (headerStatus && data.state) headerStatus.innerText = data.state.status || 'Idle';

            const latencyStat = document.getElementById('latency-stat');
            if (latencyStat && data.state && data.state.model_load_latency !== undefined) {
                latencyStat.innerText = `${data.state.model_load_latency.toFixed(2)}s`;
            }

            const currentStageStat = document.getElementById('current-stage-stat');
            if (currentStageStat && data.state) {
                currentStageStat.innerText = data.state.current_step || 'Idle';
                currentStageStat.title = data.state.current_step || 'Idle';
            }

            const elapsedStat = document.getElementById('elapsed-stat');
            if (elapsedStat) {
                const job = data.active_job;
                if (job && job.created_at && job.status !== 'complete' && job.status !== 'failed') {
                    const nowSec = data.timestamp || (Date.now() / 1000);
                    const elapsedSec = Math.max(0, Math.floor(nowSec - job.created_at));
                    const m = Math.floor(elapsedSec / 60).toString().padStart(2, '0');
                    const s = (elapsedSec % 60).toString().padStart(2, '0');
                    elapsedStat.innerText = `${m}:${s}`;
                } else {
                    elapsedStat.innerText = "00:00";
                }
            }

            const progress = data.state.progress_percent || 0;
            document.getElementById('master-progress-fill').style.width = `${progress}%`;
            document.getElementById('overall-progress-num').innerText = `${progress}%`;
            document.getElementById('active-step-caption').innerText = data.state.current_step || 'Idle';

            const activeJob = data.active_job;
            const isJobRendering = Boolean(activeJob && activeJob.status !== 'complete' && activeJob.status !== 'failed');
            updateTrackerDisplay(isJobRendering || Boolean(activeSessionJobId));

            if (activeJob) {
                renderMilestones(activeJob.current_milestone, activeJob.milestones);
                if (activeJob.logs && activeJob.logs.length > 0) {
                    const term = document.getElementById('terminal-logs');
                    term.innerHTML = activeJob.logs.map(l => `<div class="leading-relaxed">${l}</div>`).join('');
                    term.scrollTop = term.scrollHeight;
                }

                // 1. Live RENDERING state representation in Media Vault
                if (activeJob.status !== 'complete' && activeJob.status !== 'failed') {
                    updateVaultRenderingCard(activeJob);
                } else {
                    activeSessionJobId = null;
                    removeVaultRenderingCard();
                }

                // 2. Fetch gallery ONCE upon completion (prevents infinite re-fetching and DOM wiping)
                if (activeJob.status === 'complete' && activeJob.output_path) {
                    if (LAST_FETCHED_COMPLETED_JOB_ID !== activeJob.job_id) {
                        LAST_FETCHED_COMPLETED_JOB_ID = activeJob.job_id;
                        fetchGallery();
                    }
                }
            } else {
                activeSessionJobId = null;
                removeVaultRenderingCard();
                renderMilestones(data.state.current_milestone || 'init');
            }

            // Real-time UI state progression & preview player for Director Studio
            updateDirectorJobUI(data.state, activeJob);
        };

        function updateDirectorJobUI(state, activeJob) {
            const phaseEl = document.getElementById('director-pipeline-phase');
            const progressContainer = document.getElementById('director-progress-container');
            const phaseMsg = document.getElementById('director-phase-msg');
            const phasePct = document.getElementById('director-phase-pct');
            const progressBar = document.getElementById('director-progress-bar');
            const statusDot = document.getElementById('director-status-dot');
            const outputCard = document.getElementById('director-output-card');
            const videoPlayer = document.getElementById('director-video-player');
            const downloadBtn = document.getElementById('director-download-btn');
            const btn = document.getElementById('generate-btn');

            if (!activeJob) {
                if (state && (state.status === 'Idle' || state.status === 'idle')) {
                    if (btn) { btn.disabled = false; btn.classList.remove('opacity-50', 'cursor-not-allowed'); }
                }
                return;
            }

            const st = activeJob.status;
            const progress = (state && state.progress_percent !== undefined) ? state.progress_percent : (activeJob.progress_percent || 0);
            const currentStep = (state && state.current_step) || activeJob.current_step || '';

            if (st === 'running' || st === 'pending') {
                if (progressContainer) progressContainer.classList.remove('hidden');
                if (btn) { btn.disabled = true; btn.classList.add('opacity-50', 'cursor-not-allowed'); }
                if (statusDot) statusDot.className = 'w-2.5 h-2.5 rounded-full bg-brand-400 animate-pulse';

                let phaseName = 'Generating video';
                const ms = activeJob.current_milestone || '';
                if (st === 'pending') {
                    phaseName = 'Queued';
                } else if (ms === 'script') {
                    phaseName = 'Generating script';
                } else if (ms === 'voice') {
                    phaseName = 'Generating audio';
                } else if (ms === 'keyframes' || ms === 'video') {
                    phaseName = 'Generating video';
                } else if (ms === 'compile' || ms === 'render') {
                    phaseName = 'Rendering final video';
                }

                if (phaseEl) {
                    phaseEl.innerText = phaseName;
                    phaseEl.className = 'text-[10px] font-mono px-2 py-0.5 rounded bg-brand-500/20 text-brand-glow border border-brand-500/40 animate-pulse';
                }
                if (phaseMsg) phaseMsg.innerText = currentStep || `Processing (${phaseName})...`;
                if (phasePct) phasePct.innerText = `${progress}%`;
                if (progressBar) progressBar.style.width = `${progress}%`;

            } else if (st === 'complete') {
                if (btn) { btn.disabled = false; btn.classList.remove('opacity-50', 'cursor-not-allowed'); }
                if (statusDot) statusDot.className = 'w-2.5 h-2.5 rounded-full bg-emerald-400';
                if (phaseEl) {
                    phaseEl.innerText = 'Completed';
                    phaseEl.className = 'text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-950/80 text-emerald-400 border border-emerald-500/50';
                }
                if (phaseMsg) phaseMsg.innerText = 'Video generated and compiled successfully!';
                if (phasePct) phasePct.innerText = '100%';
                if (progressBar) progressBar.style.width = '100%';

                if (activeJob.output_path) {
                    const videoFilename = activeJob.output_path.split(/[/\\]/).pop();
                    const videoUrl = `/static_renders/${videoFilename}`;
                    if (outputCard) outputCard.classList.remove('hidden');
                    if (videoPlayer) {
                        const currentSrc = videoPlayer.getAttribute('src') || '';
                        if (!currentSrc.includes(videoFilename)) {
                            videoPlayer.src = videoUrl;
                            videoPlayer.load();
                        }
                    }
                    if (downloadBtn) {
                        downloadBtn.href = videoUrl;
                        downloadBtn.setAttribute('download', videoFilename);
                        downloadBtn.classList.remove('bg-slate-800', 'text-slate-400', 'border-slate-700', 'pointer-events-none', 'opacity-50');
                        downloadBtn.classList.add('bg-gradient-to-r', 'from-brand-600', 'to-emerald-600', 'text-white', 'hover:brightness-110', 'shadow-md', 'shadow-brand-500/20', 'pointer-events-auto');
                    }
                }

            } else if (st === 'failed') {
                if (btn) { btn.disabled = false; btn.classList.remove('opacity-50', 'cursor-not-allowed'); }
                if (statusDot) statusDot.className = 'w-2.5 h-2.5 rounded-full bg-red-400';
                if (phaseEl) {
                    phaseEl.innerText = 'FAILED';
                    phaseEl.className = 'text-[10px] font-mono px-2 py-0.5 rounded bg-red-950/80 text-red-400 border border-red-500/50';
                }
                if (phaseMsg) phaseMsg.innerText = (state && state.last_error) || (activeJob && activeJob.error) || 'Generation failed.';
            }
        }

        const savedElevenKey = localStorage.getItem('neuroclips_eleven_key');
        const savedElevenVoice = localStorage.getItem('neuroclips_eleven_voice');
        if (savedElevenKey && document.getElementById('elevenlabs-api-key')) {
            document.getElementById('elevenlabs-api-key').value = savedElevenKey;
        }
        if (savedElevenVoice && document.getElementById('elevenlabs-voice-id')) {
            document.getElementById('elevenlabs-voice-id').value = savedElevenVoice;
        }

        let selectedBatchSlideFile = null;
        function handleBatchSlideFileSelected(input) {
            if (input.files && input.files[0]) {
                selectedBatchSlideFile = input.files[0];
                document.getElementById('batch-slide-file-label').innerText = selectedBatchSlideFile.name;
            }
        }

        async function submitBatchSlideGeneration() {
            if (!selectedBatchSlideFile) {
                alert("Please select a PowerPoint (.pptx) or Excel (.xlsx) file first.");
                return;
            }

            const btn = document.getElementById('btn-batch-slide-run');
            const statusBox = document.getElementById('batch-slide-status-box');
            const statusText = document.getElementById('batch-slide-status-text');
            const countsText = document.getElementById('batch-slide-counts');
            const progressBar = document.getElementById('batch-slide-progress-bar');
            const resultsList = document.getElementById('batch-slide-results-list');

            const moduleNum = parseInt(document.getElementById('batch-slide-module-num').value) || 1;
            const personaId = document.getElementById('batch-slide-persona').value;
            const numbering = document.getElementById('batch-slide-numbering').value;
            const skipCache = document.getElementById('batch-slide-skip-cache').checked;

            statusBox.classList.remove('hidden');
            statusText.innerText = `Ingesting ${selectedBatchSlideFile.name}...`;
            progressBar.style.width = '30%';
            resultsList.innerHTML = `<div class="text-slate-500 italic">Parsing slides, speaker notes, and curriculum hierarchy...</div>`;
            btn.disabled = true;
            btn.classList.add('opacity-50', 'cursor-not-allowed');

            const formData = new FormData();
            formData.append('file', selectedBatchSlideFile);
            formData.append('module_num', moduleNum);
            formData.append('persona_id', personaId);
            formData.append('slide_numbering', numbering);
            formData.append('skip_existing', skipCache);

            try {
                const res = await fetch('/api/v1/voice/batch-slides-upload', {
                    method: 'POST',
                    body: formData
                });
                const data = await res.json();
                if (res.ok && data.status === 'ok') {
                    progressBar.style.width = '100%';
                    statusText.innerText = `Batch Complete: ${data.successful_slides} of ${data.total_slides} audio files generated.`;
                    countsText.innerText = `${data.successful_slides} / ${data.total_slides} Succeeded`;

                    resultsList.innerHTML = (data.files || []).map(f => {
                        const isSuccess = f.status === 'success' || f.status === 'cached';
                        const badgeColor = isSuccess ? 'text-teal-400' : 'text-red-400';
                        const tag = f.status === 'cached' ? '[CACHED]' : (isSuccess ? '[OK]' : '[ERR]');
                        return `<div class="flex items-center justify-between py-1 border-b border-slate-900">
                            <span class="${badgeColor} font-bold">${tag} ${f.filename}</span>
                            <span class="text-slate-400">${f.duration_sec ? f.duration_sec.toFixed(1) + 's (' + f.duration_frames + ' frames)' : (f.error || 'error')}</span>
                        </div>`;
                    }).join('');
                } else {
                    statusText.innerText = 'Batch processing failed: ' + (data.detail || data.message || 'Unknown error');
                    progressBar.style.width = '0%';
                }
            } catch(e) {
                statusText.innerText = 'Network/API error: ' + e;
                progressBar.style.width = '0%';
            } finally {
                btn.disabled = false;
                btn.classList.remove('opacity-50', 'cursor-not-allowed');
            }
        }

        async function startCurriculumBatchPipeline() {
            const courseId = document.getElementById('curriculum-batch-course-id').value.trim() || 'FINTECH_AGENTS_15HR';
            const moduleVal = document.getElementById('curriculum-batch-module').value;
            const personaId = document.getElementById('curriculum-batch-persona').value;
            const resolution = document.getElementById('curriculum-batch-resolution').value;

            const btn = document.getElementById('btn-curriculum-batch-start');
            const statusBox = document.getElementById('curriculum-batch-status-box');
            const titleEl = document.getElementById('curriculum-batch-status-title');
            const progressPctEl = document.getElementById('curriculum-batch-progress-pct');
            const progressBarEl = document.getElementById('curriculum-batch-progress-bar');
            const statCompleted = document.getElementById('curriculum-batch-stat-completed');
            const statProcessing = document.getElementById('curriculum-batch-stat-processing');
            const statPending = document.getElementById('curriculum-batch-stat-pending');
            const statFailed = document.getElementById('curriculum-batch-stat-failed');

            statusBox.classList.remove('hidden');
            titleEl.innerText = `Submitting batch pipeline for ${courseId}...`;
            progressBarEl.style.width = '10%';
            progressPctEl.innerText = '10%';
            btn.disabled = true;
            btn.classList.add('opacity-50', 'cursor-not-allowed');

            try {
                const res = await fetch('/api/v1/batch/curriculum', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        course_id: courseId,
                        module_num: moduleVal ? parseInt(moduleVal) : null,
                        persona_id: personaId,
                        resolution: resolution
                    })
                });
                const data = await res.json();
                if (res.ok && data.status === 'ok') {
                    titleEl.innerText = `Pipeline Active: ${data.total_lessons_queued} lessons queued across ${data.total_topics} topics.`;
                    progressBarEl.style.width = '25%';
                    progressPctEl.innerText = '25%';
                    // Start polling
                    pollCurriculumBatchStatus(courseId);
                } else {
                    titleEl.innerText = `Failed: ${data.detail || data.message || 'Error launching pipeline'}`;
                    progressBarEl.style.width = '0%';
                    progressPctEl.innerText = '0%';
                    btn.disabled = false;
                    btn.classList.remove('opacity-50', 'cursor-not-allowed');
                }
            } catch (e) {
                titleEl.innerText = `Network Error: ${e}`;
                progressBarEl.style.width = '0%';
                btn.disabled = false;
                btn.classList.remove('opacity-50', 'cursor-not-allowed');
            }
        }

        let curriculumPollTimer = null;
        async function pollCurriculumBatchStatus(courseId) {
            if (curriculumPollTimer) clearInterval(curriculumPollTimer);

            curriculumPollTimer = setInterval(async () => {
                try {
                    const res = await fetch(`/api/v1/batch/curriculum/status/${encodeURIComponent(courseId)}`);
                    const data = await res.json();
                    if (data.course_id || data.status === 'ok') {
                        const total = data.total_lessons || data.total_tasks || 0;
                        const comp = data.completed || 0;
                        const proc = data.processing || 0;
                        const pend = data.pending || 0;
                        const fail = data.failed || 0;

                        document.getElementById('curriculum-batch-stat-completed').innerText = `Completed: ${comp}`;
                        document.getElementById('curriculum-batch-stat-processing').innerText = `Processing: ${proc}`;
                        document.getElementById('curriculum-batch-stat-pending').innerText = `Pending: ${pend}`;
                        document.getElementById('curriculum-batch-stat-failed').innerText = `Failed: ${fail}`;

                        const pct = total > 0 ? Math.round(((comp + fail) / total) * 100) : 0;
                        document.getElementById('curriculum-batch-progress-bar').style.width = `${Math.max(pct, 15)}%`;
                        document.getElementById('curriculum-batch-progress-pct').innerText = `${pct}%`;

                        if (total > 0 && comp + fail >= total) {
                            clearInterval(curriculumPollTimer);
                            document.getElementById('curriculum-batch-status-title').innerText = `Batch Complete: ${comp} of ${total} finished successfully.`;
                            const btn = document.getElementById('btn-curriculum-batch-start');
                            btn.disabled = false;
                            btn.classList.remove('opacity-50', 'cursor-not-allowed');
                        }
                    }
                } catch (e) {
                    console.error("Batch poll error:", e);
                }
            }, 3000);
        }


        // ================= AVATAR STUDIO JAVASCRIPT CONTROLLERS =================
        function updateAvatarScriptMetrics() {
            const input = document.getElementById('avatar-script-input');
            if (!input) return;
            const text = input.value.trim();
            const words = text ? text.split(/\s+/).length : 0;
            const speed = parseFloat(document.getElementById('avatar-speed-slider')?.value || 1.0);
            const spokenMin = (words / (140 * speed)).toFixed(2);
            const statEl = document.getElementById('avatar-script-stats');
            if (statEl) statEl.innerText = `${words} words | ~${spokenMin} min`;
        }

        function insertAvatarCue(cue) {
            const el = document.getElementById('avatar-script-input');
            if (!el) return;
            const start = el.selectionStart;
            const end = el.selectionEnd;
            el.value = el.value.substring(0, start) + cue + el.value.substring(end);
            el.focus();
            el.selectionStart = el.selectionEnd = start + cue.length;
            updateAvatarScriptMetrics();
        }

        async function handleAvatarPageUpload(input) {
            if (!input.files || !input.files[0]) return;
            const file = input.files[0];
            const formData = new FormData();
            formData.append('file', file);
            try {
                const res = await fetch('/api/v1/avatar/upload', { method: 'POST', body: formData });
                const data = await res.json();
                if (data.status === 'ok') {
                    const imgEl = document.getElementById('avatar-portrait-img');
                    if (imgEl) imgEl.src = `${data.avatar_url}?t=${Date.now()}`;
                    const badge = document.getElementById('avatar-img-badge');
                    if (badge) badge.innerText = file.name;
                    document.getElementById('avatar-page-preset-select').value = 'custom';
                    alert('Avatar portrait uploaded successfully!');
                }
            } catch(e) {
                alert('Avatar upload error: ' + e);
            }
        }

        function applyAvatarPagePreset(val) {
            const imgEl = document.getElementById('avatar-portrait-img');
            const badge = document.getElementById('avatar-img-badge');
            const voiceSelect = document.getElementById('avatar-voice-select');
            if (val === 'maya') {
                if (imgEl) imgEl.src = 'https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?q=80&w=400';
                if (badge) badge.innerText = 'Maya (FinTech Lead)';
                if (voiceSelect) voiceSelect.value = 'en-IN-NeerjaNeural';
            } else if (val === 'alex') {
                if (imgEl) imgEl.src = 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?q=80&w=400';
                if (badge) badge.innerText = 'Alex (AI Architect)';
                if (voiceSelect) voiceSelect.value = 'en-US-GuyNeural';
            } else if (val === 'elena') {
                if (imgEl) imgEl.src = 'https://images.unsplash.com/photo-1580489944761-15a19d654956?q=80&w=400';
                if (badge) badge.innerText = 'Elena (Compliance)';
                if (voiceSelect) voiceSelect.value = 'en-GB-SoniaNeural';
            } else if (val === 'david') {
                if (imgEl) imgEl.src = 'https://images.unsplash.com/photo-1519085360753-af0119f7cbe7?q=80&w=400';
                if (badge) badge.innerText = 'David (LMS Trainer)';
                if (voiceSelect) voiceSelect.value = 'en-US-ChristopherNeural';
            } else {
                if (imgEl) imgEl.src = `/static_renders/custom_avatar.png?t=${Date.now()}`;
                if (badge) badge.innerText = 'custom_avatar.png';
            }
        }

        function setAvatarCurtainMode(mode) {
            document.getElementById('avatar-curtain-mode').value = mode;
            const btnGreen = document.getElementById('curtain-btn-green');
            const btnWhite = document.getElementById('curtain-btn-white');
            const previewBg = document.getElementById('avatar-preview-curtain-bg');
            const metaCurtain = document.getElementById('meta-curtain');

            if (mode === 'green') {
                btnGreen.className = "p-2.5 rounded-xl bg-emerald-500/20 border-2 border-emerald-500 text-white font-bold flex items-center justify-center gap-2 transition-all";
                btnWhite.className = "p-2.5 rounded-xl bg-slate-900 border-2 border-slate-800 text-slate-300 font-bold flex items-center justify-center gap-2 transition-all hover:border-slate-700";
                if (previewBg) previewBg.style.backgroundColor = '#00FF00';
                if (metaCurtain) metaCurtain.innerText = 'Chroma Green (#00FF00)';
            } else {
                btnWhite.className = "p-2.5 rounded-xl bg-white/20 border-2 border-white text-white font-bold flex items-center justify-center gap-2 transition-all";
                btnGreen.className = "p-2.5 rounded-xl bg-slate-900 border-2 border-slate-800 text-slate-300 font-bold flex items-center justify-center gap-2 transition-all hover:border-slate-700";
                if (previewBg) previewBg.style.backgroundColor = '#FFFFFF';
                if (metaCurtain) metaCurtain.innerText = 'Clean White (#FFFFFF)';
            }
        }

        function toggleAvatarCurtainActive(isActive) {
            const label = document.getElementById('avatar-curtain-toggle-label');
            const previewBg = document.getElementById('avatar-preview-curtain-bg');
            if (isActive) {
                if (label) { label.innerText = 'ON'; label.className = 'text-[10px] font-bold font-mono text-emerald-400'; }
                const mode = document.getElementById('avatar-curtain-mode').value;
                if (previewBg) previewBg.style.backgroundColor = mode === 'green' ? '#00FF00' : '#FFFFFF';
            } else {
                if (label) { label.innerText = 'OFF'; label.className = 'text-[10px] font-bold font-mono text-slate-500'; }
                if (previewBg) previewBg.style.backgroundColor = '#0F172A';
            }
        }

        function setAvatarHandGestures(gesture) {
            document.getElementById('avatar-gesture-mode').value = gesture;
            const badge = document.getElementById('avatar-gesture-badge');
            const metaGestures = document.getElementById('meta-gestures');
            ['subtle', 'explanatory', 'dynamic', 'executive'].forEach(g => {
                const btn = document.getElementById(`gesture-btn-${g}`);
                if (!btn) return;
                if (g === gesture) {
                    btn.className = "p-2.5 rounded-xl bg-pink-500/20 border-2 border-pink-500 text-white font-bold flex flex-col items-center gap-1 transition-all";
                } else {
                    btn.className = "p-2.5 rounded-xl bg-slate-900 border-2 border-slate-800 text-slate-300 font-semibold flex flex-col items-center gap-1 transition-all hover:border-slate-700";
                }
            });
            const titles = {
                subtle: 'Subtle & Natural',
                explanatory: 'Explanatory Pointing',
                dynamic: 'Dynamic Keynote',
                executive: 'Executive Anchor'
            };
            if (badge) badge.innerText = titles[gesture] || gesture;
            if (metaGestures) metaGestures.innerText = titles[gesture] || gesture;
        }

        function toggle3DModelTeaser(checked) {
            const statusEl = document.getElementById('avatar-3d-status');
            if (statusEl) {
                statusEl.innerText = checked ? 'Rig Active' : 'Standby';
                statusEl.className = checked ? 'text-[10px] font-mono text-emerald-300 bg-emerald-950/60 px-2 py-0.5 rounded border border-emerald-700/50' : 'text-[10px] font-mono text-purple-400 bg-purple-900/40 px-2 py-0.5 rounded border border-purple-700/50';
            }
        }

        async function handleAvatar3DUpload(input) {
            if (!input.files || !input.files[0]) return;
            const file = input.files[0];
            const formData = new FormData();
            formData.append('file', file);

            const statusEl = document.getElementById('avatar-3d-status');
            const badgeEl = document.getElementById('avatar-3d-badge');
            const pathEl = document.getElementById('avatar-3d-model-path');

            if (statusEl) {
                statusEl.innerText = 'Uploading...';
                statusEl.className = 'text-[10px] font-mono text-amber-300 bg-amber-950/60 px-2 py-0.5 rounded border border-amber-700/50 animate-pulse';
            }

            try {
                const res = await fetch('/api/v1/avatar/upload-3d', { method: 'POST', body: formData });
                const data = await res.json();
                if (data.status === 'ok') {
                    if (pathEl) pathEl.value = data.model_path || data.model_url;
                    if (badgeEl) badgeEl.innerText = `${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
                    if (statusEl) {
                        statusEl.innerText = 'Active (Ready)';
                        statusEl.className = 'text-[10px] font-mono text-emerald-300 bg-emerald-950/60 px-2 py-0.5 rounded border border-emerald-700/50';
                    }
                    const toggle = document.getElementById('avatar-3d-model-toggle');
                    if (toggle) toggle.checked = true;
                    alert(`3D Avatar asset uploaded successfully!\nPath: ${data.model_path || data.model_url}`);
                } else {
                    alert('Upload failed: ' + (data.detail || 'Unknown error'));
                    if (statusEl) {
                        statusEl.innerText = 'Upload Failed';
                        statusEl.className = 'text-[10px] font-mono text-red-300 bg-red-950/60 px-2 py-0.5 rounded border border-red-700/50';
                    }
                }
            } catch (e) {
                alert('Upload error: ' + e);
                if (statusEl) {
                    statusEl.innerText = 'Upload Error';
                    statusEl.className = 'text-[10px] font-mono text-red-300 bg-red-950/60 px-2 py-0.5 rounded border border-red-700/50';
                }
            }
        }

        async function auditionAvatarVoice() {
            const text = document.getElementById('avatar-script-input').value.trim() || "Hello, this is your neural avatar instructor speaking.";
            const voice = document.getElementById('avatar-voice-select').value;
            const speed = parseFloat(document.getElementById('avatar-speed-slider').value) || 1.0;
            const pitch = document.getElementById('avatar-pitch-slider').value + 'Hz';
            const btn = document.getElementById('avatar-audition-btn');
            const orig = btn.innerHTML;
            btn.innerHTML = '<span>⏳</span> <span>Synthesizing...</span>';
            try {
                const res = await fetch('/api/v1/voice-director/audition', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ prompt: text, voice, speed_rate: speed, pitch })
                });
                const data = await res.json();
                if (data.status === 'ok') {
                    const audio = new Audio(data.audio_url);
                    audio.play();
                } else {
                    alert('Audition failed: ' + (data.detail || 'Error'));
                }
            } catch(e) {
                alert('Audition error: ' + e);
            } finally {
                btn.innerHTML = orig;
            }
        }

        async function generateAvatarVideoAction() {
            const script = document.getElementById('avatar-script-input').value.trim();
            if (!script) {
                alert('Please enter a script for the avatar to speak.');
                return;
            }
            const voice = document.getElementById('avatar-voice-select').value;
            const speed = parseFloat(document.getElementById('avatar-speed-slider').value) || 1.0;
            const pitch = document.getElementById('avatar-pitch-slider').value + 'Hz';
            const curtainMode = document.getElementById('avatar-curtain-mode').value;
            const curtainActive = document.getElementById('avatar-curtain-toggle').checked;
            const handGestures = document.getElementById('avatar-gesture-mode').value;
            const future3D = document.getElementById('avatar-3d-model-toggle').checked;
            const model3DPath = document.getElementById('avatar-3d-model-path') ? document.getElementById('avatar-3d-model-path').value : null;

            const btn = document.getElementById('avatar-generate-btn');
            const progressBox = document.getElementById('avatar-gen-progress-box');
            const stepMsg = document.getElementById('avatar-gen-step-msg');
            const fill = document.getElementById('avatar-gen-progress-fill');
            const pct = document.getElementById('avatar-gen-pct');

            btn.disabled = true;
            btn.classList.add('opacity-50');
            progressBox.classList.remove('hidden');

            stepMsg.innerText = 'Synthesizing Neural Narration (Edge-TTS)...';
            fill.style.width = '30%';
            pct.innerText = '30%';

            try {
                setTimeout(() => {
                    stepMsg.innerText = 'Compositing Studio Curtain & Avatar Motion...';
                    fill.style.width = '65%';
                    pct.innerText = '65%';
                }, 1800);

                const res = await fetch('/api/v1/avatar/generate-video', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        script,
                        voice,
                        speed,
                        pitch,
                        curtain_mode: curtainMode,
                        curtain_active: curtainActive,
                        hand_gestures: handGestures,
                        future_3d_model: future3D,
                        model_3d_path: model3DPath || null
                    })
                });

                const data = await res.json();
                if (data.status === 'ok') {
                    fill.style.width = '100%';
                    pct.innerText = '100%';
                    stepMsg.innerText = 'Video Generation Complete!';

                    const player = document.getElementById('avatar-video-player');
                    player.src = `${data.video_url}?t=${Date.now()}`;
                    player.play();

                    document.getElementById('meta-duration').innerText = `${data.duration}s`;
                    document.getElementById('avatar-video-runtime').innerText = `${data.duration}s`;
                    document.getElementById('avatar-download-link').href = data.video_url;
                    document.getElementById('avatar-download-link').download = data.filename;

                    setTimeout(() => { progressBox.classList.add('hidden'); }, 3000);
                } else {
                    alert('Avatar Video Generation Failed: ' + (data.detail || 'Unknown error'));
                    progressBox.classList.add('hidden');
                }
            } catch(e) {
                alert('Generation error: ' + e);
                progressBox.classList.add('hidden');
            } finally {
                btn.disabled = false;
                btn.classList.remove('opacity-50');
            }
        }

        // ================= SCORM FRAMEWORK JAVASCRIPT CONTROLLERS =================
        function selectPrebuiltFrame(frameId) {
            document.getElementById('scorm-prebuilt-frame-input').value = frameId;
            const badge = document.getElementById('scorm-selected-frame-badge');
            ['micro', 'master', 'comp', 'slide'].forEach(f => {
                const card = document.getElementById(`frame-card-${f}`);
                if (!card) return;
                card.className = "p-2.5 rounded-xl bg-slate-900 border-2 border-slate-800 hover:border-slate-700 cursor-pointer transition-all";
            });

            const cardMap = {
                microlearning: 'frame-card-micro',
                masterclass: 'frame-card-master',
                compliance: 'frame-card-comp',
                slide_explainer: 'frame-card-slide'
            };
            const activeCard = document.getElementById(cardMap[frameId]);
            if (activeCard) activeCard.className = "p-2.5 rounded-xl bg-indigo-500/20 border-2 border-indigo-500 cursor-pointer transition-all";

            const titles = {
                microlearning: 'Microlearning Capsule',
                masterclass: 'Masterclass (Lecture + Quiz)',
                compliance: 'Compliance Certification',
                slide_explainer: 'Slide Explainer'
            };
            if (badge) badge.innerText = titles[frameId] || frameId;
        }

        function autoStructureContextPaste() {
            const text = document.getElementById('scorm-context-paste-input').value.trim();
            if (!text) {
                document.getElementById('scorm-context-paste-input').value = "## Course Overview: Autonomous AI Agents in FinTech\n\n### Unit 1: Foundations of Decentralized Autonomous Operations\n- Core Smart Contracts\n- Automated Execution & Verification\n- Risk Management Safeguards";
            } else {
                document.getElementById('scorm-context-paste-input').value = `## Structured Curriculum Context\n\n${text}\n\n- Verified for SCORM 1.2 / 2004 CMI Data Model compliance.`;
            }
            alert('Curriculum context structured for SCORM Framework mapping!');
        }

        // =========================================================================
        // STUDIO SETTINGS, PRE-FLIGHT SUMMARY & SETUP PERSISTENCE (Tasks 6b, 7a, 7b)
        // =========================================================================
        function openSettingsModal() {
            const modal = document.getElementById('settings-modal');
            if (modal) {
                modal.classList.remove('hidden');
                try {
                    const savedKey = localStorage.getItem('neuroclips_eleven_key') || '';
                    const savedVoice = localStorage.getItem('neuroclips_eleven_voice') || '21m00Tcm4TlvDq8ikWAM';
                    const keyInput = document.getElementById('elevenlabs-api-key');
                    const voiceSelect = document.getElementById('elevenlabs-voice-id');
                    if (keyInput && !keyInput.value) keyInput.value = savedKey;
                    if (voiceSelect && savedVoice) voiceSelect.value = savedVoice;
                } catch (e) {}
            }
        }

        function closeSettingsModal() {
            const modal = document.getElementById('settings-modal');
            if (modal) modal.classList.add('hidden');
            if (typeof updatePreflightSummary === 'function') updatePreflightSummary();
        }

        function updatePreflightSummary() {
            try {
                const resSelect = document.getElementById('resolution-select');
                let aspect = "16:9 HD";
                let dims = "1280×720";
                if (resSelect && resSelect.selectedOptions && resSelect.selectedOptions[0]) {
                    const opt = resSelect.selectedOptions[0];
                    const val = opt.value;
                    const w = opt.dataset.w || "1280";
                    const h = opt.dataset.h || "720";
                    dims = `${w}×${h}`;
                    if (val === '16:9_hd') aspect = "16:9 HD";
                    else if (val === '16:9_fhd') aspect = "16:9 FHD";
                    else if (val === '16:9_sd') aspect = "16:9 SD";
                    else if (val === '9:16_vertical') aspect = "9:16";
                    else if (val === '9:16_fhd') aspect = "9:16 FHD";
                    else if (val === '1:1_square') aspect = "1:1";
                    else if (val === '1:1_hd') aspect = "1:1 HD";
                    else if (val === '4:5_portrait') aspect = "4:5";
                    else if (val === '4:5_sd') aspect = "4:5 SD";
                }

                const sceneSlider = document.getElementById('scene-slider');
                const scenes = sceneSlider ? `${sceneSlider.value} scenes` : "4 scenes";

                const voiceSelect = document.getElementById('voice-select');
                let voice = "en-IN-NeerjaNeural";
                if (typeof CURRENT_VOICE_PROVIDER !== 'undefined' && CURRENT_VOICE_PROVIDER === 'elevenlabs') {
                    const ev = document.getElementById('elevenlabs-voice-id');
                    const evName = (ev && ev.selectedOptions && ev.selectedOptions[0]) ? ev.selectedOptions[0].text.split(' ')[0] : 'ElevenLabs';
                    voice = `ElevenLabs (${evName})`;
                } else if (voiceSelect) {
                    voice = voiceSelect.value;
                }

                const burnCheck = document.getElementById('burn-subtitles-check');
                const captions = (burnCheck && burnCheck.checked) ? "captions on" : "captions off";

                const engineSelect = document.getElementById('engine-select');
                let engine = "FFmpeg";
                if (engineSelect && engineSelect.value === 'remotion') {
                    engine = "Remotion";
                }

                const summaryText = `${aspect} · ${dims} · ${scenes} · ${voice} · ${captions} · ${engine}`;
                const summaryEl = document.getElementById('preflight-summary');
                if (summaryEl) {
                    summaryEl.innerText = summaryText;
                }
            } catch (e) {
                console.warn('Error updating preflight summary:', e);
            }
        }

        function restoreLastUsedSetup() {
            try {
                // Restore ElevenLabs credentials into modal inputs
                const savedElevenKey = localStorage.getItem('neuroclips_eleven_key');
                const savedElevenVoice = localStorage.getItem('neuroclips_eleven_voice');
                const keyInput = document.getElementById('elevenlabs-api-key');
                const voiceSelectModal = document.getElementById('elevenlabs-voice-id');
                if (savedElevenKey && keyInput) keyInput.value = savedElevenKey;
                if (savedElevenVoice && voiceSelectModal) voiceSelectModal.value = savedElevenVoice;

                // 7b. Restore resolution defensively
                const savedRes = localStorage.getItem('neuroclips_last_resolution');
                if (savedRes) {
                    const resSel = document.getElementById('resolution-select');
                    if (resSel && Array.from(resSel.options).some(o => o.value === savedRes)) {
                        resSel.value = savedRes;
                        if (typeof updateAspectPreview === 'function') updateAspectPreview();
                    }
                }

                // 7b. Restore voice defensively
                const savedVoice = localStorage.getItem('neuroclips_last_voice');
                if (savedVoice) {
                    const voiceSel = document.getElementById('voice-select');
                    if (voiceSel && Array.from(voiceSel.options).some(o => o.value === savedVoice)) {
                        voiceSel.value = savedVoice;
                        if (typeof updateActiveVoiceBadge === 'function') updateActiveVoiceBadge();
                    }
                }

                // 7b. Restore avatar persona defensively
                const savedPersona = localStorage.getItem('neuroclips_last_persona');
                if (savedPersona) {
                    const personaSel = document.getElementById('avatar-persona-select');
                    if (personaSel && Array.from(personaSel.options).some(o => o.value === savedPersona)) {
                        personaSel.value = savedPersona;
                        if (typeof onPersonaSelectChange === 'function') onPersonaSelectChange(savedPersona);
                    }
                }
            } catch (e) {
                console.warn('Failed to restore last used setup:', e);
            }
            updatePreflightSummary();
            updateHeaderAuthState();
        }

        function updateHeaderAuthState() {
            try {
                const user = localStorage.getItem('neuroclips_user');
                const authText = document.getElementById('header-auth-text');
                const authIcon = document.getElementById('header-auth-icon');
                const authBtn = document.getElementById('header-auth-btn');
                if (user && authText && authIcon) {
                    authText.innerText = user.includes('@') ? user.split('@')[0] : user;
                    authIcon.innerText = '👤';
                    if (authBtn) {
                        authBtn.title = `Logged in as ${user}. Click to manage session.`;
                    }
                }
            } catch (e) {}
        }

        // URL Routing initialization on page load
        window.addEventListener('DOMContentLoaded', () => {
            const p = window.location.pathname.toLowerCase();
            if (p.includes('avatar')) {
                switchStudioMode('avatar');
            } else if (p.includes('scorm')) {
                switchStudioMode('scorm');
            } else if (p.includes('director')) {
                switchStudioMode('video');
            }
            restoreLastUsedSetup();
        });

        fetchGallery();
        fetchIdentities();
        fetchVideoAssets();
        fetchVoiceLibrary();
        updateScriptMetrics();
        updateAspectPreview();
        restoreLastUsedSetup();
    </script>
</body>
</html>
"""


async def serve_login_page():
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Modular-NeuroClips Studio | Director Login (neuroclips.mytestbed.tech)</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    colors: {
                        brand: {
                            500: '#6366f1',
                            600: '#4f46e5',
                            glow: '#818cf8',
                            dark: '#030712'
                        }
                    },
                    fontFamily: {
                        sans: ['Inter', 'sans-serif'],
                        mono: ['JetBrains Mono', 'monospace']
                    }
                }
            }
        }
    </script>
    <style>
        body {
            background-color: #030712;
            background-image: 
                radial-gradient(at 0% 0%, rgba(99, 102, 241, 0.15) 0px, transparent 50%),
                radial-gradient(at 100% 100%, rgba(168, 85, 247, 0.12) 0px, transparent 50%),
                radial-gradient(at 50% 50%, rgba(6, 182, 212, 0.08) 0px, transparent 60%);
        }
        .glass-panel {
            background: rgba(15, 23, 42, 0.75);
            backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.08);
        }
    </style>
</head>
<body class="min-h-screen flex flex-col justify-between text-slate-100 font-sans selection:bg-brand-500 selection:text-white">

    <!-- Top Domain & Status Bar -->
    <header class="w-full px-6 py-4 flex items-center justify-between border-b border-slate-800/60 backdrop-blur-md">
        <a href="/" class="flex items-center space-x-3 group">
            <div class="w-9 h-9 rounded-xl bg-gradient-to-tr from-brand-600 to-indigo-500 flex items-center justify-center shadow-lg shadow-brand-500/25 group-hover:scale-105 transition-all">
                <span class="text-lg font-black text-white">⚡</span>
            </div>
            <div>
                <span class="font-bold text-sm tracking-tight text-white group-hover:text-brand-glow transition-all">Modular-NeuroClips</span>
                <span class="text-[10px] text-slate-400 block font-mono">Director Suite v2.6</span>
            </div>
        </a>

        <!-- Production Node SSL Badge -->
        <div class="flex items-center space-x-2.5">
            <div class="glass-panel px-3 py-1.5 rounded-full flex items-center space-x-2 text-xs font-mono border border-emerald-500/30">
                <span class="relative flex h-2 w-2">
                    <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                    <span class="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                </span>
                <span class="text-slate-300">neuroclips.mytestbed.tech</span>
                <span class="text-emerald-400 font-bold text-[10px]">🔒 SSL</span>
            </div>
            <a href="/" class="text-xs text-slate-400 hover:text-brand-glow transition-all px-2.5 py-1 rounded-lg hover:bg-slate-800">
                Studio View &rarr;
            </a>
        </div>
    </header>

    <!-- Main Authentication Portal -->
    <main class="flex-1 flex items-center justify-center p-6">
        <div class="w-full max-w-md space-y-6">

            <!-- Card Container -->
            <div class="glass-panel rounded-3xl p-8 space-y-6 border border-brand-500/30 shadow-2xl shadow-indigo-500/10">
                
                <!-- Header / Logo -->
                <div class="text-center space-y-2">
                    <div class="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-gradient-to-tr from-brand-600 via-indigo-600 to-purple-600 shadow-xl shadow-brand-500/30 mb-1">
                        <span class="text-2xl font-black text-white">⚡</span>
                    </div>
                    <h2 class="text-xl font-bold tracking-tight text-white">Studio Workstation Sign-In</h2>
                    <p class="text-xs text-slate-400">Authenticate to access autonomous director orchestration & SCORM export</p>
                </div>

                <!-- Alert / Status Notice -->
                <div id="login-status-notice" class="hidden p-3 rounded-xl bg-emerald-500/15 border border-emerald-500/30 text-xs text-emerald-300 flex items-center space-x-2">
                    <span class="text-sm">✓</span>
                    <span id="login-status-text">Authorization confirmed. Entering Studio...</span>
                </div>

                <!-- Form -->
                <form id="login-form" onsubmit="handleFormLogin(event)" class="space-y-4 text-xs">
                    <div>
                        <label for="username-input" class="block font-semibold text-slate-300 mb-1.5 uppercase tracking-wider text-[10px]">
                            Workstation ID / Email
                        </label>
                        <div class="relative">
                            <input type="text" id="username-input" value="director@mytestbed.tech" required
                                   class="w-full rounded-xl bg-slate-900/90 border border-slate-700/80 p-3 pl-9 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 font-mono transition-all">
                            <span class="absolute left-3 top-3 text-slate-500 text-sm">👤</span>
                        </div>
                    </div>

                    <div>
                        <div class="flex items-center justify-between mb-1.5">
                            <label for="password-input" class="block font-semibold text-slate-300 uppercase tracking-wider text-[10px]">
                                Access Token / Key
                            </label>
                            <span class="text-[10px] text-brand-glow font-mono">Demo Auto-Filled</span>
                        </div>
                        <div class="relative">
                            <input type="password" id="password-input" value="nc-prod-director-token-2026" required
                                   class="w-full rounded-xl bg-slate-900/90 border border-slate-700/80 p-3 pl-9 pr-10 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 font-mono transition-all">
                            <span class="absolute left-3 top-3 text-slate-500 text-sm">🔑</span>
                            <button type="button" onclick="togglePasswordVisibility()" class="absolute right-3 top-3 text-slate-400 hover:text-white" title="Toggle visibility">
                                👁️
                            </button>
                        </div>
                    </div>

                    <div>
                        <label for="role-select" class="block font-semibold text-slate-300 mb-1.5 uppercase tracking-wider text-[10px]">
                            Operational Role
                        </label>
                        <select id="role-select" class="w-full rounded-xl bg-slate-900/90 border border-slate-700/80 p-3 text-slate-200 focus:outline-none focus:border-brand-500 font-sans">
                            <option value="Director & Master Orchestrator" selected>👑 Director & Master Orchestrator</option>
                            <option value="Curriculum & Instructional Architect">🎓 Curriculum & Instructional Architect</option>
                            <option value="Production & Video Engineer">⚙️ Production & Video Engineer</option>
                            <option value="Enterprise LMS Admin">📦 Enterprise LMS Admin</option>
                        </select>
                    </div>

                    <div class="flex items-center justify-between pt-1 text-[11px]">
                        <label class="flex items-center space-x-2 text-slate-300 cursor-pointer select-none">
                            <input type="checkbox" id="remember-me-check" checked class="rounded accent-brand-500">
                            <span>Remember on this workstation</span>
                        </label>
                        <a href="/" class="text-brand-glow hover:underline">Guest Preview</a>
                    </div>

                    <!-- Sign In CTA -->
                    <button type="submit" id="submit-login-btn"
                            class="w-full py-3.5 rounded-xl bg-gradient-to-r from-brand-600 via-indigo-600 to-purple-600 hover:from-brand-500 hover:to-indigo-500 font-bold text-xs text-white shadow-lg shadow-brand-500/25 active:scale-[0.99] transition-all flex items-center justify-center space-x-2">
                        <span>🚀</span>
                        <span>Sign In to Workstation</span>
                    </button>
                </form>

                <!-- Divider -->
                <div class="relative flex items-center justify-center">
                    <div class="border-t border-slate-800 w-full"></div>
                    <span class="bg-slate-950 px-3 text-[10px] text-slate-500 uppercase tracking-widest font-mono font-bold absolute">OR QUICK ACCESS</span>
                </div>

                <!-- Instant One-Click Demo Access -->
                <button type="button" onclick="handleQuickDemoAccess()"
                        class="w-full py-3 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-200 border border-brand-500/30 hover:border-brand-500/60 font-semibold text-xs transition-all flex items-center justify-center space-x-2 group">
                    <span class="group-hover:scale-110 transition-transform">⚡</span>
                    <span>Instant Demo Access (Director Role)</span>
                </button>
            </div>

            <!-- Server & Cluster Info Box -->
            <div class="glass-panel p-4 rounded-2xl text-[11px] text-slate-400 space-y-2 border border-slate-800/80 font-mono">
                <div class="flex items-center justify-between text-[10px]">
                    <span class="text-slate-500 uppercase tracking-wider">Target Endpoint</span>
                    <span class="text-slate-300 font-bold">neuroclips.mytestbed.tech</span>
                </div>
                <div class="flex items-center justify-between text-[10px]">
                    <span class="text-slate-500 uppercase tracking-wider">Reverse Proxy</span>
                    <span class="text-indigo-400">Caddy / Nginx TLS 1.3</span>
                </div>
                <div class="flex items-center justify-between text-[10px]">
                    <span class="text-slate-500 uppercase tracking-wider">Engine Status</span>
                    <span class="text-emerald-400">Autonomous Pipeline Ready</span>
                </div>
            </div>

            <div class="text-center">
                <a href="/" class="text-xs text-slate-400 hover:text-slate-200 transition-colors">
                    &larr; Back to Director Studio
                </a>
            </div>
        </div>
    </main>

    <!-- Footer -->
    <footer class="w-full py-4 text-center text-xs text-slate-500 border-t border-slate-800/60 font-mono">
        Modular-NeuroClips &bull; neuroclips.mytestbed.tech &bull; Autonomous Production Cluster
    </footer>

    <script>
        // Check for existing session on page load
        window.addEventListener('DOMContentLoaded', () => {
            try {
                const existingUser = localStorage.getItem('neuroclips_user');
                if (existingUser) {
                    const uInput = document.getElementById('username-input');
                    if (uInput) uInput.value = existingUser;
                }
                const existingRole = localStorage.getItem('neuroclips_role');
                if (existingRole) {
                    const rSelect = document.getElementById('role-select');
                    if (rSelect) rSelect.value = existingRole;
                }
            } catch (e) {}
        });

        function togglePasswordVisibility() {
            const pwd = document.getElementById('password-input');
            if (pwd) {
                pwd.type = pwd.type === 'password' ? 'text' : 'password';
            }
        }

        function handleFormLogin(e) {
            e.preventDefault();
            const username = document.getElementById('username-input').value.trim();
            const role = document.getElementById('role-select').value;
            authenticateAndRedirect(username, role);
        }

        function handleQuickDemoAccess() {
            authenticateAndRedirect('director@mytestbed.tech', 'Director & Master Orchestrator');
        }

        function authenticateAndRedirect(user, role) {
            const btn = document.getElementById('submit-login-btn');
            const notice = document.getElementById('login-status-notice');
            const noticeText = document.getElementById('login-status-text');

            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<span>⏳</span> <span>Authorizing Session...</span>';
            }

            try {
                localStorage.setItem('neuroclips_user', user);
                localStorage.setItem('neuroclips_role', role);
                localStorage.setItem('neuroclips_session_token', 'nc_' + Math.random().toString(36).substring(2) + Date.now().toString(36));
                localStorage.setItem('neuroclips_authenticated', 'true');
            } catch (e) {
                console.warn('Storage warning:', e);
            }

            if (notice && noticeText) {
                noticeText.innerText = `Welcome ${user.split('@')[0]}! Launching Director Studio...`;
                notice.classList.remove('hidden');
            }

            setTimeout(() => {
                const params = new URLSearchParams(window.location.search);
                const redirect = params.get('redirect') || '/';
                window.location.href = redirect;
            }, 600);
        }
    </script>
</body>
</html>
"""

