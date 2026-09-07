"""
ADL SCORM 1.2 and SCORM 2004 imsmanifest.xml Generator.
"""
from typing import List, Dict, Any
from xml.sax.saxutils import escape as xml_escape


DEFAULT_RUNTIME_FILES: List[str] = [
    "index.html",
    "css/app.css",
    "js/scorm.js",
    "js/store.js",
    "js/components.js",
    "js/quiz.js",
    "js/player.js",
    "data/course.json"
]


def generate_scorm_manifest(
    course_id: str,
    course_title: str,
    asset_files: List[str] = None,
    scorm_version: str = "1.2",
    course_version: str = "1.0.0"
) -> str:
    """
    Builds a compliant Single-SCO imsmanifest.xml for SCORM 1.2 or 2004.
    """
    esc_course_id = xml_escape(course_id or "Course")
    esc_course_title = xml_escape(course_title or "Course")
    esc_ver = xml_escape(course_version or "1.0.0")

    all_files = list(DEFAULT_RUNTIME_FILES)
    if asset_files:
        for f in asset_files:
            clean_f = f.replace("\\", "/").lstrip("/")
            if clean_f not in all_files:
                all_files.append(clean_f)

    file_tags = "\n      ".join(f'<file href="{xml_escape(f)}"/>' for f in all_files)

    if scorm_version == "2004":
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="{esc_course_id}" version="{esc_ver}"
  xmlns="http://www.imsglobal.org/xsd/imscp_v1p1"
  xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_v1p3"
  xmlns:adlseq="http://www.adlnet.org/xsd/adlseq_v1p3"
  xmlns:adlnav="http://www.adlnet.org/xsd/adlnav_v1p3"
  xmlns:imsss="http://www.imsglobal.org/xsd/imsss"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.imsglobal.org/xsd/imscp_v1p1 imscp_v1p1.xsd
                      http://www.adlnet.org/xsd/adlcp_v1p3 adlcp_v1p3.xsd">
  <metadata>
    <schema>ADL SCORM</schema>
    <schemaversion>2004 4th Edition</schemaversion>
  </metadata>
  <organizations default="ORG-{esc_course_id}">
    <organization identifier="ORG-{esc_course_id}">
      <title>{esc_course_title}</title>
      <item identifier="ITEM-COURSE" identifierref="SCO-COURSE">
        <title>{esc_course_title}</title>
      </item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="SCO-COURSE" type="webcontent" adlcp:scormType="sco" href="index.html">
      {file_tags}
    </resource>
  </resources>
</manifest>"""

    # Default SCORM 1.2
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="{esc_course_id}" version="{esc_ver}"
  xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2"
  xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.imsproject.org/xsd/imscp_rootv1p1p2 ims_xml.xsd
                      http://www.adlnet.org/xsd/adlcp_rootv1p2 adlcp_rootv1p2.xsd">
  <metadata>
    <schema>ADL SCORM</schema>
    <schemaversion>1.2</schemaversion>
  </metadata>
  <organizations default="ORG-{esc_course_id}">
    <organization identifier="ORG-{esc_course_id}" structure="hierarchical">
      <title>{esc_course_title}</title>
      <item identifier="ITEM-COURSE" identifierref="SCO-COURSE">
        <title>{esc_course_title}</title>
      </item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="SCO-COURSE" type="webcontent" adlcp:scormtype="sco" href="index.html">
      {file_tags}
    </resource>
  </resources>
</manifest>"""
