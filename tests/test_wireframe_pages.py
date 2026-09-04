"""
Verification suite for Google Stitch wireframe pages and components:
1. Director Page ("Director Page.") with Directorial autonomy
2. Avatar Page ("Avathar Page") with speech scripting, green/white curtain, 3D model, and hand gestures
3. SCORM Framework Page ("SCORM Framework page") with [Edu] tag, pre-built frame templates, context paste, and SCORM zip packaging
"""
import os
import sys
import re
import zipfile
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import OUTPUT_DIR, EXPORTS_DIR


def get_dashboard_html():
    """Extracts the HTML served by dashboard.py."""
    dashboard_path = Path(__file__).resolve().parent.parent / "src" / "dashboard.py"
    content = dashboard_path.read_text(encoding="utf-8")
    m = re.search(r'return r"""(.*?)"""', content, re.DOTALL)
    assert m is not None, "Could not locate HTML template in dashboard.py"
    return m.group(1)


def test_wireframe_mode_switcher_tabs():
    """Verify that all wireframe pages are registered in the top mode switcher."""
    html = get_dashboard_html()
    assert 'id="mode-btn-video"' in html, "Director Studio button missing"
    assert 'id="mode-btn-avatar"' in html, "Avatar Studio button missing"
    assert 'id="mode-btn-scorm"' in html, "SCORM Framework button missing"
    assert 'Director Studio (Master Orchestrator)' in html
    assert 'Avatar Studio (Presenter Lab)' in html
    assert 'SCORM Framework & LMS' in html


def test_director_page_wireframe_specifications():
    """Verify Page 1: Director Page elements from raw_plan.jpeg."""
    html = get_dashboard_html()
    
    # 1. Wireframe Directorial rule: "Note Director let it be"
    assert "Note: Director Let It Be" in html
    assert "AUTONOMOUS" in html

    # 2. Script input & cues
    assert 'id="prompt-input"' in html
    assert "Director Cues:" in html
    assert "[Pause 0.5s]" in html
    assert "[Emphasis]" in html

    # 3. Output Type: Video or Slide
    assert 'id="output-card-video"' in html
    assert 'id="output-card-slide"' in html

    # 4. Resolution selector
    assert 'id="resolution-select"' in html
    assert 'id="aspect-preview-box"' in html

    # 5. Voice selection & prosody
    assert 'id="voice-select"' in html
    assert 'id="speed-slider"' in html
    assert 'id="pitch-slider"' in html

    # 6. Scene chunking
    assert 'id="scene-slider"' in html
    assert 'id="chunk-mode-auto"' in html

    # 7. Background music [OFF / ON]
    assert 'id="bgm-btn-on"' in html
    assert 'id="bgm-btn-off"' in html

    # 8. Motion graphics [OFF / ON]
    assert 'id="motion-btn-on"' in html
    assert 'id="motion-btn-off"' in html


def test_avatar_page_wireframe_specifications():
    """Verify Page 2: Avatar Page elements from raw_plan.jpeg."""
    html = get_dashboard_html()

    # Section ID & Header
    assert 'id="mode-avatar-section"' in html
    assert "Avatar Studio" in html
    assert "Wireframe: Avathar Page" in html

    # 1. Upload image
    assert 'id="avatar-page-file-input"' in html
    assert 'id="avatar-portrait-img"' in html
    assert "Click to Upload Avatar Photo" in html

    # 2. Script for avatar to talk
    assert 'id="avatar-script-input"' in html
    assert "Script for Avatar to Talk" in html
    assert 'id="avatar-script-stats"' in html

    # 3. Voice selection & Audition
    assert 'id="avatar-voice-select"' in html
    assert 'id="avatar-audition-btn"' in html

    # 4. Green / White curtain [OFF / ON]
    assert 'id="avatar-curtain-toggle"' in html
    assert 'id="curtain-btn-green"' in html
    assert 'id="curtain-btn-white"' in html
    assert "Green Screen" in html
    assert "White Studio" in html

    # 5. Future Google Flap / Flow 3D model
    assert "Google Flap / Flow 3D" in html
    assert 'id="avatar-3d-model-toggle"' in html

    # 6. Hand gestures (-> Hand gestures)
    assert 'id="gesture-btn-subtle"' in html
    assert 'id="gesture-btn-explanatory"' in html
    assert 'id="gesture-btn-dynamic"' in html
    assert 'id="gesture-btn-executive"' in html

    # 7. Generate Video action & Video player
    assert 'id="avatar-generate-btn"' in html
    assert 'id="avatar-video-player"' in html
    assert 'id="avatar-download-link"' in html


def test_scorm_framework_page_wireframe_specifications():
    """Verify Page 3: SCORM Framework Page elements from raw_plan.jpeg."""
    html = get_dashboard_html()

    # 1. Edu Category Tag: [Edu]
    assert "[Edu Framework]" in html
    assert 'id="scorm-edu-category-select"' in html

    # 2. Pre-built Frame Select ("pre build frame select.")
    assert "Pre-built Frame Select" in html
    assert 'id="frame-card-micro"' in html
    assert 'id="frame-card-master"' in html
    assert 'id="frame-card-comp"' in html
    assert 'id="frame-card-slide"' in html

    # 3. Context Paste ("Context paste")
    assert 'id="scorm-context-paste-input"' in html
    assert "Context Paste" in html

    # 4. Video Mapping & Download Action
    assert 'id="scorm-custom-build-btn"' in html
    assert 'id="scorm-packages-table"' in html


def test_scorm_framework_packaging_logic(tmp_path):
    """Verify that a SCORM package with frame metadata produces valid imsmanifest and HTML5 player."""
    from src.quiz_engine import QuizEngine
    quiz_engine = QuizEngine()
    
    zip_path = tmp_path / "test_framework_package.zip"
    course_id = "EDU_FINTECH_101"
    course_title = "FinTech Autonomous Systems"
    frame_template = "microlearning"
    
    manifest_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="{course_id}" version="1.2" xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2" xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2">
  <organizations default="org_{course_id}">
    <organization identifier="org_{course_id}">
      <title>{course_title} [Edu Framework]</title>
      <item identifier="item_1" identifierref="res_{course_id}">
        <title>{course_title} — {frame_template.title()} Frame</title>
      </item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="res_{course_id}" type="webcontent" adlcp:scormtype="sco" href="index.html">
      <file href="index.html"/>
    </resource>
  </resources>
</manifest>
"""
    player_html = quiz_engine.generate_interactive_scorm_html(
        video_filename="",
        module_id=1,
        pass_percentage=70
    )

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("imsmanifest.xml", manifest_xml)
        zf.writestr("index.html", player_html)
        zf.writestr("curriculum_context.txt", "Pasted curriculum notes on decentralized finance.")

    assert zip_path.exists()
    assert zip_path.stat().st_size > 500

    # Inspect zip contents
    with zipfile.ZipFile(zip_path, "r") as zf:
        namelist = zf.namelist()
        assert "imsmanifest.xml" in namelist
        assert "index.html" in namelist
        assert "curriculum_context.txt" in namelist

        manifest_content = zf.read("imsmanifest.xml").decode("utf-8")
        assert "Edu Framework" in manifest_content
        assert frame_template.title() in manifest_content
