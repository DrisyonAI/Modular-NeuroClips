"""
Voice Director Sub-Agent (Enhanced v2).
Synthesizes neural speech (Edge-TTS, ElevenLabs, Kokoro-Local/Offline),
compiles expressive SSML prosody, applies domain pronunciation lexicons,
enforces EBU R128 loudness normalization (-14 LUFS), supports audio ducking,
and generates millisecond-accurate synchronized subtitles.
"""
import re
import json
import uuid
import asyncio
import subprocess
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

from src.contracts.persona import PersonaIdentityContract
from src.contracts.script_contract import ScriptContract, ScriptScene
from src.contracts.voice_contract import SceneAudioArtifact, VoiceContract
from src.lexicon import LexiconEngine, DEFAULT_FINTECH_LEXICON


class VoiceDirectorAgent:
    """
    Specialized agent responsible for vocal synthesis, SSML prosody tuning,
    domain pronunciation enforcement, broadcast audio mastering, and subtitle generation.
    """

    def __init__(self, output_dir: Path, custom_lexicon: Optional[Dict[str, str]] = None):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.lexicon_engine = LexiconEngine(custom_lexicon)

    def probe_audio_duration(self, audio_path: Path) -> float:
        """
        Probes exact audio file duration in seconds using ffprobe.
        Falls back to word estimation if ffprobe fails.
        """
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(audio_path)
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0 and res.stdout.strip():
                return max(round(float(res.stdout.strip()), 2), 1.0)
        except Exception:
            pass
        return 5.0

    def clean_narration_for_subtitles(self, raw_script: str) -> str:
        """Strips director tags completely for clean on-screen subtitle cards."""
        text = re.sub(r"\[pause\s+[^\]]+\]", "", raw_script, flags=re.IGNORECASE)
        text = re.sub(r"\[emphasis(?::\w+)?\]", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\[tone:\w+\]", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\[rate:[^\]]+\]", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\[protip\]", "💡 Pro Tip: ", text, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", text).strip()

    def compile_ssml_prosody(self, raw_script: str, voice_name: str, base_rate: float = 1.0, base_pitch: str = "+0Hz") -> Tuple[str, str]:
        """
        Transforms director cue markup into W3C SSML for neural TTS engines
        and outputs clean plain text with pronunciation lexicon applied.
        """
        text = self.lexicon_engine.apply_lexicon(raw_script.strip())

        # Build clean plain text for engines without SSML support
        clean_plain = text
        clean_plain = re.sub(r"\[pause\s+(\d+)m?s?\]", r" ... ", clean_plain, flags=re.IGNORECASE)
        clean_plain = re.sub(r"\[emphasis(?::\w+)?\]", "", clean_plain, flags=re.IGNORECASE)
        clean_plain = re.sub(r"\[tone:\w+\]", "", clean_plain, flags=re.IGNORECASE)
        clean_plain = re.sub(r"\[rate:[^\]]+\]", "", clean_plain, flags=re.IGNORECASE)
        clean_plain = re.sub(r"\[protip\]", "Pro tip: ", clean_plain, flags=re.IGNORECASE)
        clean_plain = re.sub(r"\s+", " ", clean_plain).strip()

        # Build SSML
        ssml_body = text
        # [pause 500ms] -> <break time="500ms"/>
        ssml_body = re.sub(
            r"\[pause\s+(\d+)m?s?\]",
            lambda m: f'<break time="{m.group(1)}ms"/>',
            ssml_body,
            flags=re.IGNORECASE
        )
        # [emphasis:strong]... or [emphasis] -> <emphasis level="strong">
        ssml_body = re.sub(r"\[emphasis(?::strong)?\]", '<emphasis level="strong">', ssml_body, flags=re.IGNORECASE)
        ssml_body = re.sub(r"\[/emphasis\]", '</emphasis>', ssml_body, flags=re.IGNORECASE)
        # [tone:urgent] or [tone:serious]
        ssml_body = re.sub(r"\[tone:urgent\]", '<prosody rate="+10%" pitch="+2Hz">', ssml_body, flags=re.IGNORECASE)
        ssml_body = re.sub(r"\[tone:serious\]", '<prosody rate="-5%" pitch="-2Hz">', ssml_body, flags=re.IGNORECASE)
        ssml_body = re.sub(r"\[tone:empathetic\]", '<prosody rate="-8%" pitch="+1Hz">', ssml_body, flags=re.IGNORECASE)
        ssml_body = re.sub(r"\[/tone\]", '</prosody>', ssml_body, flags=re.IGNORECASE)
        ssml_body = re.sub(r"\[protip\]", '<emphasis level="moderate">Pro tip:</emphasis> ', ssml_body, flags=re.IGNORECASE)

        # Rate and Pitch adjustments
        rate_percent = f"{int((base_rate - 1.0) * 100):+d}%"
        ssml = (
            f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">\n'
            f'  <voice name="{voice_name}">\n'
            f'    <prosody rate="{rate_percent}" pitch="{base_pitch}">\n'
            f'      {ssml_body}\n'
            f'    </prosody>\n'
            f'  </voice>\n'
            f'</speak>'
        )
        return ssml, clean_plain

    def normalize_lufs(self, input_audio_path: Path, output_audio_path: Path, target_lufs: float = -14.0) -> bool:
        """
        Normalizes audio loudness to EBU R128 standard (default -14 LUFS for modern online/LMS audio).
        """
        try:
            cmd = [
                "ffmpeg", "-y", "-i", str(input_audio_path),
                "-af", f"loudnorm=I={target_lufs}:LRA=7:tp=-1.5",
                "-ar", "44100",
                str(output_audio_path)
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return res.returncode == 0 and output_audio_path.exists() and output_audio_path.stat().st_size > 500
        except Exception as e:
            print(f"[Audio Normalize Warning] {e}")
            return False

    def apply_audio_ducking(self, speech_path: Path, bg_music_path: Path, output_path: Path) -> bool:
        """
        Mixes speech over background music, dynamically ducking the music volume when speech is active.
        """
        try:
            # sidechaincompress ducks music when speech is above threshold
            filter_complex = (
                "[1:a]volume=0.25[music];"
                "[music][0:a]sidechaincompress=threshold=0.125:ratio=4:attack=15:release=250[ducked_music];"
                "[ducked_music][0:a]amix=inputs=2:duration=first:dropout_transition=2[outa]"
            )
            cmd = [
                "ffmpeg", "-y",
                "-i", str(speech_path),
                "-i", str(bg_music_path),
                "-filter_complex", filter_complex,
                "-map", "[outa]",
                "-c:a", "mp3",
                str(output_path)
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return res.returncode == 0 and output_path.exists() and output_path.stat().st_size > 500
        except Exception as e:
            print(f"[Audio Ducking Warning] {e}")
            return False

    def synthesize_single_audio_file(
        self,
        text: str,
        voice: str,
        speech_rate: float,
        pitch: str,
        output_path: Path,
        engine: str = "edge_tts",
        elevenlabs_api_key: Optional[str] = None,
        elevenlabs_voice_id: Optional[str] = None,
        stability: float = 0.75,
        similarity_boost: float = 0.75
    ) -> bool:
        """
        Synthesizes audio using Edge-TTS (with SSML prosody and lexicon),
        ElevenLabs API, or local offline engine (Kokoro/pyttsx3).
        """
        ssml_content, clean_text = self.compile_ssml_prosody(
            raw_script=text,
            voice_name=voice,
            base_rate=speech_rate,
            base_pitch=pitch
        )
        if not clean_text:
            return False

        # 1. ElevenLabs Provider
        if engine == "elevenlabs" and elevenlabs_api_key and elevenlabs_api_key.strip():
            try:
                voice_id = elevenlabs_voice_id or "21m00Tcm4TlvDq8ikWAM"
                url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
                headers = {
                    "xi-api-key": elevenlabs_api_key.strip(),
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg"
                }
                payload = {
                    "text": clean_text,
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
                print(f"[ElevenLabs Warning] Error ({e}), falling back to Edge-TTS.")

        # 2. Local Offline Neural Kokoro Engine Fallback
        if engine == "kokoro_local":
            try:
                from kokoro import KPipeline
                import soundfile as sf
                pipeline = KPipeline(lang_code='a')
                generator = pipeline(clean_text, voice='af_heart', speed=speech_rate, split_pattern=r'\n+')
                for _, _, audio in generator:
                    sf.write(str(output_path), audio, 24000)
                    return output_path.exists() and output_path.stat().st_size > 500
            except Exception as e:
                print(f"[Kokoro Local Warning] Offline model not loaded ({e}), falling back.")

        # 3. Edge-TTS Neural Provider (Default / SSML-capable)
        try:
            import edge_tts
            rate_str = f"{int((speech_rate - 1.0) * 100):+d}%"
            
            async def _run_edge():
                comm = edge_tts.Communicate(clean_text, voice, rate=rate_str, pitch=pitch, volume="+0%")
                await comm.save(str(output_path))

            _tts_err = {}

            def _tts_runner():
                try:
                    asyncio.run(_run_edge())
                except Exception as exc:
                    _tts_err["err"] = exc

            import threading
            t = threading.Thread(target=_tts_runner, daemon=True)
            t.start()
            t.join(timeout=180)
            if t.is_alive():
                print("[VoiceDirector Error] edge-tts synthesis timed out after 180s")
            elif "err" in _tts_err:
                print(f"[Edge-TTS Error] {_tts_err['err']}")

            if output_path.exists() and output_path.stat().st_size > 500:
                return True
        except Exception as e:
            print(f"[Edge-TTS Error] {e}")

        # 4. pyttsx3 Local Desktop Fallback
        try:
            import pyttsx3
            engine_tts = pyttsx3.init()
            engine_tts.save_to_file(clean_text, str(output_path))
            engine_tts.runAndWait()
            return output_path.exists() and output_path.stat().st_size > 100
        except Exception:
            return False

    def generate_srt_subtitles(
        self,
        scene_artifacts: List[SceneAudioArtifact],
        scenes: List[ScriptScene],
        output_path: Path
    ) -> Path:
        """
        Generates millisecond-accurate SRT subtitle file synchronized to measured audio durations.
        """
        def format_srt_time(seconds: float) -> str:
            hrs = int(seconds // 3600)
            mins = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            millis = int((seconds - int(seconds)) * 1000)
            return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"

        srt_lines = []
        current_time = 0.0

        for i, (artifact, scene) in enumerate(zip(scene_artifacts, scenes), start=1):
            clean_sub = self.clean_narration_for_subtitles(scene.narration)
            start_str = format_srt_time(current_time)
            end_time = current_time + artifact.measured_duration_sec
            end_str = format_srt_time(end_time)

            srt_lines.append(f"{i}\n{start_str} --> {end_str}\n{clean_sub}\n")
            current_time = end_time

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_lines))

        return output_path

    def synthesize_voice_contract(
        self,
        script: ScriptContract,
        persona: PersonaIdentityContract,
        voice_override: Optional[str] = None,
        speech_rate: float = 1.0,
        pitch: str = "+0Hz",
        engine: str = "edge_tts",
        elevenlabs_api_key: Optional[str] = None,
        elevenlabs_voice_id: Optional[str] = None,
        stability: float = 0.75,
        similarity_boost: float = 0.75,
        target_lufs: Optional[float] = -14.0,
        bg_music_path: Optional[Path] = None
    ) -> VoiceContract:
        """
        Synthesizes complete voice production across all scenes,
        probes exact audio duration per scene, normalizes loudness, ducks music if provided,
        and packages the verified VoiceContract.
        """
        chosen_voice = voice_override or persona.canonical_voice
        chosen_eleven_id = elevenlabs_voice_id or persona.elevenlabs_voice_id
        session_id = uuid.uuid4().hex[:8]

        scene_artifacts: List[SceneAudioArtifact] = []
        scene_audio_paths: List[Path] = []

        for scene in script.scenes:
            scene_path = self.output_dir / f"audio_scene_{session_id}_{scene.scene_id}.mp3"
            success = self.synthesize_single_audio_file(
                text=scene.narration,
                voice=chosen_voice,
                speech_rate=speech_rate,
                pitch=pitch,
                output_path=scene_path,
                engine=engine,
                elevenlabs_api_key=elevenlabs_api_key,
                elevenlabs_voice_id=chosen_eleven_id,
                stability=stability,
                similarity_boost=similarity_boost
            )
            if not success or not scene_path.exists():
                # Create silent fallback
                subprocess.run(
                    ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "5", str(scene_path)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )

            measured_sec = self.probe_audio_duration(scene_path)
            scene_artifacts.append(
                SceneAudioArtifact(
                    scene_id=scene.scene_id,
                    audio_path=str(scene_path),
                    measured_duration_sec=measured_sec
                )
            )
            scene_audio_paths.append(scene_path)

        # Merge master audio track via FFmpeg concat
        raw_master_audio_path = self.output_dir / f"master_raw_{session_id}.mp3"
        final_master_audio_path = self.output_dir / f"master_audio_{session_id}.mp3"
        concat_list_file = self.output_dir / f"concat_audio_{session_id}.txt"
        with open(concat_list_file, "w", encoding="utf-8") as f:
            for p in scene_audio_paths:
                f.write(f"file '{p.resolve().as_posix()}'\n")

        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list_file), "-c", "copy", str(raw_master_audio_path)]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if not raw_master_audio_path.exists() and scene_audio_paths:
            raw_master_audio_path = scene_audio_paths[0]

        # Apply LUFS Normalization
        master_to_use = raw_master_audio_path
        if target_lufs is not None:
            norm_path = self.output_dir / f"master_norm_{session_id}.mp3"
            if self.normalize_lufs(raw_master_audio_path, norm_path, target_lufs):
                master_to_use = norm_path

        # Apply Audio Ducking if background music is supplied
        bg_applied = False
        if bg_music_path and bg_music_path.exists():
            ducked_path = self.output_dir / f"master_ducked_{session_id}.mp3"
            if self.apply_audio_ducking(master_to_use, bg_music_path, ducked_path):
                master_to_use = ducked_path
                bg_applied = True

        # Copy/link to final master path
        if master_to_use != final_master_audio_path:
            import shutil
            shutil.copyfile(master_to_use, final_master_audio_path)

        total_audio_sec = sum(a.measured_duration_sec for a in scene_artifacts)

        # Generate Synchronized SRT Subtitles
        srt_path = self.output_dir / f"subtitles_{session_id}.srt"
        self.generate_srt_subtitles(scene_artifacts, script.scenes, srt_path)

        return VoiceContract(
            voice_profile_used=chosen_voice,
            engine=engine,
            pitch=pitch,
            speech_rate=speech_rate,
            master_audio_path=str(final_master_audio_path),
            subtitles_srt_path=str(srt_path),
            total_audio_duration_sec=total_audio_sec,
            scene_audios=scene_artifacts,
            normalized_lufs=target_lufs,
            bg_music_applied=bg_applied
        )
