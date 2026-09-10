"""
Unified pipeline execution runner.
Deduplicates generation logic across direct prompt and custom storyboard workflows.
"""
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from src.config import OUTPUT_DIR, ASSETS_DIR, RESOLUTION_PROFILES, get_resolution_dimensions
from src.pipeline import MediaGenerationEngine, VRAMGuard
from src.compiler import compile_final_video, generate_srt_subtitles
from src.services.audio_service import (
    generate_voiceover_audio_sync,
    translate_narration_text,
    resolve_video_path,
)
from src.services.job_manager import job_manager
from src.services.video_generation_service import VideoGenerationService


def run_production_pipeline(
    job_id: str,
    title: str,
    art_style: str,
    scenes: List[Dict[str, Any]],
    resolution: str = "16:9_hd",
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
    topic: Optional[str] = None,
    output_type: str = "video",
    motion_graphics: bool = True,
    background_music: bool = False,
    voiceover_script: Optional[str] = None,
    reference_media_url: Optional[str] = None,
) -> None:
    """Executes full production workflow for a given job and scene list."""
    job = job_manager.get_job(job_id)
    if not job:
        return

    width, height = get_resolution_dimensions(resolution)
    engine = MediaGenerationEngine()

    if auto_clean:
        for old_f in list(OUTPUT_DIR.glob("scene_*.*")) + list(OUTPUT_DIR.glob("audio_*.*")):
            try:
                old_f.unlink(missing_ok=True)
            except Exception:
                pass

    try:
        # Multi-Language Dubbing
        if language != "en-US":
            job_manager.log_milestone(
                job_id, "scripting", f"Translating script into {language}...", 32, f"Dubbing narration into {language}"
            )
            for sc in scenes:
                raw_narr = sc.get("narration", "")
                if raw_narr:
                    sc["narration"] = translate_narration_text(raw_narr, language)

        # MILESTONES 2 & 3: KEYFRAMES & ANIMATION
        clip_paths: List[str] = []
        keyframe_paths: List[str] = []
        total = max(1, len(scenes))

        for idx, scene in enumerate(scenes, start=1):
            job["processed_scenes"] = idx
            job_manager.pipeline_state["processed_scenes"] = idx

            v_type = scene.get("video_source_type", "ai_generated")
            v_url = scene.get("video_source_url", "")
            dur = float(scene.get("duration_seconds", 4))
            vis_prompt = scene.get("visual_prompt", "")
            mot_prompt = scene.get("motion_prompt", "Slow cinematic camera pan")
            scene_id = scene.get("scene_id", idx)
            scene_output_type = scene.get("output_type") or output_type
            scene_motion = scene.get("motion_graphics", motion_graphics)

            resolved_v_path = resolve_video_path(v_url) if (v_type == "uploaded_video" and v_url) else None

            # Multimodal Reference Media Support (Uploaded Image or Video)
            ref_image_path = None
            if not resolved_v_path and reference_media_url and idx == 1:
                ref_candidate = Path(reference_media_url)
                if not ref_candidate.is_absolute():
                    c1 = OUTPUT_DIR / ref_candidate.name
                    c2 = ASSETS_DIR / ref_candidate.name
                    if c1.exists():
                        ref_candidate = c1
                    elif c2.exists():
                        ref_candidate = c2
                if ref_candidate.exists():
                    ext = ref_candidate.suffix.lower()
                    if ext in [".mp4", ".mov", ".mkv", ".webm"]:
                        resolved_v_path = str(ref_candidate)
                    elif ext in [".jpg", ".jpeg", ".png", ".webp", ".bmp"]:
                        ref_image_path = str(ref_candidate)

            if resolved_v_path:
                base_p = 30 + int(((idx - 0.5) / total) * 35)
                job_manager.log_milestone(
                    job_id, "keyframes", f"Extracting frame from video asset {idx}/{total}...", base_p, f"Scene {idx}: Using user video clip -> {Path(resolved_v_path).name}"
                )
                kf_path = str(OUTPUT_DIR / f"scene_{scene_id}_{job_id}_keyframe.png")
                engine.extract_video_thumbnail(resolved_v_path, Path(kf_path), width=width, height=height)
                keyframe_paths.append(kf_path)
                job["keyframe_paths"] = keyframe_paths

                anim_p = 30 + int((idx / total) * 35)
                job_manager.log_milestone(
                    job_id, "animation", f"Normalizing video clip {idx}/{total}...", anim_p, f"Scene {idx}: Conforming video ({dur}s, {width}x{height})"
                )
                clip_path = engine.prepare_existing_video_clip(
                    resolved_v_path, scene_id, job_id=job_id, target_duration=dur, width=width, height=height
                )
                clip_paths.append(clip_path)
                job["clip_paths"] = clip_paths

            elif scene_output_type == "slide":
                # Static instructional slide scene for educational/course content
                base_p = 30 + int(((idx - 0.5) / total) * 35)
                job_manager.log_milestone(
                    job_id, "keyframes", f"Composing instructional slide {idx}/{total}...", base_p, f"Scene {idx}: Instructional Slide -> {vis_prompt[:50]}..."
                )
                kf_path = str(OUTPUT_DIR / f"slide_{job_id}_scene_{scene_id}.png")
                slide_title = scene.get("title") or f"Concept #{scene_id}: {title[:30]}"
                engine.generate_instructional_slide(
                    title=slide_title,
                    content=vis_prompt or scene.get("narration", "") or title,
                    output_path=Path(kf_path),
                    resolution=resolution
                )
                keyframe_paths.append(kf_path)
                job["keyframe_paths"] = keyframe_paths

                anim_p = 30 + int((idx / total) * 35)
                if output_type == "slide":
                    # Pure slide mode: do NOT generate video clips
                    job_manager.log_milestone(
                        job_id, "animation", f"Formatted slide presentation {idx}/{total}...", anim_p, f"Scene {idx}: Static instructional slide card ready"
                    )
                else:
                    # Video mode containing a slide scene: render video clip for compositor
                    job_manager.log_milestone(
                        job_id, "animation", f"Rendering slide presentation {idx}/{total}...", anim_p, f"Scene {idx}: Static instructional slide ({dur}s)"
                    )
                    clip_path = engine.generate_video_clip(
                        kf_path, mot_prompt, scene_id, job_id=job_id, width=width, height=height,
                        force_refresh=True, motion_graphics=scene_motion, duration_sec=dur
                    )
                    clip_paths.append(clip_path)
                    job["clip_paths"] = clip_paths

            else:
                base_p = 30 + int(((idx - 0.5) / total) * 35)
                job_manager.log_milestone(
                    job_id, "keyframes", f"Synthesizing keyframe {idx}/{total}...", base_p, f"Scene {idx}: Visual Prompt -> {vis_prompt[:60]}..."
                )
                if ref_image_path:
                    # Multi-modal reference foundation
                    vgs = VideoGenerationService()
                    kf_path = vgs.adapter.generate_keyframe(
                        prompt=vis_prompt,
                        reference_media_path=ref_image_path,
                        width=width,
                        height=height,
                        art_style=art_style,
                        scene_id=scene_id,
                        job_id=job_id
                    )
                else:
                    full_prompt = f"{art_style}, {vis_prompt}" if art_style else vis_prompt
                    kf_path = engine.generate_image_keyframe(
                        full_prompt, scene_id, job_id=job_id, width=width, height=height, force_refresh=True
                    )
                keyframe_paths.append(kf_path)
                job["keyframe_paths"] = keyframe_paths

                anim_p = 30 + int((idx / total) * 35)
                job_manager.log_milestone(
                    job_id, "animation", f"Animating scene {idx}/{total}...", anim_p, f"Scene {idx}: Motion -> {mot_prompt[:50]}..."
                )
                clip_path = engine.generate_video_clip(
                    kf_path, mot_prompt, scene_id, job_id=job_id, width=width, height=height,
                    force_refresh=True, motion_graphics=scene_motion, duration_sec=dur
                )
                clip_paths.append(clip_path)
                job["clip_paths"] = clip_paths

        # MILESTONE 4: VOICEOVER / TTS
        # Audio / Visual Separation & Empty Script Rule:
        # If voiceover_script is explicitly passed:
        #   - Empty / whitespace-only string: 100% Silent video! Skip voice generation entirely.
        #   - Non-empty: Synthesize strictly from voiceover_script.
        # If voiceover_script is None (backward compatibility):
        #   - Use scene narration if present; otherwise fallback to topic / title for legacy tests.
        is_silent_requested = (voiceover_script is not None and not voiceover_script.strip())
        audio_file = None

        if is_silent_requested:
            narration_text = ""
            burn_subtitles = False
            job_manager.log_milestone(
                job_id, "voiceover", "Silent mode active (Zero narration requested)", 80, "Zero voiceover narration synthesized per empty script rule"
            )
        else:
            if voiceover_script is not None and voiceover_script.strip():
                narration_text = voiceover_script.strip()
            else:
                scene_narr = " ".join([s.get("narration", "").strip() for s in scenes if s.get("narration", "").strip()])
                narration_text = scene_narr or topic or title

            if not narration_text or not narration_text.strip():
                burn_subtitles = False
                job_manager.log_milestone(
                    job_id, "voiceover", "Silent mode active (No narration text)", 80, "No voiceover synthesized"
                )
            else:
                audio_file = OUTPUT_DIR / f"audio_{job_id}.mp3"
                job_manager.log_milestone(
                    job_id, "voiceover", f"Synthesizing voiceover ({voice}, {speech_rate}x, {voice_provider})...", 75, f"Generating neural voice narration for '{title}'"
                )
                tts_ok = generate_voiceover_audio_sync(
                    text=narration_text,
                    voice=voice,
                    speech_rate=speech_rate,
                    output_path=audio_file,
                    pitch=pitch,
                    volume=volume,
                    voice_provider=voice_provider,
                    elevenlabs_api_key=elevenlabs_api_key,
                    elevenlabs_voice_id=elevenlabs_voice_id,
                    stability=stability,
                    similarity_boost=similarity_boost,
                )
                if tts_ok and audio_file.exists() and audio_file.stat().st_size > 100:
                    job["audio_paths"] = [str(audio_file)]
                    job_manager.log_milestone(
                        job_id,
                        "voiceover",
                        "Voiceover synthesized successfully",
                        80,
                        f"Generated voice audio: {audio_file.name} ({audio_file.stat().st_size / 1024:.1f} KB)",
                    )
                else:
                    audio_file = None
                    job_manager.log_milestone(
                        job_id, "voiceover", "Audio generated (silent mode)", 80, "No TTS audio generated"
                    )

        # SRT SUBTITLE GENERATION
        srt_file = OUTPUT_DIR / f"subtitles_{job_id}.srt"
        if is_silent_requested or not narration_text.strip():
            burn_subtitles = False
            srt_file.write_text("", encoding="utf-8")
            job["srt_path"] = str(srt_file)
        else:
            scenes_data = [
                {
                    "scene_id": sc.get("scene_id", i + 1),
                    "narration": sc.get("narration", ""),
                    "visual_prompt": sc.get("visual_prompt", ""),
                    "duration_seconds": sc.get("duration_seconds", 4),
                }
                for i, sc in enumerate(scenes)
            ]
            generate_srt_subtitles(scenes_data, srt_file, width=width, height=height)
            job["srt_path"] = str(srt_file)

        # MILESTONE 5: COMPILATION & FINALIZATION
        if output_type == "slide":
            # Pure slide mode: skip video/MP4 compilation
            job_manager.log_milestone(
                job_id,
                "compilation",
                "Instructional slides finalized",
                95,
                f"Generated {len(keyframe_paths)} instructional slides with synchronized audio ({language}). Video compilation skipped per Slide mode.",
            )
            primary_slide = keyframe_paths[0] if keyframe_paths else str(OUTPUT_DIR / f"slide_{job_id}_deck.png")
            job["slide_paths"] = keyframe_paths
            job["output_type"] = "slide"
            job_manager.complete_job(job_id, primary_slide)
            return

        job_manager.log_milestone(
            job_id,
            "compilation",
            f"Compiling via {compiler_engine.upper()} engine...",
            88,
            f"Executing multi-layer compositing (subtitles: {burn_subtitles}, avatar: {avatar_persona}, bgm: {background_music})",
        )
        output_filename = f"prod_{job_id}_{int(time.time())}.mp4"
        audio_param = str(audio_file) if (audio_file is not None and audio_file.exists() and audio_file.stat().st_size > 100) else None

        avatar_img_path = None
        if avatar_persona == "custom_upload":
            custom_p = OUTPUT_DIR / "custom_avatar.png"
            if custom_p.exists():
                avatar_img_path = str(custom_p)

        remotion_meta = {
            "title": title,
            "art_style_preset": art_style,
            "scenes": [
                {
                    "scene_id": sc.get("scene_id", i + 1),
                    "keyframe_path": keyframe_paths[i] if i < len(keyframe_paths) else "",
                    "visual_prompt": sc.get("visual_prompt", ""),
                    "motion_prompt": sc.get("motion_prompt", ""),
                    "narration": sc.get("narration", "") or sc.get("visual_prompt", ""),
                    "duration_seconds": sc.get("duration_seconds", 4),
                }
                for i, sc in enumerate(scenes)
            ],
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
            outro_video_path=resolve_video_path(outro_video_url),
            width=width,
            height=height,
            background_music=background_music,
        )

        # MILESTONE 6: COMPLETE
        job_manager.complete_job(job_id, final_video)

    except Exception as exc:
        job_manager.fail_job(job_id, str(exc))
        VRAMGuard.cleanup()
