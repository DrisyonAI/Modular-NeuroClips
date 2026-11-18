"""
FaceFusion Headless Lip-Sync & Avatar Service.
Integrates FaceFusion's headless CLI directly into Modular-NeuroClips without requiring face_enhancer.
Configured with wav2lip_gan, region masking restricted to mouth, and seamless boundary blur.
"""

import os
import sys
import shutil
import asyncio
import subprocess
import logging
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger("facefusion_service")
logger.setLevel(logging.INFO)


class FaceFusionLipSyncService:
    """
    Executes FaceFusion in headless CLI mode for audio-driven lip synchronization.
    Explicitly excludes face_enhancer as requested, focusing on mouth-region masking
    and wav2lip_gan for optimal fidelity without over-smoothing.
    """

    def __init__(
        self,
        facefusion_root: Optional[str] = None,
        python_executable: Optional[str] = None,
        execution_provider: str = "cuda",
    ):
        # Locate FaceFusion root from environment or common installation locations
        env_root = os.getenv("FACEFUSION_PATH")
        if facefusion_root:
            self.facefusion_root = Path(facefusion_root)
        elif env_root:
            self.facefusion_root = Path(env_root)
        else:
            # Look in parent/sibling directory or project tools/facefusion
            candidate = Path(__file__).resolve().parent.parent.parent / "facefusion"
            self.facefusion_root = candidate

        self.python_executable = python_executable or sys.executable
        self.execution_provider = execution_provider

    def is_available(self) -> bool:
        """Checks if FaceFusion entry script exists."""
        entry = self.facefusion_root / "facefusion.py"
        return entry.is_file()

    def build_cli_command(
        self,
        target_video_or_image: Path,
        source_audio: Path,
        output_path: Path,
        source_face: Optional[Path] = None,
        lip_syncer_model: str = "wav2lip_gan",
        face_mask_blur: float = 0.3,
        video_quality: int = 90,
    ) -> list[str]:
        """
        Builds headless FaceFusion command arguments.
        NO face_enhancer is added.
        """
        entry_script = str((self.facefusion_root / "facefusion.py").resolve())

        processors = ["lip_syncer"]
        source_paths = [str(source_audio.resolve())]

        # Optional face-swap before lip-syncing if a source avatar identity portrait is supplied
        if source_face and source_face.exists():
            processors.insert(0, "face_swapper")
            source_paths.append(str(source_face.resolve()))

        cmd = [
            self.python_executable,
            entry_script,
            "run",
            "--headless",
            "--execution-providers", self.execution_provider,
            "--frame-processors", *processors,
            "--source-paths", *source_paths,
            "--target-path", str(target_video_or_image.resolve()),
            "--output-path", str(output_path.resolve()),
            "--lip-syncer-model", lip_syncer_model,
            "--face-mask-types", "region",
            "--face-mask-regions", "mouth",
            "--face-mask-blur", str(face_mask_blur),
            "--output-video-quality", str(video_quality),
        ]
        return cmd

    async def run_lipsync_async(
        self,
        target_video_or_image: Path,
        source_audio: Path,
        output_path: Path,
        source_face: Optional[Path] = None,
        lip_syncer_model: str = "wav2lip_gan",
        face_mask_blur: float = 0.3,
        video_quality: int = 90,
    ) -> Dict[str, Any]:
        """
        Asynchronously runs FaceFusion lip-syncing without blocking the event loop.
        """
        if not self.is_available():
            raise FileNotFoundError(
                f"FaceFusion not found at {self.facefusion_root}. "
                f"Please clone facefusion and set FACEFUSION_PATH in .env"
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = self.build_cli_command(
            target_video_or_image=target_video_or_image,
            source_audio=source_audio,
            output_path=output_path,
            source_face=source_face,
            lip_syncer_model=lip_syncer_model,
            face_mask_blur=face_mask_blur,
            video_quality=video_quality,
        )

        logger.info(f"Starting FaceFusion LipSync: {' '.join(cmd)}")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.facefusion_root),
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode(errors="replace")
            logger.error(f"FaceFusion execution failed (code {process.returncode}): {error_msg}")
            raise RuntimeError(f"FaceFusion CLI failed:\n{error_msg}")

        logger.info(f"FaceFusion completed successfully: {output_path}")
        return {
            "status": "completed",
            "output_path": str(output_path.resolve()),
            "stdout": stdout.decode(errors="replace")[-500:],  # Tail logs
        }

    def run_lipsync_sync(
        self,
        target_video_or_image: Path,
        source_audio: Path,
        output_path: Path,
        source_face: Optional[Path] = None,
        lip_syncer_model: str = "wav2lip_gan",
        face_mask_blur: float = 0.3,
        video_quality: int = 90,
    ) -> Dict[str, Any]:
        """
        Synchronous wrapper suitable for background threads or Celery tasks.
        """
        if not self.is_available():
            raise FileNotFoundError(
                f"FaceFusion not found at {self.facefusion_root}. "
                f"Please clone facefusion and set FACEFUSION_PATH in .env"
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = self.build_cli_command(
            target_video_or_image=target_video_or_image,
            source_audio=source_audio,
            output_path=output_path,
            source_face=source_face,
            lip_syncer_model=lip_syncer_model,
            face_mask_blur=face_mask_blur,
            video_quality=video_quality,
        )

        res = subprocess.run(
            cmd,
            cwd=str(self.facefusion_root),
            capture_output=True,
            text=True,
        )

        if res.returncode != 0:
            raise RuntimeError(f"FaceFusion CLI failed:\n{res.stderr}")

        return {
            "status": "completed",
            "output_path": str(output_path.resolve()),
            "stdout": res.stdout[-500:],
        }
