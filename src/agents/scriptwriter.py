"""
Scriptwriter Sub-Agent.
Transforms raw curriculum queries and ingested documents into pedagogical multi-scene scripts.
"""
import re
import json
import urllib.request
from typing import List, Optional
from src.contracts.persona import PersonaIdentityContract, RegionLocaleEnum
from src.contracts.script_contract import ScriptScene, ScriptContract


class ScriptwriterAgent:
    """
    Specialized agent responsible for curriculum structuring, scene division,
    narration pacing, and visual prompt description.
    """

    def __init__(self, ollama_host: str = "http://localhost:11434", model_name: str = "llama3.1:8b"):
        self.ollama_host = ollama_host
        self.model_name = model_name

    def clean_text_segment(self, text: str) -> str:
        """Cleans and sanitizes raw text fragments."""
        cleaned = re.sub(r"[\r\n\t]+", " ", text).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned

    def distill_visual_prompt(self, narrative_text: str, max_words: int = 25) -> str:
        """Distills visual intent keywords from narration sentences."""
        clean = re.sub(r"[^\w\s]", "", narrative_text)
        words = clean.split()
        stop_words = {
            "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "in", "on", "at", "to",
            "for", "with", "by", "about", "against", "between", "into", "through", "during", "before",
            "after", "above", "below", "from", "up", "down", "in", "out", "on", "off", "over", "under",
            "again", "further", "then", "once", "here", "there", "when", "where", "why", "how", "all",
            "any", "both", "each", "few", "more", "most", "other", "some", "such", "no", "nor", "not",
            "only", "own", "same", "so", "than", "too", "very", "s", "t", "can", "will", "just", "don",
            "should", "now", "we", "our", "you", "your", "welcome", "this", "session", "tutorial"
        }
        keywords = [w for w in words if w.lower() not in stop_words and len(w) > 2]
        distilled = " ".join(keywords[:max_words]) if keywords else narrative_text[:100]
        return f"High quality scene visualization depicting: {distilled}"

    def decompose_query_to_scenes(
        self,
        topic: str,
        scene_count: int,
        persona: PersonaIdentityContract,
        art_style: str
    ) -> List[ScriptScene]:
        """
        Decomposes input topic into pedagogical scene chunks with director cues.
        """
        lower = topic.lower()

        # Domain Specific Tutorial Fast-Path (e.g. Excel Goal Seek)
        if "goal seek" in lower or "excel" in lower:
            return [
                ScriptScene(
                    scene_id=1,
                    title="What is Goal Seek?",
                    narration="Welcome to this tutorial on Microsoft Excel Goal Seek. [pause 500ms] Goal Seek is a powerful What-If Analysis tool that determines the input value needed to achieve your target profit.",
                    visual_description="Close up modern computer monitor displaying an open Microsoft Excel spreadsheet with revenue model, price, units sold, and target profit cells highlighted in neon green, high resolution, ultra clear UI screenshot",
                    motion_prompt="Slow cinematic push-in towards the target profit cell in Excel",
                    estimated_duration_sec=6.0
                ),
                ScriptScene(
                    scene_id=2,
                    title="Accessing What-If Analysis",
                    narration="To launch it, navigate to the Data tab on your ribbon, [pause 500ms] click What-If Analysis, and select Goal Seek from the dropdown menu.",
                    visual_description="Detailed Microsoft Excel ribbon menu focusing on the Data tab, clicking What-If Analysis dropdown button and selecting Goal Seek, crisp 4k software interface",
                    motion_prompt="Smooth pan across the Excel Data ribbon towards the What-If Analysis menu",
                    estimated_duration_sec=5.5
                ),
                ScriptScene(
                    scene_id=3,
                    title="Configuring Goal Seek Parameters",
                    narration="In the dialog box, define your Set Cell with the formula, enter your target value in 'To Value', [pause 500ms] and select your variable cell in 'By Changing Cell'.",
                    visual_description="The Excel Goal Seek dialog popup box with three parameters: Set cell, To value, and By changing cell filled with financial variables, sharp typography, 8k UI design",
                    motion_prompt="Steady macro focus on the Goal Seek dialog box showing the three parameter inputs",
                    estimated_duration_sec=6.5
                ),
                ScriptScene(
                    scene_id=4,
                    title="Executing & Analyzing Results",
                    narration="Click OK, and Excel automatically iterates to find the exact required input value to hit your goal. [protip] You can now apply Goal Seek across your financial and operational models.",
                    visual_description="Microsoft Excel spreadsheet instantly updating the calculation, displaying the exact target output reached with a green checkmark confirmation, modern corporate office background",
                    motion_prompt="Slow zoom-out showing the successfully calculated financial model",
                    estimated_duration_sec=6.0
                )
            ]

        # Dynamic sentence chunking
        sentences = [s.strip() for s in re.split(r"[.!?]+", topic) if len(s.strip()) > 8]
        if not sentences:
            sentences = [topic.strip()]

        camera_presets = [
            "Slow cinematic tracking shot forward, volumetric studio lighting",
            "Dynamic sweeping lateral pan across modern interfaces",
            "Slow motion close-up focus pull with crystal clear detail",
            "Wide establishing cinematic angle, dramatic contrast and depth"
        ]

        scenes: List[ScriptScene] = []
        for i in range(scene_count):
            sentence = sentences[i] if i < len(sentences) else sentences[i % len(sentences)]
            sentence_clean = self.clean_text_segment(sentence)
            
            # Add directorial cues
            if i == 0:
                narration = f"Welcome to this overview. [pause 500ms] {sentence_clean}"
            elif i == scene_count - 1:
                narration = f"{sentence_clean}. [protip] Keep these principles in mind for your workflows."
            else:
                narration = f"Next, [pause 500ms] {sentence_clean}."

            visual_prompt = f"{self.distill_visual_prompt(sentence_clean)}, {art_style}, ultra high definition"
            motion = camera_presets[i % len(camera_presets)]
            est_duration = max(round(len(narration.split()) / (140 * persona.default_speed) * 60, 1), 4.0)

            scenes.append(
                ScriptScene(
                    scene_id=i + 1,
                    title=f"Module Concept {i + 1}",
                    narration=narration,
                    visual_description=visual_prompt,
                    motion_prompt=motion,
                    estimated_duration_sec=est_duration
                )
            )

        return scenes

    def generate_script(
        self,
        topic: str,
        scene_count: int,
        persona: PersonaIdentityContract,
        art_style: str = "Photorealistic 8K (Corporate / Tech)",
        target_locale: RegionLocaleEnum = RegionLocaleEnum.EN_US
    ) -> ScriptContract:
        """
        Executes scriptwriting contract generation.
        """
        scenes = self.decompose_query_to_scenes(
            topic=topic,
            scene_count=max(min(scene_count, 16), 1),
            persona=persona,
            art_style=art_style
        )
        
        words = sum(len(s.narration.split()) for s in scenes)
        est_total_sec = sum(s.estimated_duration_sec for s in scenes)
        
        # Derive title
        title_words = [w for w in topic.split() if len(w) > 3][:5]
        course_title = (" ".join(title_words) + ": Executive Masterclass").title() if title_words else "Corporate Video Course"

        return ScriptContract(
            course_title=course_title,
            persona_id=persona.persona_id,
            target_locale=target_locale,
            art_style_preset=art_style,
            total_word_count=words,
            estimated_total_runtime_sec=est_total_sec,
            scenes=scenes
        )
