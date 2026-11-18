# Modular-NeuroClips Examples & Prototypes

This directory contains experimental scripts, tutorial demos, and prototype user interfaces that are decoupled from the core production engine.

---

### 1. `streamlit_video_studio.py`
* **Purpose**: Lightweight standalone Streamlit app demonstrating AI short-form reel scripting with Google Gemini and neural voiceover with Edge-TTS.
* **Run**:
  ```bash
  streamlit run examples/streamlit_video_studio.py
  ```

---

### 2. `gemini_reel_pipeline.py`
* **Purpose**: Standalone CLI script testing 9:16 vertical video storyboard generation with Gemini Flash, neural audio synthesis, and dynamic FFmpeg zoom/pan animations.
* **Run**:
  ```bash
  python examples/gemini_reel_pipeline.py
  ```

---

### 3. `generate_goalseek_demo.py`
* **Purpose**: Programmatic demo generator producing an instructional Microsoft Excel Goal Seek tutorial video, keyframes, and SCORM e-learning package.
* **Run**:
  ```bash
  python examples/generate_goalseek_demo.py
  ```

---

### Production Entry Points (Core System)
For actual production runs, use the official root entry points:
* **Web UI & REST API**: `uvicorn src.dashboard:app --reload`
* **CLI Production Pipeline**: `python main.py --topic "Your Topic" --scenes 3`
