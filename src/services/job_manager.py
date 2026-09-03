"""
Thread-safe job and pipeline state management service.
Coordinates background production jobs, milestone progression, and SSE telemetry streams.
"""
import time
import uuid
import threading
from pathlib import Path
from typing import Dict, List, Any, Optional

MILESTONES = [
    {"id": "init", "name": "Initialization", "description": "Setting up generation pipeline & allocating VRAM"},
    {"id": "scripting", "name": "Llama 3 Scripting", "description": "Generating directorial multi-scene screenplay"},
    {"id": "keyframes", "name": "Keyframe Synthesis", "description": "Generating image keyframes matching prompt"},
    {"id": "animation", "name": "Motion Dynamics", "description": "Rendering camera motion video clips"},
    {"id": "voiceover", "name": "Edge-TTS Voiceover", "description": "Synthesizing neural voice narration audio"},
    {"id": "compilation", "name": "Engine Compilation", "description": "Stitching scenes, subtitles & audio sync"},
    {"id": "complete", "name": "Completed", "description": "Production ready for playback, SRT & SCORM export"},
]


class JobManager:
    """Thread-safe manager for jobs and pipeline status."""

    def __init__(self, max_history: int = 100):
        self._lock = threading.RLock()
        self._max_history = max_history
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self.active_job_id: Optional[str] = None
        self.pipeline_state: Dict[str, Any] = {
            "status": "Idle",
            "current_step": "Ready for jobs",
            "last_error": None,
            "model_load_latency": 0.0,
            "processed_scenes": 0,
            "total_scenes": 0,
            "current_milestone": "init",
            "progress_percent": 0,
        }

    def create_job(
        self,
        topic: str,
        scene_count: int,
        art_style: str,
        resolution: str,
        voice: str,
        engine_type: str = "ffmpeg",
        output_type: str = "video",
    ) -> str:
        """Initializes a new tracked job."""
        with self._lock:
            # Evict oldest completed/failed jobs if limit reached
            if len(self.jobs) >= self._max_history:
                oldest_id = next(iter(self.jobs))
                del self.jobs[oldest_id]

            job_id = str(uuid.uuid4())[:8]
            job = {
                "job_id": job_id,
                "topic": topic,
                "scene_count": scene_count,
                "art_style": art_style,
                "resolution": resolution,
                "voice": voice,
                "engine_type": engine_type,
                "output_type": output_type,
                "status": "in_progress",
                "current_milestone": "init",
                "current_step": "Initializing pipeline",
                "progress_percent": 5,
                "processed_scenes": 0,
                "total_scenes": scene_count,
                "script": None,
                "clip_paths": [],
                "keyframe_paths": [],
                "slide_paths": [],
                "audio_paths": [],
                "srt_path": None,
                "output_path": None,
                "created_at": time.time(),
                "updated_at": time.time(),
                "logs": [
                    f"[{time.strftime('%H:%M:%S')}] Job #{job_id} initiated: '{topic[:40]}...' ({resolution}, {output_type})"
                ],
                "milestones": {m["id"]: "pending" for m in MILESTONES},
            }
            job["milestones"]["init"] = "in_progress"

            self.jobs[job_id] = job
            self.active_job_id = job_id

            self.pipeline_state["status"] = "Generating Script"
            self.pipeline_state["current_step"] = "Job queued and initializing"
            self.pipeline_state["current_milestone"] = "init"
            self.pipeline_state["progress_percent"] = 5
            self.pipeline_state["total_scenes"] = scene_count
            self.pipeline_state["processed_scenes"] = 0
            self.pipeline_state["last_error"] = None
            return job_id

    def log_milestone(
        self,
        job_id: str,
        milestone_id: str,
        step_msg: str,
        progress: int,
        log_text: Optional[str] = None,
    ):
        """Updates milestone progress for a job and pipeline status."""
        with self._lock:
            if job_id not in self.jobs:
                return
            job = self.jobs[job_id]
            job["current_milestone"] = milestone_id
            job["current_step"] = step_msg
            job["progress_percent"] = progress
            job["updated_at"] = time.time()

            found = False
            for m in MILESTONES:
                if m["id"] == milestone_id:
                    job["milestones"][m["id"]] = "in_progress"
                    found = True
                elif not found:
                    job["milestones"][m["id"]] = "completed"
                else:
                    job["milestones"][m["id"]] = "pending"

            if log_text:
                job["logs"].append(f"[{time.strftime('%H:%M:%S')}] {log_text}")

            self.pipeline_state["status"] = f"Milestone: {milestone_id.capitalize()}"
            self.pipeline_state["current_step"] = step_msg
            self.pipeline_state["current_milestone"] = milestone_id
            self.pipeline_state["progress_percent"] = progress

    def complete_job(self, job_id: str, output_path: str):
        """Marks job and pipeline as completed."""
        with self._lock:
            if job_id in self.jobs:
                job = self.jobs[job_id]
                job["status"] = "complete"
                job["output_path"] = output_path
                job["progress_percent"] = 100
                job["milestones"] = {m["id"]: "completed" for m in MILESTONES}
                is_slide = (job.get("output_type") == "slide")
                clean_name = Path(output_path).name if output_path else ("output.png" if is_slide else "output.mp4")
                output_label = "Slide presentation ready" if is_slide else "Video ready"
                self.log_milestone(
                    job_id,
                    "complete",
                    f"{output_label}: {clean_name}",
                    100,
                    f"[SUCCESS] Production finished ({job.get('output_type', 'video')}): {output_path}",
                )

            self.pipeline_state["status"] = "Complete"
            clean_name = Path(output_path).name if output_path else "output"
            self.pipeline_state["current_step"] = f"Saved: {clean_name}"

    def fail_job(self, job_id: str, error_msg: str):
        """Marks job and pipeline as failed."""
        with self._lock:
            if job_id in self.jobs:
                job = self.jobs[job_id]
                job["status"] = "failed"
                job["logs"].append(f"[{time.strftime('%H:%M:%S')}] [ERROR] Pipeline failed: {error_msg}")

            self.pipeline_state["status"] = "Failed"
            self.pipeline_state["last_error"] = str(error_msg)
            self.pipeline_state["current_step"] = f"Error: {str(error_msg)}"

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self.jobs.get(job_id)

    def get_active_job(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            if self.active_job_id:
                return self.jobs.get(self.active_job_id)
            return None

    def reset_pipeline(self):
        with self._lock:
            self.pipeline_state["status"] = "Idle"
            self.pipeline_state["current_step"] = "Ready for jobs"
            self.pipeline_state["last_error"] = None
            self.pipeline_state["progress_percent"] = 0
            self.pipeline_state["processed_scenes"] = 0
            self.active_job_id = None


# Global singleton instance
job_manager = JobManager()
