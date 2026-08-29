# Modular-NeuroClips

A modular, low-VRAM AI video generation engine and orchestrator engineered for VPS environments. `Modular-NeuroClips` automates the end-to-end production of multi-scene videos and educational course modules from text prompts or structured curriculum spreadsheets.

The pipeline integrates **Ollama (Llama 3)** for structured scene breakdown, **Stable Diffusion** for keyframe synthesis, **CogVideoX** for image-to-video diffusion, **Edge-TTS** for zero-VRAM voiceover synthesis, and **FFmpeg** for video-audio assembly—all monitored in real time via a lightweight telemetry dashboard.

---

## Features

* **Sequential VRAM Offloading:** Automatically loads and unloads models between text generation, image diffusion, and video animation stages to run reliably within 8GB–12GB VRAM limits.
* **Fast Standard-Definition (SD/480p) Preset:** Optimized render profiles ($576\times320$) reduce inference steps and eliminate memory bottlenecks.
* **Zero-VRAM Voice Synthesis:** Integrated `edge-tts` engine generates studio-quality voiceovers without competing for GPU memory.
* **Curriculum & Spreadsheet Ingestion:** Batch-processes multi-module curriculum files (`.xlsx`) into structured video lessons.
* **Fault-Tolerant Error Recovery:** Automatic exponential backoff, resolution step-down, and retries for failed or OOM diffusion frames.
* **Real-Time Telemetry Dashboard:** Live SSE-powered web interface tracking GPU VRAM allocation, GPU core load, step latency, and rendering status.

---

## System Architecture

```
                       [ Prompt / Curriculum Excel ]
                                     │
                                     ▼
                     [ LangChain + Ollama (Llama 3) ]
                     • Structured Scene Breakdowns
                     • Style Anchoring & Camera Prompts
                                     │
                                     ▼
    ┌────────────────────────────────┴────────────────────────────────┐
    ▼                                                                 ▼
[ Edge-TTS (CPU/Network) ]                           [ Sequential Diffusion Engine ]
• Zero-VRAM Audio Gen                                1. Stable Diffusion (Keyframe)
• MP3 Voiceover Tracks                               2. VRAM Cache Cleanup & Unload
                                                     3. CogVideoX-I2V (Motion Clip)
                                                     4. Dynamic Resizing on OOM
    │                                                                 │
    └────────────────────────────────┬────────────────────────────────┘
                                     ▼
                         [ FFmpeg Video Compiler ]
                         • Loops / Trims Video to Audio
                         • Standardizes 480p H.264 Video
                         • Compiles Final Production
                                     ▲
                                     │
                   [ FastAPI Telemetry Dashboard (SSE) ]
                   • Live VRAM & GPU Metrics (pynvml)
                   • Pipeline Step & Latency Tracking

```

---

## Directory Structure

```
Modular-NeuroClips/
├── .env.example
├── .gitignore
├── README.md
├── requirements.txt
├── main.py
└── src/
    ├── __init__.py
    ├── config.py             # Environment configuration & resolution profiles
    ├── orchestrator.py       # LangChain + Ollama structured scene builder
    ├── pipeline.py           # VRAM-safe SD & CogVideoX generation engine
    ├── compiler.py           # FFmpeg clip concatenator and audio merger
    ├── curriculum_engine.py  # Batch processing engine for Excel course files
    └── dashboard.py          # FastAPI + SSE real-time telemetry dashboard

```

---

## Prerequisites

* **OS:** Ubuntu 22.04+ / Debian 12 (or any modern Linux VPS)
* **GPU:** NVIDIA GPU with $\ge$ 8GB VRAM (CUDA 12.1+ recommended)
* **System Packages:** Python 3.10+, FFmpeg, and Ollama

---

## Installation & Setup

### 1. Clone the Repository

```bash
git clone https://github.com/DrisyonAI/Modular-NeuroClips.git
cd Modular-NeuroClips

```

### 2. Set Up Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

```

### 3. Install System Dependencies & Ollama

```bash
# Install FFmpeg
sudo apt-get update && sudo apt-get install -y ffmpeg

# Install Ollama & download Llama 3
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3

```

### 4. Configure Environment Variables

Copy `.env.example` to `.env` and configure your settings:

```bash
cp .env.example .env

```

Default `.env` configuration for standard definition:

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3
OUTPUT_DIR=./render_output
DEVICE=cuda

# Low-VRAM Standard-Definition Models
T2I_MODEL=runwayml/stable-diffusion-v1-5
I2V_MODEL=THUDM/CogVideoX-2b-I2V

# Frame Dimensions (Must be divisible by 16)
RENDER_WIDTH=576
RENDER_HEIGHT=320

DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=8000

```

---

## VPS Quick-Start & Usage

### 1. Launch the Telemetry Dashboard

Run the dashboard in a persistent background process or `tmux` session:

```bash
tmux new -s dashboard
source venv/bin/activate
uvicorn src.dashboard:app --host 0.0.0.0 --port 8000

```

*Detach with `Ctrl + B`, then `D`. Access the live UI at `http://<YOUR_VPS_IP>:8000`.*

### 2. Generate Video from a Text Prompt

```bash
python main.py --topic "Autonomous AI agents managing financial transactions and real-time fraud detection" --scenes 3

```

Outputs will be saved in `./render_output/`:

* `scene_X_keyframe.png`: Generated initial frames.
* `scene_X_clip.mp4`: Animated scene segments.
* `final_production_sd.mp4`: Concatenated final video.

### 3. Batch Generate Videos from Curriculum Spreadsheet

Place your curriculum spreadsheet (e.g., `Nipuna_AI_Agents_in_FinTech_15_Hour_Course-updated-v3.xlsx`) in the root directory and run:

```bash
python src/curriculum_engine.py

```

This parses narration scripts, synthesizes zero-VRAM voiceovers via `edge-tts`, generates keyframes and motion clips, and exports compiled video lessons into `./curriculum_output/`.

---

## Hardware & Performance Benchmarks

| Specification | Standard Definition (SD / 480p) | High Definition (HD / 720p) |
| --- | --- | --- |
| **Keyframe Resolution** | $576 \times 320$ | $1024 \times 576$ |
| **Diffusion Steps (T2I / I2V)** | 20 / 20 steps | 30 / 35 steps |
| **Peak VRAM Usage** | ~6.5 GB – 8.5 GB | ~16 GB – 22 GB |
| **Generation Time / Scene** | ~35 – 60 seconds | ~2.5 – 4.0 minutes |
| **Recommended GPU** | RTX 3060 / 4060 / T4 / L4 | RTX 3090 / 4090 / A5000 / A100 |

---

## Troubleshooting

* **CUDA Out of Memory (OOM):** Ensure `RENDER_WIDTH` and `RENDER_HEIGHT` are set to `576` and `320` in `.env`. `pipeline.py` will also automatically step down resolution and clear the CUDA cache on memory errors.
* **Ollama Connection Refused:** Ensure the Ollama daemon is running with `ollama serve` or `systemctl status ollama`.
* **FFmpeg Concat Errors:** Check that relative file paths inside `./render_output/concat_list.txt` exist and are accessible.

---

## License

This project is licensed under the Apache 2.0 License.
