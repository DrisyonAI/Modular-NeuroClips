"""
Audio and media utility service.
Provides neural speech synthesis, prosody adjustments, format conversion,
lightweight narration translation, and asset path resolution.
"""
import os
import re
import json
import asyncio
import threading
import subprocess
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Optional

from src.config import OUTPUT_DIR, ASSETS_DIR


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
    similarity_boost: float = 0.75,
) -> bool:
    """
    Generates voiceover narration supporting Edge-TTS with pitch/rate/volume prosody
    and ElevenLabs multilingual neural synthesis with stability/similarity control.
    Uses thread-isolated event loops to prevent event loop collision under ASGI/uvloop.
    """
    clean_text = text.strip()
    if not clean_text:
        return False

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. ElevenLabs Neural Provider
    if voice_provider == "elevenlabs" and elevenlabs_api_key and elevenlabs_api_key.strip():
        try:
            voice_id = elevenlabs_voice_id or "21m00Tcm4TlvDq8ikWAM"
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
            headers = {
                "xi-api-key": elevenlabs_api_key.strip(),
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
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
                    "use_speaker_boost": True,
                },
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
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
        formatted_text = re.sub(r"\[pause\s+(\d+)m?s?\]", r" ... ", clean_text, flags=re.IGNORECASE)
        formatted_text = re.sub(r"\[emphasis\]", "", formatted_text, flags=re.IGNORECASE)
        formatted_text = re.sub(r"\[protip\]", "Pro tip: ", formatted_text, flags=re.IGNORECASE)

        async def _save_tts():
            communicate = edge_tts.Communicate(
                formatted_text, voice, rate=rate_str, pitch=pitch, volume=volume
            )
            await communicate.save(str(output_path))

        _tts_err = {}

        def _tts_runner():
            try:
                asyncio.run(_save_tts())
            except Exception as exc:
                _tts_err["err"] = exc

        _t = threading.Thread(target=_tts_runner, daemon=True)
        _t.start()
        _t.join(timeout=180)
        if _t.is_alive():
            raise TimeoutError("edge-tts did not complete within 180s")
        if "err" in _tts_err:
            raise _tts_err["err"]

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

    return False


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
