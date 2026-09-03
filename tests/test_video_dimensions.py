"""Compositor geometry for each aspect ratio.

The filter graph is what actually decides the shape of the exported file, so these
assert on the generated ffmpeg filter strings rather than on a rendered file, which
keeps them fast and runnable without ffmpeg present.
"""
import re
import sys
import tempfile
from pathlib import Path

NARRATION_FOR_ASS = ("Welcome to this overview. [pause 500ms] Match every settlement "
                     "file the same day. [Emphasis] Investigate breaks while they are small.")

# src.compiler pulls in remotion_renderer -> config; stub only what is heavy.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.compiler import (  # noqa: E402
    build_avatar_layers,
    caption_metrics,
    caption_budget,
    chunk_narration,
    strip_director_cues,
    srt_to_ass,
    generate_srt_subtitles,
)
from src.config import RESOLUTION_PROFILES  # noqa: E402

fails = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (("  -> " + extra) if extra and not cond else ""))
    if not cond:
        fails.append(name)


LANDSCAPE = (1280, 720)
PORTRAIT = (720, 1280)
SQUARE = (720, 720)


def overlay_of(parts):
    for p in parts:
        m = re.search(r"overlay=([^:]+):([^:]+):", p)
        if m:
            return m.group(1), m.group(2)
    return None, None


def scale_of(parts):
    m = re.search(r"scale=(\d+):(\d+)", parts[0])
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


# --- 1. profiles are self-consistent --------------------------------------
for key, p in RESOLUTION_PROFILES.items():
    w, h, aspect = p["width"], p["height"], p["aspect"]
    num, den = (int(x) for x in aspect.split(":"))
    check(f"profile {key} matches its stated {aspect}",
          abs((w / h) - (num / den)) < 0.02, f"{w}x{h} = {w/h:.3f}")
    orient = p["orientation"]
    expect = "portrait" if h > w else ("square" if h == w else "landscape")
    check(f"profile {key} orientation is {expect}", orient == expect, orient)
    check(f"profile {key} names a use case", bool(p.get("use_case")))

# --- 2. every profile has even dimensions (yuv420p requirement) -----------
for key, p in RESOLUTION_PROFILES.items():
    check(f"profile {key} has even dimensions for yuv420p",
          p["width"] % 2 == 0 and p["height"] % 2 == 0,
          f'{p["width"]}x{p["height"]}')

# --- 3. PiP scales with the canvas, not fixed pixels ----------------------
land = build_avatar_layers("pip_bottom_right", *LANDSCAPE)
port = build_avatar_layers("pip_bottom_right", *PORTRAIT)
lw, lh = scale_of(land)
pw, ph = scale_of(port)
check("PiP badge is square in landscape", lw == lh, f"{lw}x{lh}")
check("PiP badge is square in portrait", pw == ph, f"{pw}x{ph}")
check("PiP badge sized off the short edge (720 both) so weight is consistent",
      lw == pw, f"landscape {lw} vs portrait {pw}")
check("PiP badge is a sane fraction of the frame, not oversized",
      0.15 <= pw / min(PORTRAIT) <= 0.45, str(pw / min(PORTRAIT)))
check("landscape PiP preserves the previous ~220px look", 200 <= lw <= 240, str(lw))

# --- 4. PiP corner placement ---------------------------------------------
x, y = overlay_of(build_avatar_layers("pip_bottom_right", *PORTRAIT))
check("bottom-right PiP anchors to both far edges", "W-w-" in x and "H-h-" in y, f"{x},{y}")
x, y = overlay_of(build_avatar_layers("pip_top_right", *PORTRAIT))
check("top-right PiP anchors to the top edge", "W-w-" in x and "H-h-" not in y, f"{x},{y}")

# --- 5. split screen follows the long axis -------------------------------
parts = build_avatar_layers("split_screen", *LANDSCAPE)
w, h = scale_of(parts)
check("landscape split gives the presenter a full-height right column",
      h == LANDSCAPE[1] and w < LANDSCAPE[0], f"{w}x{h}")
parts = build_avatar_layers("split_screen", *PORTRAIT)
w, h = scale_of(parts)
check("portrait split stacks instead, full-width bottom band",
      w == PORTRAIT[0] and h < PORTRAIT[1], f"{w}x{h}")

# --- 6. full anchor covers exactly, never distorts ------------------------
for name, dims in (("landscape", LANDSCAPE), ("portrait", PORTRAIT), ("square", SQUARE)):
    parts = build_avatar_layers("full_anchor", *dims)
    w, h = scale_of(parts)
    check(f"full anchor fills the {name} canvas", (w, h) == dims, f"{w}x{h}")
    check(f"full anchor crops rather than stretches ({name})",
          "force_original_aspect_ratio=increase" in parts[0] and "crop=" in parts[0])

# --- 7. no layout ever stretches the avatar ------------------------------
for layout in ("pip_bottom_right", "pip_top_right", "split_screen", "full_anchor"):
    for dims in (LANDSCAPE, PORTRAIT, SQUARE):
        parts = build_avatar_layers(layout, *dims)
        check(f"{layout} preserves avatar aspect at {dims[0]}x{dims[1]}",
              "force_original_aspect_ratio=increase" in parts[0])

# --- 8. avatar stays inside the frame ------------------------------------
for dims in (LANDSCAPE, PORTRAIT, SQUARE):
    parts = build_avatar_layers("split_screen", *dims)
    x, y = overlay_of(parts)
    w, h = scale_of(parts)
    check(f"split-screen band sits inside the {dims[0]}x{dims[1]} frame",
          int(x) + w <= dims[0] and int(y) + h <= dims[1], f"x={x} y={y} {w}x{h}")

# --- 9. captions scale with the frame ------------------------------------
def style_val(style, key):
    return int(re.search(key + r"=(\d+)", style).group(1))


m_land = caption_metrics(*LANDSCAPE)
m_port = caption_metrics(*PORTRAIT)

check("caption size is driven by the short edge, so it is equal at 1280x720 and 720x1280",
      m_land["font_size"] == m_port["font_size"],
      f'{m_land["font_size"]} vs {m_port["font_size"]}')
check("caption is a legible fraction of the short edge",
      0.04 <= m_port["font_size"] / min(PORTRAIT) <= 0.07,
      str(m_port["font_size"] / min(PORTRAIT)))
check("portrait caption clears the bottom edge proportionally",
      m_port["margin_v"] > m_land["margin_v"])
check("captions inset from the narrow portrait side edges", m_port["margin_lr"] >= 16)
for dims in (LANDSCAPE, PORTRAIT, SQUARE):
    mm = caption_metrics(*dims)
    check(f"caption fits well inside the {dims[0]}x{dims[1]} frame",
          mm["margin_v"] < dims[1] / 4 and mm["margin_lr"] < dims[0] / 4)

# The burned subtitle script resolution MUST equal the frame. ffmpeg renders an SRT
# through a fixed 384x288 ASS script and scales that to the video, so font size is
# not in frame pixels and a 4:3 script over a 9:16 frame scales differently on each
# axis. A real 720x1280 render came out ~4x oversized and clipped on both sides;
# these assert the ASS that replaced it.
tmp_dir = Path(tempfile.mkdtemp())
for name, dims in (("landscape", LANDSCAPE), ("portrait", PORTRAIT), ("square", SQUARE)):
    srt = tmp_dir / f"{name}.srt"
    generate_srt_subtitles(
        [{"scene_id": 1, "narration": NARRATION_FOR_ASS, "duration_seconds": 6.0}],
        srt, width=dims[0], height=dims[1])
    ass_p = srt_to_ass(str(srt), tmp_dir / f"{name}.ass", dims[0], dims[1])
    ass = Path(ass_p).read_text(encoding="utf-8")
    mm = caption_metrics(*dims)
    check(f"{name} ASS pins PlayRes to the frame",
          f"PlayResX: {dims[0]}" in ass and f"PlayResY: {dims[1]}" in ass)
    check(f"{name} ASS font size is in frame pixels",
          f",Arial,{mm['font_size']}," in ass)
    check(f"{name} ASS is bottom-centred with the computed margins",
          f",2,{mm['margin_lr']},{mm['margin_lr']},{mm['margin_v']}," in ass)
    check(f"{name} ASS carries every cue", ass.count("Dialogue:") >= 1)
    check(f"{name} ASS timestamps are well formed",
          bool(re.search(r"Dialogue: 0,\d:\d\d:\d\d\.\d\d,\d:\d\d:\d\d\.\d\d,", ass)))
    check(f"{name} burned captions carry no director cues",
          "[pause" not in ass.lower() and "[emphasis]" not in ass.lower())

# --- 10. caption text is chunked to fit the frame ------------------------
NARRATION = ("Three quick habits that keep your payments reconciliation clean. "
             "Match every settlement file the same day. Investigate breaks while "
             "they are small and document each fix so the next person is faster.")

b_land = caption_budget(*LANDSCAPE)
b_port = caption_budget(*PORTRAIT)
check("a narrow portrait frame holds fewer characters per cue than landscape",
      b_port < b_land, f"portrait {b_port} vs landscape {b_land}")

for name, dims in (("landscape", LANDSCAPE), ("portrait", PORTRAIT), ("square", SQUARE)):
    budget = caption_budget(*dims)
    chunks = chunk_narration(NARRATION, budget)
    check(f"{name} splits long narration into multiple cues", len(chunks) > 1, str(len(chunks)))
    check(f"{name} keeps every cue within its budget",
          all(len(c) <= budget for c in chunks),
          f"budget {budget}, longest {max(len(c) for c in chunks)}")
    check(f"{name} loses no words when chunking",
          " ".join(chunks).split() == NARRATION.split())

check("chunking never splits a word",
      all(w in NARRATION for w in " ".join(chunk_narration(NARRATION, 30)).split()))
check("empty narration yields no cues", chunk_narration("   ", 80) == [])
check("a word longer than the budget is still emitted rather than dropped",
      chunk_narration("supercalifragilistic", 5) == ["supercalifragilistic"])

# --- 11. director cues are voice directives, never caption text ----------
check("[pause 500ms] stripped", "pause" not in strip_director_cues("A [pause 500ms] B").lower())
check("[Emphasis] stripped", strip_director_cues("A [Emphasis] B") == "A B")
check("[Pro Tip] stripped", "tip" not in strip_director_cues("A [Pro Tip] B").lower())
check("surrounding words survive cue removal",
      strip_director_cues("Match every file. [pause 1s] Investigate breaks.")
      == "Match every file. Investigate breaks.")
check("ordinary bracketed text is left alone",
      strip_director_cues("See figure [3] for detail") == "See figure [3] for detail")

print()
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
