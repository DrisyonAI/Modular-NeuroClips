"""Exercise scorm_upload's pure logic with the web stack stubbed out."""
import sys, types, zipfile, tempfile, os
from pathlib import Path

# --- stub fastapi / starlette so the module imports without the web stack ---
fastapi = types.ModuleType("fastapi")
class HTTPException(Exception):
    def __init__(self, status_code=400, detail=""):
        self.status_code, self.detail = status_code, detail
        super().__init__(f"{status_code}: {detail}")
fastapi.HTTPException = HTTPException
fastapi.File = lambda *a, **k: None
fastapi.Form = lambda *a, **k: None
class UploadFile: pass
fastapi.UploadFile = UploadFile
sys.modules["fastapi"] = fastapi

sc = types.ModuleType("starlette.concurrency")
sc.run_in_threadpool = None
starlette = types.ModuleType("starlette")
starlette.concurrency = sc
sys.modules["starlette"] = starlette
sys.modules["starlette.concurrency"] = sc

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import scorm_upload as su

tmp = Path(tempfile.mkdtemp())
fails = []
def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (("  -> " + extra) if extra and not cond else ""))
    if not cond: fails.append(name)

# --- 1. normal zip with nested dirs + non-video files ----------------------
z1 = tmp / "normal.zip"
with zipfile.ZipFile(z1, "w") as zf:
    zf.writestr("intro.mp4", b"\x00" * 2048)
    zf.writestr("nested/deep/lesson2.mov", b"\x00" * 2048)
    zf.writestr("notes.txt", b"ignore me")
    zf.writestr("thumb.png", b"\x89PNG")
out1 = tmp / "out1"; out1.mkdir()
vids = su._extract_videos_from_zip(z1, out1)
names = sorted(v.name for v in vids)
check("extracts only videos, flattens dirs", names == ["intro.mp4", "lesson2.mov"], str(names))
check("non-video files are ignored", not (out1 / "notes.txt").exists())
check("extracted files land in dest", all(v.parent == out1.resolve() or v.parent == out1 for v in vids))

# --- 2. zip-slip: traversal entry must not escape -------------------------
z2 = tmp / "slip.zip"
with zipfile.ZipFile(z2, "w") as zf:
    zf.writestr("../../escaped.mp4", b"\x00" * 2048)
out2 = tmp / "out2"; out2.mkdir()
escaped_target = out2.parent.parent / "escaped.mp4"
try:
    su._extract_videos_from_zip(z2, out2)
    slip_ok = not escaped_target.exists()
    detail = "no exception, but file contained (flattened)"
except HTTPException as e:
    slip_ok = True
    detail = f"rejected: {e.detail}"
check("zip-slip cannot write outside dest", slip_ok and not escaped_target.exists(), detail)

# --- 3. colliding basenames get unique names ------------------------------
z3 = tmp / "collide.zip"
with zipfile.ZipFile(z3, "w") as zf:
    zf.writestr("a/clip.mp4", b"\x00" * 2048)
    zf.writestr("b/clip.mp4", b"\x11" * 2048)
    zf.writestr("c/clip.mp4", b"\x22" * 2048)
out3 = tmp / "out3"; out3.mkdir()
v3 = su._extract_videos_from_zip(z3, out3)
n3 = sorted(v.name for v in v3)
check("colliding basenames de-duplicated", len(set(n3)) == 3 and len(n3) == 3, str(n3))

# --- 4. zip with no videos is rejected ------------------------------------
z4 = tmp / "novid.zip"
with zipfile.ZipFile(z4, "w") as zf:
    zf.writestr("readme.txt", b"nothing here")
out4 = tmp / "out4"; out4.mkdir()
try:
    su._extract_videos_from_zip(z4, out4); r4 = False; d4 = "accepted an archive with no videos"
except HTTPException as e:
    r4 = e.status_code == 400; d4 = str(e.detail)
check("archive with no videos rejected", r4, d4)

# --- 5. corrupt zip is rejected cleanly -----------------------------------
z5 = tmp / "bad.zip"; z5.write_bytes(b"this is not a zip file at all")
out5 = tmp / "out5"; out5.mkdir()
try:
    su._extract_videos_from_zip(z5, out5); r5 = False; d5 = "accepted a corrupt archive"
except HTTPException as e:
    r5 = e.status_code == 400; d5 = str(e.detail)
check("corrupt archive rejected with 400", r5, d5)

# --- 6. declared-size bomb is refused before extracting -------------------
orig = su.MAX_UNPACKED_BYTES
su.MAX_UNPACKED_BYTES = 4096
z6 = tmp / "bomb.zip"
with zipfile.ZipFile(z6, "w", zipfile.ZIP_DEFLATED) as zf:
    zf.writestr("big.mp4", b"\x00" * (64 * 1024))
out6 = tmp / "out6"; out6.mkdir()
try:
    su._extract_videos_from_zip(z6, out6); r6 = False; d6 = "accepted an oversized archive"
except HTTPException as e:
    r6 = e.status_code == 413; d6 = str(e.detail)
check("oversized archive refused with 413", r6, d6)
su.MAX_UNPACKED_BYTES = orig

# --- 7. manifest is well-formed XML and escapes user input ----------------
import xml.etree.ElementTree as ET
man = su._build_manifest("FIN_M1", 'Course & "Quotes" <hi>', "Module 1: Intro", "1.2",
                         ["a.mp4", "b & c.mp4"])
try:
    ET.fromstring(man); ok7 = True; d7 = ""
except Exception as e:
    ok7 = False; d7 = str(e)
check("SCORM 1.2 manifest is valid XML with escaped input", ok7, d7)

man2004 = su._build_manifest("FIN_M1", "Course", "Module", "2004", ["a.mp4"])
try:
    ET.fromstring(man2004); ok8 = "2004" in man2004
except Exception as e:
    ok8 = False
check("SCORM 2004 manifest is valid XML", ok8)

# --- 8. playlist player embeds the list and escapes the title -------------
html = su._playlist_player_html(["a.mp4", "b.mp4"], 'C&o <x>', "Mod", "Topic", None)
check("playlist HTML contains the video list", '"a.mp4"' in html and '"b.mp4"' in html)
check("playlist HTML escapes the course title", "C&amp;o" in html and "<x>" not in html)
check("playlist HTML reports completion to the LMS", "completion_status" in html and "LMSSetValue" in html)

# --- 9. identifier sanitising ---------------------------------------------
check("course id sanitised", su._safe_id("../../evil id!", "X") == "evilid")
check("empty course id falls back", su._safe_id("", "COURSE") == "COURSE")
check("filename sanitised", su._unique_name("../../etc/passwd.mp4", set()) == "passwd.mp4")

print()
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
