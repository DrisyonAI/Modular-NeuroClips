from typing import List
from pydantic import BaseModel, Field
from langchain_community.chat_models import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from src.config import OLLAMA_BASE_URL, OLLAMA_MODEL

class VideoScene(BaseModel):
    scene_id: int = Field(description="Sequential index starting from 1")
    visual_prompt: str = Field(description="Detailed text-to-image prompt with style and character consistency.")
    motion_prompt: str = Field(description="Action and camera movement prompt for video generation.")
    duration_seconds: int = Field(default=4, description="Target duration of the scene in seconds.")

class VideoScript(BaseModel):
    title: str = Field(description="Title of the video production")
    art_style_preset: str = Field(description="Consistent style anchor (e.g., 'Cinematic 35mm, volumetric lighting')")
    scenes: List[VideoScene] = Field(description="Ordered list of visual scenes")

class ScriptOrchestrator:
    def __init__(self, model_name: str = OLLAMA_MODEL, base_url: str = OLLAMA_BASE_URL):
        self.llm = ChatOllama(model=model_name, base_url=base_url, temperature=0.7)
        self.parser = JsonOutputParser(pydantic_object=VideoScript)
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an expert film director and AI video prompter. "
                       "Break down video concepts into highly coherent, sequential visual scenes. "
                       "Ensure character descriptions, lighting styles, and color palettes stay identical across scenes.\n"
                       "{format_instructions}"),
            ("user", "Create a video script for the following topic: {topic}. Target duration: {scene_count} scenes.")
        ])

    def generate_script(self, topic: str, scene_count: int = 3) -> VideoScript:
        chain = self.prompt | self.llm | self.parser
        raw_output = chain.invoke({
            "topic": topic,
            "scene_count": scene_count,
            "format_instructions": self.parser.get_format_instructions()
        })
        return VideoScript(**raw_output)