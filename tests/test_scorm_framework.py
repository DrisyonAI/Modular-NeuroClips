"""
Comprehensive unit & integration tests for the NeuroClips SCORM Framework.
Validates course schema validation, manifest generation, runtime file packaging,
and LMS compatibility contracts.
"""
import os
import json
import zipfile
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
import pytest

# Ensure src in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from src.scorm.validator import validate_course_document
from src.scorm.manifest import generate_scorm_manifest
from src.scorm.packager import SCORMPackageBuilder
from src.scorm.converter import build_canonical_course_document
from src.scorm_packager import SCORMPackager


def test_validator_valid_course():
    """Valid course document passes validation without errors."""
    course_path = PROJECT_ROOT / "examples" / "course.json"
    with open(course_path, "r", encoding="utf-8") as f:
        doc = json.load(f)

    report = validate_course_document(doc)
    assert report["valid"] is True
    assert len(report["errors"]) == 0
    assert len(report["files"]) > 0


def test_validator_detects_duplicate_ids():
    """Validator rejects duplicate IDs across modules, lessons, and questions."""
    bad_doc = {
        "schemaVersion": "1.0",
        "course": {
            "id": "course-dup",
            "title": "Dup Test",
            "modules": [
                {
                    "id": "mod-1",
                    "title": "Mod 1",
                    "lessons": [
                        {"id": "lesson-x", "title": "L1"},
                        {"id": "lesson-x", "title": "L2"}  # Duplicate
                    ]
                }
            ]
        }
    }
    report = validate_course_document(bad_doc)
    assert report["valid"] is False
    assert any("Duplicate lesson id: 'lesson-x'" in err for err in report["errors"])


def test_validator_detects_unsafe_asset_paths():
    """Validator rejects paths with directory traversal or absolute paths."""
    bad_doc = {
        "schemaVersion": "1.0",
        "course": {
            "id": "course-safe",
            "title": "Safety Test",
            "modules": [
                {
                    "id": "mod-1",
                    "title": "Mod 1",
                    "lessons": [
                        {
                            "id": "lesson-1",
                            "title": "L1",
                            "video": {"src": "../../../etc/shadow"}
                        }
                    ]
                }
            ]
        }
    }
    report = validate_course_document(bad_doc)
    assert report["valid"] is False
    assert any("Unsafe asset path" in err for err in report["errors"])


def test_manifest_generation_scorm12():
    """Generates valid SCORM 1.2 manifest XML with proper namespaces."""
    xml_str = generate_scorm_manifest(
        course_id="CRS_101",
        course_title="AI in <FinTech> & 'Banking'",
        asset_files=["assets/videos/clip.mp4", "assets/images/poster.jpg"],
        scorm_version="1.2"
    )
    root = ET.fromstring(xml_str)
    assert root.tag.endswith("manifest")
    assert "1.2" in xml_str
    assert "assets/videos/clip.mp4" in xml_str
    assert "SCO-COURSE" in xml_str


def test_manifest_generation_scorm2004():
    """Generates valid SCORM 2004 4th Edition manifest XML."""
    xml_str = generate_scorm_manifest(
        course_id="CRS_2004",
        course_title="Autonomous Agents",
        asset_files=[],
        scorm_version="2004"
    )
    root = ET.fromstring(xml_str)
    assert root.tag.endswith("manifest")
    assert "2004" in xml_str
    assert "adlseq" in xml_str


def test_package_builder_creates_valid_archive():
    """SCORMPackageBuilder bundles runtime, course.json, and manifest at root."""
    course_path = PROJECT_ROOT / "examples" / "course.json"
    with open(course_path, "r", encoding="utf-8") as f:
        doc = json.load(f)

    with tempfile.TemporaryDirectory() as td:
        out_zip = Path(td) / "test_package.zip"
        builder = SCORMPackageBuilder(course_data=doc, scorm_version="1.2")
        result_path = builder.build_zip(out_zip)
        assert result_path.exists()

        with zipfile.ZipFile(result_path, "r") as zf:
            files = zf.namelist()
            # Root-level requirements
            assert "imsmanifest.xml" in files
            assert "index.html" in files
            assert "css/app.css" in files
            assert "js/scorm.js" in files
            assert "js/store.js" in files
            assert "js/components.js" in files
            assert "js/quiz.js" in files
            assert "js/player.js" in files
            assert "data/course.json" in files

            # Verify course.json content inside zip
            raw_course = zf.read("data/course.json").decode("utf-8")
            loaded_course = json.loads(raw_course)
            assert loaded_course["course"]["id"] == doc["course"]["id"]


def test_scorm_packager_backwards_compatibility():
    """Legacy SCORMPackager methods seamlessly construct new modular SCORM packages."""
    packager = SCORMPackager(
        course_id="COMPAT_COURSE_01",
        course_title="Compatibility Test Course",
        course_description="Testing legacy methods with new engine",
        version="1.2"
    )
    packager.add_module("m1", "Module 1: Foundations")
    packager.add_lesson(
        module_id="m1",
        lesson_id="l101",
        lesson_title="Lesson 1: Intro",
        topic="Introduction to Agents"
    )

    with tempfile.TemporaryDirectory() as td:
        out_zip = Path(td) / "compat_out.zip"
        res = packager.export_zip(out_zip)
        assert res.exists()

        with zipfile.ZipFile(res, "r") as zf:
            files = zf.namelist()
            assert "imsmanifest.xml" in files
            assert "data/course.json" in files
            course_json = json.loads(zf.read("data/course.json").decode("utf-8"))
            assert len(course_json["course"]["modules"]) == 1
            assert course_json["course"]["modules"][0]["lessons"][0]["id"] == "l101"


if __name__ == "__main__":
    print("[*] Running SCORM Framework Test Suite...")
    test_validator_valid_course()
    test_validator_detects_duplicate_ids()
    test_validator_detects_unsafe_asset_paths()
    test_manifest_generation_scorm12()
    test_manifest_generation_scorm2004()
    test_package_builder_creates_valid_archive()
    test_scorm_packager_backwards_compatibility()
    print("[PASS] ALL SCORM FRAMEWORK TESTS PASSED.")
