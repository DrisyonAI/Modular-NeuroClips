import os
import asyncio
import pandas as pd
import subprocess
from pathlib import Path
import edge_tts
from src.pipeline import MediaGenerationEngine

EXCEL_FILE = "Nipuna_AI_Agents_in_FinTech_15_Hour_Course-updated-v3.xlsx"
OUTPUT_BASE = Path("./curriculum_output")
OUTPUT_BASE.mkdir(parents=True, exist_ok=True)

VOICE_PROFILE = "en-IN-NeerjaNeural"  # or "en-US-GuyNeural"

async def generate_narration(text: str, audio_path: str):
    """Generates audio voiceover with zero VRAM consumption."""
    communicate = edge_tts.Communicate(text, VOICE_PROFILE)
    await communicate.save(audio_path)

def process_course_sheet():
    engine = MediaGenerationEngine(output_dir=OUTPUT_BASE / "cache")
    
    # Load curriculum sheet
    df = pd.read_excel(EXCEL_FILE, sheet_name="Course Map")
    
    print(f"[*] Loaded course map with {len(df)} entries.")
    
    # Iterate through lessons and produce assets
    for index, row in df.iterrows():
        # Adjust column keys according to parsed headers
        lesson_id = row.get("Unnamed: 0", f"lesson_{index}")
        script_text = row.get("Unnamed: 7", None) # Narration script
        visual_prompt = row.get("Unnamed: 5", "Educational visual explaining financial AI workflows")
        
        if not script_text or pd.isna(script_text):
            continue
            
        print(f"\n[+] Processing {lesson_id}...")
        lesson_dir = OUTPUT_BASE / str(lesson_id)
        lesson_dir.mkdir(parents=True, exist_ok=True)
        
        audio_file = lesson_dir / "narration.mp3"
        keyframe_file = lesson_dir / "keyframe.png"
        video_clip_file = lesson_dir / "clip.mp4"
        final_video_file = lesson_dir / "final_lesson.mp4"
        
        # 1. Voice Synthesis
        if not audio_file.exists():
            print(" -> Synthesizing audio...")
            asyncio.run(generate_narration(str(script_text), str(audio_file)))
            
        # 2. Keyframe Generation
        if not keyframe_file.exists():
            print(" -> Generating visual keyframe...")
            full_prompt = f"Cinematic educational visual, high quality, 4k: {visual_prompt}"
            engine.generate_image_keyframe(full_prompt, scene_id=index)
            
        # 3. CogVideoX Motion Generation
        if not video_clip_file.exists():
            print(" -> Animating scene with CogVideoX...")
            engine.generate_video_clip(str(keyframe_file), str(visual_prompt), scene_id=index)
            
        # 4. Audio-Video Synchronization via FFmpeg
        if not final_video_file.exists():
            print(" -> Merging audio & looping video to narration length...")
            cmd = [
                "ffmpeg", "-y",
                "-stream_loop", "-1",
                "-i", str(video_clip_file),
                "-i", str(audio_file),
                "-shortest",
                "-c:v", "libx264",
                "-c:a", "aac",
                "-b:a", "192k",
                "-pix_fmt", "yuv420p",
                str(final_video_file)
            ]
            subprocess.run(cmd, check=True)
            print(f" [✔] Lesson completed: {final_video_file}")

if __name__ == "__main__":
    process_course_sheet()