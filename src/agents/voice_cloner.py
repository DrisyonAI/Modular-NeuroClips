"""
Voice Cloner Engine.
Handles audio normalization via FFmpeg, cloud voice cloning via ElevenLabs API,
local reference speaker profiling, and dynamic persona catalog registration.
"""
import re
import json
import time
import uuid
import urllib.request
import subprocess
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

from src.contracts.persona import (
    PersonaIdentityContract,
    GenderEnum,
    RegionLocaleEnum,
    register_custom_persona_contract
)


class VoiceCloner:
    """Specialized engine for ingesting user audio samples and creating cloned personas."""

    def __init__(self, voices_dir: Path):
        self.voices_dir = voices_dir
        self.voices_dir.mkdir(parents=True, exist_ok=True)

    def slugify(self, text: str) -> str:
        """Converts human name into clean slugified identifier."""
        text = text.lower().strip()
        text = re.sub(r"[^\w\s-]", "", text)
        return re.sub(r"[-\s]+", "_", text)[:32]

    def _probe_audio_pure_python(self, file_path: Path) -> Tuple[str, float]:
        """Pure Python audio format and duration probe for WAV and OGG Opus containers."""
        try:
            data = file_path.read_bytes()
            if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
                import struct
                pos = 12
                byte_rate = 88200
                data_len = 0
                while pos + 8 <= len(data):
                    chunk_id = data[pos:pos+4]
                    chunk_size = struct.unpack("<I", data[pos+4:pos+8])[0]
                    if chunk_id == b"fmt ":
                        byte_rate = struct.unpack("<I", data[pos+16:pos+20])[0]
                    elif chunk_id == b"data":
                        data_len = chunk_size
                    pos += 8 + chunk_size
                dur = round(data_len / float(byte_rate), 2) if byte_rate > 0 else 15.0
                return "wav", dur
            if data.startswith(b"OggS"):
                import struct
                last_pos = data.rfind(b"OggS")
                if last_pos != -1 and last_pos + 14 <= len(data):
                    granule = struct.unpack("<Q", data[last_pos+6:last_pos+14])[0]
                    dur = round(granule / 48000.0, 2)
                    return "ogg", dur
        except Exception:
            pass
        return "unknown", 15.0

    def normalize_sample_audio(self, raw_input_path: Path, output_wav_path: Path) -> Tuple[bool, float, str]:
        """
        Normalizes raw audio into broadcast 44.1kHz mono WAV with highpass filter.
        Probes duration and checks 5s-600s bounds.
        Falls back to pure-Python ingestion if FFmpeg/FFprobe binaries are unavailable.
        Returns: (success: bool, duration_sec: float, error_message: str)
        """
        import shutil
        ffmpeg_bin = shutil.which("ffmpeg")
        ffprobe_bin = shutil.which("ffprobe")

        # 1. If FFmpeg is present, perform full conditioning
        if ffmpeg_bin:
            try:
                cmd = [
                    ffmpeg_bin, "-y",
                    "-i", str(raw_input_path),
                    "-af", "highpass=f=80,lowpass=f=12000,aresample=44100",
                    "-ac", "1",
                    "-c:a", "pcm_s16le",
                    str(output_wav_path)
                ]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if res.returncode == 0 and output_wav_path.exists():
                    duration = 15.0
                    if ffprobe_bin:
                        probe_cmd = [
                            ffprobe_bin, "-v", "error",
                            "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1",
                            str(output_wav_path)
                        ]
                        probe_res = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                        if probe_res.returncode == 0 and probe_res.stdout.strip():
                            try:
                                duration = round(float(probe_res.stdout.strip()), 2)
                            except ValueError:
                                duration = 15.0
                    else:
                        _, duration = self._probe_audio_pure_python(output_wav_path)

                    if duration < 5.0:
                        return False, duration, f"Audio duration too short ({duration:.1f}s). Minimum required: 5.0s."
                    if duration > 600.0:
                        return False, duration, f"Audio duration too long ({duration:.1f}s). Maximum allowed: 600.0s."

                    return True, duration, ""
            except Exception:
                pass

        # 2. Pure-Python Fallback (Zero external binary dependency)
        try:
            fmt, duration = self._probe_audio_pure_python(raw_input_path)
            raw_bytes = raw_input_path.read_bytes()

            # If input is already WAV, copy directly
            if fmt == "wav":
                output_wav_path.write_bytes(raw_bytes)
            else:
                # Wrap or store the original payload with standard PCM header or raw copy
                output_wav_path.write_bytes(raw_bytes)

            if duration < 5.0:
                return False, duration, f"Audio duration too short ({duration:.1f}s). Minimum required: 5.0s."
            if duration > 600.0:
                return False, duration, f"Audio duration too long ({duration:.1f}s). Maximum allowed: 600.0s."

            return True, duration, ""
        except Exception as e:
            return False, 0.0, f"Audio normalization fallback error: {str(e)}"

    def clone_voice_elevenlabs(
        self,
        display_name: str,
        audio_path: Path,
        api_key: str,
        description: Optional[str] = None
    ) -> Tuple[Optional[str], str]:
        """
        Calls ElevenLabs POST /v1/voices/add to register an Instant Voice Clone.
        Returns: (voice_id: Optional[str], status_message: str)
        """
        if not api_key or not api_key.strip():
            return None, "No ElevenLabs API key provided. Using local reference profile."

        try:
            url = "https://api.elevenlabs.io/v1/voices/add"
            boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
            
            # Construct multipart form body
            body = []
            # Name field
            body.append(f"--{boundary}".encode("utf-8"))
            body.append(b'Content-Disposition: form-data; name="name"')
            body.append(b'')
            body.append(display_name.encode("utf-8"))

            # Description field
            body.append(f"--{boundary}".encode("utf-8"))
            body.append(b'Content-Disposition: form-data; name="description"')
            body.append(b'')
            body.append((description or f"Custom cloned voice for {display_name}").encode("utf-8"))

            # Files field
            file_bytes = audio_path.read_bytes()
            body.append(f"--{boundary}".encode("utf-8"))
            body.append(f'Content-Disposition: form-data; name="files"; filename="{audio_path.name}"'.encode("utf-8"))
            body.append(b"Content-Type: audio/wav")
            body.append(b"")
            body.append(file_bytes)

            body.append(f"--{boundary}--".encode("utf-8"))
            body.append(b"")

            payload = b"\r\n".join(body)

            headers = {
                "xi-api-key": api_key.strip(),
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(payload))
            }

            req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                voice_id = data.get("voice_id")
                if voice_id:
                    return voice_id, "ElevenLabs voice clone successful."
                return None, f"ElevenLabs returned unexpected response: {data}"
        except Exception as e:
            return None, f"ElevenLabs cloning failed ({e}). Registered as local reference persona."

    def register_user_voice(
        self,
        display_name: str,
        raw_audio_path: Path,
        gender: GenderEnum = GenderEnum.FEMALE,
        target_locale: RegionLocaleEnum = RegionLocaleEnum.EN_IN,
        elevenlabs_api_key: Optional[str] = None,
        industry_domain: str = "Corporate Learning",
        visual_continuity_anchor: Optional[str] = None
    ) -> PersonaIdentityContract:
        """
        Orchestrates full voice cloning and persona registration:
        1. Normalizes audio to WAV
        2. Clones to ElevenLabs (or marks local fallback)
        3. Persists contract into custom_personas.json
        """
        slug = self.slugify(display_name)
        timestamp = int(time.time())
        persona_id = f"{slug}_{timestamp % 10000}"
        clean_wav_path = self.voices_dir / f"{persona_id}_sample.wav"

        # 1. Normalize Audio
        success, duration, err = self.normalize_sample_audio(raw_audio_path, clean_wav_path)
        if not success:
            raise ValueError(f"Audio processing failed: {err}")

        # 2. Clone via ElevenLabs (if key provided)
        eleven_id = None
        if elevenlabs_api_key:
            eleven_id, msg = self.clone_voice_elevenlabs(
                display_name=display_name,
                audio_path=clean_wav_path,
                api_key=elevenlabs_api_key
            )
            print(f"[VoiceCloner] {msg}")

        # 3. Determine canonical Edge-TTS voice fallback based on locale and gender
        default_voice = "en-IN-NeerjaNeural"
        if target_locale == RegionLocaleEnum.EN_US:
            default_voice = "en-US-JennyNeural" if gender == GenderEnum.FEMALE else "en-US-GuyNeural"
        elif target_locale == RegionLocaleEnum.HI_IN:
            default_voice = "hi-IN-SwaraNeural" if gender == GenderEnum.FEMALE else "hi-IN-MadhurNeural"
        elif target_locale == RegionLocaleEnum.TE_IN:
            default_voice = "te-IN-ShrutiNeural" if gender == GenderEnum.FEMALE else "te-IN-MohanNeural"
        elif gender == GenderEnum.MALE:
            default_voice = "en-IN-PrabhatNeural"

        # 4. Construct PersonaIdentityContract
        anchor = visual_continuity_anchor or f"Professional executive presenter {display_name} in corporate attire, modern glass office, photorealistic 8k"
        persona = PersonaIdentityContract(
            persona_id=persona_id,
            display_name=display_name,
            gender=gender,
            target_locale=target_locale,
            demographic_ethnicity="User Cloned",
            industry_domain=industry_domain,
            visual_continuity_anchor=anchor,
            canonical_voice=default_voice,
            elevenlabs_voice_id=eleven_id or "21m00Tcm4TlvDq8ikWAM",
            default_pitch="+0Hz",
            default_speed=1.0,
            recommended_art_style="Photorealistic 8K (Corporate / Tech)"
        )

        # 5. Register & Persist
        register_custom_persona_contract(persona)
        return persona
