import json
import shutil
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional
from src.config import OUTPUT_DIR, RENDER_WIDTH, RENDER_HEIGHT

REMOTION_DIR = Path(__file__).resolve().parent.parent / "remotion"

def is_remotion_available() -> bool:
    """Checks if Node.js and Remotion packages are installed and available."""
    if not (REMOTION_DIR / "package.json").exists():
        return False
    if not (REMOTION_DIR / "node_modules").exists():
        return False
    return shutil.which("npx") is not None or shutil.which("node") is not None

def render_with_remotion(
    title: str,
    art_style_preset: str,
    scenes: List[Dict[str, Any]],
    output_filename: str = "final_production_remotion.mp4",
    audio_path: Optional[str] = None,
    width: int = RENDER_WIDTH,
    height: int = RENDER_HEIGHT
) -> str:
    """
    Renders dynamic multi-layer scene sequences using Remotion React video engine.

    `width`/`height` come from the job's resolution profile. They were previously
    fixed at RENDER_WIDTH x RENDER_HEIGHT, so this engine ignored the requested
    aspect ratio exactly as the FFmpeg path did.
    """
    final_output_path = OUTPUT_DIR / output_filename

    props_data = {
        "title": title,
        "artStylePreset": art_style_preset,
        "scenes": scenes,
        "audioPath": str(Path(audio_path).resolve()) if audio_path else "",
        # The composition needs the canvas too, so React layers lay out against the
        # real frame instead of assuming 16:9.
        "width": width,
        "height": height
    }

    props_file = OUTPUT_DIR / f"remotion_props_{Path(output_filename).stem}.json"
    with open(props_file, "w", encoding="utf-8") as f:
        json.dump(props_data, f, indent=2)

    cmd = [
        "npx", "remotion", "render",
        "src/index.ts",
        "MainVideo",
        str(final_output_path.resolve()),
        f"--props={props_file.resolve()}",
        f"--width={width}",
        f"--height={height}",
        "--overwrite"
    ]

    result = subprocess.run(
        cmd,
        cwd=str(REMOTION_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=180
    )

    if result.returncode != 0:
        raise RuntimeError(f"Remotion render failed: {result.stderr or result.stdout}")

    return str(final_output_path)
