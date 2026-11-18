import os
import asyncio
import subprocess
import streamlit as st
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
import edge_tts

# ---------------------------------------------------------
# Page Configuration & Styling
# ---------------------------------------------------------
st.set_page_config(
    page_title="AI Video Studio",
    page_icon="🎬",
    layout="wide"
)

st.title("🎬 AI Short-Form Video Studio")
st.caption("Generate scripted reels with Google Gemini, neural voiceovers, and dynamic motion.")

# ---------------------------------------------------------
# Data Models
# ---------------------------------------------------------
class Scene(BaseModel):
    scene_number: int
    duration_seconds: int = Field(default=5)
    visual_prompt: str
    narration: str
    motion_type: str = Field(default="zoom_in")

class VideoPlan(BaseModel):
    title: str
    scenes: list[Scene]

# ---------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------
def generate_storyboard(topic: str, style: str, num_scenes: int) -> VideoPlan:
    client = genai.Client()
    prompt = f"""
    Create a highly engaging short-form video script for a {style} video about: '{topic}'.
    Format the output with exactly {num_scenes} sequential scenes for a 9:16 vertical reel.
    Visual prompts should be cinematic, detailed, and match the {style} theme.
    Motion types should be one of: 'zoom_in', 'zoom_out', 'pan_left', 'pan_right'.
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
    return VideoPlan.model_validate_json(response.text)

async def synthesize_voiceover(text: str, voice: str, output_path: str):
    communicate = edge_tts.Communicate(text=text, voice=voice, rate="+5%")
    await communicate.save(output_path)

def render_motion_clip(prompt: str, motion_type: str, duration: int, output_mp4: str):
    total_frames = duration * 30
    if motion_type == "zoom_in":
        zoom_expr = f"zoompan=z='min(zoom+0.0015,1.25)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30"
    elif motion_type == "zoom_out":
        zoom_expr = f"zoompan=z='if(lte(zoom,1.0),1.25,max(1.001,zoom-0.0015))':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30"
    elif motion_type == "pan_left":
        zoom_expr = f"zoompan=z=1.2:x='if(lte(on,1),(iw-iw/zoom)/2,x-0.5)':y='ih/2-(ih/zoom/2)':d={total_frames}:s=1080x1920:fps=30"
    else:
        zoom_expr = f"zoompan=z=1.2:x='if(lte(on,1),0,x+0.5)':y='ih/2-(ih/zoom/2)':d={total_frames}:s=1080x1920:fps=30"

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=0x111827:s=1080x1920:d={duration}",
        "-vf", (
            f"{zoom_expr},"
            f"drawtext=text='{prompt[:40]}...':fontcolor=white:fontsize=48:x=(w-text_w)/2:y=(h-text_h)/2"
        ),
        "-t", str(duration),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        output_mp4
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

def assemble_final_video(clips: list[str], audio_path: str, output_path: str):
    concat_file = "temp_concat.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for c in clips:
            f.write(f"file '{os.path.abspath(c)}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat_file,
        "-i", audio_path,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        output_path
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    if os.path.exists(concat_file):
        os.remove(concat_file)

# ---------------------------------------------------------
# UI Layout: Sidebar Settings
# ---------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Configuration")
    style_option = st.selectbox(
        "Content Niche / Style",
        ["Cinematic Documentary", "High-Tech / Future", "Mystery / Thriller", "Motivational", "Educational"]
    )
    voice_option = st.selectbox(
        "Narrator Voice",
        [
            ("en-US-ChristopherNeural", "Christopher (Male, Professional)"),
            ("en-US-JennyNeural", "Jenny (Female, Friendly)"),
            ("en-US-GuyNeural", "Guy (Male, Casual)"),
            ("en-GB-SoniaNeural", "Sonia (British Female, Elegant)"),
        ],
        format_func=lambda x: x[1]
    )[0]
    num_scenes = st.slider("Number of Scenes", min_value=2, max_value=5, value=3)

# ---------------------------------------------------------
# Step 1: Input & Storyboard Generation
# ---------------------------------------------------------
topic = st.text_input("Enter your video concept or topic:", placeholder="e.g. Why the deepest ocean trenches terrify scientists")

if st.button("Generate Storyboard & Script", type="primary"):
    if not topic.strip():
        st.warning("Please enter a topic first.")
    else:
        with st.spinner("Gemini is planning your script and scenes..."):
            plan = generate_storyboard(topic, style_option, num_scenes)
            st.session_state["video_plan"] = plan

# ---------------------------------------------------------
# Step 2: Storyboard Review & Editor
# ---------------------------------------------------------
if "video_plan" in st.session_state:
    plan: VideoPlan = st.session_state["video_plan"]
    st.subheader(f"📝 Storyboard: {plan.title}")
    
    col1, col2 = st.columns([2, 1])
    with col1:
        edited_scenes = []
        for i, scene in enumerate(plan.scenes):
            with st.expander(f"Scene {scene.scene_number} ({scene.duration_seconds}s)", expanded=True):
                v_prompt = st.text_area(f"Visual Prompt #{i+1}", value=scene.visual_prompt, key=f"vp_{i}")
                narration = st.text_area(f"Voiceover Text #{i+1}", value=scene.narration, key=f"narr_{i}")
                motion = st.selectbox(f"Camera Motion #{i+1}", ["zoom_in", "zoom_out", "pan_left", "pan_right"], index=0, key=f"mot_{i}")
                edited_scenes.append(Scene(
                    scene_number=scene.scene_number,
                    duration_seconds=scene.duration_seconds,
                    visual_prompt=v_prompt,
                    narration=narration,
                    motion_type=motion
                ))
    
    with col2:
        st.info("💡 **Tip**: You can tweak the narration and visual prompts on the left before rendering the final video.")
        if st.button("🚀 Render Video Now", type="primary"):
            os.makedirs("output_temp", exist_ok=True)
            progress_bar = st.progress(0, text="Starting render...")
            
            progress_bar.progress(20, text="Synthesizing neural voiceover...")
            audio_path = os.path.join("output_temp", "narration.mp3")
            full_narration = " ".join([s.narration for s in edited_scenes])
            asyncio.run(synthesize_voiceover(full_narration, voice_option, audio_path))
            
            scene_clips = []
            step_increment = 60 / len(edited_scenes)
            for idx, s in enumerate(edited_scenes):
                progress_bar.progress(
                    int(20 + (idx + 1) * step_increment),
                    text=f"Rendering Scene {s.scene_number} with {s.motion_type} motion..."
                )
                clip_path = os.path.join("output_temp", f"scene_{s.scene_number}.mp4")
                render_motion_clip(s.visual_prompt, s.motion_type, s.duration_seconds, clip_path)
                scene_clips.append(clip_path)
                
            progress_bar.progress(90, text="Stitching scenes and audio...")
            final_mp4 = "final_output.mp4"
            assemble_final_video(scene_clips, audio_path, final_mp4)
            progress_bar.progress(100, text="Done!")
            
            st.success("🎉 Video rendered successfully!")
            st.video(final_mp4)
            
            with open(final_mp4, "rb") as file:
                st.download_button(
                    label="⬇️ Download Reel (MP4)",
                    data=file,
                    file_name="generated_reel.mp4",
                    mime="video/mp4"
                )