"""
Script Orchestration Facade.
Provides backwards-compatible interface bridging to the new ScriptwriterAgent & PersonaIdentityContract.
"""
from typing import List, Optional
from pydantic import BaseModel, Field
from src.config import OLLAMA_BASE_URL, OLLAMA_MODEL, AVATAR_PROFILES
from src.contracts.persona import get_persona_contract, PersonaIdentityContract
from src.agents.scriptwriter import ScriptwriterAgent


class VideoScene(BaseModel):
    scene_id: int = Field(description="Sequential index starting from 1")
    visual_prompt: str = Field(default="", description="Detailed text-to-image prompt with style and character consistency.")
    motion_prompt: str = Field(default="Slow subtle cinematic camera motion", description="Action and camera movement prompt for video generation.")
    narration: Optional[str] = Field(default="", description="Spoken narration for this scene")
    duration_seconds: int = Field(default=5, description="Target duration of the scene in seconds.")
    video_source_type: str = Field(default="ai_generated", description="'ai_generated' or 'uploaded_video'")
    video_source_url: Optional[str] = Field(default="", description="Relative or absolute path to user uploaded MP4 video clip.")
    keep_original_audio: bool = Field(default=False, description="Whether to preserve the clip's original audio track instead of AI voiceover.")


class VideoScript(BaseModel):
    title: str = Field(description="Title of the video production")
    art_style_preset: str = Field(description="Consistent style anchor")
    avatar_anchor: Optional[str] = Field(default="", description="Character & persona continuity anchor")
    scenes: List[VideoScene] = Field(description="Ordered list of visual scenes")


class ScriptOrchestrator:
    def __init__(self, model_name: str = OLLAMA_MODEL, base_url: str = OLLAMA_BASE_URL):
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.scriptwriter = ScriptwriterAgent(ollama_host=self.base_url, model_name=self.model_name)

    @staticmethod
    def get_avatar_anchor(avatar_id: str) -> str:
        persona = get_persona_contract(avatar_id)
        return persona.visual_continuity_anchor

    @staticmethod
    def distill_visual_prompt(text: str, max_words: int = 35) -> str:
        agent = ScriptwriterAgent()
        return agent.distill_visual_prompt(text, max_words)

    def generate_script(
        self,
        topic: str,
        scene_count: int = 4,
        art_style: str = "Photorealistic 8K (Architectural / Corporate)",
        avatar_persona: str = "maya_fintech"
    ) -> VideoScript:
        persona = get_persona_contract(avatar_persona)
        contract = self.scriptwriter.generate_script(
            topic=topic,
            scene_count=scene_count,
            persona=persona,
            art_style=art_style
        )
        
        legacy_scenes = [
            VideoScene(
                scene_id=s.scene_id,
                visual_prompt=s.visual_description,
                motion_prompt=s.motion_prompt,
                narration=s.narration,
                duration_seconds=int(s.estimated_duration_sec),
                video_source_type=s.video_source_type,
                video_source_url=s.video_source_url
            )
            for s in contract.scenes
        ]

        return VideoScript(
            title=contract.course_title,
            art_style_preset=contract.art_style_preset,
            avatar_anchor=persona.visual_continuity_anchor,
            scenes=legacy_scenes
        )
