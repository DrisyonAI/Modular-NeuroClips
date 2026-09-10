# Google Stitch Screen Prompts & Technical Wireframe Mappings
> **Source Artifact:** `wire_frames/raw_plan.jpeg`  
> **Tool:** Google Stitch AI Agent (`stitch.withgoogle.com` / `stitch-mcp-cli`)  
> **Design Theme:** Obsidian Glassmorphism (`DESIGN.md`)

---

## Overview
This document maps each sketched section in `wire_frames/raw_plan.jpeg` to production-grade Google Stitch prompt recipes and component contracts.

---

## Screen 1: Director Page ("Director Page.")

### Stitch Natural Language Prompt
```text
Design a cyber-executive AI Video Director control room page called "Director Page" in dark obsidian glassmorphism.
Top right banner: "Directorial Autonomy: Active (Note: Director Let It Be)" with a toggle for autonomous directorial orchestration.
Main panel left (7 cols):
1. Master Script Input: Textarea with word count, speech time calculation, and quick insert pills: [Pause 0.5s], [Pause 1.0s], [Emphasis], [ProTip]. Add a document upload button (.txt, .md, .srt).
2. Output Type Selector: Dual segmented cards for "Video Scene Mode" (dynamic camera motion, b-roll) and "Instructional Slide Mode" (static diagrams, bullet points, voiceover).
3. Resolution & Aspect Ratio: Quick switch pills for 16:9 Landscape, 9:16 Vertical, 1:1 Square, 4:5 Portrait with a live visual aspect ratio box preview and resolution dropdown.
4. Scene Chunking: Segmented switch for "AI Smart Chunking" and "Target Scene Count" with a 1-16 scenes slider and quick preset chips (Shorts 3, Standard 6, Deep 10, Master 16).
5. Voice Selection: Dropdown with regional neural voices (Neerja, Guy, Aria, etc.), emotion archetypes, sliders for Speed, Pitch, Stability, and Clarity, with an "Audition Voice Line" audio deck.
6. Visuals & Audio FX:
   - Motion Graphics toggle [ON/OFF] for subpixel Ken Burns zoompan.
   - Background Music toggle [ON/OFF] for ambient bed ducked beneath voiceover (-18dB).
   - Avatar Persona select (Maya, Alex, Elena, David, Custom) with PiP/Split-screen layout dropdown.
Bottom: Action buttons for "✨ Compose Screenplay (Storyboard)" and "🚀 Render Direct Video".
Main panel right: Interactive Storyboard card grid showing keyframe thumbnail, visual prompt, motion prompt, duration, and single-scene render buttons.
```

---

## Screen 2: Avatar Page ("Avathar Page")

### Stitch Natural Language Prompt
```text
Design an AI Presenter & Avatar Video Studio page called "Avatar Page" adhering to dark obsidian glassmorphism.
Layout: 2-column studio.
Left Column (Controls):
1. Avatar Portrait Uploader: Drag & drop image area supporting PNG/JPG/WebP with circular/portrait mask preview, upload status, and fallback persona cards (Maya, Alex, Elena, David).
2. Talking Script: Textarea labeled "Script for Avatar to Talk" with live word count and estimated speech duration, plus Director pause cues.
3. Voice Selector: Dropdown with neural voices (English, Hindi, Telugu, Tamil, Spanish, French, German, Japanese) with speed and pitch sliders and an audition audio button.
4. Studio Curtain Backdrop:
   - Green / White Curtain segmented toggle [OFF/ON].
   - When ON, select between "Green Screen (#00FF00 Chroma Key)" and "Clean Studio White (#FFFFFF)".
   - Live color swatch preview showing the avatar over the chosen curtain background.
5. Future 3D Model Teaser: A futuristic card titled "Google Flap / Flow 3D Model" with a glowing neural mesh icon and an interactive toggle for 3D GLTF avatars.
6. Hand Gestures Selector: Directional segmented selector with 4 gesture presets: "Subtle & Natural", "Explanatory / Pointing", "Dynamic / Keynote", "Executive / Anchored".
7. CTA Button: Glowing primary button "🎬 Generate Avatar Video".

Right Column (Preview & Player):
- Video container with a responsive HTML5 player showing the rendered talking head avatar video.
- Play, pause, timeline scrub bar, volume, fullscreen.
- Status card showing Audio Synthesis -> Curtain Compositing -> Video Compilation.
- One-click "⬇️ Download Avatar Video (.mp4)" button.
```

---

## Screen 3: SCORM Framework Page ("SCORM Framework page")

### Stitch Natural Language Prompt
```text
Design a universal SCORM e-learning courseware generator page called "SCORM Framework Page" in dark obsidian glassmorphism.
Top Tag: Prominent "[Edu]" category badge with domain dropdown (FinTech Academy, EdTech Higher Ed, Corporate Compliance, AI Engineering).
Layout:
1. Pre-built Frame Select: Visual card picker with 4 interactive courseware templates:
   - "FinTech Executive Masterclass" (Video + 32-Question Bank)
   - "Microlearning Capsule" (3-min fast concept + 5-Question Mastery Check)
   - "Compliance & Regulatory Certification" (Mandatory full watch + 80% passing lock)
   - "Slide Deck + Avatar Explainer" (Split-screen presentation with synchronized transcript)
2. Curriculum Context Paste: Large textarea labeled "Context Paste" for instructors to paste syllabus, lecture notes, or course outlines, with an "✨ AI Auto-Structure Context" button.
3. Video Asset Mapping: Interactive media library grid showing available project and uploaded videos with thumbnails, duration, and "Map to Lesson" checkboxes.
4. Mapping Connector: Visual flowchart arrow "Context + Videos -> SCORM Package".
5. Action Bar: SCORM Standard selector (SCORM 1.2 vs SCORM 2004) and "📦 Map & Download SCORM Package (.zip)" button.
Right Column / Modal:
- LMS CMI Data Model Inspector showing cmi.core.score.raw, cmi.core.lesson_status, and passing percentage slider.
- Recent exported SCORM packages download table.
```
