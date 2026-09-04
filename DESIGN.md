# Google Stitch Design System — Modular-NeuroClips Studio
> **Architecture & UI/UX Specification for Google Stitch Prototyping and Code Generation**  
> **Target Framework:** Modern Tailwind CSS + Glassmorphism + Lucide Icons + Google Stitch MCP  
> **Source Wireframes:** `wire_frames/raw_plan.jpeg`

---

## 1. Executive Summary & Design Vision

**Modular-NeuroClips Studio** is an autonomous AI video generation workbench and instructional courseware production engine. This design system serves as the definitive specification for **Google Stitch** (`stitch.withgoogle.com`) and front-end implementations.

The design language embodies **"Deep Obsidian Glassmorphism"** — a sleek, modern, cyber-executive studio control room engineered for high cognitive throughput, tactile precision, and zero-clutter directorial workflows.

---

## 2. Core Color Tokens & Visual Hierarchy

### 2.1 Theme Palette
| Token Name | Hex Code | Tailwind Equivalent | Role / Usage |
| :--- | :--- | :--- | :--- |
| `surface-base` | `#090D16` | `bg-slate-950` | Primary viewport background canvas |
| `surface-panel` | `rgba(15, 23, 42, 0.75)` | `bg-slate-900/75` | Glassmorphism cards with `backdrop-blur-md` |
| `surface-card-glow`| `rgba(15, 23, 42, 0.85)` | `bg-slate-900/85` | Highlighted cards with subtle outer glow |
| `border-subtle` | `rgba(255, 255, 255, 0.08)` | `border-slate-800/80`| Default card boundaries and dividers |
| `border-focus` | `#38BDF8` | `border-sky-400` | Active input rings, selected cards |
| `accent-primary` | `#0EA5E9` / `#38BDF8` | `brand-500` / `brand-glow`| Primary action buttons, progress bars, active badges |
| `accent-director`| `#6366F1` | `indigo-500` | Directorial controls, script cues, orchestration tags |
| `accent-avatar` | `#EC4899` / `#A855F7` | `pink-500` / `purple-500`| Avatar studio accent, face capture, gesture controls |
| `curtain-green` | `#00FF00` / `#10B981` | `emerald-500` | Chroma Key backdrop toggle indicator & preview |
| `curtain-white` | `#FFFFFF` | `white` | High-key clean studio white backdrop preview |
| `status-success` | `#10B981` | `emerald-400` | Active pipeline milestones, complete renders |
| `status-warning` | `#F59E0B` | `amber-400` | VRAM warnings, unsaved screenplay drafts |
| `status-danger` | `#F43F5E` | `rose-500` | CUDA OOM alerts, purge VRAM action |

### 2.2 Glassmorphism & Elevation Tokens
- **Glass Panel:** `backdrop-filter: blur(16px); background: rgba(15, 23, 42, 0.75); border: 1px solid rgba(255, 255, 255, 0.08);`
- **Glass Panel Glow:** `backdrop-filter: blur(20px); border: 1px solid rgba(56, 189, 248, 0.25); box-shadow: 0 0 25px rgba(14, 165, 233, 0.12);`
- **Curtain Preview Glow (Green):** `box-shadow: 0 0 20px rgba(16, 185, 129, 0.3); border-color: rgba(16, 185, 129, 0.5);`
- **Curtain Preview Glow (White):** `box-shadow: 0 0 20px rgba(255, 255, 255, 0.25); border-color: rgba(255, 255, 255, 0.6);`

---

## 3. Typography & Micro-Copy Rules

- **Headings & Primary Interface:** `Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`
  - Font weights: Light (300), Regular (400), Medium (500), Semi-bold (600), Bold (700), Black (900).
- **Code, Telemetry, Timecodes & Metrics:** `JetBrains Mono, Fira Code, monospace`
  - Used for VRAM gauges (`4.2 / 12.0 GB`), word counts (`240 words | ~1.6 min`), timestamps, and SCORM unit codes (`L101`).

---

## 4. Wireframe Page Specifications (`raw_plan.jpeg`)

### 4.1 Page 1: Director Page ("Director Page.")
The master orchestration station translating narrative scripts into video timelines or instructional slides.

#### Required Component Architecture
1. **Directorial Autonomy Banner ("Note: Director Let It Be")**:
   - Visual card/badge at top right indicating the AI Director agent is governing pacing, camera motions, and voice acting.
   - Allows creators to let the Director autonomously choreograph scenes or switch to manual granularity.
2. **Master Script Input Zone**:
   - Multi-line textarea for script narration.
   - Quick-insert cue buttons: `[pause 500ms]`, `[pause 1.0s]`, `[emphasis]`, `[protip]`.
   - File drag-and-drop uploader (`.txt`, `.md`, `.srt`, `.vtt`, `.json`).
   - Dynamic counter: word count, reading speed, and estimated playback time.
3. **Output Type Selector (Video vs. Instructional Slide)**:
   - Segmented interactive cards:
     - 🎬 **Video Scene Mode:** Full camera motion, neural b-roll, dynamic visual cues.
     - 📊 **Instructional Slide Mode:** Clean high-contrast slide with diagram cards, bullet points, and presenter voiceover.
4. **Resolution & Aspect Ratio Selector**:
   - Quick-switch pills: `16:9 ▭` (YouTube/LMS HD), `9:16 ▯` (Reels/Shorts), `1:1 ▢` (Square Social), `4:5 ▰` (Feed).
   - Live visual aspect preview box showing the proportional geometry.
5. **Voice Selection & Emotion Archetype**:
   - Neural voice dropdown with regional accents (`en-IN Neerja`, `en-US Guy`, `en-US Aria`, etc.).
   - Emotional archetypes (`Technical Instructor`, `Executive Boardroom`, `Conversational Mentor`, `High-Energy Presenter`).
   - Granular sliders: Pacing Speed (`0.75x - 1.30x`), Pitch (`-10Hz to +10Hz`), Stability (`20% - 100%`).
   - Instant "Audition Voice Line" deck with audio waveform preview.
6. **Scene Chunking Mode**:
   - Segmented toggle: `🤖 AI Smart Chunking` (pedagogical scene breakdown) vs `🎯 Target Scene Count` (slider 1 to 16 scenes).
7. **Background Music [OFF / ON]**:
   - Two-state toggle switch with volume bed ducking (-18dB beneath narration).
8. **Motion Graphics [OFF / ON]**:
   - Toggle switch for subpixel Ken Burns zoom-and-pan camera kinematics and animated lower-thirds.
9. **Interactive Storyboard & Scene Breakdown**:
   - Per-scene cards displaying Scene ID, keyframe thumbnail, visual prompt editor, motion prompt editor, and single-scene render button.

---

### 4.2 Page 2: Avatar Page ("Avathar Page")
Dedicated presenter generation studio designed to convert user portrait photos or digital identities into talking educational presenters.

#### Required Component Architecture
1. **Avatar Image Uploader ("upload image.")**:
   - Drag-and-drop upload zone supporting `.png`, `.jpg`, `.jpeg`, `.webp`.
   - Live portrait preview card with circular or 3:4 aspect mask.
   - Quick-select preset identities fallback:
     - 🇮🇳 Maya (Senior FinTech Lead)
     - 🇺🇸 Alex (Enterprise AI Architect)
     - 🇪🇺 Elena (Risk & Governance Director)
     - 🇬🇧 David (Global LMS Instructor)
     - 📸 Custom Uploaded Image
2. **Script for Avatar to Talk ("script for avathar to talk.")**:
   - Dedicated speech text area with real-time word counter and duration estimation.
   - Quick-insert cues for natural vocal pauses and emphasis.
3. **Voice Selection ("Voice selection")**:
   - Multi-language voice selector with instant audition player.
   - Fine pitch and speech rate adjustments.
4. **Backdrop Curtain Selector ("green / white curtain [OFF / ON]")**:
   - Toggleable studio curtain backdrop mode:
     - 🟢 **Green Screen Curtain (`#00FF00` Chroma Key):** For clean background removal in Premiere/After Effects/OBS.
     - ⚪ **Studio White Curtain (`#FFFFFF` High-Key Clean):** Professional minimalist educational backdrop.
     - ⬛ **Studio Dark (Curtain OFF):** Executive deep obsidian backdrop.
   - Interactive live preview swatch showing the selected backdrop color with the avatar superimposed.
5. **Future 3D Model Card ("Future Google Flap / Flow 3D model")**:
   - Futuristic neural mesh card highlighting next-gen 3D conversational avatars.
   - Toggle switch indicating support for 3D GLTF / blendshapes rigging with visual "Future Ready" tag.
6. **Hand Gestures Selector ("-> Hand gestures")**:
   - Four distinct pedagogical gesture styles:
     - 👐 **Subtle & Natural:** Micro-expressions, gentle conversational breathing, and head tilt.
     - 👉 **Explanatory & Pointing:** Directional gestures indicating diagrams and charts.
     - 🎙️ **Dynamic Keynote:** Expressive two-handed conference presenter gestures.
     - 👔 **Executive & Anchored:** Poised, authoritative boardroom anchor posture.
7. **Generate Video Action ("Generate Video")**:
   - Prominent primary gradient CTA: `🎬 Generate Avatar Video`.
   - Displays real-time synthesis status: `Synthesizing Neural Audio` ➔ `Compositing Curtain Backdrop` ➔ `Compiling Avatar Stream`.
8. **Avatar Video Output Player ("Video")**:
   - Integrated HTML5 video player container.
   - Play/pause, playback speed scrubber, timecode display, fullscreen toggle.
   - One-click `⬇️ Download Avatar Video (.mp4)` button.

---

### 4.3 Page 3: SCORM Framework Page ("SCORM Framework page")
Automated e-learning courseware compilation hub mapping educational context, video assets, and assessment engines into universally compliant SCORM packages.

#### Required Component Architecture
1. **Educational Category Tag ("[Edu]")**:
   - Domain tag / category badge: `[Edu]` with selectable tracks:
     - 🎓 EdTech & University Higher Ed
     - 💳 FinTech & Banking Academy
     - ⚖️ Enterprise Compliance & Ethics
     - ☁️ Cloud Architecture & AI Engineering
2. **Pre-Built Frame Selector ("pre build frame select.")**:
   - Four interactive template frame cards:
     - 🏛️ **Frame 1: Executive Masterclass:** Comprehensive video lecture, full syllabus overview, and 32-question assessment gate.
     - ⚡ **Frame 2: Microlearning Capsule:** Fast-paced 3-minute focused concept video with immediate 5-question comprehension check.
     - ⚖️ **Frame 3: Compliance & Regulatory Certification:** Mandatory full-video completion lock and 80% passing grade requirement.
     - 📊 **Frame 4: Slide Deck + Avatar Explainer:** Dual-pane presentation with synchronized interactive transcript.
3. **Curriculum Context Paste ("Context paste")**:
   - Large context input textarea for instructors to paste course syllabus, lecture transcripts, markdown lesson notes, or learning objectives.
   - "✨ AI Auto-Structure Context" button to parse the pasted text into organized module units.
4. **Video Asset Mapping Grid ("Video's")**:
   - Visual media vault picker displaying all available videos (rendered studio videos and externally uploaded clips).
   - Shows thumbnail, filename, duration, and a "Map to Frame" toggle checkbox.
5. **Map & SCORM Download Engine ("map -> SCORM download")**:
   - Visual mapping connector showing Context + Videos bridging into the SCORM manifest.
   - One-click `📦 Map & Download SCORM Package (.zip)` button.
   - Builds compliant ADL SCORM 1.2 or SCORM 2004 archive with `imsmanifest.xml`, interactive HTML5 player, CMI telemetry, and embedded quiz bank.

---

## 5. Google Stitch Screen Prompts & Implementation Guide

When using **Google Stitch** (`stitch.withgoogle.com`) or the Stitch MCP, input the screen definitions located in `wire_frames/STITCH_SPECIFICATIONS.md`.

All generated screens inherit the Obsidian Glassmorphism theme tokens defined above, ensuring full brand and UI coherence across the entire Modular-NeuroClips suite.
