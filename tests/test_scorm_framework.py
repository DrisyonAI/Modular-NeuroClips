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


def test_scorm_dynamic_module2_and_lesson21():
    """Validates dynamic Module 2, Lesson 2.1, 2-3 question Understanding Check, and intro video bundling."""
    packager = SCORMPackager(
        course_id="M2_FINTECH_AGENTS",
        course_title="AI Agents in FinTech: Autonomous Execution",
        course_description="Module 2 courseware",
        version="1.2"
    )
    packager.add_module(
        module_id="mod_2",
        module_title="Module 2: Intelligent & Autonomous Transactions",
        module_number=2,
        module_name="Intelligent & Autonomous Transactions"
    )
    packager.add_lesson(
        module_id="mod_2",
        lesson_id="les_2_1",
        lesson_title="2.1 Intelligent & Autonomous Transactions",
        topic="Intelligent & Autonomous Transactions",
        lesson_number="2.1",
        lesson_name="Intelligent & Autonomous Transactions"
    )

    with tempfile.TemporaryDirectory() as td:
        out_zip = Path(td) / "m2_scorm.zip"
        res = packager.export_zip(out_zip)
        assert res.exists()

        with zipfile.ZipFile(res, "r") as zf:
            files = zf.namelist()
            assert "imsmanifest.xml" in files
            assert "index.html" in files
            assert "data/course.json" in files
            assert "assets/videos/AI-FinTech-v0.mp4" in files

            course_json = json.loads(zf.read("data/course.json").decode("utf-8"))
            course = course_json["course"]

            # Intro video must be set
            assert course.get("introBackgroundVideo") == "assets/videos/AI-FinTech-v0.mp4"

            # Module checks
            assert len(course["modules"]) == 1
            mod = course["modules"][0]
            assert mod["number"] == 2
            assert "Intelligent & Autonomous Transactions" in mod["title"]
            assert "Module 1" not in mod["title"]

            # Lesson checks
            assert len(mod["lessons"]) == 1
            les = mod["lessons"][0]
            assert les["number"] == "2.1"
            assert "2.1" in les["title"]
            assert "1.1" not in les["title"]
            assert "Lesson 1.1" not in les["title"]

            # Formative Understanding Check: strictly 2-3 questions
            assert "quiz" in les
            quiz = les["quiz"]
            assert quiz["title"] == "Understanding Check"
            assert 2 <= len(quiz["questions"]) <= 3

            # Ensure zero references to Module 1 or Lesson 1.1 in course.json
            raw_course_text = zf.read("data/course.json").decode("utf-8")
            assert "Module 1" not in raw_course_text
            assert "Lesson 1.1" not in raw_course_text
            assert '"number": "1.1"' not in raw_course_text


def test_custom_build_api_dynamic_module_and_lesson():
    """Validates custom_scorm_build_api handles dynamic module & lesson numbers and 2-3 questions check."""
    import asyncio
    from src.dashboard import custom_scorm_build_api, CustomSCORMBuildRequest

    req = CustomSCORMBuildRequest(
        course_title="AI Agents in FinTech: Autonomous Execution",
        course_id="M2_API_TEST",
        module_number=2,
        module_name="Intelligent & Autonomous Transactions",
        lesson_number="2.1",
        lesson_name="Intelligent & Autonomous Transactions",
        lesson_id="L201",
        pass_percentage=70,
        scorm_version="1.2"
    )

    res = asyncio.run(custom_scorm_build_api(req))
    assert res["status"] == "ok"
    assert res["module_number"] == "2"
    assert res["lesson_number"] == "2.1"
    assert 2 <= res["questions_count"] <= 3

    zip_path = PROJECT_ROOT / "exports" / res["package_name"]
    if not zip_path.exists():
        from src.config import EXPORTS_DIR
        zip_path = EXPORTS_DIR / res["package_name"]
    assert zip_path.exists()

    with zipfile.ZipFile(zip_path, "r") as zf:
        raw_json = zf.read("data/course.json").decode("utf-8")
        assert "Module 1" not in raw_json
        assert "Lesson 1.1" not in raw_json
        course_data = json.loads(raw_json)
        assert course_data["course"]["modules"][0]["number"] == 2
        assert course_data["course"]["modules"][0]["lessons"][0]["number"] == "2.1"
        # Check intro background video is attached
        assert course_data["course"]["introBackgroundVideo"] == "assets/videos/AI-FinTech-v0.mp4"


if __name__ == "__main__":
    print("[*] Running SCORM Framework Test Suite...")
    test_validator_valid_course()
    test_validator_detects_duplicate_ids()
    test_validator_detects_unsafe_asset_paths()
    test_manifest_generation_scorm12()
    test_manifest_generation_scorm2004()
    test_package_builder_creates_valid_archive()
    test_scorm_packager_backwards_compatibility()
    test_scorm_dynamic_module2_and_lesson21()
    print("[PASS] ALL SCORM FRAMEWORK TESTS PASSED.")
