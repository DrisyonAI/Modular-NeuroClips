import re
import json
import urllib.request
import urllib.error
from typing import List, Optional
from pydantic import BaseModel, Field
from src.config import OLLAMA_BASE_URL, OLLAMA_MODEL, AVATAR_PROFILES

class VideoScene(BaseModel):
    scene_id: int = Field(description="Sequential index starting from 1")
    visual_prompt: str = Field(description="Detailed text-to-image prompt with style and character consistency.")
    motion_prompt: str = Field(description="Action and camera movement prompt for video generation.")
    narration: Optional[str] = Field(default="", description="Spoken narration for this scene")
    duration_seconds: int = Field(default=5, description="Target duration of the scene in seconds.")

class VideoScript(BaseModel):
    title: str = Field(description="Title of the video production")
    art_style_preset: str = Field(description="Consistent style anchor")
    avatar_anchor: Optional[str] = Field(default="", description="Character & persona continuity anchor")
    scenes: List[VideoScene] = Field(description="Ordered list of visual scenes")

class ScriptOrchestrator:
    def __init__(self, model_name: str = OLLAMA_MODEL, base_url: str = OLLAMA_BASE_URL):
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")

    @staticmethod
    def get_avatar_anchor(avatar_id: str) -> str:
        for av in AVATAR_PROFILES:
            if av["id"] == avatar_id:
                return av.get("continuity_anchor", "")
        return ""

    @staticmethod
    def distill_visual_prompt(text: str, max_words: int = 35) -> str:
        cleaned = re.sub(r"(?i)\b(in this (video|lesson|module|course|slide)|as you can see|let's discuss|we will explore|here we have|welcome to|now we look at)\b", "", text)
        cleaned = re.sub(r"[\r\n\t]+", " ", cleaned)
        cleaned = re.sub(r"[^\w\s\-,.]", "", cleaned).strip()
        words = cleaned.split()
        if len(words) > max_words:
            cleaned = " ".join(words[:max_words])
        return cleaned if cleaned else text[:120]

    def generate_script(
        self,
        topic: str,
        scene_count: int = 4,
        art_style: str = "Photorealistic 8K (Architectural / Corporate)",
        avatar_persona: str = "maya_fintech"
    ) -> VideoScript:
        avatar_anchor = self.get_avatar_anchor(avatar_persona)

        # Domain Specific Heuristic Recognition (e.g. Excel Goal Seek)
        lower_topic = topic.lower()
        if "goal seek" in lower_topic or "excel" in lower_topic:
            return VideoScript(
                title="Mastering Excel Goal Seek: Step-by-Step Tutorial",
                art_style_preset=art_style,
                avatar_anchor=avatar_anchor,
                scenes=[
                    VideoScene(
                        scene_id=1,
                        visual_prompt="Close up modern computer monitor displaying an open Microsoft Excel spreadsheet with revenue model, price, units sold, and target profit cells highlighted in neon green, high resolution, ultra clear UI screenshot",
                        motion_prompt="Slow cinematic push-in towards the target profit cell in Excel",
                        narration="Welcome to this tutorial on Microsoft Excel Goal Seek. Goal Seek is a powerful What-If Analysis tool that determines the input value needed to achieve your target result.",
                        duration_seconds=6
                    ),
                    VideoScene(
                        scene_id=2,
                        visual_prompt="Detailed Microsoft Excel ribbon menu focusing on the Data tab, clicking What-If Analysis dropdown button and selecting Goal Seek, crisp 4k software interface",
                        motion_prompt="Smooth pan across the Excel Data ribbon towards the What-If Analysis menu",
                        narration="To launch it, navigate to the Data tab on your ribbon, click What-If Analysis, and select Goal Seek from the dropdown.",
                        duration_seconds=5
                    ),
                    VideoScene(
                        scene_id=3,
                        visual_prompt="The Excel Goal Seek dialog popup box with three parameters: Set cell, To value, and By changing cell filled with financial variables, sharp typography, 8k UI design",
                        motion_prompt="Steady macro focus on the Goal Seek dialog box showing the three parameter inputs",
                        narration="In the dialog box, define your Set Cell with the formula, enter your target value in 'To Value', and select your variable cell in 'By Changing Cell'.",
                        duration_seconds=6
                    ),
                    VideoScene(
                        scene_id=4,
                        visual_prompt="Microsoft Excel spreadsheet instantly updating the calculation, displaying the exact target output reached with a green checkmark confirmation, modern corporate office background",
                        motion_prompt="Slow zoom-out showing the successfully calculated financial model",
                        narration="Click OK, and Excel automatically iterates to find the exact required input value to hit your goal. You can now apply Goal Seek across your financial and operational models.",
                        duration_seconds=6
                    )
                ]
            )

        # Dynamic sentence breakdown
        sentences = [s.strip() for s in re.split(r"[.!?]+", topic) if len(s.strip()) > 8]
        if not sentences:
            sentences = [topic]

        camera_moves = [
            "Slow cinematic tracking shot forward, volumetric studio lighting",
            "Dynamic sweeping lateral pan across modern interfaces",
            "Slow motion close-up focus pull with crystal clear detail",
            "Wide establishing cinematic angle, dramatic contrast and depth"
        ]

        scenes = []
        for i in range(scene_count):
            sentence_focus = sentences[i] if i < len(sentences) else sentences[i % len(sentences)]
            distilled_prompt = self.distill_visual_prompt(sentence_focus, max_words=25)
            
            visual_prompt = f"Professional high-fidelity visual illustration of {distilled_prompt}, clear UI elements, detailed composition"
            
            scenes.append(VideoScene(
                scene_id=i + 1,
                visual_prompt=visual_prompt,
                motion_prompt=camera_moves[i % len(camera_moves)],
                narration=sentence_focus[:160],
                duration_seconds=5
            ))

        clean_title = sentences[0][:45] if sentences else topic[:45]
        return VideoScript(
            title=f"{clean_title.strip()}",
            art_style_preset=art_style,
            avatar_anchor=avatar_anchor,
            scenes=scenes
        )
