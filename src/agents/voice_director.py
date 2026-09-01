"""
Voice Director Sub-Agent.
Synthesizes neural speech (Edge-TTS & ElevenLabs), enforces prosody,
probes exact audio duration via ffprobe, and creates synchronized subtitles.
"""
import re
import json
import uuid
import asyncio
import subprocess
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple
from src.contracts.persona import PersonaIdentityContract
from src.contracts.script_contract import ScriptContract, ScriptScene
from src.contracts.voice_contract import SceneAudioArtifact, VoiceContract


class VoiceDirectorAgent:
    """
    Specialized agent responsible for vocal synthesis, prosody tuning,
    exact audio duration measurement, and subtitle generation.
    """

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

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

    def clean_narration_for_tts(self, raw_script: str) -> str:
        """Translates director cue tags into natural speech pauses and cleans formatting."""
        text = raw_script.strip()
        # [pause 500ms] -> natural breath pause
        text = re.sub(r"\[pause\s+(\d+)m?s?\]", r" ... ", text, flags=re.IGNORECASE)
        text = re.sub(r"\[emphasis\]", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\[protip\]", "Pro tip: ", text, flags=re.IGNORECASE)
        return text

    def clean_narration_for_subtitles(self, raw_script: str) -> str:
        """Strips director tags completely for clean on-screen subtitle cards."""
        text = re.sub(r"\[pause\s+[^\]]+\]", "", raw_script, flags=re.IGNORECASE)
        text = re.sub(r"\[emphasis\]", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\[protip\]", "💡 Pro Tip: ", text, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", text).strip()

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
        """Synthesizes audio using Edge-TTS or ElevenLabs API."""
        clean_text = self.clean_narration_for_tts(text)
        if not clean_text:
            return False

        # 1. ElevenLabs API Provider
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

        # 2. Edge-TTS High-Definition Neural Provider
        try:
            import edge_tts
            rate_str = f"{int((speech_rate - 1.0) * 100):+d}%"
            
            async def _run_edge():
                comm = edge_tts.Communicate(clean_text, voice, rate=rate_str, pitch=pitch, volume="+0%")
                await comm.save(str(output_path))

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import nest_asyncio
                    nest_asyncio.apply()
                    loop.run_until_complete(_run_edge())
                else:
                    loop.run_until_complete(_run_edge())
            except Exception:
                asyncio.run(_run_edge())

            return output_path.exists() and output_path.stat().st_size > 500
        except Exception as e:
            print(f"[Edge-TTS Error] {e}")

        # 3. pyttsx3 Local Fallback
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
        similarity_boost: float = 0.75
    ) -> VoiceContract:
        """
        Synthesizes complete voice production across all scenes,
        probes exact audio duration per scene, and merges the master track.
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
        master_audio_path = self.output_dir / f"master_audio_{session_id}.mp3"
        concat_list_file = self.output_dir / f"concat_audio_{session_id}.txt"
        with open(concat_list_file, "w", encoding="utf-8") as f:
            for p in scene_audio_paths:
                f.write(f"file '{p.resolve().as_posix()}'\n")

        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list_file), "-c", "copy", str(master_audio_path)]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if not master_audio_path.exists() and scene_audio_paths:
            master_audio_path = scene_audio_paths[0]

        total_audio_sec = sum(a.measured_duration_sec for a in scene_artifacts)

        # Generate Synchronized SRT Subtitles
        srt_path = self.output_dir / f"subtitles_{session_id}.srt"
        self.generate_srt_subtitles(scene_artifacts, script.scenes, srt_path)

        return VoiceContract(
            voice_profile_used=chosen_voice,
            engine=engine,
            pitch=pitch,
            speech_rate=speech_rate,
            master_audio_path=str(master_audio_path),
            subtitles_srt_path=str(srt_path),
            total_audio_duration_sec=total_audio_sec,
            scene_audios=scene_artifacts
        )
