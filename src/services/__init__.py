"""
Modular services package for background jobs, audio processing, telemetry, and pipeline execution.
"""
from src.services.telemetry import get_system_telemetry, GPU_AVAILABLE
from src.services.audio_service import (
    generate_voiceover_audio_sync,
    convert_audio_format,
    translate_narration_text,
    resolve_video_path,
)
from src.services.job_manager import JobManager, MILESTONES
from src.services.alert_dispatcher import (
    dispatch_security_alert,
    dispatch_threat_detection,
    dispatch_pipeline_failure,
)

__all__ = [
    "get_system_telemetry",
    "GPU_AVAILABLE",
    "generate_voiceover_audio_sync",
    "convert_audio_format",
    "translate_narration_text",
    "resolve_video_path",
    "JobManager",
    "MILESTONES",
    "dispatch_security_alert",
    "dispatch_threat_detection",
    "dispatch_pipeline_failure",
]
