"""
SCORM 1.2 & SCORM 2004 Packaging Utility for Modular-NeuroClips.
Creates compliant e-learning archives with imsmanifest.xml, single-SCO data-driven SPA player,
interactive knowledge assessments, and LMS tracking conforming to the NeuroClips SCORM Framework.
"""
import os
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape
from typing import List, Optional, Dict, Any, Union
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
    lesson_number: Optional[str] = None
    lesson_name: Optional[str] = None
    topic: Optional[str] = ""
    description: Optional[str] = ""
    video_path: Optional[str] = None
    srt_path: Optional[str] = None
    audio_path: Optional[str] = None
    runtime_seconds: Optional[float] = 0.0
    understanding_check: Optional[List[Dict[str, Any]]] = None


class SCORMModuleModel(BaseModel):
    module_id: str
    module_title: str
    module_number: Optional[Union[int, str]] = None
    module_name: Optional[str] = None
    description: Optional[str] = ""
    lessons: List[SCORMLessonModel] = Field(default_factory=list)


class SCORMPackageRequest(BaseModel):
    course_id: str
    course_title: str
    course_description: Optional[str] = ""
    version: str = "1.2"
    intro_video_path: Optional[str] = None
    modules: List[SCORMModuleModel] = Field(default_factory=list)


class SCORMPackager:
    """
    Modern SCORM 1.2 & 2004 Course Packager.
    Converts course metadata, modules, lessons, and media into a self-contained single-SCO package.
    """
    def __init__(
        self,
        course_id: str,
        course_title: str,
        course_description: str = "",
        version: str = "1.2",
        default_quiz_module_id: int = 1,
        intro_video_path: Optional[str] = None
    ):
        self.course_id = course_id
        self.course_title = course_title
        self.course_description = course_description
        self.version = version
        self.default_quiz_module_id = default_quiz_module_id
        self.intro_video_path = intro_video_path
        self.modules: List[Dict[str, Any]] = []

    def add_module(
        self,
        module_id: str,
        module_title: str,
        description: str = "",
        module_number: Optional[Union[int, str]] = None,
        module_name: Optional[str] = None
    ):
        mod_name = module_name or module_title
        self.modules.append({
            "module_id": module_id,
            "module_title": module_title,
            "module_name": mod_name,
            "module_number": module_number,
            "number": module_number,
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
        lesson_number: Optional[str] = None,
        lesson_name: Optional[str] = None,
        video_path: Optional[str] = None,
        srt_path: Optional[str] = None,
        audio_path: Optional[str] = None,
        runtime_seconds: float = 0.0,
        understanding_check: Optional[List[Dict[str, Any]]] = None
    ):
        target_mod = next((m for m in self.modules if m["module_id"] == module_id), None)
        if not target_mod:
            self.add_module(module_id, module_id.replace("_", " ").title(), module_number=1)
            target_mod = self.modules[-1]

        target_mod["lessons"].append({
            "lesson_id": lesson_id,
            "lesson_title": lesson_title,
            "lesson_name": lesson_name or lesson_title,
            "lesson_number": lesson_number,
            "number": lesson_number,
            "topic": topic,
            "description": description,
            "video_path": video_path,
            "srt_path": srt_path,
            "audio_path": audio_path,
            "runtime_seconds": runtime_seconds,
            "understanding_check": understanding_check
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

        # Resolve intro background video
        intro_vid = self.intro_video_path
        if not intro_vid or not Path(intro_vid).exists():
            # Check default reference location
            candidates = [
                Path("scrom_reference") / "AI-FinTech-v0.mp4",
                Path(__file__).parent / "scorm" / "runtime" / "assets" / "videos" / "AI-FinTech-v0.mp4"
            ]
            for cand in candidates:
                if cand.exists():
                    intro_vid = cand
                    break

        intro_target_rel = None
        if intro_vid and Path(intro_vid).exists():
            p_intro = Path(intro_vid)
            intro_target_rel = f"assets/videos/{p_intro.name}"
            asset_files_map[intro_target_rel] = p_intro

        # Convert to canonical course document
        course_doc = build_canonical_course_document(
            course_id=self.course_id,
            course_title=self.course_title,
            course_description=self.course_description,
            modules_data=self.modules,
            default_quiz_module_id=self.default_quiz_module_id,
            pass_percentage=70,
            intro_video_path=intro_target_rel
        )

        # Build complete package using the modern SCORM runtime builder
        builder = SCORMPackageBuilder(
            course_data=course_doc,
            scorm_version=self.version,
            asset_files_map=asset_files_map
        )

        return builder.build_zip(out_path)

    def export_scenario_zip(self, scenario_dag: Any, output_zip_path: Optional[Path] = None, pass_percentage: int = 70) -> Path:
        """
        Exports an interactive NeuroBranch™ adaptive scenario simulation package (SCORM 1.2 / 2004 compatible).
        """
        out_path = output_zip_path or EXPORTS_DIR / f"SCORM_SIM_{scenario_dag.scenario_id}.zip"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        sid = _xml_escape(str(scenario_dag.scenario_id), {'"': "&quot;"})
        title = _xml_escape(str(scenario_dag.title))
        manifest_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="sim_{sid}" version="1.0"
          xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2"
          xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2">
  <organizations default="org_{sid}">
    <organization identifier="org_{sid}">
      <title>{title}</title>
      <item identifier="item_{sid}" identifierref="sim_resource">
        <title>{title}</title>
      </item>
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
