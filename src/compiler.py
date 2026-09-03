import re
from typing import List, Optional, Dict, Any
import subprocess
from pathlib import Path
from src.config import OUTPUT_DIR, ASSETS_DIR, RENDER_WIDTH, RENDER_HEIGHT
from src.remotion_renderer import is_remotion_available, render_with_remotion

def format_srt_time(seconds: float) -> str:
    """Converts seconds into SRT timestamp format: HH:MM:SS,mmm"""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"

def caption_budget(width: int, height: int, max_lines: int = 3) -> int:
    """Characters a caption cue can hold before it overruns the frame.

    Derived from the frame rather than guessed: the drawable width is the frame
    minus the side margins, and Arial Bold advances at roughly 0.55 em, so
    usable / (0.55 * font size) characters fit on a line. A 9:16 frame is only 720
    wide, so a cue that is comfortable in landscape is roughly twice too long here -
    holding a whole scene's narration on one cue is what pushed portrait captions off
    the top of the frame.
    """
    m = caption_metrics(width, height)
    usable = width - 2 * m["margin_lr"]
    per_line = max(12, int(usable / (0.55 * m["font_size"])))
    return per_line * max_lines


def chunk_narration(text: str, budget: int) -> List[str]:
    """Split on word boundaries into pieces that each fit `budget` characters."""
    words = text.split()
    if not words:
        return []
    chunks, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > budget:
            chunks.append(current)
            current = word
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def generate_srt_subtitles(scenes: List[Dict[str, Any]], output_srt_path: Path,
                           width: int = RENDER_WIDTH, height: int = RENDER_HEIGHT) -> str:
    """Generates standard ADL/YouTube compliant .srt subtitle file from scene narration.

    Long narration is split across several timed cues sized for `width`x`height`
    instead of being held on screen as one block, which both reads better and keeps
    captions inside the frame on tall, narrow canvases.
    """
    srt_lines = []
    current_time = 0.0
    budget = caption_budget(width, height)
    cue_index = 1

    for scene in scenes:
        duration = float(scene.get("duration_seconds", 5.0))
        narration = scene.get("narration", "").strip()
        if not narration:
            narration = scene.get("visual_prompt", "").strip()[:80]

        cleaned_text = strip_director_cues(re.sub(r"\s+", " ", narration))
        if not cleaned_text:
            current_time += duration
            continue
        chunks = chunk_narration(cleaned_text, budget) or [cleaned_text]

        # Share the scene's time out by length, so a long chunk is not flashed for
        # the same span as a short one.
        total_chars = sum(len(c) for c in chunks) or 1
        chunk_start = current_time
        for i, chunk in enumerate(chunks):
            share = duration * (len(chunk) / total_chars)
            # Absorb rounding into the last chunk so cues stay flush with the scene.
            chunk_end = current_time + duration if i == len(chunks) - 1 else chunk_start + share

            srt_lines.append(f"{cue_index}")
            srt_lines.append(f"{format_srt_time(chunk_start)} --> {format_srt_time(chunk_end)}")
            srt_lines.append(chunk)
            srt_lines.append("")
            cue_index += 1
            chunk_start = chunk_end

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

def build_avatar_layers(
    avatar_layout: str,
    width: int,
    height: int,
    input_label: str = "[2:v]",
    base_label: str = "[bg]",
    out_label: str = "[v_avatar]"
) -> List[str]:
    """Filter chain that places the avatar for `avatar_layout` on a `width`x`height` canvas.

    Every size and offset is derived from the canvas rather than fixed in pixels, so
    the same layout reads the same way at any aspect ratio. The scale factors are
    tuned so that 16:9 HD reproduces the previous hard-coded look almost exactly
    (min(1280,720)*0.30 = 216 vs the old 220 box; *0.05 = 36, the old margin), which
    keeps existing landscape output stable while making portrait and square correct.

    `split_screen` splits along the LONG axis: side-by-side in landscape, stacked in
    portrait. Splitting a 9:16 frame vertically would leave two unusable slivers.
    """
    short_edge = min(width, height)
    margin = max(8, round(short_edge * 0.05))
    portrait = height > width

    if avatar_layout == "full_anchor":
        # Cover the whole canvas, cropping the overflow rather than distorting.
        return [
            f"{input_label}scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},format=yuva420p[avatar]",
            f"{base_label}[avatar]overlay=0:0:shortest=1{out_label}",
        ]

    if avatar_layout == "split_screen":
        if portrait:
            # Presenter occupies the bottom 40% band, full width.
            aw, ah = width, round(height * 0.4)
            ax, ay = 0, height - ah
        else:
            # Presenter occupies the right-hand 40% column, full height.
            aw, ah = round(width * 0.4), height
            ax, ay = width - aw, 0
        return [
            f"{input_label}scale={aw}:{ah}:force_original_aspect_ratio=increase,"
            f"crop={aw}:{ah},format=yuva420p[avatar]",
            f"{base_label}[avatar]overlay={ax}:{ay}:shortest=1{out_label}",
        ]

    # Picture-in-picture. A square badge sized off the short edge, so it stays the
    # same visual weight whichever way the canvas is oriented.
    box = max(64, round(short_edge * 0.30))
    y_expr = f"{margin}" if avatar_layout == "pip_top_right" else f"H-h-{margin}"
    return [
        f"{input_label}scale={box}:{box}:force_original_aspect_ratio=increase,"
        f"crop={box}:{box},format=yuva420p[avatar]",
        f"{base_label}[avatar]overlay=W-w-{margin}:{y_expr}:shortest=1{out_label}",
    ]


# Director cues are prosody instructions for the voice engine. They must never be
# shown to a viewer; before this they were burned into the frame verbatim as
# "[pause 500ms]".
DIRECTOR_CUE_RE = re.compile(r"\[\s*(?:pause[^\]]*|emphasis|pro\s*tip)\s*\]", re.IGNORECASE)


def strip_director_cues(text: str) -> str:
    """Remove [pause 500ms] / [emphasis] / [Pro Tip] markers from caption text."""
    return re.sub(r"\s{2,}", " ", DIRECTOR_CUE_RE.sub(" ", text)).strip()


def caption_metrics(width: int, height: int) -> Dict[str, int]:
    """Caption sizing in real frame pixels, for a script whose PlayRes is the frame.

    Size comes from the SHORT edge, not the height. The short edge is what limits how
    many characters fit on a line, so this keeps captions at the same visual weight
    and with the same wrapping behaviour in landscape, portrait and square. Sizing off
    height instead makes a 9:16 caption nearly twice too large.
    """
    short_edge = min(width, height)
    font_size = max(14, round(short_edge * 0.055))
    return {
        "font_size": font_size,
        "margin_v": max(16, round(height * 0.06)),
        "margin_lr": max(16, round(width * 0.06)),
        "outline": max(2, round(font_size * 0.10)),
    }


def _srt_time_to_ass(ts: str) -> str:
    """'00:00:04,823' -> '0:00:04.82' (ASS uses centiseconds and a 1-digit hour)."""
    ts = ts.strip().replace(",", ".")
    hh, mm, rest = ts.split(":")
    secs = float(rest)
    return f"{int(hh)}:{mm}:{secs:05.2f}"


def parse_srt(srt_path: str) -> List[Dict[str, str]]:
    """Minimal SRT reader: returns [{start, end, text}] with newlines as '\\N'."""
    raw = Path(srt_path).read_text(encoding="utf-8", errors="replace")
    cues = []
    for block in re.split(r"\r?\n\r?\n", raw.strip()):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        timing = next((ln for ln in lines if "-->" in ln), None)
        if not timing:
            continue
        start, end = (p.strip() for p in timing.split("-->")[:2])
        text_lines = lines[lines.index(timing) + 1:]
        if not text_lines:
            continue
        cues.append({
            "start": _srt_time_to_ass(start),
            "end": _srt_time_to_ass(end),
            # ASS is one line per event; \N is its hard line break.
            "text": r"\N".join(ln.strip() for ln in text_lines),
        })
    return cues


def srt_to_ass(srt_path: str, ass_path: Path, width: int, height: int) -> Optional[str]:
    """Rewrite an SRT as ASS with PlayRes pinned to the frame.

    This exists because burning the SRT directly does not respect the frame shape.
    ffmpeg converts SRT to ASS with a fixed 384x288 script resolution and libass then
    scales that to the video, so `force_style` FontSize is not in frame pixels and a
    4:3 script laid over a 9:16 frame scales differently across the two axes. In a
    real 720x1280 render that produced captions roughly 4x too large, clipped on both
    sides and running off the top of the frame.

    With PlayResX/PlayResY equal to the frame, every value below IS in frame pixels,
    so one rule sizes captions correctly at any aspect ratio.
    """
    cues = parse_srt(srt_path)
    if not cues:
        return None

    m = caption_metrics(width, height)
    font_size, margin_v = m["font_size"], m["margin_v"]
    margin_lr, outline = m["margin_lr"], m["outline"]

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: None

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},&H00FFFFFF,&H00FFFFFF,&H00090D16,&H80000000,1,0,0,0,100,100,0,0,1,{outline},0,2,{margin_lr},{margin_lr},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    body = "\n".join(
        f"Dialogue: 0,{c['start']},{c['end']},Default,,0,0,0,,{c['text']}" for c in cues
    )
    ass_path.write_text(header + body + "\n", encoding="utf-8")
    return str(ass_path)


def build_subtitle_filter(subtitle_path: str, in_label: str,
                          out_label: str = "[v_sub]") -> str:
    """Burn a pre-sized ASS file. Its own PlayRes governs layout, so no force_style."""
    escaped = str(Path(subtitle_path).resolve()).replace("\\", "/").replace(":", "\\:")
    return f"{in_label}ass='{escaped}'{out_label}"


def ensure_ambient_bgm_track() -> Optional[Path]:
    """Ensures a subtle, warm ambient background music track exists in ASSETS_DIR."""
    bgm_file = ASSETS_DIR / "ambient_bed.mp3"
    if bgm_file.exists() and bgm_file.stat().st_size > 1000:
        return bgm_file
    try:
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "sine=frequency=216:beep_factor=0,volume=0.06",
            "-t", "120",
            "-c:a", "libmp3lame",
            "-b:a", "128k",
            str(bgm_file)
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if res.returncode == 0 and bgm_file.exists():
            return bgm_file
    except Exception:
        pass
    return None


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
    outro_video_path: Optional[str] = None,
    width: int = RENDER_WIDTH,
    height: int = RENDER_HEIGHT,
    background_music: bool = False,
    bgm_path: Optional[str] = None
) -> str:
    """
    Unified compiler supporting Remotion React and FFmpeg PiP Multi-Layer Compositing
    with Subtitle Burning, optional Intro / Outro Video Bumpers, and Background Music.
    """
    final_output_path = OUTPUT_DIR / output_filename

    # Assemble sequence clips with optional intro and outro bumpers
    final_clips = list(clip_paths)
    if intro_video_path:
        intro_norm = normalize_bumper_clip(
            intro_video_path,
            OUTPUT_DIR / f"intro_{Path(output_filename).stem}.mp4",
            width=width,
            height=height
        )
        if intro_norm:
            final_clips.insert(0, intro_norm)

    if outro_video_path:
        outro_norm = normalize_bumper_clip(
            outro_video_path,
            OUTPUT_DIR / f"outro_{Path(output_filename).stem}.mp4",
            width=width,
            height=height
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
                audio_path=audio_path,
                width=width,
                height=height
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

    # Background music resolution
    bgm_file = None
    if background_music and has_audio:
        if bgm_path and Path(bgm_path).exists():
            bgm_file = Path(bgm_path)
        else:
            bgm_file = ensure_ambient_bgm_track()

    has_bgm = bgm_file is not None and bgm_file.exists()

    try:
        filter_parts = []
        filter_parts.append(
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[bg]"
        )
        last_v = "[bg]"

        inputs = ["-f", "concat", "-safe", "0", "-i", str(concat_list_path)]
        input_count = 1

        voice_idx = None
        if has_audio:
            inputs.extend(["-stream_loop", "-1", "-i", str(Path(audio_path).resolve())])
            voice_idx = input_count
            input_count += 1

        avatar_idx = None
        if has_avatar:
            inputs.extend(["-loop", "1", "-i", str(Path(avatar_image_path).resolve())])
            avatar_idx = input_count
            input_count += 1

        bgm_idx = None
        if has_bgm:
            inputs.extend(["-stream_loop", "-1", "-i", str(bgm_file.resolve())])
            bgm_idx = input_count
            input_count += 1

        if has_avatar:
            avatar_parts = build_avatar_layers(
                avatar_layout, width, height, input_label=f"[{avatar_idx}:v]", base_label=last_v
            )
            filter_parts.extend(avatar_parts)
            last_v = "[v_avatar]"

        if has_srt:
            ass_file = srt_to_ass(
                srt_path,
                OUTPUT_DIR / f"subs_{Path(output_filename).stem}.ass",
                width,
                height,
            )
            if ass_file:
                filter_parts.append(build_subtitle_filter(ass_file, last_v))
                last_v = "[v_sub]"

        # Audio mixing if background music is active
        audio_map = None
        if has_bgm and voice_idx is not None:
            filter_parts.append(
                f"[{voice_idx}:a]volume=1.0[a_voice];[{bgm_idx}:a]volume=0.10[a_bgm];"
                f"[a_voice][a_bgm]amix=inputs=2:duration=first:dropout_transition=2[a_out]"
            )
            audio_map = "[a_out]"
        elif voice_idx is not None:
            audio_map = f"{voice_idx}:a:0"

        filter_complex_str = ";".join(filter_parts)

        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", filter_complex_str,
            "-map", last_v
        ]

        if audio_map:
            cmd.extend(["-map", audio_map, "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2", "-shortest"])

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
                "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                       f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1",
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
