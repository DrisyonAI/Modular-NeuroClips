"""
Curriculum Batch Video Pipeline Runner for Modular-NeuroClips.
Ingests Excel course maps, queues multi-lesson video synthesis jobs in SQLite,
and orchestrates background FFmpeg / Remotion video generation.
"""
import os
import json
import time
import zipfile
import threading
from pathlib import Path
from typing import Dict, List, Any, Optional
import xml.etree.ElementTree as ET
from pydantic import BaseModel

from src.config import BASE_DIR, OUTPUT_DIR, CURRICULUM_OUTPUT_DIR, EXPORTS_DIR
from src.batch_manager import BatchCourseManager, DB_PATH
from src.agents.slide_batch_processor import SlideBatchProcessor, SlideBatchItem
from src.contracts.persona import PERSONA_CATALOG


class CurriculumBatchRequest(BaseModel):
    excel_path: Optional[str] = None
    course_id: str = "FINTECH_AGENTS_15HR"
    course_title: str = "AI Agents in FinTech: Autonomous Execution, Risk & Compliance"
    module_id: Optional[int] = None  # None = all modules
    persona_id: str = "maya_fintech"
    resolution: str = "16:9_hd"
    speech_rate: float = 1.0


class CurriculumBatchRunner:
    """Orchestrates end-to-end curriculum video production jobs from spreadsheet inputs."""

    def __init__(self, output_base: Optional[Path] = None):
        self.output_base = output_base or CURRICULUM_OUTPUT_DIR
        self.output_base.mkdir(parents=True, exist_ok=True)
        self.active_batch_threads: Dict[str, threading.Thread] = {}

    def parse_excel_lessons(self, excel_path: Path) -> List[Dict[str, Any]]:
        """
        Extracts structured lessons and topic narration scripts from Course Map Excel.
        """
        processor = SlideBatchProcessor()
        items = processor.parse_excel_course_map(excel_path)
        
        # Group items by (module, lesson)
        lessons_map: Dict[str, Dict[str, Any]] = {}
        for item in items:
            key = f"M{item.module_num}_L{item.lesson_num}"
            if key not in lessons_map:
                lessons_map[key] = {
                    "module_num": item.module_num,
                    "lesson_num": item.lesson_num,
                    "lesson_title": item.title,
                    "topic_num": item.topic_num,
                    "narration_parts": [],
                    "slides_count": 0
                }
            lessons_map[key]["narration_parts"].append(item.narration_text)
            lessons_map[key]["slides_count"] += 1

        structured_lessons = []
        for key, val in lessons_map.items():
            full_script = " ".join(val["narration_parts"]).strip()
            structured_lessons.append({
                "lesson_id": key,
                "module_id": f"M{val['module_num']:02d}",
                "module_title": f"Module {val['module_num']}",
                "lesson_title": val["lesson_title"],
                "speaker_script": full_script,
                "visual_prompt": f"Professional presentation graphics showing {val['lesson_title']}, FinTech financial systems, 4k",
                "slides_count": val["slides_count"]
            })
        return structured_lessons

    def enqueue_curriculum(self, req: CurriculumBatchRequest) -> Dict[str, Any]:
        """
        Loads course lessons into the SQLite batch pipeline queue.
        """
        excel_path = Path(req.excel_path) if req.excel_path else (BASE_DIR / "docs" / "Nipuna_AI_Agents_in_FinTech_15_Hour_Course_v4.xlsx")
        fallback = os.getenv("CURRICULUM_FALLBACK_EXCEL")
        if not excel_path.exists() and fallback:
            excel_path = Path(fallback)

        if not excel_path.exists():
            raise FileNotFoundError(f"Course Excel map not found at: {excel_path}")

        manager = BatchCourseManager(
            course_id=req.course_id,
            title=req.course_title,
            instructor_persona=req.persona_id,
            resolution=req.resolution
        )

        all_lessons = self.parse_excel_lessons(excel_path)
        queued_count = 0

        for ls in all_lessons:
            if req.module_id is not None:
                mod_str = f"M{req.module_id:02d}"
                if ls["module_id"] != mod_str:
                    continue

            manager.add_lesson(
                module_id=ls["module_id"],
                module_title=ls["module_title"],
                lesson_id=ls["lesson_id"],
                lesson_title=ls["lesson_title"],
                speaker_script=ls["speaker_script"],
                visual_prompt=ls["visual_prompt"]
            )
            queued_count += 1

        # Launch non-blocking worker thread
        t = threading.Thread(
            target=self._run_batch_worker,
            args=(req.course_id, req.persona_id, req.speech_rate, req.resolution),
            daemon=True
        )
        t.start()
        self.active_batch_threads[req.course_id] = t

        return {
            "status": "queued",
            "course_id": req.course_id,
            "total_lessons_queued": queued_count,
            "source_excel": str(excel_path.name),
            "output_directory": str(self.output_base)
        }

    def _run_batch_worker(self, course_id: str, persona_id: str, speech_rate: float, resolution: str = "16:9_hd"):
        """Worker thread executing voiceover synthesis & video timeline compiling."""
        from src.batch_manager import BatchCourseManager
        from src.agents.voice_director import VoiceDirectorAgent
        from src.contracts.script_contract import ScriptContract, ScriptScene
        from src.pipeline import MediaGenerationEngine
        from src.compiler import compile_final_video

        manager = BatchCourseManager(course_id=course_id, title=course_id)
        pending = manager.get_pending_lessons()

        course_out_dir = self.output_base / course_id
        course_out_dir.mkdir(parents=True, exist_ok=True)
        vd = VoiceDirectorAgent(output_dir=course_out_dir)
        media_engine = MediaGenerationEngine(output_dir=course_out_dir)
        persona = PERSONA_CATALOG.get(persona_id, PERSONA_CATALOG["maya_fintech"])

        for ls in pending:
            lesson_id = ls["lesson_id"]
            script_text = ls["speaker_script"] or ls["lesson_title"]
            
            try:
                manager.update_lesson_status(lesson_id, status="processing")
                
                # Single scene lecture audio synthesis
                scene = ScriptScene(
                    scene_id=1,
                    title=ls["lesson_title"],
                    visual_description=ls["visual_prompt"] or ls["lesson_title"],
                    narration=script_text[:1200],  # Cap per scene to prevent timeout
                    estimated_duration_sec=round(len(script_text.split()) / 2.5, 2)
                )
                contract = ScriptContract(
                    course_title=ls["lesson_title"],
                    persona_id=persona.persona_id,
                    art_style_preset="corporate_fintech",
                    total_word_count=len(script_text.split()),
                    estimated_total_runtime_sec=scene.estimated_duration_sec,
                    scenes=[scene]
                )

                # 1. Synthesize EBU R128 Voiceover
                v_result = vd.synthesize_voice_contract(
                    script=contract,
                    persona=persona,
                    speech_rate=speech_rate,
                    target_lufs=-14.0
                )

                measured_dur = vd.probe_audio_duration(Path(v_result.master_audio_path))

                # 2. Synthesize Visual Keyframe Image
                keyframe_path = course_out_dir / f"kf_{course_id}_{lesson_id}.png"
                media_engine.generate_image(
                    prompt=f"{scene.visual_description}, professional FinTech interface, corporate presentation 4k",
                    output_path=keyframe_path,
                    resolution=resolution
                )

                # 3. Generate Motion Clip matching exact audio duration
                clip_path = course_out_dir / f"clip_{course_id}_{lesson_id}.mp4"
                media_engine.generate_video(
                    image_path=keyframe_path,
                    motion_prompt="Subtle camera push in",
                    output_path=clip_path,
                    duration_sec=max(3, int(measured_dur) + 1),
                    resolution=resolution
                )

                # 4. Compile Final Production Video with burned-in subtitles & synchronized audio
                final_video_name = f"{course_id}_{lesson_id}.mp4"
                final_video_file = OUTPUT_DIR / final_video_name
                compile_final_video(
                    clip_paths=[str(clip_path)],
                    output_filename=final_video_name,
                    audio_path=v_result.master_audio_path,
                    engine="ffmpeg",
                    burn_subtitles=True,
                    srt_path=v_result.subtitles_srt_path
                )

                manager.update_lesson_status(
                    lesson_id,
                    status="completed",
                    video_path=str(final_video_file),
                    audio_path=v_result.master_audio_path,
                    srt_path=v_result.subtitles_srt_path
                )
            except Exception as e:
                manager.update_lesson_status(
                    lesson_id,
                    status="failed",
                    error=str(e)
                )

    def get_course_status(self, course_id: str) -> Dict[str, Any]:
        """Returns live completion stats for a curriculum batch course."""
        import sqlite3
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT status, count(*) as cnt FROM lessons WHERE course_id = ? GROUP BY status", (course_id,))
            counts = {row["status"]: row["cnt"] for row in c.fetchall()}
            
            c.execute("SELECT * FROM lessons WHERE course_id = ? ORDER BY module_id, lesson_id", (course_id,))
            lessons = [dict(row) for row in c.fetchall()]

        total = sum(counts.values())
        completed = counts.get("completed", 0)
        pct = round((completed / total * 100), 1) if total > 0 else 0

        return {
            "course_id": course_id,
            "total_lessons": total,
            "completed": completed,
            "pending": counts.get("pending", 0),
            "processing": counts.get("processing", 0),
            "failed": counts.get("failed", 0),
            "progress_percent": pct,
            "lessons": lessons
        }
