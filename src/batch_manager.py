import os
import time
import json
import sqlite3
import zipfile
import threading
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict

from src.config import BASE_DIR, OUTPUT_DIR, CURRICULUM_OUTPUT_DIR, EXPORTS_DIR
from src.orchestrator import ScriptOrchestrator, VideoScript, VideoScene
from src.pipeline import MediaGenerationEngine, VRAMGuard
from src.compiler import compile_final_video, generate_srt_subtitles

COURSES_DIR = BASE_DIR / "courses"
COURSES_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = BASE_DIR / "batch_production.db"

def init_batch_database():
    """Initializes SQLite persistent schema for multi-course, 100+ hour batch pipelines."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS courses (
            course_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            instructor_persona TEXT,
            voice TEXT,
            language TEXT,
            resolution TEXT,
            total_modules INTEGER DEFAULT 0,
            total_lessons INTEGER DEFAULT 0,
            status TEXT DEFAULT 'queued',
            created_at REAL,
            updated_at REAL
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS lessons (
            lesson_id TEXT PRIMARY KEY,
            course_id TEXT NOT NULL,
            module_id TEXT NOT NULL,
            module_title TEXT,
            lesson_title TEXT,
            speaker_script TEXT,
            visual_prompt TEXT,
            art_style TEXT,
            duration_seconds REAL DEFAULT 0,
            status TEXT DEFAULT 'pending',
            video_path TEXT,
            audio_path TEXT,
            srt_path TEXT,
            scorm_path TEXT,
            retry_count INTEGER DEFAULT 0,
            last_error TEXT,
            created_at REAL,
            updated_at REAL,
            FOREIGN KEY (course_id) REFERENCES courses(course_id)
        )
        """)
        conn.commit()

init_batch_database()

@dataclass
class LessonTask:
    lesson_id: str
    course_id: str
    module_id: str
    module_title: str
    lesson_title: str
    speaker_script: str
    visual_prompt: str
    art_style: str = "Cinematic 35mm"
    status: str = "pending"
    duration_seconds: float = 0
    video_path: Optional[str] = None
    audio_path: Optional[str] = None
    srt_path: Optional[str] = None
    scorm_path: Optional[str] = None

class BatchCourseManager:
    """Manages courseware hierarchy, checkpoint-resume, and mass asset production."""
    
    def __init__(self, course_id: str, title: str, instructor_persona: str = "maya_fintech", voice: str = "en-IN-NeerjaNeural", language: str = "en-US", resolution: str = "16:9_hd"):
        self.course_id = course_id
        self.title = title
        self.instructor_persona = instructor_persona
        self.voice = voice
        self.language = language
        self.resolution = resolution
        self.course_dir = COURSES_DIR / course_id
        self.course_dir.mkdir(parents=True, exist_ok=True)
        self._register_course()

    def _register_course(self):
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT OR REPLACE INTO courses (course_id, title, instructor_persona, voice, language, resolution, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (self.course_id, self.title, self.instructor_persona, self.voice, self.language, self.resolution, time.time(), time.time()))
            conn.commit()

    def add_lesson(self, module_id: str, module_title: str, lesson_id: str, lesson_title: str, speaker_script: str, visual_prompt: str, art_style: str = "Photorealistic 8K"):
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT OR IGNORE INTO lessons (lesson_id, course_id, module_id, module_title, lesson_title, speaker_script, visual_prompt, art_style, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (lesson_id, self.course_id, module_id, module_title, lesson_title, speaker_script, visual_prompt, art_style, time.time(), time.time()))
            conn.commit()

    def get_pending_lessons(self) -> List[Dict[str, Any]]:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM lessons WHERE course_id = ? AND status IN ('pending', 'failed') ORDER BY module_id, lesson_id", (self.course_id,))
            return [dict(row) for row in cursor.fetchall()]

    def update_lesson_status(self, lesson_id: str, status: str, video_path: str = None, audio_path: str = None, srt_path: str = None, scorm_path: str = None, error: str = None):
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE lessons 
            SET status = ?, video_path = ?, audio_path = ?, srt_path = ?, scorm_path = ?, last_error = ?, updated_at = ?
            WHERE lesson_id = ?
            """, (status, video_path, audio_path, srt_path, scorm_path, error, time.time(), lesson_id))
            conn.commit()

    def export_master_scORM_package(self) -> str:
        """Packages all completed modules & lessons into a master Multi-SCO SCORM 2004 / 1.2 course package."""
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM lessons WHERE course_id = ? AND status = 'completed' ORDER BY module_id, lesson_id", (self.course_id,))
            lessons = [dict(row) for row in cursor.fetchall()]

        if not lessons:
            raise ValueError("No completed lessons to package.")

        master_zip = EXPORTS_DIR / f"MASTER_COURSE_{self.course_id}.zip"
        
        # Build Multi-Item IMS Manifest
        items_xml = []
        resources_xml = []
        
        for idx, ls in enumerate(lessons, start=1):
            vid_filename = Path(ls["video_path"]).name if ls["video_path"] else f"lesson_{idx}.mp4"
            items_xml.append(f"""
        <item identifier="item_{ls['lesson_id']}" identifierref="res_{ls['lesson_id']}">
          <title>{ls['module_title']} - {ls['lesson_title']}</title>
        </item>""")
            resources_xml.append(f"""
    <resource identifier="res_{ls['lesson_id']}" type="webcontent" adlcp:scormtype="sco" href="{vid_filename}">
      <file href="{vid_filename}"/>
    </resource>""")

        manifest_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="Course_{self.course_id}" version="1.0" xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2" xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p1p2">
  <organizations default="org_{self.course_id}">
    <organization identifier="org_{self.course_id}">
      <title>{self.title}</title>
      {"".join(items_xml)}
    </organization>
  </organizations>
  <resources>
    {"".join(resources_xml)}
  </resources>
</manifest>
"""
        with zipfile.ZipFile(master_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("imsmanifest.xml", manifest_xml)
            for ls in lessons:
                if ls["video_path"] and Path(ls["video_path"]).exists():
                    zf.write(ls["video_path"], arcname=Path(ls["video_path"]).name)
                    
        return str(master_zip)
