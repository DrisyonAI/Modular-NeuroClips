import re
from typing import List, Optional, Dict, Any
import subprocess
from pathlib import Path
from src.config import OUTPUT_DIR, RENDER_WIDTH, RENDER_HEIGHT
from src.remotion_renderer import is_remotion_available, render_with_remotion

def format_srt_time(seconds: float) -> str:
    """Converts seconds into SRT timestamp format: HH:MM:SS,mmm"""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"

def generate_srt_subtitles(scenes: List[Dict[str, Any]], output_srt_path: Path) -> str:
    """Generates standard ADL/YouTube compliant .srt subtitle file from scene narration."""
    srt_lines = []
    current_time = 0.0

    for idx, scene in enumerate(scenes, start=1):
        duration = float(scene.get("duration_seconds", 5.0))
        narration = scene.get("narration", "").strip()
        if not narration:
            narration = scene.get("visual_prompt", "").strip()[:80]

        start_str = format_srt_time(current_time)
        end_str = format_srt_time(current_time + duration)
        cleaned_text = re.sub(r"\s+", " ", narration)

        srt_lines.append(f"{idx}")
        srt_lines.append(f"{start_str} --> {end_str}")
        srt_lines.append(cleaned_text)
        srt_lines.append("")

        current_time += duration

    with open(output_srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(srt_lines))

    return str(output_srt_path)

def normalize_bumper_clip(video_path: str, output_path: Path, width: int = RENDER_WIDTH, height: int = RENDER_HEIGHT) -> Optional[str]:
    """Normalizes an intro or outro video bumper to match studio resolution and 30fps."""
    p = Path(video_path)
    if not p.exists():
        from src.config import ASSETS_DIR
        alt_p = ASSETS_DIR / p.name
        if alt_p.exists():
            p = alt_p
        else:
            return None
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(p.resolve()),
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,fps=30",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-an",
            str(output_path)
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return str(output_path)
    except Exception as e:
        print(f"[Bumper Warning] Failed to normalize bumper ({e}).")
        return str(p.resolve())

def compile_final_video(
    clip_paths: List[str],
    output_filename: str = "final_production_sd.mp4",
    audio_path: Optional[str] = None,
    engine: str = "ffmpeg",
    avatar_image_path: Optional[str] = None,
    avatar_layout: str = "pip_bottom_right",
    burn_subtitles: bool = True,
    srt_path: Optional[str] = None,
    remotion_metadata: Optional[Dict[str, Any]] = None,
    intro_video_path: Optional[str] = None,
    outro_video_path: Optional[str] = None
) -> str:
    """
    Unified compiler supporting Remotion React and FFmpeg PiP Multi-Layer Compositing
    with Subtitle Burning and optional Intro / Outro Video Bumpers.
    """
    final_output_path = OUTPUT_DIR / output_filename

    # Assemble sequence clips with optional intro and outro bumpers
    final_clips = list(clip_paths)
    if intro_video_path:
        intro_norm = normalize_bumper_clip(
            intro_video_path,
            OUTPUT_DIR / f"intro_{Path(output_filename).stem}.mp4",
            width=RENDER_WIDTH,
            height=RENDER_HEIGHT
        )
        if intro_norm:
            final_clips.insert(0, intro_norm)

    if outro_video_path:
        outro_norm = normalize_bumper_clip(
            outro_video_path,
            OUTPUT_DIR / f"outro_{Path(output_filename).stem}.mp4",
            width=RENDER_WIDTH,
            height=RENDER_HEIGHT
        )
        if outro_norm:
            final_clips.append(outro_norm)

    # 1. Remotion React Engine
    if engine == "remotion" and is_remotion_available() and remotion_metadata:
        try:
            print("[*] Compiling multi-layer video via Remotion React Engine...")
            return render_with_remotion(
                title=remotion_metadata.get("title", "Production"),
                art_style_preset=remotion_metadata.get("art_style_preset", "Cinematic"),
                scenes=remotion_metadata.get("scenes", []),
                output_filename=output_filename,
                audio_path=audio_path
            )
        except Exception as err:
            print(f"[Remotion Warning] Failed ({err}). Falling back to FFmpeg multi-layer.")

    # 2. FFmpeg Multi-Layer PiP & Subtitles Concatenation
    concat_list_path = OUTPUT_DIR / f"concat_{Path(output_filename).stem}.txt"
    with open(concat_list_path, "w") as f:
        for clip in final_clips:
            f.write(f"file '{Path(clip).resolve()}'\n")

    has_audio = audio_path and Path(audio_path).exists() and Path(audio_path).stat().st_size > 100
    has_avatar = avatar_image_path and Path(avatar_image_path).exists() and avatar_layout != "none"
    has_srt = burn_subtitles and srt_path and Path(srt_path).exists()

    try:
        filter_parts = []
        filter_parts.append(f"[0:v]scale={RENDER_WIDTH}:{RENDER_HEIGHT}[bg]")
        last_v = "[bg]"

        if has_avatar:
            filter_parts.append(f"[2:v]scale=220:220,format=yuva420p[avatar]")
            filter_parts.append(f"{last_v}[avatar]overlay=W-w-36:H-h-36:shortest=1[v_avatar]")
            last_v = "[v_avatar]"

        if has_srt:
            escaped_srt = str(Path(srt_path).resolve()).replace("\\", "/").replace(":", "\\:")
            filter_parts.append(
                f"{last_v}subtitles='{escaped_srt}':force_style='FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00090D16,BorderStyle=3,MarginV=36,Fontname=Arial,Bold=1'[v_sub]"
            )
            last_v = "[v_sub]"

        filter_complex_str = ";".join(filter_parts)

        inputs = ["-f", "concat", "-safe", "0", "-i", str(concat_list_path)]
        if has_audio:
            inputs.extend(["-stream_loop", "-1", "-i", str(Path(audio_path).resolve())])
        if has_avatar:
            inputs.extend(["-loop", "1", "-i", str(Path(avatar_image_path).resolve())])

        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", filter_complex_str,
            "-map", last_v
        ]

        if has_audio:
            cmd.extend(["-map", "1:a:0", "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2", "-shortest"])

        cmd.extend([
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(final_output_path)
        ])

        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return str(final_output_path)
    except Exception as e:
        print(f"[FFmpeg Warning in Compiler] Advanced encode fallback ({e}).")
        try:
            cmd_simple = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0", "-i", str(concat_list_path),
                "-vf", f"scale={RENDER_WIDTH}:{RENDER_HEIGHT}",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "22",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                str(final_output_path)
            ]
            subprocess.run(cmd_simple, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except Exception:
            if clip_paths and Path(clip_paths[0]).exists():
                with open(clip_paths[0], "rb") as f_src, open(final_output_path, "wb") as f_dst:
                    f_dst.write(f_src.read())
        return str(final_output_path)
