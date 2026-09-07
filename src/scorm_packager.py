"""
SCORM 1.2 & SCORM 2004 Packaging Utility for Modular-NeuroClips.
Creates compliant e-learning archives with imsmanifest.xml, single-SCO data-driven SPA player,
interactive knowledge assessments, and LMS tracking conforming to the NeuroClips SCORM Framework.
"""
import os
from pathlib import Path
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

try:
    from src.config import EXPORTS_DIR, OUTPUT_DIR
    from src.scorm.converter import build_canonical_course_document
    from src.scorm.packager import SCORMPackageBuilder
except ImportError:
    from config import EXPORTS_DIR, OUTPUT_DIR
    from scorm.converter import build_canonical_course_document
    from scorm.packager import SCORMPackageBuilder


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
    """
    Modern SCORM 1.2 & 2004 Course Packager.
    Converts course metadata, modules, lessons, and media into a self-contained single-SCO package.
    """
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

    def add_lesson(
        self,
        module_id: str,
        lesson_id: str,
        lesson_title: str,
        topic: str = "",
        description: str = "",
        video_path: Optional[str] = None,
        srt_path: Optional[str] = None,
        audio_path: Optional[str] = None,
        runtime_seconds: float = 0.0
    ):
        target_mod = next((m for m in self.modules if m["module_id"] == module_id), None)
        if not target_mod:
            self.add_module(module_id, module_id.replace("_", " ").title())
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
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Build asset files map for any attached video, srt, audio files
        asset_files_map: Dict[str, Path] = {}
        for mod in self.modules:
            for les in mod["lessons"]:
                v_path = les.get("video_path")
                if v_path:
                    p = Path(v_path)
                    if p.exists():
                        target_key = f"assets/videos/{p.name}"
                        asset_files_map[target_key] = p
                s_path = les.get("srt_path")
                if s_path:
                    p = Path(s_path)
                    if p.exists():
                        target_key = f"assets/captions/{p.name}"
                        asset_files_map[target_key] = p

        # Convert to canonical course document
        course_doc = build_canonical_course_document(
            course_id=self.course_id,
            course_title=self.course_title,
            course_description=self.course_description,
            modules_data=self.modules,
            pass_percentage=70
        )

        # Build complete package using the modern SCORM runtime builder
        builder = SCORMPackageBuilder(
            course_data=course_doc,
            scorm_version=self.version,
            asset_files_map=asset_files_map
        )

        return builder.build_zip(out_path)
