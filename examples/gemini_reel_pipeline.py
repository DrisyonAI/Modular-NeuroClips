import os
import sys
import json
import asyncio
import subprocess
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# 1. Data Models for Storyboard & Script
# ---------------------------------------------------------------------------
class Scene(BaseModel):
    scene_number: int
    duration_seconds: int = Field(description="Target clip length in seconds, e.g., 5-7s")
    visual_prompt: str = Field(description="Photorealistic visual prompt describing the scene")
    narration: str = Field(description="Voiceover text for this scene")
    motion_type: str = Field(
        default="zoom_in",
        description="Camera movement: 'zoom_in', 'zoom_out', 'pan_left', or 'pan_right'"
    )

class VideoPlan(BaseModel):
    title: str
    target_aspect_ratio: str = "9:16"  # Portrait for Reels/Shorts
    scenes: list[Scene]

# ---------------------------------------------------------------------------
# 2. Step 1: Script & Storyboard Generation (Gemini Flash)
# ---------------------------------------------------------------------------
def generate_storyboard(topic: str) -> VideoPlan:
    print(f"\n[1/4] Generating script & storyboard for: '{topic}'...")
    client = genai.Client()
    
    prompt = f"""
    Create a highly engaging short-form video script (3 scenes total, ~15-20 seconds total) about: '{topic}'.
    Format the output for a vertical 9:16 video (TikTok/Instagram Reels/YouTube Shorts).
    Make the visual prompts photorealistic, cinematic, and detailed.
    """
    
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=VideoPlan,
            temperature=0.7
        )
    )
    plan = VideoPlan.model_validate_json(response.text)
    print(f"       Generated plan '{plan.title}' with {len(plan.scenes)} scenes.")
    return plan

# ---------------------------------------------------------------------------
# 3. Step 2: High-Quality Voiceover Generation (Edge-TTS - Free)
# ---------------------------------------------------------------------------
async def generate_voiceover(scenes: list[Scene], output_audio_path: str):
    print(f"\n[2/4] Synthesizing voiceover narration...")
    import edge_tts
    
    # Combine narrations into a coherent full script
    full_text = " ".join([s.narration for s in scenes])
    
    # High-quality neural voices: 'en-US-ChristopherNeural' or 'en-US-JennyNeural'
    voice = "en-US-ChristopherNeural"
    communicate = edge_tts.Communicate(text=full_text, voice=voice, rate="+5%")
    await communicate.save(output_audio_path)
    print(f"       Saved voiceover to: {output_audio_path}")

# ---------------------------------------------------------------------------
# 4. Step 3: Visual Generation & Dynamic Camera Motion (FFmpeg ZoomPan)
# ---------------------------------------------------------------------------
def render_motion_clip(prompt: str, motion_type: str, duration: int, output_mp4: str):
    total_frames = duration * 30
    
    if motion_type == "zoom_in":
        zoom_expr = f"zoompan=z='min(zoom+0.0015,1.25)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30"
    elif motion_type == "zoom_out":
        zoom_expr = f"zoompan=z='if(lte(zoom,1.0),1.25,max(1.001,zoom-0.0015))':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30"
    elif motion_type == "pan_left":
        zoom_expr = f"zoompan=z=1.2:x='if(lte(on,1),(iw-iw/zoom)/2,x-0.5)':y='ih/2-(ih/zoom/2)':d={total_frames}:s=1080x1920:fps=30"
    else:  # default pan right
        zoom_expr = f"zoompan=z=1.2:x='if(lte(on,1),0,x+0.5)':y='ih/2-(ih/zoom/2)':d={total_frames}:s=1080x1920:fps=30"

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=0x111827:s=1080x1920:d={duration}",
        "-vf", (
            f"{zoom_expr},"
            f"drawtext=text='{prompt[:45]}...':fontcolor=white:fontsize=48:x=(w-text_w)/2:y=(h-text_h)/2"
        ),
        "-t", str(duration),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        output_mp4
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

# ---------------------------------------------------------------------------
# 5. Step 4: Stitching & Final Video Assembly
# ---------------------------------------------------------------------------
def assemble_final_video(scene_clips: list[str], audio_path: str, final_output: str):
    print(f"\n[4/4] Stitching scenes and mixing master audio track...")
    
    concat_file = "temp_concat.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for clip in scene_clips:
            f.write(f"file '{os.path.abspath(clip)}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat_file,
        "-i", audio_path,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        final_output
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    
    if os.path.exists(concat_file):
        os.remove(concat_file)
    print(f"\n Success! Exported final video: {os.path.abspath(final_output)}")

# ---------------------------------------------------------------------------
# Main Orchestration Loop
# ---------------------------------------------------------------------------
async def run_pipeline(topic: str):
    os.makedirs("output_temp", exist_ok=True)
    
    plan = generate_storyboard(topic)
    
    audio_path = os.path.join("output_temp", "narration.mp3")
    await generate_voiceover(plan.scenes, audio_path)
    
    print(f"\n[3/4] Generating dynamic scene clips...")
    scene_clips = []
    for s in plan.scenes:
        clip_path = os.path.join("output_temp", f"scene_{s.scene_number}.mp4")
        print(f"       Rendering Scene {s.scene_number} ({s.duration_seconds}s) with motion '{s.motion_type}'...")
        render_motion_clip(
            prompt=s.visual_prompt,
            motion_type=s.motion_type,
            duration=s.duration_seconds,
            output_mp4=clip_path
        )
        scene_clips.append(clip_path)
        
    final_output = "final_reel.mp4"
    assemble_final_video(scene_clips, audio_path, final_output)

if __name__ == "__main__":
    test_topic = "The secret psychology of why coffee makes you productive"
    asyncio.run(run_pipeline(test_topic))
