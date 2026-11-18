import os
import sys
import time
import zipfile
import asyncio
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import subprocess

# 1. Setup Directories
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "render_output"
EXPORTS_DIR = BASE_DIR / "exports"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

print("=" * 70)
print("⚡ MODULAR-NEUROCLIPS: GENERATING EXCEL GOAL SEEK TUTORIAL VIDEO")
print("=" * 70)

# 2. Define 4-Step Screenplay with Domain Visuals & Narration
SCENES = [
    {
        "id": 1,
        "title": "Introduction to Goal Seek",
        "visual_desc": "Microsoft Excel Spreadsheet - Financial Revenue & Target Profit Model",
        "formula": "= Units_Sold * Unit_Price - Fixed_Costs",
        "narration": "Welcome to this tutorial on Microsoft Excel Goal Seek. Goal Seek is a powerful What-If Analysis tool that calculates the exact input value required to achieve your target financial outcome.",
        "duration": 6
    },
    {
        "id": 2,
        "title": "Accessing What-If Analysis",
        "visual_desc": "Excel Data Ribbon > Forecast Group > What-If Analysis > Goal Seek",
        "formula": "Ribbon: [Data Tab] -> [What-If Analysis] -> [Goal Seek...]",
        "narration": "To launch Goal Seek, navigate to the Data tab on your Excel ribbon. In the Forecast group, click What-If Analysis, and select Goal Seek from the dropdown menu.",
        "duration": 6
    },
    {
        "id": 3,
        "title": "Configuring Goal Seek Parameters",
        "visual_desc": "Goal Seek Dialog: Set cell: B5 ($100,000) | To value: 150000 | By changing cell: B2 (Units)",
        "formula": "Set cell: [B5] | To value: [150,000] | By changing cell: [B2]",
        "narration": "In the dialog box, set your target formula cell in 'Set cell', enter your desired profit target in 'To value', and select the variable input cell—such as units sold—in 'By changing cell'.",
        "duration": 7
    },
    {
        "id": 4,
        "title": "Execution & Target Solved",
        "visual_desc": "Goal Seek Status: Target value found! Solution: 1,875 Units Required (Success)",
        "formula": "Status: Target Value Reached -> Required Sales: 1,875 Units",
        "narration": "Click OK, and Excel instantly calculates the exact input required to hit your financial target. You can now apply Goal Seek to your financial forecasting, loan amortizations, and break-even models.",
        "duration": 7
    }
]

# 3. Generate High-Fidelity Excel Keyframes
print("\n[*] Step 1: Synthesizing High-Definition Excel UI Keyframes (1280x720)...")
keyframe_paths = []

for sc in SCENES:
    img_path = OUTPUT_DIR / f"scene_{sc['id']}_goalseek_keyframe.png"
    img = Image.new("RGB", (1280, 720), color=(15, 23, 42))
    draw = ImageDraw.Draw(img)

    # Background gradient
    for y in range(720):
        r = int(10 + (y / 720) * 15)
        g = int(20 + (y / 720) * 35)
        b = int(35 + (y / 720) * 60)
        draw.line([(0, y), (1280, y)], fill=(r, g, b))

    # Outer Glass Card
    draw.rectangle([(30, 30), (1250, 690)], outline=(56, 189, 248), width=2)
    
    # Top Excel Header Bar
    draw.rectangle([(30, 30), (1250, 90)], fill=(16, 124, 65))  # Excel Green
    draw.text((50, 48), f"📊 MICROSOFT EXCEL TUTORIAL | STEP {sc['id']} of 4: {sc['title'].upper()}", fill=(255, 255, 255))

    # Main Visual Panel
    draw.rectangle([(60, 120), (1220, 480)], fill=(24, 34, 53), outline=(71, 85, 105), width=1)
    
    # Excel Grid Simulation
    draw.rectangle([(80, 140), (1200, 200)], fill=(30, 41, 59))
    draw.text((100, 160), f"UI FOCUS: {sc['visual_desc']}", fill=(56, 189, 248))
    
    draw.rectangle([(80, 220), (1200, 320)], fill=(15, 23, 42), outline=(51, 65, 85))
    draw.text((100, 245), f"FORMULA / PARAMETERS:", fill=(148, 163, 184))
    draw.text((100, 275), sc['formula'], fill=(245, 158, 11))

    # Action Guidance Badge
    draw.rectangle([(80, 350), (1200, 450)], fill=(2, 132, 199))
    draw.text((100, 375), f"GUIDANCE STEP #{sc['id']}:", fill=(255, 255, 255))
    draw.text((100, 405), sc['narration'][:110] + ("..." if len(sc['narration']) > 110 else ""), fill=(240, 249, 255))

    # Speaker Avatar Glass Card (Bottom Right PiP)
    draw.rectangle([(980, 470), (1220, 660)], fill=(15, 23, 42), outline=(56, 189, 248), width=2)
    draw.text((1040, 520), "👩‍💼", fill=(255, 255, 255))
    draw.text((1015, 590), "Maya (FinTech Lead)", fill=(241, 245, 249))
    draw.text((1035, 620), "● Presenting", fill=(52, 211, 153))

    img.save(img_path)
    keyframe_paths.append(str(img_path))
    print(f" [✔] Saved Keyframe: {img_path.name}")

# 4. Render Video Clips with Motion
print("\n[*] Step 2: Rendering Subpixel Camera Motion Dynamics...")
clip_paths = []
for idx, (sc, kf) in enumerate(zip(SCENES, keyframe_paths), start=1):
    clip_path = OUTPUT_DIR / f"scene_{idx}_goalseek_clip.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(kf),
        "-vf", f"zoompan=z='min(zoom+0.0010,1.15)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={sc['duration']*25}:s=1280x720",
        "-t", str(sc['duration']),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "ultrafast",
        str(clip_path)
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception:
        # Fallback copy if ffmpeg zoompan fails
        cmd_simple = ["ffmpeg", "-y", "-loop", "1", "-i", str(kf), "-t", str(sc['duration']), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip_path)]
        subprocess.run(cmd_simple, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
    clip_paths.append(str(clip_path))
    print(f" [✔] Saved Motion Clip: {clip_path.name} ({sc['duration']}s)")

# 5. Synthesize Edge-TTS Voiceover Audio
print("\n[*] Step 3: Synthesizing Synchronized Neural Voiceover (en-IN-NeerjaNeural)...")
full_script_text = " ".join([sc['narration'] for sc in SCENES])
audio_path = OUTPUT_DIR / "audio_goalseek_demo.mp3"

async def generate_voice():
    try:
        import edge_tts
        communicate = edge_tts.Communicate(full_script_text, "en-IN-NeerjaNeural")
        await communicate.save(str(audio_path))
        print(f" [✔] Edge-TTS Voiceover Generated: {audio_path.name} ({audio_path.stat().st_size / 1024:.1f} KB)")
    except Exception as e:
        print(f" [!] Edge-TTS warning ({e}). Generating fallback audio.")
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.save_to_file(full_script_text, str(audio_path))
            engine.runAndWait()
            print(f" [✔] Local TTS Audio Generated: {audio_path.name}")
        except Exception:
            pass

asyncio.run(generate_voice())

# 6. Generate Standard SRT Subtitles
print("\n[*] Step 4: Generating Synchronized .SRT Subtitles File...")
srt_path = OUTPUT_DIR / "subtitles_goalseek_demo.srt"

def format_srt_time(seconds: float) -> str:
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"

srt_lines = []
curr_t = 0.0
for idx, sc in enumerate(SCENES, start=1):
    start_s = format_srt_time(curr_t)
    end_s = format_srt_time(curr_t + sc['duration'])
    srt_lines.append(f"{idx}\n{start_s} --> {end_s}\n{sc['narration']}\n")
    curr_t += sc['duration']

with open(srt_path, "w", encoding="utf-8") as f:
    f.write("\n".join(srt_lines))
print(f" [✔] Saved Subtitles: {srt_path.name}")

# 7. Compile Final Video with Audio Multiplexing & Burned-In Captions
print("\n[*] Step 5: Multiplexing Final Video (H.264 + AAC 192k + Burned Subtitles)...")
final_video_path = OUTPUT_DIR / "prod_goalseek_demo.mp4"
concat_file = OUTPUT_DIR / "concat_goalseek.txt"

with open(concat_file, "w") as f:
    for cp in clip_paths:
        f.write(f"file '{Path(cp).resolve()}'\n")

escaped_srt = str(srt_path.resolve()).replace("\\", "/").replace(":", "\\:")
has_audio = audio_path.exists() and audio_path.stat().st_size > 100

if has_audio:
    cmd_mux = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-stream_loop", "-1", "-i", str(audio_path.resolve()),
        "-vf", f"scale=1280:720,subtitles='{escaped_srt}':force_style='FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00090D16,BorderStyle=3,MarginV=36,Bold=1'",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "44100",
        "-ac", "2",
        "-shortest",
        "-preset", "fast",
        "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(final_video_path)
    ]
else:
    cmd_mux = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-vf", f"scale=1280:720,subtitles='{escaped_srt}':force_style='FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00090D16,BorderStyle=3,MarginV=36,Bold=1'",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(final_video_path)
    ]

try:
    subprocess.run(cmd_mux, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
except Exception:
    # Direct concat fallback
    cmd_simple = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(final_video_path)]
    subprocess.run(cmd_simple, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

print(f" [✔] Final Production Video Rendered: {final_video_path.name} ({final_video_path.stat().st_size / (1024*1024):.2f} MB)")

# 8. Package 1-Click SCORM 1.2 Bundle
print("\n[*] Step 6: Packaging Standard SCORM 1.2 LMS Package (.zip)...")
scorm_zip_path = EXPORTS_DIR / "SCORM_prod_goalseek_demo.zip"

manifest_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="Course_Excel_Goal_Seek" version="1.0" xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2">
  <organizations default="org1">
    <organization identifier="org1">
      <title>Microsoft Excel Goal Seek Tutorial</title>
      <item identifier="item1" identifierref="resource1">
        <title>Goal Seek Formula & What-If Analysis</title>
      </item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="resource1" type="webcontent" adlcp:scormtype="sco" href="index.html">
      <file href="index.html"/>
      <file href="{final_video_path.name}"/>
    </resource>
  </resources>
</manifest>
"""

player_html = f"""<!DOCTYPE html>
<html>
<head>
  <title>Microsoft Excel Goal Seek Tutorial</title>
  <style>
    body {{ margin:0; background:#090d16; display:flex; flex-direction:column; justify-content:center; align-items:center; min-height:100vh; font-family:sans-serif; color:#fff; }}
    .player-card {{ background:#0f172a; padding:24px; border-radius:16px; border:1px solid #38bdf8; box-shadow:0 0 30px rgba(56,189,248,0.2); max-width:960px; width:90%; text-align:center; }}
    video {{ width:100%; border-radius:12px; margin-top:16px; }}
    h1 {{ font-size:20px; margin:0; color:#38bdf8; }}
    p {{ font-size:12px; color:#94a3b8; margin:8px 0 0 0; }}
  </style>
</head>
<body>
  <div class="player-card">
    <h1>📊 Microsoft Excel Goal Seek Tutorial</h1>
    <p>Module: What-If Financial & Break-Even Analysis | Runtime: 26 Seconds</p>
    <video src="{final_video_path.name}" controls autoplay></video>
  </div>
</body>
</html>
"""

with zipfile.ZipFile(scorm_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    zf.writestr("imsmanifest.xml", manifest_xml)
    zf.writestr("index.html", player_html)
    zf.write(final_video_path, arcname=final_video_path.name)

print(f" [✔] SCORM 1.2 Package Saved: {scorm_zip_path.name} ({scorm_zip_path.stat().st_size / (1024*1024):.2f} MB)")

print("\n" + "=" * 70)
print("🎉 ALL PRODUCTION ARTIFACTS GENERATED SUCCESSFULLY!")
print("=" * 70)
print(f"📁 Video:    {final_video_path}")
print(f"📁 Audio:    {audio_path}")
print(f"📁 Subtitle: {srt_path}")
print(f"📁 SCORM:    {scorm_zip_path}")
print("=" * 70)
