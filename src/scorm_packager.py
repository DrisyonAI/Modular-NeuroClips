"""
SCORM 1.2 & SCORM 2004 Packaging Utility for Modular-NeuroClips.
Creates compliant e-learning archives with imsmanifest.xml and HTML5 interactive players.
"""
import os
import zipfile
from pathlib import Path
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from src.config import EXPORTS_DIR, OUTPUT_DIR
from src.quiz_engine import QuizEngine


class SCORMLessonModel(BaseModel):
    lesson_id: str
    lesson_title: str
    topic: Optional[str] = ""
    description: Optional[str] = ""
    video_path: Optional[str] = None
    srt_path: Optional[str] = None
    audio_path: Optional[str] = None
    runtime_seconds: Optional[float] = 0.0


class SCORMModuleModel(BaseModel):
    module_id: str
    module_title: str
    description: Optional[str] = ""
    lessons: List[SCORMLessonModel] = Field(default_factory=list)


class SCORMPackageRequest(BaseModel):
    course_id: str
    course_title: str
    course_description: Optional[str] = ""
    version: str = "1.2"
    modules: List[SCORMModuleModel] = Field(default_factory=list)


class SCORMPackager:
    def __init__(self, course_id: str, course_title: str, course_description: str = "", version: str = "1.2"):
        self.course_id = course_id
        self.course_title = course_title
        self.course_description = course_description
        self.version = version
        self.modules: List[Dict[str, Any]] = []

    def add_module(self, module_id: str, module_title: str, description: str = ""):
        self.modules.append({
            "module_id": module_id,
            "module_title": module_title,
            "description": description,
            "lessons": []
        })

    def add_lesson(self, module_id: str, lesson_id: str, lesson_title: str, topic: str = "", description: str = "", video_path: Optional[str] = None, srt_path: Optional[str] = None, audio_path: Optional[str] = None, runtime_seconds: float = 0.0):
        target_mod = next((m for m in self.modules if m["module_id"] == module_id), None)
        if not target_mod:
            self.add_module(module_id, module_id.title())
            target_mod = self.modules[-1]
            
        target_mod["lessons"].append({
            "lesson_id": lesson_id,
            "lesson_title": lesson_title,
            "topic": topic,
            "description": description,
            "video_path": video_path,
            "srt_path": srt_path,
            "audio_path": audio_path,
            "runtime_seconds": runtime_seconds
        })

    def export_zip(self, output_zip_path: Optional[Path] = None) -> Path:
        out_path = output_zip_path or EXPORTS_DIR / f"SCORM_{self.course_id}.zip"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        
        manifest_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="{self.course_id}" version="1.0" xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2">
  <organizations default="org_{self.course_id}">
    <organization identifier="org_{self.course_id}">
      <title>{self.course_title}</title>
    </organization>
  </organizations>
  <resources>
    <resource identifier="resource1" type="webcontent" adlcp:scormtype="sco" href="index.html">
      <file href="index.html"/>
    </resource>
  </resources>
</manifest>
"""
        quiz_engine = QuizEngine()
        player_html = quiz_engine.generate_interactive_scorm_html(
            video_filename="lesson_video.mp4",
            module_id=1,
            pass_percentage=70
        )
        
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("imsmanifest.xml", manifest_xml)
            zf.writestr("index.html", player_html)
            
        return out_path

    def export_scenario_zip(self, scenario_dag: Any, output_zip_path: Optional[Path] = None, pass_percentage: int = 70) -> Path:
        """
        Exports an interactive NeuroBranch™ adaptive scenario simulation package (SCORM 1.2 / 2004 compatible).
        """
        out_path = output_zip_path or EXPORTS_DIR / f"SCORM_SIM_{scenario_dag.scenario_id}.zip"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        manifest_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="sim_{scenario_dag.scenario_id}" version="1.0" xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2">
  <organizations default="org_{scenario_dag.scenario_id}">
    <organization identifier="org_{scenario_dag.scenario_id}">
      <title>{scenario_dag.title}</title>
    </organization>
  </organizations>
  <resources>
    <resource identifier="sim_resource" type="webcontent" adlcp:scormtype="sco" href="index.html">
      <file href="index.html"/>
    </resource>
  </resources>
</manifest>
"""
        from src.neurobranch_player import generate_neurobranch_player_html
        player_html = generate_neurobranch_player_html(scenario_dag, pass_percentage=pass_percentage)

        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("imsmanifest.xml", manifest_xml)
            zf.writestr("index.html", player_html)

        return out_path

