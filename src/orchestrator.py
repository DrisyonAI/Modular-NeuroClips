import re
import json
import urllib.request
import urllib.error
from typing import List, Optional
from pydantic import BaseModel, Field
from src.config import OLLAMA_BASE_URL, OLLAMA_MODEL

class VideoScene(BaseModel):
    scene_id: int = Field(description="Sequential index starting from 1")
    visual_prompt: str = Field(description="Detailed text-to-image prompt with style and character consistency.")
    motion_prompt: str = Field(description="Action and camera movement prompt for video generation.")
    narration: Optional[str] = Field(default="", description="Spoken narration for this scene")
    duration_seconds: int = Field(default=4, description="Target duration of the scene in seconds.")

class VideoScript(BaseModel):
    title: str = Field(description="Title of the video production")
    art_style_preset: str = Field(description="Consistent style anchor")
    scenes: List[VideoScene] = Field(description="Ordered list of visual scenes")

class ScriptOrchestrator:
    def __init__(self, model_name: str = OLLAMA_MODEL, base_url: str = OLLAMA_BASE_URL):
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")

    @staticmethod
    def distill_visual_prompt(text: str, max_words: int = 35) -> str:
        """Cleans conversational or lengthy text into a crisp, high-impact visual scene prompt."""
        cleaned = re.sub(r"(?i)\b(in this (video|lesson|module|course|slide)|as you can see|let's discuss|we will explore|here we have|welcome to|now we look at)\b", "", text)
        cleaned = re.sub(r"[\r\n\t]+", " ", cleaned)
        cleaned = re.sub(r"[^\w\s\-,.]", "", cleaned).strip()
        
        words = cleaned.split()
        if len(words) > max_words:
            cleaned = " ".join(words[:max_words])
            
        return cleaned if cleaned else text[:120]

    def generate_script(self, topic: str, scene_count: int = 3, art_style: str = "Cinematic 35mm") -> VideoScript:
        """Generates structured multi-scene script via Ollama REST API or intelligent heuristic director."""
        try:
            from langchain_community.chat_models import ChatOllama
            from langchain_core.prompts import ChatPromptTemplate
            from langchain_core.output_parsers import JsonOutputParser
            
            llm = ChatOllama(model=self.model_name, base_url=self.base_url, temperature=0.7)
            parser = JsonOutputParser(pydantic_object=VideoScript)
            prompt = ChatPromptTemplate.from_messages([
                ("system", "You are an expert film director and AI video prompter. "
                           "Break down video concepts or long scripts into concise, vivid visual prompts per scene (under 30 words per visual prompt). "
                           "Ensure lighting styles, colors, and subjects stay visually cohesive.\n"
                           "{format_instructions}"),
                ("user", "Create a video script for topic: {topic}. Target duration: {scene_count} scenes. Art style: {art_style}")
            ])
            chain = prompt | llm | parser
            raw_output = chain.invoke({
                "topic": topic,
                "scene_count": scene_count,
                "art_style": art_style,
                "format_instructions": parser.get_format_instructions()
            })
            return VideoScript(**raw_output)
        except Exception:
            pass

        try:
            req_url = f"{self.base_url}/api/generate"
            prompt_text = f"""
            You are an expert film director. Break down this concept/script into {scene_count} distinct visual scenes.
            CRITICAL: 'visual_prompt' must be a concise (15-30 words) description of visual subjects, setting, lighting, and textures (NOT the spoken paragraph).
            
            Output ONLY valid JSON matching this schema:
            {{
              "title": "Short Title",
              "art_style_preset": "{art_style}",
              "scenes": [
                 {{
                   "scene_id": 1,
                   "visual_prompt": "Concise visual scene description",
                   "motion_prompt": "Cinematic camera movement",
                   "narration": "Short spoken sentence",
                   "duration_seconds": 4
                 }}
              ]
            }}
            
            Topic/Source Text: {topic}
            """
            payload = json.dumps({"model": self.model_name, "prompt": prompt_text, "stream": False, "format": "json"}).encode("utf-8")
            req = urllib.request.Request(req_url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                parsed = json.loads(res_data.get("response", "{}"))
                return VideoScript(**parsed)
        except Exception:
            pass

        sentences = [s.strip() for s in re.split(r"[.!?]+", topic) if len(s.strip()) > 8]
        if not sentences:
            sentences = [topic]

        camera_moves = [
            "Slow cinematic tracking shot forward, volumetric rim lighting",
            "Dynamic sweeping lateral pan across modern holographic interfaces",
            "Slow motion close-up focus pull with subtle atmospheric haze",
            "Wide establishing cinematic angle, dramatic contrast and depth",
            "Elevated crane shot drifting smoothly over high-tech command center",
            "Low angle hero perspective, sleek reflections and glass textures"
        ]

        stage_descriptors = [
            "establishing visual concept, digital infrastructure",
            "detailed algorithmic process flow, glowing data stream",
            "interactive decision dashboard, analytics visualization",
            "successful execution outcome, secure verified transaction network"
        ]

        scenes = []
        for i in range(scene_count):
            sentence_focus = sentences[i] if i < len(sentences) else sentences[i % len(sentences)]
            distilled_prompt = self.distill_visual_prompt(sentence_focus, max_words=25)
            stage_desc = stage_descriptors[i % len(stage_descriptors)]

            visual_prompt = f"{distilled_prompt}, {stage_desc}, ultra-detailed cinematic composition"
            
            scenes.append(VideoScene(
                scene_id=i + 1,
                visual_prompt=visual_prompt,
                motion_prompt=camera_moves[i % len(camera_moves)],
                narration=sentence_focus[:160],
                duration_seconds=4
            ))

        clean_title = sentences[0][:45] if sentences else topic[:45]
        return VideoScript(
            title=f"{clean_title.strip()}",
            art_style_preset=art_style,
            scenes=scenes
        )
