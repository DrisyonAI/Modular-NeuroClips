import os
import time
import json
import uuid
import zipfile
import asyncio
from pathlib import Path
from typing import Dict, List, Any, Optional
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

app = FastAPI(title="Modular-NeuroClips Studio & VPS Control Plane", version="2.6.0")

app.mount("/static_renders", StaticFiles(directory=str(OUTPUT_DIR)), name="static_renders")
app.mount("/static_curriculum", StaticFiles(directory=str(CURRICULUM_OUTPUT_DIR)), name="static_curriculum")
app.mount("/static_exports", StaticFiles(directory=str(EXPORTS_DIR)), name="static_exports")
app.mount("/static_assets", StaticFiles(directory=str(ASSETS_DIR)), name="static_assets")

try:
    import psutil
except ImportError:
    psutil = None

try:
    import pynvml
    pynvml.nvmlInit()
    GPU_AVAILABLE = True
except Exception:
    pynvml = None
    GPU_AVAILABLE = False

def get_system_telemetry():
    vram_used = 0
    vram_total = 0
    gpu_util = 0
    gpu_name = "NVIDIA GeForce (CUDA)" if GPU_AVAILABLE else "CPU / Virtual Mode"
    
    if GPU_AVAILABLE:
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            name = pynvml.nvmlDeviceGetName(handle)
            gpu_name = name.decode("utf-8") if isinstance(name, bytes) else str(name)
            vram_used = round(info.used / (1024 ** 2), 2)
            vram_total = round(info.total / (1024 ** 2), 2)
            gpu_util = util.gpu
        except Exception:
            pass
    
    cpu_percent = psutil.cpu_percent(interval=None) if hasattr(psutil, 'cpu_percent') else 0
    ram = psutil.virtual_memory() if hasattr(psutil, 'virtual_memory') else None
    
    return {
        "gpu": {
            "name": gpu_name,
            "used_mb": vram_used,
            "total_mb": vram_total,
            "utilization": gpu_util,
            "available": GPU_AVAILABLE
        },
        "system": {
            "cpu_percent": cpu_percent,
            "ram_used_gb": round(ram.used / (1024 ** 3), 2) if ram else 0,
            "ram_total_gb": round(ram.total / (1024 ** 3), 2) if ram else 0,
            "ram_percent": ram.percent if ram else 0
        },
        "timestamp": time.time()
    }

MILESTONES = [
    {"id": "init", "name": "Initialization", "description": "Setting up generation pipeline & allocating VRAM"},
    {"id": "scripting", "name": "Llama 3 Scripting", "description": "Generating directorial multi-scene screenplay"},
    {"id": "keyframes", "name": "Keyframe Synthesis", "description": "Generating image keyframes matching prompt"},
    {"id": "animation", "name": "Motion Dynamics", "description": "Rendering camera motion video clips"},
    {"id": "voiceover", "name": "Edge-TTS Voiceover", "description": "Synthesizing neural voice narration audio"},
    {"id": "compilation", "name": "Engine Compilation", "description": "Stitching scenes, subtitles & audio sync"},
    {"id": "complete", "name": "Completed", "description": "Production ready for playback, SRT & SCORM export"}
]

JOBS_DB: Dict[str, Dict[str, Any]] = {}
ACTIVE_JOB_ID: Optional[str] = None

PIPELINE_STATE = {
    "status": "Idle",
    "current_step": "Ready for jobs",
    "last_error": None,
    "model_load_latency": 0.0,
    "processed_scenes": 0,
    "total_scenes": 0,
    "current_milestone": "init",
    "progress_percent": 0
}

def create_tracked_job(topic: str, scene_count: int, art_style: str, resolution: str, voice: str, engine_type: str = "ffmpeg") -> str:
    global ACTIVE_JOB_ID
    job_id = str(uuid.uuid4())[:8]
    job = {
        "job_id": job_id,
        "topic": topic,
        "scene_count": scene_count,
        "art_style": art_style,
        "resolution": resolution,
        "voice": voice,
        "engine_type": engine_type,
        "status": "in_progress",
        "current_milestone": "init",
        "current_step": "Initializing pipeline",
        "progress_percent": 5,
        "processed_scenes": 0,
        "total_scenes": scene_count,
        "script": None,
        "clip_paths": [],
        "keyframe_paths": [],
        "audio_paths": [],
        "srt_path": None,
        "output_path": None,
        "created_at": time.time(),
        "updated_at": time.time(),
        "logs": [f"[{time.strftime('%H:%M:%S')}] Job #{job_id} initiated: '{topic[:40]}...' ({resolution}, {engine_type})"],
        "milestones": {m["id"]: "pending" for m in MILESTONES}
    }
    job["milestones"]["init"] = "in_progress"
    JOBS_DB[job_id] = job
    ACTIVE_JOB_ID = job_id
    
    PIPELINE_STATE["status"] = "Generating Script"
    PIPELINE_STATE["current_step"] = "Job queued and initializing"
    PIPELINE_STATE["current_milestone"] = "init"
    PIPELINE_STATE["progress_percent"] = 5
    PIPELINE_STATE["total_scenes"] = scene_count
    PIPELINE_STATE["processed_scenes"] = 0
    return job_id

def log_job_milestone(job_id: str, milestone_id: str, step_msg: str, progress: int, log_text: Optional[str] = None):
    if job_id not in JOBS_DB:
        return
    job = JOBS_DB[job_id]
    job["current_milestone"] = milestone_id
    job["current_step"] = step_msg
    job["progress_percent"] = progress
    job["updated_at"] = time.time()
    
    found = False
    for m in MILESTONES:
        if m["id"] == milestone_id:
            job["milestones"][m["id"]] = "in_progress"
            found = True
        elif not found:
            job["milestones"][m["id"]] = "completed"
        else:
            job["milestones"][m["id"]] = "pending"
            
    if log_text:
        job["logs"].append(f"[{time.strftime('%H:%M:%S')}] {log_text}")
        
    PIPELINE_STATE["status"] = f"Milestone: {milestone_id.capitalize()}"
    PIPELINE_STATE["current_step"] = step_msg
    PIPELINE_STATE["current_milestone"] = milestone_id
    PIPELINE_STATE["progress_percent"] = progress

def generate_voiceover_audio_sync(
    text: str,
    voice: str,
    speech_rate: float,
    output_path: Path,
    pitch: str = "+0Hz",
    volume: str = "+0%",
    voice_provider: str = "edge_tts",
    elevenlabs_api_key: Optional[str] = None,
    elevenlabs_voice_id: Optional[str] = "21m00Tcm4TlvDq8ikWAM",
    stability: float = 0.75,
    similarity_boost: float = 0.75
) -> bool:
    """
    Generates voiceover narration supporting Edge-TTS with pitch/rate/volume prosody
    and ElevenLabs multilingual neural synthesis with stability/similarity control.
    """
    clean_text = text.strip()
    if not clean_text:
        return False

    # 1. ElevenLabs Neural Provider
    if voice_provider == "elevenlabs" and elevenlabs_api_key and elevenlabs_api_key.strip():
        try:
            voice_id = elevenlabs_voice_id or "21m00Tcm4TlvDq8ikWAM"
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
            headers = {
                "xi-api-key": elevenlabs_api_key.strip(),
                "Content-Type": "application/json",
                "Accept": "audio/mpeg"
            }
            # Clean director tags for ElevenLabs input
            raw_script = re.sub(r"\[pause\s+\w+\]", " ... ", clean_text, flags=re.IGNORECASE)
            raw_script = re.sub(r"\[emphasis\]", "", raw_script, flags=re.IGNORECASE)
            payload = {
                "text": raw_script,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": float(stability),
                    "similarity_boost": float(similarity_boost),
                    "style": 0.0,
                    "use_speaker_boost": True
                }
            }
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                audio_data = resp.read()
                if audio_data and len(audio_data) > 500:
                    with open(output_path, "wb") as f:
                        f.write(audio_data)
                    return True
        except Exception as e:
            print(f"[ElevenLabs Warning] Synthesis error ({e}). Falling back to Edge-TTS.")

    # 2. Edge-TTS High-Definition Neural Voice with Prosody Pitch & Speed
    try:
        import edge_tts
        rate_str = f"{int((speech_rate - 1.0) * 100):+d}%"
        # Parse natural pauses: replace [pause 500ms] with brief ellipses
        formatted_text = re.sub(r"\[pause\s+(\d+)m?s?\]", r" ... ", clean_text, flags=re.IGNORECASE)
        formatted_text = re.sub(r"\[emphasis\]", "", formatted_text, flags=re.IGNORECASE)
        formatted_text = re.sub(r"\[protip\]", "Pro tip: ", formatted_text, flags=re.IGNORECASE)
        
        async def _save_tts():
            communicate = edge_tts.Communicate(formatted_text, voice, rate=rate_str, pitch=pitch, volume=volume)
            await communicate.save(str(output_path))
            
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import nest_asyncio
                nest_asyncio.apply()
                loop.run_until_complete(_save_tts())
            else:
                loop.run_until_complete(_save_tts())
        except Exception:
            asyncio.run(_save_tts())
            
        if output_path.exists() and output_path.stat().st_size > 500:
            return True
    except Exception as e:
        print(f"[TTS Error] Edge-TTS error ({e}). Trying local fallback.")

    # 3. pyttsx3 Local Fallback
    try:
        import pyttsx3
        tts_engine = pyttsx3.init()
        tts_engine.save_to_file(clean_text, str(output_path))
        tts_engine.runAndWait()
        if output_path.exists() and output_path.stat().st_size > 100:
            return True
    except Exception:
        pass

def convert_audio_format(input_path: Path, target_format: str, output_path: Path) -> bool:
    """Converts synthesized audio to target format (MP3, WAV, M4A/AAC, OGG, FLAC) using ffmpeg."""
    target_format = target_format.lower().replace(".", "").strip()
    cmd = ["ffmpeg", "-y", "-i", str(input_path)]
    if target_format == "wav":
        cmd.extend(["-c:a", "pcm_s16le", "-ar", "44100"])
    elif target_format in ["m4a", "aac"]:
        cmd.extend(["-c:a", "aac", "-b:a", "256k"])
    elif target_format == "ogg":
        cmd.extend(["-c:a", "libvorbis", "-q:a", "6"])
    elif target_format == "flac":
        cmd.extend(["-c:a", "flac"])
    elif target_format == "mp3":
        cmd.extend(["-c:a", "libmp3lame", "-b:a", "256k"])
    else:
        cmd.extend(["-c:a", "copy"])
    cmd.append(str(output_path))
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return res.returncode == 0 and output_path.exists()

def translate_narration_text(text: str, target_lang: str) -> str:
    """Translates narration text into the target dubbing language using lightweight translation endpoint."""
    if target_lang == "en-US" or not text.strip():
        return text

    target_code = target_lang.split("-")[0]
    encoded = urllib.parse.quote(text[:450])
    try:
        url = f"https://api.mymemory.translated.net/get?q={encoded}&langpair=en|{target_code}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            translated = data.get("responseData", {}).get("translatedText")
            if translated and len(translated) > 3:
                return translated
    except Exception as e:
        print(f"[Translation Notice] Using source text ({e})")
    return text

def resolve_video_path(url_or_path: Optional[str]) -> Optional[str]:
    """Resolves a video URL (static asset or render) to an absolute local filesystem path."""
    if not url_or_path:
        return None
    s = str(url_or_path).strip()
    if not s:
        return None
    if s.startswith("/static_assets/"):
        p = ASSETS_DIR / s.replace("/static_assets/", "")
        return str(p) if p.exists() else None
    if s.startswith("/static_renders/"):
        p = OUTPUT_DIR / s.replace("/static_renders/", "")
        return str(p) if p.exists() else None
    p = Path(s)
    if p.exists():
        return str(p)
    alt = ASSETS_DIR / p.name
    if alt.exists():
        return str(alt)
    return None

async def execute_tracked_generation(
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
    similarity_boost: float = 0.75
):
    job = JOBS_DB.get(job_id)
    if not job:
        return

    if auto_clean:
        for old_f in list(OUTPUT_DIR.glob("scene_*.*")) + list(OUTPUT_DIR.glob("audio_*.*")):
            try:
                old_f.unlink(missing_ok=True)
            except Exception:
                pass
        
    res_info = RESOLUTION_PROFILES.get(resolution, RESOLUTION_PROFILES["16:9_hd"])
    width, height = res_info["width"], res_info["height"]

    engine = MediaGenerationEngine()
    orchestrator = ScriptOrchestrator()
    
    try:
        # MILESTONE 1: SCRIPTING & PROMPT DISTILLATION
        log_job_milestone(job_id, "scripting", "Director composing visual screenplay...", 15, f"Distilling visual scene prompts from user content ({width}x{height}, {art_style})")
        t0 = time.time()
        
        script = orchestrator.generate_script(
            topic=topic,
            scene_count=scene_count,
            art_style=art_style,
            avatar_persona=avatar_persona
        )
            
        latency = time.time() - t0
        job["script"] = script.model_dump() if hasattr(script, "model_dump") else script.dict()
        job["total_scenes"] = len(script.scenes)
        PIPELINE_STATE["model_load_latency"] = latency
        PIPELINE_STATE["total_scenes"] = len(script.scenes)
        log_job_milestone(job_id, "scripting", f"Script ready ({len(script.scenes)} scenes, {latency:.2f}s)", 30, f"Directorial screenplay composed: '{script.title}'")
        
        # Multi-Language Dubbing: Translate Narration if target language != en-US
        if language != "en-US":
            log_job_milestone(job_id, "scripting", f"Translating script into {language}...", 32, f"Dubbing narration into {language}")
            translated_topic = translate_narration_text(topic, language)
            topic = translated_topic
            for sc in script.scenes:
                if getattr(sc, "narration", ""):
                    sc.narration = translate_narration_text(sc.narration, language)

        # MILESTONES 2 & 3: KEYFRAMES & ANIMATION
        clip_paths, keyframe_paths = [], []
        total = len(script.scenes)
        
        for idx, scene in enumerate(script.scenes, start=1):
            job["processed_scenes"] = idx
            PIPELINE_STATE["processed_scenes"] = idx
            
            v_type = getattr(scene, "video_source_type", "ai_generated")
            v_url = getattr(scene, "video_source_url", "")
            dur = getattr(scene, "duration_seconds", 4)
            vis_prompt = getattr(scene, "visual_prompt", "")
            mot_prompt = getattr(scene, "motion_prompt", "")
            resolved_v_path = resolve_video_path(v_url) if (v_type == "uploaded_video" and v_url) else None

            if resolved_v_path:
                base_p = 30 + int(((idx - 0.5) / total) * 35)
                log_job_milestone(job_id, "keyframes", f"Extracting frame from video asset {idx}/{total}...", base_p, f"Scene {idx}: Using user video clip -> {Path(resolved_v_path).name}")
                kf_path = str(OUTPUT_DIR / f"scene_{scene.scene_id}_{job_id}_keyframe.png")
                engine.extract_video_thumbnail(resolved_v_path, Path(kf_path), width=width, height=height)
                keyframe_paths.append(kf_path)
                job["keyframe_paths"] = keyframe_paths

                anim_p = 30 + int((idx / total) * 35)
                log_job_milestone(job_id, "animation", f"Normalizing video clip {idx}/{total}...", anim_p, f"Scene {idx}: Conforming video ({dur}s, {width}x{height})")
                clip_path = engine.prepare_existing_video_clip(resolved_v_path, scene.scene_id, job_id=job_id, target_duration=float(dur), width=width, height=height)
                clip_paths.append(clip_path)
                job["clip_paths"] = clip_paths
            else:
                base_p = 30 + int(((idx - 0.5) / total) * 35)
                log_job_milestone(job_id, "keyframes", f"Synthesizing keyframe {idx}/{total}...", base_p, f"Scene {idx}: Visual Prompt -> {vis_prompt[:60]}...")
                full_prompt = f"{script.art_style_preset}, {vis_prompt}"
                kf_path = engine.generate_image_keyframe(full_prompt, scene.scene_id, job_id=job_id, width=width, height=height, force_refresh=True)
                keyframe_paths.append(kf_path)
                job["keyframe_paths"] = keyframe_paths
                
                anim_p = 30 + int((idx / total) * 35)
                log_job_milestone(job_id, "animation", f"Animating scene {idx}/{total}...", anim_p, f"Scene {idx}: Motion -> {mot_prompt[:50]}...")
                clip_path = engine.generate_video_clip(kf_path, mot_prompt, scene.scene_id, job_id=job_id, width=width, height=height, force_refresh=True)
                clip_paths.append(clip_path)
                job["clip_paths"] = clip_paths

        # MILESTONE 4: VOICEOVER / TTS
        audio_file = OUTPUT_DIR / f"audio_{job_id}.mp3"
        log_job_milestone(job_id, "voiceover", f"Synthesizing voiceover ({voice}, {speech_rate}x, {voice_provider})...", 75, f"Generating neural voice narration for '{script.title}'")
        
        tts_ok = generate_voiceover_audio_sync(
            text=topic,
            voice=voice,
            speech_rate=speech_rate,
            output_path=audio_file,
            pitch=pitch,
            volume=volume,
            voice_provider=voice_provider,
            elevenlabs_api_key=elevenlabs_api_key,
            elevenlabs_voice_id=elevenlabs_voice_id,
            stability=stability,
            similarity_boost=similarity_boost
        )
        if tts_ok:
            job["audio_paths"] = [str(audio_file)]
            log_job_milestone(job_id, "voiceover", "Voiceover synthesized successfully", 80, f"Generated voice audio: {audio_file.name} ({audio_file.stat().st_size / 1024:.1f} KB)")
        else:
            log_job_milestone(job_id, "voiceover", "Audio generated (silent mode)", 80, "No TTS audio generated")

        # SRT SUBTITLE GENERATION
        srt_file = OUTPUT_DIR / f"subtitles_{job_id}.srt"
        scenes_data = [
            {
                "scene_id": sc.scene_id,
                "narration": getattr(sc, "narration", "") or sc.visual_prompt,
                "visual_prompt": sc.visual_prompt,
                "duration_seconds": sc.duration_seconds
            }
            for sc in script.scenes
        ]
        generate_srt_subtitles(scenes_data, srt_file)
        job["srt_path"] = str(srt_file)

        # MILESTONE 5: COMPILATION
        log_job_milestone(job_id, "compilation", f"Compiling via {compiler_engine.upper()} engine...", 88, f"Executing multi-layer compositing (subtitles: {burn_subtitles}, avatar: {avatar_persona})")
        output_filename = f"prod_{job_id}_{int(time.time())}.mp4"
        audio_param = str(audio_file) if (audio_file.exists() and audio_file.stat().st_size > 100) else None
        
        avatar_img_path = None
        if avatar_persona == "custom_upload":
            custom_p = OUTPUT_DIR / "custom_avatar.png"
            if custom_p.exists():
                avatar_img_path = str(custom_p)
        
        remotion_meta = {
            "title": script.title,
            "art_style_preset": script.art_style_preset,
            "scenes": [
                {
                    "scene_id": sc.scene_id,
                    "keyframe_path": keyframe_paths[i] if i < len(keyframe_paths) else "",
                    "visual_prompt": sc.visual_prompt,
                    "motion_prompt": sc.motion_prompt,
                    "narration": getattr(sc, "narration", "") or sc.visual_prompt,
                    "duration_seconds": sc.duration_seconds
                }
                for i, sc in enumerate(script.scenes)
            ]
        }
        
        final_video = compile_final_video(
            clip_paths,
            output_filename=output_filename,
            audio_path=audio_param,
            engine=compiler_engine,
            avatar_image_path=avatar_img_path,
            avatar_layout=avatar_layout,
            burn_subtitles=burn_subtitles,
            srt_path=str(srt_file),
            remotion_metadata=remotion_meta,
            intro_video_path=resolve_video_path(intro_video_url),
            outro_video_path=resolve_video_path(outro_video_url)
        )
        
        # MILESTONE 6: COMPLETE
        job["status"] = "complete"
        job["output_path"] = final_video
        job["progress_percent"] = 100
        job["milestones"] = {m["id"]: "completed" for m in MILESTONES}
        log_job_milestone(job_id, "complete", f"Video ready: {Path(final_video).name}", 100, f"[SUCCESS] Production finished: {final_video}")
        PIPELINE_STATE["status"] = "Complete"
        PIPELINE_STATE["current_step"] = f"Saved: {Path(final_video).name}"
        
    except Exception as exc:
        job["status"] = "failed"
        job["logs"].append(f"[{time.strftime('%H:%M:%S')}] [ERROR] Pipeline failed: {str(exc)}")
        PIPELINE_STATE["status"] = "Failed"
        PIPELINE_STATE["last_error"] = str(exc)
        PIPELINE_STATE["current_step"] = f"Error: {str(exc)}"
        VRAMGuard.cleanup()

# -------------------------------------------------------------
# REST API Endpoints
# -------------------------------------------------------------
class GenerationRequest(BaseModel):
    topic: str
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
        engine_type=req.compiler_engine
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
        "asset_status": "Synthesizing",
        "script_words": word_count,
        "spoken_min": spoken_min,
        "gap_vs_runtime_min": runtime_gap
    }
    
    background_tasks.add_task(
        execute_tracked_generation,
        job_id=job_id,
        topic=req.topic,
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
        similarity_boost=req.similarity_boost or 0.75
    )
    
    return {"status": "started", "job_id": job_id, "topic": req.topic, "scenes": req.scenes, "meta": job["curriculum_meta"]}

class StoryboardPreviewRequest(BaseModel):
    topic: str
    scenes: int = 3
    art_style: str = "Cinematic 35mm (Volumetric Lighting)"
    avatar_persona: str = "maya_fintech"

@app.post("/api/v1/storyboard/preview")
async def preview_storyboard_api(req: StoryboardPreviewRequest):
    orchestrator = ScriptOrchestrator()
    script = orchestrator.generate_script(
        topic=req.topic,
        scene_count=req.scenes,
        art_style=req.art_style,
        avatar_persona=req.avatar_persona
    )
    return {"status": "ok", "script": script.model_dump() if hasattr(script, "model_dump") else script.dict()}

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
        engine_type=req.compiler_engine
    )

    async def _run_custom_storyboard():
        job = JOBS_DB[job_id]
        engine = MediaGenerationEngine()
        res_info = RESOLUTION_PROFILES.get(req.resolution, RESOLUTION_PROFILES["16:9_hd"])
        width, height = res_info["width"], res_info["height"]

        try:
            log_job_milestone(job_id, "scripting", "Ingesting refined storyboard scenes...", 20, f"Screenplay: '{req.title}' ({len(req.scenes)} scenes)")
            job["script"] = {"title": req.title, "art_style_preset": req.art_style, "scenes": req.scenes}
            job["total_scenes"] = len(req.scenes)

            clip_paths, keyframe_paths = [], []
            total = len(req.scenes)

            for idx, scene in enumerate(req.scenes, start=1):
                job["processed_scenes"] = idx
                PIPELINE_STATE["processed_scenes"] = idx

                v_type = scene.get("video_source_type", "ai_generated")
                v_url = scene.get("video_source_url", "")
                dur = float(scene.get("duration_seconds", 4))
                vis_prompt = scene.get("visual_prompt", "")
                mot_prompt = scene.get("motion_prompt", "")

                resolved_v_path = resolve_video_path(v_url) if (v_type == "uploaded_video" and v_url) else None

                if resolved_v_path:
                    base_p = 25 + int(((idx - 0.5) / total) * 40)
                    log_job_milestone(job_id, "keyframes", f"Extracting frame from video asset {idx}/{total}...", base_p, f"Scene {idx}: Using user video asset -> {Path(resolved_v_path).name}")
                    kf_path = str(OUTPUT_DIR / f"scene_{scene.get('scene_id', idx)}_{job_id}_keyframe.png")
                    engine.extract_video_thumbnail(resolved_v_path, Path(kf_path), width=width, height=height)
                    keyframe_paths.append(kf_path)
                    job["keyframe_paths"] = keyframe_paths

                    anim_p = 25 + int((idx / total) * 40)
                    log_job_milestone(job_id, "animation", f"Normalizing video clip {idx}/{total}...", anim_p, f"Scene {idx}: Conforming video ({dur}s, {width}x{height})")
                    clip_path = engine.prepare_existing_video_clip(resolved_v_path, scene.get("scene_id", idx), job_id=job_id, target_duration=dur, width=width, height=height)
                    clip_paths.append(clip_path)
                    job["clip_paths"] = clip_paths
                else:
                    base_p = 25 + int(((idx - 0.5) / total) * 40)
                    log_job_milestone(job_id, "keyframes", f"Synthesizing keyframe {idx}/{total}...", base_p, f"Scene {idx}: Visual -> {vis_prompt[:50]}...")
                    full_prompt = f"{req.art_style}, {vis_prompt}"
                    kf_path = engine.generate_image_keyframe(full_prompt, scene.get("scene_id", idx), job_id=job_id, width=width, height=height, force_refresh=True)
                    keyframe_paths.append(kf_path)
                    job["keyframe_paths"] = keyframe_paths

                    anim_p = 25 + int((idx / total) * 40)
                    log_job_milestone(job_id, "animation", f"Animating scene {idx}/{total}...", anim_p, f"Scene {idx}: Motion -> {mot_prompt[:50]}...")
                    clip_path = engine.generate_video_clip(kf_path, mot_prompt, scene.get("scene_id", idx), job_id=job_id, width=width, height=height, force_refresh=True)
                    clip_paths.append(clip_path)
                    job["clip_paths"] = clip_paths

            audio_file = OUTPUT_DIR / f"audio_{job_id}.mp3"
            log_job_milestone(job_id, "voiceover", f"Generating voiceover for refined storyboard ({req.voice_provider})...", 75, "Synthesizing audio")
            generate_voiceover_audio_sync(
                text=full_narration or req.title,
                voice=req.voice,
                speech_rate=req.speech_rate,
                output_path=audio_file,
                pitch=req.pitch or "+0Hz",
                volume=req.volume or "+0%",
                voice_provider=req.voice_provider or "edge_tts",
                elevenlabs_api_key=req.elevenlabs_api_key,
                elevenlabs_voice_id=req.elevenlabs_voice_id,
                stability=req.stability or 0.75,
                similarity_boost=req.similarity_boost or 0.75
            )
            job["audio_paths"] = [str(audio_file)]

            srt_file = OUTPUT_DIR / f"subtitles_{job_id}.srt"
            generate_srt_subtitles(req.scenes, srt_file)
            job["srt_path"] = str(srt_file)

            avatar_img_path = None
            if req.avatar_persona == "custom_upload":
                custom_p = OUTPUT_DIR / "custom_avatar.png"
                if custom_p.exists():
                    avatar_img_path = str(custom_p)

            log_job_milestone(job_id, "compilation", f"Compiling via {req.compiler_engine.upper()}...", 88, "Stitching clips & audio sync")
            output_filename = f"prod_{job_id}_{int(time.time())}.mp4"
            audio_param = str(audio_file) if (audio_file.exists() and audio_file.stat().st_size > 100) else None

            remotion_meta = {
                "title": req.title,
                "art_style_preset": req.art_style,
                "scenes": [
                    {
                        "scene_id": sc.get("scene_id", i+1),
                        "keyframe_path": keyframe_paths[i],
                        "visual_prompt": sc.get("visual_prompt", ""),
                        "motion_prompt": sc.get("motion_prompt", ""),
                        "narration": sc.get("narration", ""),
                        "duration_seconds": sc.get("duration_seconds", 4)
                    }
                    for i, sc in enumerate(req.scenes)
                ]
            }

            final_video = compile_final_video(
                clip_paths,
                output_filename=output_filename,
                audio_path=audio_param,
                engine=req.compiler_engine,
                avatar_image_path=avatar_img_path,
                avatar_layout=req.avatar_layout,
                burn_subtitles=req.burn_subtitles,
                srt_path=str(srt_file),
                remotion_metadata=remotion_meta,
                intro_video_path=resolve_video_path(req.intro_video_url),
                outro_video_path=resolve_video_path(req.outro_video_url)
            )

            job["status"] = "complete"
            job["output_path"] = final_video
            job["progress_percent"] = 100
            job["milestones"] = {m["id"]: "completed" for m in MILESTONES}
            log_job_milestone(job_id, "complete", f"Video ready: {Path(final_video).name}", 100, f"[SUCCESS] Storyboard production finished: {final_video}")
            PIPELINE_STATE["status"] = "Complete"
            PIPELINE_STATE["current_step"] = f"Saved: {Path(final_video).name}"

        except Exception as exc:
            job["status"] = "failed"
            job["logs"].append(f"[{time.strftime('%H:%M:%S')}] [ERROR] Storyboard pipeline failed: {str(exc)}")
            PIPELINE_STATE["status"] = "Failed"
            PIPELINE_STATE["last_error"] = str(exc)
            VRAMGuard.cleanup()

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
    return {
        "status": "ok",
        "avatar_url": f"/static_renders/{custom_avatar_path.name}?t={int(time.time())}",
        "message": "Custom avatar uploaded and active."
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

@app.post("/api/v1/scorm/export/{filename}")
async def export_scorm_package(filename: str):
    video_path = OUTPUT_DIR / filename
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video file not found")
        
    package_name = f"SCORM_{video_path.stem}.zip"
    zip_path = EXPORTS_DIR / package_name
    
    manifest_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="Course_{video_path.stem}" version="1.0" xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2">
  <organizations default="org1">
    <organization identifier="org1">
      <title>{video_path.stem.replace('_', ' ').title()}</title>
      <item identifier="item1" identifierref="resource1">
        <title>Module Video Lesson</title>
      </item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="resource1" type="webcontent" adlcp:scormtype="sco" href="index.html">
      <file href="index.html"/>
      <file href="{filename}"/>
    </resource>
  </resources>
</manifest>
"""
    player_html = f"""<!DOCTYPE html>
<html>
<head>
  <title>{video_path.stem}</title>
  <style>body {{ margin:0; background:#0f172a; display:flex; justify-content:center; align-items:center; height:100vh; }} video {{ max-width:90%; border-radius:12px; }}</style>
</head>
<body>
  <video src="{filename}" controls autoplay></video>
</body>
</html>
"""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("imsmanifest.xml", manifest_xml)
        zf.writestr("index.html", player_html)
        zf.write(video_path, arcname=filename)
        
    return {
        "status": "ok",
        "package_name": package_name,
        "download_url": f"/static_exports/{package_name}",
        "size_mb": round(zip_path.stat().st_size / (1024 ** 2), 2)
    }

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
        </div>
    </header>

    <!-- Main Container -->
    <main class="flex-1 max-w-7xl w-full mx-auto p-6 space-y-6">

        <!-- 🌟 MILESTONE PROGRESS SECTION -->
        <section class="glass-panel-glow rounded-2xl p-6 relative overflow-hidden">
            <div class="flex items-center justify-between mb-4">
                <div>
                    <h2 class="text-base font-bold text-white flex items-center gap-2">
                        <span>🎯</span> End-to-End Production Milestones
                    </h2>
                    <p class="text-xs text-slate-400">Real-time lifecycle tracking across all generative stages</p>
                </div>
                <div class="text-right">
                    <span id="overall-progress-num" class="text-2xl font-black text-brand-glow font-mono">0%</span>
                    <p id="active-step-caption" class="text-xs text-slate-400">Waiting for job</p>
                </div>
            </div>

            <div class="w-full h-2.5 bg-slate-800/80 rounded-full overflow-hidden mb-6 p-0.5 border border-slate-700/50">
                <div id="master-progress-fill" class="h-full bg-gradient-to-r from-brand-600 via-indigo-500 to-brand-glow rounded-full transition-all duration-500 shadow-lg shadow-brand-500/50" style="width: 0%"></div>
            </div>

            <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3" id="milestones-container">
            </div>
        </section>

        <!-- Studio Control Grid -->
        <div class="grid grid-cols-1 lg:grid-cols-12 gap-6">

            <!-- LEFT: Generation Studio (7 cols) -->
            <div class="lg:col-span-7 space-y-6">
                <div class="glass-panel rounded-2xl p-6 space-y-5">
                    <div class="flex items-center justify-between border-b border-slate-800 pb-3">
                        <h3 class="text-sm font-bold uppercase tracking-wider text-slate-300 flex items-center gap-2">
                            <span>🎬</span> Director Studio & Curriculum Matrix
                        </h3>
                        <span class="text-xs text-brand-glow bg-brand-500/10 px-2 py-0.5 rounded border border-brand-500/20">Prompt-to-Visual AI Synthesis</span>
                    </div>

                    <!-- Speaker Script Input with Director Toolbar & Document Ingestion -->
                    <div class="space-y-1.5">
                        <div class="flex justify-between items-center">
                            <label class="text-xs font-semibold text-slate-300">Speaker Script (Narration & Directorial Cues)</label>
                            <div class="flex items-center space-x-3">
                                <label for="script-file-upload" class="text-[10px] text-brand-glow hover:underline cursor-pointer flex items-center gap-1 font-sans">
                                    <span>📁</span> <span>Upload Document (.txt, .md, .srt)</span>
                                </label>
                                <input type="file" id="script-file-upload" class="hidden" accept=".txt,.md,.srt,.vtt,.json" onchange="handleScriptDocumentUpload(this)">
                                <span id="script-stats" class="text-[11px] font-mono text-brand-glow">0 words | ~0.0 min</span>
                            </div>
                        </div>
                        
                        <!-- Director Quick Insert Toolbar -->
                        <div class="flex items-center space-x-1.5 overflow-x-auto py-1 text-[11px]">
                            <span class="text-slate-500 font-semibold text-[10px] uppercase tracking-wider mr-1">Director Cues:</span>
                            <button type="button" onclick="insertScriptTag('[pause 500ms] ')" class="px-2 py-0.5 rounded bg-slate-800/90 text-slate-300 border border-slate-700 hover:bg-brand-500/20 hover:text-brand-glow hover:border-brand-500/30 transition-all font-mono">
                                ⏱️ [Pause 0.5s]
                            </button>
                            <button type="button" onclick="insertScriptTag('[pause 1s] ')" class="px-2 py-0.5 rounded bg-slate-800/90 text-slate-300 border border-slate-700 hover:bg-brand-500/20 hover:text-brand-glow hover:border-brand-500/30 transition-all font-mono">
                                ⏱️ [Pause 1.0s]
                            </button>
                            <button type="button" onclick="insertScriptTag('[emphasis] ')" class="px-2 py-0.5 rounded bg-slate-800/90 text-slate-300 border border-slate-700 hover:bg-brand-500/20 hover:text-brand-glow hover:border-brand-500/30 transition-all font-mono">
                                ✨ [Emphasis]
                            </button>
                            <button type="button" onclick="insertScriptTag('[protip] ')" class="px-2 py-0.5 rounded bg-slate-800/90 text-slate-300 border border-slate-700 hover:bg-brand-500/20 hover:text-brand-glow hover:border-brand-500/30 transition-all font-mono">
                                💡 [Pro Tip]
                            </button>
                        </div>

                        <textarea id="prompt-input" rows="4" oninput="updateScriptMetrics()" class="w-full rounded-xl bg-slate-900/90 border border-slate-700/80 p-3 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 transition-all font-sans" placeholder="Enter lecture topic or upload a text file (e.g. In this session, [pause 500ms] we explore algorithmic liquidity and automated dispute settlement with AI agents)..."></textarea>
                    </div>

                    <!-- Language, Resolution, Style, and Chunking Scenes -->
                    <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
                        <div>
                            <label class="block text-xs font-semibold text-slate-300 mb-1">🌐 Language & Dubbing</label>
                            <select id="language-select" onchange="onLanguageChange()" class="w-full rounded-xl bg-slate-900 border border-slate-700/80 p-2 text-xs text-slate-200 focus:outline-none focus:border-brand-500">
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
                        <div>
                            <label class="block text-xs font-semibold text-slate-300 mb-1">Resolution & Format</label>
                            <select id="resolution-select" class="w-full rounded-xl bg-slate-900 border border-slate-700/80 p-2 text-xs text-slate-200 focus:outline-none focus:border-brand-500">
                                <option value="16:9_hd" selected>16:9 HD Broadcast (1280x720)</option>
                                <option value="16:9_sd">16:9 SD Fast Preview (576x320)</option>
                                <option value="16:9_fhd">16:9 Full HD (1920x1080)</option>
                                <option value="9:16_vertical">9:16 Mobile Shorts (720x1280)</option>
                                <option value="1:1_square">1:1 LMS Widget / Square (720x720)</option>
                            </select>
                        </div>
                        <div>
                            <div class="flex justify-between text-xs font-semibold text-slate-300 mb-1">
                                <span>Scene Chunking (#)</span>
                                <span id="scene-val" class="font-mono text-brand-glow font-bold">4 Scenes</span>
                            </div>
                            <input id="scene-slider" type="range" min="1" max="16" value="4" oninput="document.getElementById('scene-val').innerText = this.value + ' Scenes'" class="w-full accent-brand-500 bg-slate-800 rounded-lg cursor-pointer">
                            <div class="flex items-center justify-between text-[10px] text-slate-400 mt-1">
                                <button type="button" onclick="setSceneChunk(3)" class="hover:text-brand-glow">Shorts (3)</button>
                                <button type="button" onclick="setSceneChunk(6)" class="hover:text-brand-glow">Standard (6)</button>
                                <button type="button" onclick="setSceneChunk(10)" class="hover:text-brand-glow">Deep (10)</button>
                                <button type="button" onclick="setSceneChunk(16)" class="hover:text-brand-glow">Master (16)</button>
                            </div>
                        </div>
                    </div>

                    <!-- Speaker Avatar Persona & Persistent Identity Row -->
                    <div class="p-3.5 rounded-xl bg-slate-950/80 border border-brand-500/20 space-y-3">
                        <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                            <span class="text-xs font-bold text-slate-300 flex items-center gap-1.5">
                                <span>👤</span> <span>Speaker Avatar & Persistent Identity</span>
                            </span>
                            <div class="flex items-center space-x-2">
                                <select id="identity-load-select" onchange="loadSelectedIdentity(this.value)" class="rounded bg-slate-900 border border-slate-700 text-[10px] text-slate-300 p-1">
                                    <option value="">📂 Load Identity Profile...</option>
                                </select>
                                <button onclick="saveCurrentIdentity()" class="text-[10px] px-2 py-0.5 rounded bg-brand-500/20 text-brand-glow border border-brand-500/30 hover:bg-brand-500/30 transition-all">
                                    💾 Save
                                </button>
                            </div>
                        </div>

                        <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
                            <div>
                                <div class="flex justify-between items-center mb-1">
                                    <label class="text-xs font-semibold text-slate-300">Avatar Persona</label>
                                    <label for="avatar-file-input" class="text-[10px] text-brand-glow hover:underline cursor-pointer flex items-center gap-0.5">
                                        <span>📸</span> <span>Upload Photo</span>
                                    </label>
                                    <input type="file" id="avatar-file-input" class="hidden" accept="image/*" onchange="uploadAvatar(this)">
                                </div>
                                <select id="avatar-persona-select" class="w-full rounded-lg bg-slate-900 border border-slate-700/80 p-1.5 text-xs text-slate-200">
                                    <option value="maya_fintech">Maya (Senior FinTech Lead)</option>
                                    <option value="alex_ai">Alex (Enterprise AI Architect)</option>
                                    <option value="elena_compliance">Elena (Risk & Governance Director)</option>
                                    <option value="david_trainer">David (Global LMS Instructor)</option>
                                    <option value="custom_upload">Custom Uploaded Portrait</option>
                                </select>
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

                            <div>
                                <label class="block text-xs font-semibold text-slate-300 mb-1">Compiler Engine</label>
                                <select id="engine-select" class="w-full rounded-lg bg-slate-900 border border-slate-700/80 p-1.5 text-xs text-slate-200">
                                    <option value="ffmpeg">Standard FFmpeg (Fast)</option>
                                    <option value="remotion">Remotion React (Broadcast Motion)</option>
                                </select>
                            </div>
                        </div>
                    </div>

                    <!-- 🎙️ NEURAL VOICE DIRECTOR STUDIO (ELEVENLABS-STYLE CONTROL DECK) -->
                    <div class="p-4 rounded-xl bg-slate-950/90 border border-brand-500/30 space-y-3.5 shadow-lg shadow-brand-500/5">
                        <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                            <div class="flex items-center space-x-2">
                                <span class="text-sm">🎙️</span>
                                <div>
                                    <span class="text-xs font-bold text-white">Neural Voice Director Studio</span>
                                    <span class="text-[10px] text-slate-400 block">Prosody, emotion tuning & dual-engine synthesis</span>
                                </div>
                            </div>
                            
                            <!-- Engine Switcher -->
                            <div class="flex rounded-lg bg-slate-900 p-0.5 border border-slate-800 text-[10px]">
                                <button type="button" id="engine-tab-edgetts" onclick="switchVoiceEngine('edge_tts')" class="px-2.5 py-1 rounded-md bg-brand-600 text-white font-bold transition-all">
                                    ⚡ Free Neural
                                </button>
                                <button type="button" id="engine-tab-elevenlabs" onclick="switchVoiceEngine('elevenlabs')" class="px-2.5 py-1 rounded-md text-slate-400 hover:text-white transition-all">
                                    👑 ElevenLabs Studio
                                </button>
                            </div>
                        </div>

                        <!-- ElevenLabs API Key / Voice ID Config (Collapsible) -->
                        <div id="elevenlabs-config-box" class="hidden p-3 rounded-lg bg-amber-500/10 border border-amber-500/30 space-y-2 text-xs">
                            <div class="flex items-center justify-between">
                                <span class="text-amber-300 font-bold text-[11px] flex items-center gap-1">
                                    <span>👑</span> <span>ElevenLabs MultiLingual V2 Credentials</span>
                                </span>
                                <span class="text-[10px] text-slate-400">Stored locally in your browser</span>
                            </div>
                            <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
                                <div>
                                    <label class="block text-[10px] text-slate-300 mb-1">ElevenLabs API Key</label>
                                    <input type="password" id="elevenlabs-api-key" placeholder="xi-api-key..." onchange="localStorage.setItem('neuroclips_eleven_key', this.value)" class="w-full rounded bg-slate-900 border border-slate-700 p-1.5 text-xs text-white">
                                </div>
                                <div>
                                    <label class="block text-[10px] text-slate-300 mb-1">Voice ID (or Cloned ID)</label>
                                    <select id="elevenlabs-voice-id" onchange="localStorage.setItem('neuroclips_eleven_voice', this.value)" class="w-full rounded bg-slate-900 border border-slate-700 p-1.5 text-xs text-white">
                                        <option value="21m00Tcm4TlvDq8ikWAM" selected>Rachel (Female - Warm & Professional)</option>
                                        <option value="pNInz6obpgDQGcFmaJgB">Adam (Male - Deep & Executive)</option>
                                        <option value="ErXwobaYiN019PkySvjV">Antoni (Male - Engaging Narrator)</option>
                                        <option value="EXAVITQu4vr4xnSDxMaL">Bella (Female - Crisp Educational)</option>
                                        <option value="TxGEqnHWrfWFTfGW9XjX">Josh (Male - Conversational Host)</option>
                                    </select>
                                </div>
                            </div>
                        </div>

                        <!-- Voice Profile & Archetype Selection -->
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                            <div id="edgetts-voice-container">
                                <div class="flex justify-between items-center mb-1">
                                    <label class="text-xs font-semibold text-slate-300">Voice Profile</label>
                                    <span class="text-[10px] text-brand-glow">HD Neural</span>
                                </div>
                                <select id="voice-select" class="w-full rounded-lg bg-slate-900 border border-slate-700/80 p-2 text-xs text-slate-200">
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
                                <label class="block text-xs font-semibold text-slate-300 mb-1">🎭 Emotion & Prosody Archetype</label>
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

                        <!-- Audition Deck & Waveform Audio Preview -->
                        <div class="flex flex-col sm:flex-row items-center justify-between gap-2.5 p-2.5 rounded-lg bg-slate-900/90 border border-slate-800 text-xs">
                            <div class="flex items-center space-x-2 w-full sm:w-auto">
                                <button type="button" onclick="auditionVoiceDirector()" id="audition-btn" class="px-3 py-1.5 rounded-lg bg-gradient-to-r from-brand-600 to-indigo-600 text-white font-bold hover:brightness-110 transition-all flex items-center gap-1.5 shadow-md shadow-brand-500/20 whitespace-nowrap">
                                    <span>🔊</span> <span>Audition Voice Line</span>
                                </button>
                                <span id="audition-status" class="text-[11px] text-slate-400 font-mono">Ready</span>
                            </div>
                            <audio id="director-audio-player" controls class="h-7 w-full sm:w-64 accent-brand-500" style="filter: invert(1) hue-rotate(180deg) brightness(0.85);"></audio>
                        </div>

                        <!-- 🎧 Standalone Audio Master & Subtitle Export -->
                        <div class="p-3 rounded-lg bg-slate-900/95 border border-emerald-500/30 space-y-2.5 text-xs">
                            <div class="flex items-center justify-between">
                                <span class="text-emerald-400 font-bold flex items-center gap-1.5">
                                    <span>🎧</span> <span>Export Standalone Audio Master</span>
                                </span>
                                <span class="text-[10px] text-slate-400">Generate high-fidelity audio + subtitles without video</span>
                            </div>
                            <div class="flex flex-col md:flex-row items-center justify-between gap-2.5">
                                <div class="flex items-center space-x-2 w-full md:w-auto">
                                    <label class="text-[11px] text-slate-300 font-semibold whitespace-nowrap">Output Format:</label>
                                    <select id="audio-export-format" class="rounded bg-slate-950 border border-slate-700 p-1.5 text-xs text-brand-glow font-mono font-bold">
                                        <option value="mp3" selected>🎵 MP3 (Universal Broadcast 256k)</option>
                                        <option value="wav">🎙️ WAV (Studio Lossless Master 44.1kHz)</option>
                                        <option value="m4a">📱 M4A / AAC (Apple Podcasts & LMS)</option>
                                        <option value="ogg">🌐 OGG (Web Audio / Game Engines)</option>
                                        <option value="flac">💿 FLAC (Audiophile Lossless)</option>
                                    </select>
                                </div>
                                <div class="flex items-center space-x-2 w-full md:w-auto justify-end">
                                    <button type="button" onclick="exportStandaloneAudio()" id="export-audio-btn" class="w-full md:w-auto px-3.5 py-1.5 rounded-lg bg-gradient-to-r from-emerald-600 to-teal-600 text-white font-bold hover:brightness-110 transition-all flex items-center justify-center gap-1.5 shadow-md shadow-emerald-500/20">
                                        <span>⚡</span> <span>Generate & Download Audio Master</span>
                                    </button>
                                </div>
                            </div>
                            <div id="audio-export-result-box" class="hidden p-2 rounded bg-slate-950 border border-emerald-500/40 flex items-center justify-between">
                                <span id="audio-export-meta" class="text-[11px] text-emerald-300 font-mono"></span>
                                <div class="flex items-center space-x-3 text-[11px]">
                                    <a id="audio-download-link" href="#" download class="text-brand-glow hover:underline font-bold">⬇️ Download Audio</a>
                                    <a id="srt-download-link" href="#" download class="text-indigo-400 hover:underline font-bold">📄 Download Subtitles (.SRT)</a>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Video Bumpers: Intro & Outro (Optional Pre-recorded Clips) -->
                    <div class="p-3.5 rounded-xl bg-slate-950/80 border border-indigo-500/20 space-y-2.5">
                        <div class="flex items-center justify-between border-b border-slate-800 pb-1.5">
                            <label class="text-xs font-bold text-slate-300 flex items-center gap-1.5">
                                <span>🎞️</span> <span>Branded Video Bumpers (Intro / Outro)</span>
                            </label>
                            <button onclick="openAssetVaultModal()" class="text-[10px] text-indigo-400 hover:underline">
                                Manage Video Library ↗
                            </button>
                        </div>
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                            <div>
                                <label class="block text-[11px] text-slate-400 mb-1">Intro Opener Clip</label>
                                <select id="intro-bumper-select" class="w-full rounded-lg bg-slate-900 border border-slate-700/80 p-1.5 text-xs text-slate-200">
                                    <option value="">None (Direct start)</option>
                                </select>
                            </div>
                            <div>
                                <label class="block text-[11px] text-slate-400 mb-1">Outro Closer Clip</label>
                                <select id="outro-bumper-select" class="w-full rounded-lg bg-slate-900 border border-slate-700/80 p-1.5 text-xs text-slate-200">
                                    <option value="">None (Direct finish)</option>
                                </select>
                            </div>
                        </div>
                    </div>

                    <!-- Toggles & Action Buttons -->
                    <div class="space-y-3 pt-1">
                        <div class="flex items-center space-x-4 px-1">
                            <div class="flex items-center space-x-2">
                                <input type="checkbox" id="burn-subtitles-check" class="rounded accent-brand-500 cursor-pointer" checked>
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

                        <div class="grid grid-cols-2 gap-3">
                            <button id="storyboard-btn" onclick="openStoryboardPreview()" class="py-3.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 font-bold text-sm text-slate-200 transition-all flex items-center justify-center space-x-2">
                                <span>🎬</span>
                                <span>Storyboard Preview</span>
                            </button>
                            <button id="generate-btn" onclick="startGeneration()" class="py-3.5 rounded-xl bg-gradient-to-r from-brand-600 via-indigo-600 to-brand-500 hover:from-brand-500 hover:to-indigo-500 font-bold text-sm text-white shadow-lg shadow-brand-500/20 active:scale-[0.99] transition-all flex items-center justify-center space-x-2">
                                <span>🚀</span>
                                <span>Direct Render</span>
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            <!-- RIGHT: Telemetry & Live Streaming Log Terminal (5 cols) -->
            <div class="lg:col-span-5 space-y-6">
                <div class="grid grid-cols-2 gap-3">
                    <div class="glass-panel p-3.5 rounded-xl">
                        <span class="text-xs text-slate-400">GPU VRAM</span>
                        <div id="vram-stat" class="text-base font-bold text-brand-glow font-mono mt-0.5">0 / 0 MB</div>
                        <div class="w-full bg-slate-800 h-1 rounded-full mt-1.5 overflow-hidden"><div id="vram-bar" class="bg-brand-500 h-full w-0"></div></div>
                    </div>
                    <div class="glass-panel p-3.5 rounded-xl">
                        <span class="text-xs text-slate-400">GPU Utilization</span>
                        <div id="gpu-util-stat" class="text-base font-bold text-white font-mono mt-0.5">0%</div>
                        <div class="w-full bg-slate-800 h-1 rounded-full mt-1.5 overflow-hidden"><div id="gpu-bar" class="bg-emerald-400 h-full w-0"></div></div>
                    </div>
                    <div class="glass-panel p-3.5 rounded-xl">
                        <span class="text-xs text-slate-400">System CPU</span>
                        <div id="cpu-stat" class="text-base font-bold text-white font-mono mt-0.5">0%</div>
                        <div class="w-full bg-slate-800 h-1 rounded-full mt-1.5 overflow-hidden"><div id="cpu-bar" class="bg-indigo-400 h-full w-0"></div></div>
                    </div>
                    <div class="glass-panel p-3.5 rounded-xl">
                        <span class="text-xs text-slate-400">Script Latency</span>
                        <div id="latency-stat" class="text-base font-bold text-brand-glow font-mono mt-0.5">0.00s</div>
                        <span class="text-[10px] text-slate-500">Llama 3 Director</span>
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

    </main>

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

    <!-- Footer -->
    <footer class="border-t border-slate-800/80 py-4 text-center text-xs text-slate-500">
        Modular-NeuroClips Studio &bull; Autonomous Video Course Engine &bull; SCORM 1.2 &bull; Edge-TTS &bull; FFmpeg &bull; Remotion React
    </footer>

    <!-- Scripts -->
    <script>
        const MILESTONE_DEFS = [
            { id: 'init', name: '1. Init', icon: '⚙️' },
            { id: 'scripting', name: '2. Script', icon: '📝' },
            { id: 'keyframes', name: '3. Keyframes', icon: '🖼️' },
            { id: 'animation', name: '4. Motion', icon: '🎥' },
            { id: 'voiceover', name: '5. Voiceover', icon: '🎙️' },
            { id: 'compilation', name: '6. Stitch', icon: '🎞️' },
            { id: 'complete', name: '7. Ready', icon: '✨' }
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

        renderMilestones('init');

        function updateScriptMetrics() {
            const text = document.getElementById('prompt-input').value.trim();
            const words = text ? text.split(/\s+/).length : 0;
            const speed = parseFloat(document.getElementById('speed-slider').value) || 1.0;
            const spokenMin = (words / (140 * speed)).toFixed(2);
            document.getElementById('script-stats').innerText = `${words} words | ~${spokenMin} min`;
        }

        function newProjectCanvas() {
            document.getElementById('prompt-input').value = '';
            updateScriptMetrics();
            activeSessionJobId = null;
            document.getElementById('terminal-logs').innerHTML = `<div class="text-brand-glow italic">[NEW PROJECT] Workspace reset to pristine blank canvas. Ready for new course.</div>`;
            renderMilestones('init');
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

        async function fetchGallery() {
            const container = document.getElementById('gallery-grid');
            try {
                const url = (currentSessionOnly && activeSessionJobId) ? `/api/v1/gallery?session_job_id=${activeSessionJobId}` : '/api/v1/gallery';
                const res = await fetch(url);
                const data = await res.json();
                
                if (data.videos.length === 0) {
                    container.innerHTML = `<div class="col-span-3 text-center text-xs text-slate-500 py-8 bg-slate-900/40 rounded-xl border border-slate-800/80">
                        ${currentSessionOnly ? 'No videos rendered in this active session yet. Click Direct Render or Storyboard to create.' : 'Media Vault is empty.'}
                    </div>`;
                    return;
                }

                container.innerHTML = data.videos.map(v => `
                    <div class="glass-panel p-3.5 rounded-xl space-y-2.5 border border-slate-800/90 flex flex-col justify-between">
                        <div class="space-y-2">
                            <video controls class="w-full h-40 rounded-lg bg-black object-cover" src="${v.url}"></video>
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

                                    <a href="${v.url}" download title="Download MP4" class="px-2 py-0.5 rounded bg-brand-500/10 hover:bg-brand-500/20 text-brand-glow text-[11px]">
                                        MP4
                                    </a>

                                    <button onclick="deleteGalleryItem('${v.filename}')" title="Delete Video" class="text-red-400 hover:text-red-300 p-1 text-[11px]">
                                        🗑️
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                `).join('');
            } catch (err) {
                container.innerHTML = '<div class="col-span-3 text-center text-xs text-red-400 py-4">Failed to load media vault.</div>';
            }
        }

        async function exportScormPackage(filename) {
            try {
                const res = await fetch(`/api/v1/scorm/export/${filename}`, { method: 'POST' });
                const data = await res.json();
                if (data.status === 'ok') {
                    const link = document.createElement('a');
                    link.href = data.download_url;
                    link.download = data.package_name;
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);
                    alert(`📦 SCORM 1.2 Package (${data.size_mb} MB) generated and downloading for LMS import!`);
                } else {
                    alert("SCORM export failed: " + data.detail);
                }
            } catch(e) {
                alert("SCORM Export error: " + e);
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
                    document.getElementById('prompt-input').value = data.content;
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
            const text = document.getElementById('prompt-input').value.trim();
            if (!text) {
                alert("Please enter narration text or upload a script document first.");
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

        function insertScriptTag(tag) {
            const textarea = document.getElementById('prompt-input');
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
            slider.value = count;
            document.getElementById('scene-val').innerText = count + ' Scenes';
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
            const text = document.getElementById('prompt-input').value.trim() || "Welcome to Modular-NeuroClips. Auditioning neural voice director prosody and natural pacing.";
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

        async function startGeneration() {
            const topic = document.getElementById('prompt-input').value.trim();
            if (!topic) {
                alert('Please enter a concept or Speaker Script.');
                return;
            }

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

            const btn = document.getElementById('generate-btn');
            btn.disabled = true;
            btn.classList.add('opacity-50', 'cursor-not-allowed');

            try {
                const res = await fetch('/api/v1/generate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        topic,
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
                        similarity_boost
                    })
                });
                const data = await res.json();
                if (data.status === 'started') {
                    activeSessionJobId = data.job_id;
                    if (currentSessionOnly) fetchGallery();
                } else if (res.status === 409) {
                    alert(data.message);
                }
            } catch (err) {
                alert('Generation failed: ' + err);
            } finally {
                setTimeout(() => {
                    btn.disabled = false;
                    btn.classList.remove('opacity-50', 'cursor-not-allowed');
                }, 3000);
            }
        }

        async function openStoryboardPreview() {
            const topic = document.getElementById('prompt-input').value.trim();
            if (!topic) {
                alert('Please enter a concept or Speaker Script first.');
                return;
            }
            const scenes = parseInt(document.getElementById('scene-slider').value);
            const avatar_persona = document.getElementById('avatar-persona-select').value;

            const btn = document.getElementById('storyboard-btn');
            btn.innerHTML = '<span>⏳</span> <span>Directing...</span>';

            try {
                await fetchVideoAssets();
                const res = await fetch('/api/v1/storyboard/preview', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ topic, scenes, art_style: 'Cinematic 35mm (Volumetric Lighting)', avatar_persona })
                });
                const data = await res.json();
                currentStoryboardData = data.script;
                renderStoryboardModal(data.script);
                document.getElementById('storyboard-modal').classList.remove('hidden');
            } catch(err) {
                alert('Storyboard generation failed: ' + err);
            } finally {
                btn.innerHTML = '<span>🎬</span> <span>Storyboard Preview</span>';
            }
        }

        function renderStoryboardModal(script) {
            const container = document.getElementById('storyboard-scenes-list');
            container.innerHTML = `
                <div class="p-3 rounded-xl bg-brand-500/10 border border-brand-500/20 text-xs text-brand-glow flex items-center justify-between">
                    <span class="font-bold">Production: ${script.title}</span>
                    <span class="font-mono text-[11px] text-slate-400">${script.scenes.length} Scenes Drafted</span>
                </div>
            `;

            script.scenes.forEach((sc, idx) => {
                const card = document.createElement('div');
                const isVideo = sc.video_source_type === 'uploaded_video';
                card.className = "p-4 rounded-xl bg-slate-900/90 border border-slate-800 space-y-3";
                
                card.innerHTML = `
                    <div class="flex items-center justify-between border-b border-slate-800 pb-2">
                        <div class="flex items-center space-x-3">
                            <span class="text-xs font-bold text-white font-mono">
                                <span class="px-2 py-0.5 rounded bg-brand-500/20 text-brand-glow">Scene #${sc.scene_id}</span>
                            </span>
                            <div class="flex rounded-lg bg-slate-950 p-0.5 border border-slate-800 text-[11px]">
                                <button onclick="onSceneSourceToggle(${idx}, 'ai_generated')" class="px-2.5 py-1 rounded-md transition-all ${!isVideo ? 'bg-brand-600 text-white font-bold' : 'text-slate-400 hover:text-white'}">
                                    ✨ AI Diffusion
                                </button>
                                <button onclick="onSceneSourceToggle(${idx}, 'uploaded_video')" class="px-2.5 py-1 rounded-md transition-all ${isVideo ? 'bg-indigo-600 text-white font-bold' : 'text-slate-400 hover:text-white'}">
                                    📼 Video Clip
                                </button>
                            </div>
                        </div>
                        <button onclick="removeStoryboardScene(${idx})" class="text-red-400 hover:text-red-300 text-xs">🗑️ Remove</button>
                    </div>

                    ${isVideo ? `
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
                    `}

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
            currentStoryboardData.scenes.push({
                scene_id: nextId,
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
                const isVideo = sc.video_source_type === 'uploaded_video';
                return {
                    scene_id: idx + 1,
                    visual_prompt: (!isVideo && document.getElementById(`sb-visual-${idx}`)) ? document.getElementById(`sb-visual-${idx}`).value : (sc.visual_prompt || 'Visual presentation scene'),
                    motion_prompt: (!isVideo && document.getElementById(`sb-motion-${idx}`)) ? document.getElementById(`sb-motion-${idx}`).value : (sc.motion_prompt || 'Cinematic pan'),
                    narration: document.getElementById(`sb-narration-${idx}`) ? document.getElementById(`sb-narration-${idx}`).value : (sc.narration || ''),
                    duration_seconds: parseFloat(document.getElementById(`sb-duration-${idx}`) ? document.getElementById(`sb-duration-${idx}`).value : sc.duration_seconds) || 4.0,
                    video_source_type: sc.video_source_type || 'ai_generated',
                    video_source_url: isVideo ? (document.getElementById(`sb-videosrc-${idx}`) ? document.getElementById(`sb-videosrc-${idx}`).value : sc.video_source_url) : ''
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

        const evtSource = new EventSource('/api/v1/telemetry/stream');
        evtSource.onmessage = function(e) {
            const data = JSON.parse(e.data);
            const gpu = data.telemetry.gpu;
            document.getElementById('header-vram').innerText = `${gpu.used_mb} / ${gpu.total_mb} MB`;
            document.getElementById('vram-stat').innerText = `${gpu.used_mb} / ${gpu.total_mb} MB`;
            const vramPct = (gpu.used_mb / gpu.total_mb * 100) || 0;
            document.getElementById('vram-bar').style.width = `${vramPct}%`;

            document.getElementById('gpu-util-stat').innerText = `${gpu.utilization}%`;
            document.getElementById('gpu-bar').style.width = `${gpu.utilization}%`;
            document.getElementById('cpu-stat').innerText = `${data.telemetry.system.cpu_percent}%`;
            document.getElementById('cpu-bar').style.width = `${data.telemetry.system.cpu_percent}%`;

            document.getElementById('header-status').innerText = data.state.status;
            document.getElementById('latency-stat').innerText = `${data.state.model_load_latency.toFixed(2)}s`;

            const progress = data.state.progress_percent || 0;
            document.getElementById('master-progress-fill').style.width = `${progress}%`;
            document.getElementById('overall-progress-num').innerText = `${progress}%`;
            document.getElementById('active-step-caption').innerText = data.state.current_step || 'Idle';

            const activeJob = data.active_job;
            if (activeJob) {
                renderMilestones(activeJob.current_milestone, activeJob.milestones);
                if (activeJob.logs && activeJob.logs.length > 0) {
                    const term = document.getElementById('terminal-logs');
                    term.innerHTML = activeJob.logs.map(l => `<div class="leading-relaxed">${l}</div>`).join('');
                    term.scrollTop = term.scrollHeight;
                }
                if (activeJob.status === 'complete' && activeJob.output_path) {
                    fetchGallery();
                }
            } else {
                renderMilestones(data.state.current_milestone || 'init');
            }
        };

        const savedElevenKey = localStorage.getItem('neuroclips_eleven_key');
        const savedElevenVoice = localStorage.getItem('neuroclips_eleven_voice');
        if (savedElevenKey && document.getElementById('elevenlabs-api-key')) {
            document.getElementById('elevenlabs-api-key').value = savedElevenKey;
        }
        if (savedElevenVoice && document.getElementById('elevenlabs-voice-id')) {
            document.getElementById('elevenlabs-voice-id').value = savedElevenVoice;
        }

        fetchGallery();
        fetchIdentities();
        fetchVideoAssets();
        updateScriptMetrics();
    </script>
</body>
</html>
"""
