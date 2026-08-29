import subprocess
from pathlib import Path
from typing import List
from src.config import OUTPUT_DIR, RENDER_WIDTH, RENDER_HEIGHT

def compile_final_video(clip_paths: List[str], output_filename: str = "final_production_sd.mp4") -> str:
    concat_list_path = OUTPUT_DIR / "concat_list.txt"
    final_output_path = OUTPUT_DIR / output_filename

    with open(concat_list_path, "w") as f:
        for clip in clip_paths:
            f.write(f"file '{Path(clip).resolve()}'\n")

    # Fast SD H.264 encode (CRF 22, ultrafast/fast preset)
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list_path),
        "-vf", f"scale={RENDER_WIDTH}:{RENDER_HEIGHT}",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-pix_fmt", "yuv420p",
        str(final_output_path)
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return str(final_output_path)