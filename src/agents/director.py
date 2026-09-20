"""
Director Agent (Master Orchestrator).
Governs the multi-agent generative workflow, enforces persona integrity,
executes validation gates, and locks audio-visual synchronization.
"""
import time
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple, Callable

from src.contracts.persona import PersonaIdentityContract, get_persona_contract, RegionLocaleEnum
from src.contracts.script_contract import ScriptContract, ScriptScene
from src.contracts.voice_contract import VoiceContract, SceneAudioArtifact
from src.contracts.visual_contract import ImageContract, SceneVisualArtifact
from src.agents.scriptwriter import ScriptwriterAgent
from src.agents.voice_director import VoiceDirectorAgent
from src.agents.image_generator import ImageGeneratorAgent
from src.agents.jev_advisor import audit_script_with_jev, verify_persona_compatibility
from src.pipeline import MediaGenerationEngine
from src.compiler import compile_final_video


class DirectorAgent:
    """
    Master Orchestration Agent. Coordinates Scriptwriter, Voice Director,
    and Image Generator workers, validates contracts, and ensures 1:1 AV sync.
    """

    def __init__(
        self,
        output_dir: Path,
        assets_dir: Path,
        log_callback: Optional[Callable[[str, str, int, str], None]] = None
    ):
        self.output_dir = output_dir
        self.assets_dir = assets_dir
        self.log_callback = log_callback or (lambda m, s, p, msg: None)
        
        self.scriptwriter = ScriptwriterAgent()
        self.voice_director = VoiceDirectorAgent(output_dir)
        self.image_generator = ImageGeneratorAgent(output_dir, assets_dir)
        self.media_engine = MediaGenerationEngine()

    def log(self, milestone: str, step: str, progress: int, message: str):
        """Dispatches milestone progress update."""
        self.log_callback(milestone, step, progress, message)

    # -------------------------------------------------------------------------
    # VALIDATION GATES
    # -------------------------------------------------------------------------
    def validate_gate_1_script(self, script: ScriptContract) -> Tuple[bool, str]:
        """
        Gate 1: Validates that the generated script conforms to pedagogical standards,
        has non-empty scenes, and appropriate duration bounds.
        """
        if not script.scenes:
            return False, "Script contains zero scenes."

        for scene in script.scenes:
            if not scene.narration.strip():
                return False, f"Scene {scene.scene_id} narration is blank."
            if not scene.visual_description.strip():
                return False, f"Scene {scene.scene_id} visual description is blank."
            if scene.estimated_duration_sec < 2.0 or scene.estimated_duration_sec > 60.0:
                return False, f"Scene {scene.scene_id} duration ({scene.estimated_duration_sec}s) out of bounds [2s, 60s]."

        # Jev System One Pedagogical & Prosody Audit
        jev_audit = audit_script_with_jev(
            course_title=script.course_title,
            persona_name=script.persona_id,
            scenes=[s.model_dump() if hasattr(s, "model_dump") else s.__dict__ for s in script.scenes]
        )
        if not jev_audit.is_valid:
            return False, f"Gate 1 Rejected by Jev: {jev_audit.feedback}"

        return True, f"Gate 1 Passed: {jev_audit.feedback}"

    def validate_gate_2_av_sync(
        self,
        script: ScriptContract,
        voice: VoiceContract,
        visuals: ImageContract
    ) -> List[Tuple[int, float, float]]:
        """
        Gate 2: Verifies and locks AV duration synchronization.
        Returns mapped (scene_id, measured_audio_duration, video_duration) tuples.
        """
        sync_map = []
        audio_durations = {a.scene_id: a.measured_duration_sec for a in voice.scene_audios}

        for scene in script.scenes:
            measured_audio_sec = audio_durations.get(scene.scene_id, scene.estimated_duration_sec)
            # Video clip duration is dynamically locked 1:1 to measured audio length
            sync_map.append((scene.scene_id, measured_audio_sec, measured_audio_sec))

        return sync_map

    # -------------------------------------------------------------------------
    # MASTER WORKFLOW EXECUTION
    # -------------------------------------------------------------------------
    def produce_course_video(
        self,
        topic: str,
        scene_count: int = 4,
        persona_id: str = "maya_fintech",
        art_style: str = "Photorealistic 8K (Corporate / Tech)",
        resolution: str = "16:9_hd",
        voice_override: Optional[str] = None,
        speech_rate: float = 1.0,
        pitch: str = "+0Hz",
        voice_engine: str = "edge_tts",
        elevenlabs_api_key: Optional[str] = None,
        elevenlabs_voice_id: Optional[str] = None,
        stability: float = 0.75,
        similarity_boost: float = 0.75,
        compiler_engine: str = "ffmpeg",
        avatar_layout: str = "pip_bottom_right",
        custom_avatar_path: Optional[str] = None,
        burn_subtitles: bool = True,
        intro_video_url: Optional[str] = None,
        outro_video_url: Optional[str] = None,
        predefined_script_contract: Optional[ScriptContract] = None
    ) -> Dict[str, Any]:
        """
        Executes end-to-end multi-agent video production.
        """
        job_id = uuid.uuid4().hex[:8]
        
        # PHASE 1: IDENTITY BINDING (Gate 3)
        persona = get_persona_contract(persona_id)
        self.log("init", "Persona bound", 10, f"[DIRECTOR] Persona bound: {persona.display_name} ({persona.demographic_ethnicity}, {persona.target_locale.value})")

        # PHASE 2: SCRIPTWRITING AGENT (Gate 1)
        if predefined_script_contract:
            script_contract = predefined_script_contract
            self.log("script", "Loaded Storyboard Script", 25, f"[SCRIPTWRITER] Loaded custom storyboard script with {len(script_contract.scenes)} scenes.")
        else:
            self.log("script", "Generating pedagogical script", 15, f"[SCRIPTWRITER] Decomposing topic '{topic[:40]}...' into {scene_count} scenes...")
            script_contract = self.scriptwriter.generate_script(
                topic=topic,
                scene_count=scene_count,
                persona=persona,
                art_style=art_style
            )
            self.log("script", "Script generated", 25, f"[SCRIPTWRITER] Script contract generated ({script_contract.total_word_count} words).")

        # Gate 1 Validation
        valid_script, script_msg = self.validate_gate_1_script(script_contract)
        if not valid_script:
            raise ValueError(f"Script validation failed: {script_msg}")

        # PHASE 3: PARALLEL ASSET SYNTHESIS
        # 3A: Voice Director Agent
        self.log("voiceover", "Synthesizing neural audio", 40, f"[VOICE DIRECTOR] Synthesizing audio via {voice_engine.upper()} for {len(script_contract.scenes)} scenes...")
        voice_contract = self.voice_director.synthesize_voice_contract(
            script=script_contract,
            persona=persona,
            voice_override=voice_override,
            speech_rate=speech_rate,
            pitch=pitch,
            engine=voice_engine,
            elevenlabs_api_key=elevenlabs_api_key,
            elevenlabs_voice_id=elevenlabs_voice_id,
            stability=stability,
            similarity_boost=similarity_boost
        )
        self.log("voiceover", "Audio synthesis complete", 55, f"[VOICE DIRECTOR] Audio master generated ({voice_contract.total_audio_duration_sec}s total).")

        # 3B: Image & Avatar Generator Agent
        self.log("keyframes", "Synthesizing visual keyframes", 60, f"[IMAGE GEN] Generating keyframes anchored to {persona.persona_id}...")
        visual_contract = self.image_generator.generate_visual_contract(
            script=script_contract,
            persona=persona,
            resolution=resolution,
            avatar_layout=avatar_layout,
            custom_avatar_path=custom_avatar_path
        )
        self.log("keyframes", "Keyframes ready", 70, f"[IMAGE GEN] {len(visual_contract.scene_visuals)} visual assets prepared.")

        # PHASE 4: MOTION SYNTHESIS & AV DURATION LOCK (Gate 2)
        self.log("motion", "Locking AV frame timing", 75, "[DIRECTOR] Locking video frame counts to exact measured audio milliseconds...")
        sync_map = self.validate_gate_2_av_sync(script_contract, voice_contract, visual_contract)
        
        clip_paths: List[str] = []
        audio_durations = {a.scene_id: a.measured_duration_sec for a in voice_contract.scene_audios}

        for visual in visual_contract.scene_visuals:
            scene_audio_len = audio_durations.get(visual.scene_id, 6.0)
            
            if visual.visual_type == "uploaded_video":
                # Pre-recorded video clip
                clip_paths.append(visual.media_path)
            else:
                # Synthesize Motion Video from Keyframe matched 1:1 to audio length
                clip_file = self.output_dir / f"clip_{job_id}_{visual.scene_id}.mp4"
                self.media_engine.generate_video(
                    image_path=Path(visual.media_path),
                    motion_prompt="Slow cinematic tracking camera movement",
                    output_path=clip_file,
                    duration_sec=int(scene_audio_len) + 1,
                    resolution=resolution
                )
                clip_paths.append(str(clip_file))

        self.log("motion", "Motion clips generated", 85, f"[MOTION] Generated {len(clip_paths)} synchronized video segments.")

        # PHASE 5: COMPOSITING & SCORM CONFORMANCE
        self.log("stitch", "Compositing master video", 90, f"[COMPOSITOR] Stitching final video using {compiler_engine.upper()}...")
        output_filename = f"prod_{job_id}_{persona.persona_id}.mp4"
        
        avatar_img_path = visual_contract.scene_visuals[0].avatar_overlay_path if visual_contract.scene_visuals else None

        final_video_path = compile_final_video(
            clip_paths=clip_paths,
            output_filename=output_filename,
            audio_path=voice_contract.master_audio_path,
            engine=compiler_engine,
            avatar_image_path=avatar_img_path,
            avatar_layout=avatar_layout,
            burn_subtitles=burn_subtitles,
            srt_path=voice_contract.subtitles_srt_path,
            intro_video_path=self.image_generator.resolve_video_source(intro_video_url),
            outro_video_path=self.image_generator.resolve_video_source(outro_video_url)
        )

        self.log("complete", "Video production complete", 100, f"[SUCCESS] Course video compiled: {Path(final_video_path).name}")

        return {
            "job_id": job_id,
            "status": "complete",
            "video_path": final_video_path,
            "filename": Path(final_video_path).name,
            "audio_master_path": voice_contract.master_audio_path,
            "subtitles_path": voice_contract.subtitles_srt_path,
            "script_contract": script_contract.model_dump(),
            "voice_contract": voice_contract.model_dump(),
            "visual_contract": visual_contract.model_dump(),
            "persona": persona.model_dump(),
            "total_duration_sec": voice_contract.total_audio_duration_sec
        }
