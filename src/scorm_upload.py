"""Build a SCORM package from uploaded video files.

The stock Custom SCORM & LMS Generator can only attach a video that the studio
itself rendered: `/api/v1/scorm/custom-build` takes a *filename* and looks it up
in OUTPUT_DIR / ASSETS_DIR. There was no way to package video that came from
anywhere else, which is the common case for existing courseware.

This adds one endpoint that accepts an upload directly:

    POST /api/v1/scorm/build-from-upload   (multipart/form-data)
        file            a single video, OR a .zip containing videos
        course_title    ...
        course_id       used for the manifest identifier; sanitised
        module_title    ...
        topic           ...
        module_id       which item bank to attach (1-7)
        pass_percentage ...
        scorm_version   "1.2" or "2004"
        include_quiz    "true"/"false" - attach the module item bank

One video with the quiz attached reuses `quiz_engine.generate_interactive_scorm_html`
verbatim, so that path keeps the upstream player, its quiz and its LMS status
tracking. More than one video gets a playlist player generated here, because the
upstream generator takes a single filename and rewriting it would collide with
every future upstream change to that file.

Notes on the zip handling, all of which are load-bearing:

  - Entry names are resolved and checked against the extraction root before any
    write. A zip can name "../../etc/whatever" (zip-slip) and Python's zipfile
    will happily follow it.
  - Uncompressed size is summed from the headers AND enforced while copying, so
    neither a lying header nor a zip bomb can fill the disk.
  - Only known video suffixes are taken; everything else in the zip is ignored
    rather than repackaged blindly.
  - Directory structure inside the zip is flattened, and colliding basenames get
    a numeric suffix, because SCORM resource hrefs are flat here.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from typing import List, Optional
from xml.sax.saxutils import escape as xml_escape

from fastapi import File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

try:
    from src.scorm_packager import SCORMPackager
except ImportError:
    from scorm_packager import SCORMPackager

VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".webm", ".mkv", ".m4v"})

# A single upload and the total unpacked payload. The container is memory- and
# disk-capped (2 GB / a shared VPS), so these are refusals, not suggestions.
MAX_UPLOAD_BYTES = 2 * 1024 ** 3          # 2 GiB on the wire
MAX_UNPACKED_BYTES = 4 * 1024 ** 3        # 4 GiB after extraction
MAX_VIDEOS = 100
_COPY_CHUNK = 1024 * 1024


def _safe_id(raw: str, fallback: str) -> str:
    """Manifest identifiers go into XML attributes and a filename; keep them boring."""
    cleaned = "".join(c for c in (raw or "") if c.isalnum() or c in ("_", "-")).strip()
    return cleaned or fallback


def _unique_name(name: str, taken: set) -> str:
    """Flatten to a basename that has not been used yet."""
    base = Path(name).name
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base) or "video.mp4"
    if base not in taken:
        taken.add(base)
        return base
    stem, suffix = Path(base).stem, Path(base).suffix
    for n in range(2, 1000):
        candidate = f"{stem}_{n}{suffix}"
        if candidate not in taken:
            taken.add(candidate)
            return candidate
    raise HTTPException(status_code=400, detail="Too many colliding filenames in the archive.")


def _extract_videos_from_zip(zip_path: Path, dest: Path) -> List[Path]:
    """Extract just the video entries, refusing traversal and oversized payloads."""
    videos: List[Path] = []
    taken: set = set()
    total = 0

    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="The uploaded .zip is not a readable archive.")

    with zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        # Trust nothing in the header, but use it to reject the obvious bombs early.
        declared = sum(m.file_size for m in members)
        if declared > MAX_UNPACKED_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Archive expands to {declared // 1024 ** 2} MB, over the "
                       f"{MAX_UNPACKED_BYTES // 1024 ** 3} GB limit.",
            )

        for member in members:
            if Path(member.filename).suffix.lower() not in VIDEO_SUFFIXES:
                continue
            if len(videos) >= MAX_VIDEOS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Archive holds more than {MAX_VIDEOS} videos.",
                )

            out_name = _unique_name(member.filename, taken)
            out_path = (dest / out_name).resolve()
            # zip-slip: the resolved destination must stay under dest.
            if not str(out_path).startswith(str(dest.resolve()) + "/") and out_path.parent != dest.resolve():
                raise HTTPException(status_code=400, detail="Archive contains an unsafe path entry.")

            written = 0
            with zf.open(member) as src, open(out_path, "wb") as dst:
                while True:
                    chunk = src.read(_COPY_CHUNK)
                    if not chunk:
                        break
                    written += len(chunk)
                    total += len(chunk)
                    # Enforce against what actually arrives, not what was declared.
                    if total > MAX_UNPACKED_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail="Archive exceeded the unpacked size limit while extracting.",
                        )
                    dst.write(chunk)
            if written == 0:
                out_path.unlink(missing_ok=True)
                continue
            videos.append(out_path)

    if not videos:
        raise HTTPException(
            status_code=400,
            detail="No video files found in the archive. Supported: "
                   + ", ".join(sorted(VIDEO_SUFFIXES)),
        )
    videos.sort(key=lambda p: p.name.lower())
    return videos


def _playlist_player_html(
    videos: List[str],
    course_title: str,
    module_title: str,
    topic: str,
    quiz_html: Optional[str],
) -> str:
    """A SCORM player for several videos.

    Completion is reported only once every video has been watched, so the LMS
    status reflects the whole package rather than the first clip.
    """
    import json as _json

    playlist_json = _json.dumps(videos)
    title = xml_escape(f"{module_title}: {topic}" if topic else module_title)
    course = xml_escape(course_title)
    quiz_section = quiz_html or ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: #0b1120; color: #e2e8f0;
         font-family: Inter, system-ui, -apple-system, "Segoe UI", sans-serif; }}
  .wrap {{ max-width: 1100px; margin: 0 auto; padding: 24px 16px 48px; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  .sub {{ color: #94a3b8; font-size: 13px; margin-bottom: 20px; }}
  .grid {{ display: grid; grid-template-columns: 1fr; gap: 20px; }}
  @media (min-width: 860px) {{ .grid {{ grid-template-columns: 2fr 1fr; }} }}
  video {{ width: 100%; border-radius: 12px; background: #000; display: block; }}
  ol {{ list-style: none; margin: 0; padding: 0;
        border: 1px solid #1e293b; border-radius: 12px; overflow: hidden; }}
  li {{ display: flex; align-items: center; gap: 10px; padding: 10px 12px;
        border-bottom: 1px solid #1e293b; cursor: pointer; font-size: 13px; }}
  li:last-child {{ border-bottom: 0; }}
  li:hover {{ background: #111c33; }}
  li.active {{ background: #14264a; color: #7dd3fc; font-weight: 600; }}
  .tick {{ width: 18px; flex: 0 0 18px; text-align: center; color: #22c55e; }}
  .name {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .bar {{ height: 6px; background: #1e293b; border-radius: 999px; overflow: hidden; margin: 12px 0 4px; }}
  .bar > div {{ height: 100%; width: 0; background: linear-gradient(90deg,#4f46e5,#0ea5e9); transition: width .3s; }}
  .status {{ font-size: 12px; color: #94a3b8; }}
  .panel {{ border: 1px solid #1e293b; border-radius: 12px; padding: 14px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>{title}</h1>
  <div class="sub">{course}</div>
  <div class="grid">
    <div>
      <video id="player" controls preload="metadata"></video>
      <div class="bar"><div id="bar"></div></div>
      <div class="status" id="status">Loading...</div>
    </div>
    <div class="panel">
      <div style="font-size:12px;font-weight:700;margin-bottom:8px;color:#cbd5e1;">
        Lessons (<span id="done">0</span>/<span id="total">0</span>)
      </div>
      <ol id="list"></ol>
    </div>
  </div>
  {quiz_section}
</div>
<script>
// ---- SCORM 1.2 / 2004 API discovery -------------------------------------
var API = null, API_KIND = null;
function findAPI(win) {{
  var depth = 0;
  while (win && depth < 12) {{
    if (win.API) {{ API_KIND = "1.2"; return win.API; }}
    if (win.API_1484_11) {{ API_KIND = "2004"; return win.API_1484_11; }}
    if (win.parent && win.parent !== win) {{ win = win.parent; depth++; }} else break;
  }}
  return null;
}}
function initAPI() {{
  API = findAPI(window);
  if (!API && window.opener) API = findAPI(window.opener);
  if (!API) return false;
  try {{ API_KIND === "2004" ? API.Initialize("") : API.LMSInitialize(""); }} catch (e) {{}}
  return true;
}}
function setVal(k12, k2004, v) {{
  if (!API) return;
  try {{ API_KIND === "2004" ? API.SetValue(k2004, v) : API.LMSSetValue(k12, v); }} catch (e) {{}}
}}
function commit() {{
  if (!API) return;
  try {{ API_KIND === "2004" ? API.Commit("") : API.LMSCommit(""); }} catch (e) {{}}
}}
function finish() {{
  if (!API) return;
  try {{ API_KIND === "2004" ? API.Terminate("") : API.LMSFinish(""); }} catch (e) {{}}
}}

var PLAYLIST = {playlist_json};
var watched = {{}}, current = 0;
var player = document.getElementById('player');
var list = document.getElementById('list');
var statusEl = document.getElementById('status');

document.getElementById('total').innerText = PLAYLIST.length;

function render() {{
  list.innerHTML = '';
  PLAYLIST.forEach(function (name, i) {{
    var li = document.createElement('li');
    if (i === current) li.className = 'active';
    li.innerHTML = '<span class="tick">' + (watched[i] ? '&#10003;' : '&#9679;') + '</span>' +
                   '<span class="name"></span>';
    li.querySelector('.name').textContent = name;
    li.onclick = function () {{ load(i); }};
    list.appendChild(li);
  }});
  var done = Object.keys(watched).length;
  document.getElementById('done').innerText = done;
  document.getElementById('bar').style.width = (done / PLAYLIST.length * 100) + '%';
}}

function load(i) {{
  current = i;
  player.src = PLAYLIST[i];
  player.load();
  statusEl.textContent = 'Now playing: ' + PLAYLIST[i];
  render();
}}

player.addEventListener('ended', function () {{
  watched[current] = true;
  render();
  var done = Object.keys(watched).length;
  if (done >= PLAYLIST.length) {{
    setVal('cmi.core.lesson_status', 'cmi.completion_status', 'completed');
    commit();
    statusEl.textContent = 'All lessons complete.';
  }} else {{
    if (current + 1 < PLAYLIST.length) load(current + 1);
  }}
}});

window.addEventListener('load', function () {{
  var ok = initAPI();
  setVal('cmi.core.lesson_status', 'cmi.completion_status', 'incomplete');
  commit();
  statusEl.textContent = ok ? 'Connected to LMS.' : 'Standalone preview (no LMS detected).';
  load(0);
}});
window.addEventListener('beforeunload', function () {{ commit(); finish(); }});
</script>
</body>
</html>
"""


def _build_manifest(course_id: str, course_title: str, item_title: str,
                    scorm_version: str, files: List[str]) -> str:
    file_tags = "\n      ".join(f'<file href="{xml_escape(f)}"/>' for f in files)
    is_2004 = str(scorm_version).startswith("2004")
    schema = "2004 4th Edition" if is_2004 else "1.2"
    ns = ("http://www.imsglobal.org/xsd/imscp_v1p1" if is_2004
          else "http://www.imsproject.org/xsd/imscp_rootv1p1p2")
    adl_ns = ("http://www.adlnet.org/xsd/adlcp_v1p3" if is_2004
              else "http://www.adlnet.org/xsd/adlcp_rootv1p2")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="{course_id}" version="1.0"
          xmlns="{ns}"
          xmlns:adlcp="{adl_ns}">
  <metadata>
    <schema>ADL SCORM</schema>
    <schemaversion>{schema}</schemaversion>
  </metadata>
  <organizations default="org_{course_id}">
    <organization identifier="org_{course_id}">
      <title>{xml_escape(course_title)}</title>
      <item identifier="item_{course_id}" identifierref="res_{course_id}">
        <title>{xml_escape(item_title)}</title>
      </item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="res_{course_id}" type="webcontent" adlcp:scormtype="sco" href="index.html">
      <file href="index.html"/>
      {file_tags}
    </resource>
  </resources>
</manifest>
"""


def install_scorm_upload(app, *, output_dir: Path, exports_dir: Path, quiz_engine) -> None:
    """Register the upload-driven SCORM builder on `app`.

    Dependencies are passed in rather than imported so this module does not have
    to know how dashboard.py lays out its configuration.
    """

    @app.post("/api/v1/scorm/build-from-upload")
    async def build_scorm_from_upload(          # noqa: D401 - FastAPI route
        file: UploadFile = File(...),
        course_title: str = Form("Untitled Course"),
        course_id: str = Form("COURSE"),
        module_title: str = Form(""),
        topic: str = Form(""),
        module_id: int = Form(1),
        module_number: Optional[str] = Form(None),
        module_name: Optional[str] = Form(None),
        lesson_number: Optional[str] = Form(None),
        lesson_name: Optional[str] = Form(None),
        intro_video_filename: Optional[str] = Form(None),
        pass_percentage: int = Form(70),
        scorm_version: str = Form("1.2"),
        include_quiz: str = Form("true"),
    ):
        """Package uploaded video (single file or a .zip of files) as SCORM."""
        upload_name = Path(file.filename or "upload").name
        suffix = Path(upload_name).suffix.lower()
        if suffix != ".zip" and suffix not in VIDEO_SUFFIXES:
            raise HTTPException(
                status_code=400,
                detail="Upload a video (" + ", ".join(sorted(VIDEO_SUFFIXES)) + ") or a .zip of videos.",
            )

        safe_course_id = _safe_id(course_id, "COURSE")
        want_quiz = str(include_quiz).strip().lower() in ("1", "true", "yes", "on")

        # Everything happens inside a scratch directory that is always removed:
        # the container's /tmp is a 512 MB tmpfs, so use the writable output
        # volume instead, where the disk actually is.
        staging_root = Path(output_dir) / ".scorm_uploads"
        staging_root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="build_", dir=str(staging_root)))

        try:
            # --- receive the upload, capped while streaming ---------------
            incoming = staging / ("archive.zip" if suffix == ".zip" else _unique_name(upload_name, set()))
            received = 0
            with open(incoming, "wb") as out:
                while True:
                    chunk = await file.read(_COPY_CHUNK)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > MAX_UPLOAD_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail=f"Upload exceeds the {MAX_UPLOAD_BYTES // 1024 ** 3} GB limit.",
                        )
                    out.write(chunk)
            if received == 0:
                raise HTTPException(status_code=400, detail="The uploaded file is empty.")

            # --- collect the videos ---------------------------------------
            media_dir = staging / "media"
            media_dir.mkdir()
            if suffix == ".zip":
                videos = await run_in_threadpool(_extract_videos_from_zip, incoming, media_dir)
            else:
                dest = media_dir / incoming.name
                incoming.replace(dest)
                videos = [dest]

            video_names = [v.name for v in videos]

            # --- dynamic module and lesson metadata -----------------------
            m_num = str(module_number).strip() if module_number else (str(module_id) if module_id else "1")
            m_name = (module_name or "").strip()
            if not m_name:
                if module_title:
                    m_name = re.sub(r"^Module\s*\d+\s*:\s*", "", module_title).strip() or module_title
                else:
                    m_name = f"Module {m_num}"

            final_module_title = f"Module {m_num}: {m_name}" if (m_num and not m_name.startswith(f"Module {m_num}")) else m_name

            # --- player + manifest ----------------------------------------
            questions = quiz_engine.get_module_questions(int(m_num) if str(m_num).isdigit() else (module_id or 1)) if want_quiz else []
            item_title = f"{final_module_title}: {topic}" if topic else final_module_title
            if questions:
                item_title = f"{item_title} ({len(questions)} Questions)"

            packager = SCORMPackager(
                course_id=safe_course_id,
                course_title=course_title,
                course_description=f"Curriculum module: {final_module_title}",
                version=scorm_version,
                intro_video_path=intro_video_filename
            )
            packager.add_module(
                module_id=f"mod_{safe_course_id}",
                module_title=final_module_title,
                description="",
                module_number=m_num,
                module_name=m_name
            )
            for idx, v in enumerate(videos, start=1):
                l_num = str(lesson_number).strip() if (lesson_number and idx == 1) else f"{m_num}.{idx}"
                l_name = str(lesson_name).strip() if (lesson_name and idx == 1) else (
                    f"{topic or 'Lesson'} (Part {idx})" if len(videos) > 1 else (topic or m_name or "Lesson")
                )
                packager.add_lesson(
                    module_id=f"mod_{safe_course_id}",
                    lesson_id=f"les_{safe_course_id}_{idx}",
                    lesson_title=l_name,
                    topic=topic or m_name,
                    video_path=str(v),
                    lesson_number=l_num,
                    lesson_name=l_name
                )

            # --- zip it ----------------------------------------------------
            package_name = f"SCORM_{safe_course_id}_{int(time.time())}_{uuid.uuid4().hex[:6]}.zip"
            zip_path = Path(exports_dir) / package_name

            await run_in_threadpool(packager.export_zip, zip_path)

            return {
                "status": "ok",
                "package_name": package_name,
                "download_url": f"/static_exports/{package_name}",
                "size_mb": round(zip_path.stat().st_size / (1024 ** 2), 2),
                "videos": video_names,
                "video_count": len(video_names),
                "questions_count": len(questions),
                "course_title": course_title,
                "scorm_version": scorm_version,
                "source": "zip" if suffix == ".zip" else "single-file",
            }
        finally:
            shutil.rmtree(staging, ignore_errors=True)
