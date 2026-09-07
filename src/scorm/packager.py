"""
NeuroClips SCORM 1.2 & SCORM 2004 Packager.
Assembles compliant, self-contained single-SCO e-learning packages.
"""
import os
import json
import shutil
import zipfile
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Optional, Union

from .validator import validate_course_document
from .manifest import generate_scorm_manifest
try:
    from src.config import EXPORTS_DIR
except ImportError:
    from config import EXPORTS_DIR

RUNTIME_SRC_DIR = Path(__file__).parent / "runtime"


class SCORMPackageBuilder:
    def __init__(
        self,
        course_data: Dict[str, Any],
        scorm_version: str = "1.2",
        asset_files_map: Optional[Dict[str, Path]] = None
    ):
        """
        :param course_data: Canonical course document conforming to schemaVersion 1.0
        :param scorm_version: "1.2" or "2004"
        :param asset_files_map: Mapping of relative package destination (e.g. "assets/videos/clip.mp4")
                                to local source Path on disk.
        """
        self.course_data = course_data
        self.scorm_version = scorm_version
        self.asset_files_map = asset_files_map or {}

    def validate(self) -> Dict[str, Any]:
        return validate_course_document(self.course_data)

    def build_zip(self, output_zip_path: Path) -> Path:
        """
        Builds the SCORM package ZIP archive with imsmanifest.xml at the root.
        """
        output_zip_path = Path(output_zip_path)
        output_zip_path.parent.mkdir(parents=True, exist_ok=True)

        validation = self.validate()
        if not validation["valid"]:
            raise ValueError(f"SCORM Course validation failed: {'; '.join(validation['errors'])}")

        c_info = self.course_data["course"]
        course_id = c_info.get("id", "course-001")
        course_title = c_info.get("title", "Course")
        course_ver = c_info.get("version", "1.0.0")

        with tempfile.TemporaryDirectory() as staging_tmp:
            staging_dir = Path(staging_tmp)

            # 1. Copy runtime files (index.html, css/, js/)
            if not RUNTIME_SRC_DIR.exists():
                raise FileNotFoundError(f"SCORM runtime template directory not found at {RUNTIME_SRC_DIR}")

            shutil.copytree(RUNTIME_SRC_DIR, staging_dir, dirs_exist_ok=True)

            # 2. Write data/course.json
            data_dir = staging_dir / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            with open(data_dir / "course.json", "w", encoding="utf-8") as f:
                json.dump(self.course_data, f, indent=2)

            # 3. Copy attached assets
            manifest_asset_paths: List[str] = []
            for target_rel_path, src_path in self.asset_files_map.items():
                if src_path and Path(src_path).exists():
                    dest = staging_dir / target_rel_path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_path, dest)
                    manifest_asset_paths.append(target_rel_path.replace("\\", "/"))

            # 4. Generate imsmanifest.xml
            manifest_xml = generate_scorm_manifest(
                course_id=course_id,
                course_title=course_title,
                asset_files=manifest_asset_paths,
                scorm_version=self.scorm_version,
                course_version=course_ver
            )
            with open(staging_dir / "imsmanifest.xml", "w", encoding="utf-8") as f:
                f.write(manifest_xml)

            # 5. Create ZIP Archive with root-level manifest
            with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(staging_dir):
                    for file in files:
                        full_path = Path(root) / file
                        rel_path = full_path.relative_to(staging_dir)
                        # Store videos uncompressed to speed up packing
                        compress = zipfile.ZIP_STORED if file.lower().endswith(('.mp4', '.mov', '.webm')) else zipfile.ZIP_DEFLATED
                        zf.write(full_path, arcname=str(rel_path).replace("\\", "/"), compress_type=compress)

        return output_zip_path
