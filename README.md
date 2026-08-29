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
SCORM Cloud Deployment Pipeline (n8n)Automate packaging lesson files (index.html, imsmanifest.xml, and media assets) into SCORM-compliant .zip bundles and deploying them directly to SCORM Cloud.Setup InstructionsOpen your n8n workspace.Navigate to Workflows $\rightarrow$ Import from JSON (or press Ctrl + V / Cmd + V on the canvas).Paste the workflow JSON below.In the Set Course Configuration node, update:courseId: Identifier for the course module (e.g., FinTech_Agent_Module_1).folderPath: Absolute path to the course asset folder.zipOutputPath: Destination path for the .zip archive.scormAppId: Your SCORM Cloud Application ID.scormSecretKey: Your SCORM Cloud Secret Key.Execute the workflow to package and deploy.JSON{
  "name": "SCORM Cloud - Package and Deploy Pipeline",
  "nodes": [
    {
      "parameters": {},
      "id": "90e0c034-7546-4e56-b188-75179ee49b25",
      "name": "When clicking ‘Test workflow’",
      "type": "n8n-nodes-base.manualTrigger",
      "typeVersion": 1,
      "position": [
        220,
        300
      ]
    },
    {
      "parameters": {
        "values": {
          "string": [
            {
              "name": "courseId",
              "value": "NovaAI_Module_2"
            },
            {
              "name": "folderPath",
              "value": "C:\\tt-ai-stack\\01_projects\\active\\bov\\02_curriculum_tracks\\financials\\module_2"
            },
            {
              "name": "zipOutputPath",
              "value": "C:\\tt-ai-stack\\01_projects\\active\\bov\\02_curriculum_tracks\\financials\\module_2\\module_2_scorm12.zip"
            },
            {
              "name": "scormAppId",
              "value": "YOUR_SCORM_CLOUD_APP_ID"
            },
            {
              "name": "scormSecretKey",
              "value": "YOUR_SCORM_CLOUD_SECRET_KEY"
            }
          ]
        },
        "options": {}
      },
      "id": "a671cf47-0e6d-4952-b80c-7b470daecae6",
      "name": "Set Course Configuration",
      "type": "n8n-nodes-base.set",
      "typeVersion": 2,
      "position": [
        440,
        300
      ]
    },
    {
      "parameters": {
        "command": "=powershell.exe -Command \"Compress-Archive -Path '{{ $json.folderPath }}\\imsmanifest.xml', '{{ $json.folderPath }}\\index.html', '{{ $json.folderPath }}\\assets' -DestinationPath '{{ $json.zipOutputPath }}' -Force\""
      },
      "id": "e0b8cb55-6d04-4b5c-a5b6-68b209e51ea7",
      "name": "Package SCORM ZIP",
      "type": "n8n-nodes-base.executeCommand",
      "typeVersion": 1,
      "position": [
        660,
        300
      ]
    },
    {
      "parameters": {
        "fileSelector": "={{ $('Set Course Configuration').item.json.zipOutputPath }}",
        "options": {}
      },
      "id": "18f972b9-e137-4d92-9111-e77ad45e7f1e",
      "name": "Read ZIP from Disk",
      "type": "n8n-nodes-base.readWriteFile",
      "typeVersion": 1,
      "position": [
        880,
        300
      ]
    },
    {
      "parameters": {
        "method": "POST",
        "url": "=https://cloud.scorm.com/api/v2/courses/importJobs/upload?courseId={{ $('Set Course Configuration').item.json.courseId }}",
        "sendHeaders": true,
        "headerParameters": {
          "parameters": [
            {
              "name": "Authorization",
              "value": "=Basic {{ Buffer.from($('Set Course Configuration').item.json.scormAppId + ':' + $('Set Course Configuration').item.json.scormSecretKey).toString('base64') }}"
            }
          ]
        },
        "sendBody": true,
        "contentType": "multipart-form-data",
        "bodyParameters": {
          "parameters": [
            {
              "parameterType": "formBinaryData",
              "name": "file",
              "inputDataFieldName": "data"
            }
          ]
        },
        "options": {}
      },
      "id": "cc074e2d-327c-47bc-ae51-40e9f1cf98f0",
      "name": "Upload to SCORM Cloud API v2",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.2,
      "position": [
        1100,
        300
      ]
    },
    {
      "parameters": {
        "amount": 5,
        "unit": "seconds"
      },
      "id": "b1b7ce3a-3d23-41bb-b054-d83ee6ae1a44",
      "name": "Wait for Processing",
      "type": "n8n-nodes-base.wait",
      "typeVersion": 1.1,
      "position": [
        1320,
        300
      ],
      "webhookId": "9b122709-3221-4ebc-a81d-6512ce24ff88"
    },
    {
      "parameters": {
        "method": "GET",
        "url": "=https://cloud.scorm.com/api/v2/courses/importJobs/{{ $('Upload to SCORM Cloud API v2').item.json.result }}",
        "sendHeaders": true,
        "headerParameters": {
          "parameters": [
            {
              "name": "Authorization",
              "value": "=Basic {{ Buffer.from($('Set Course Configuration').item.json.scormAppId + ':' + $('Set Course Configuration').item.json.scormSecretKey).toString('base64') }}"
            }
          ]
        },
        "options": {}
      },
      "id": "422e1327-0cbe-4fc4-bbdc-e875db0c6ff2",
      "name": "Check Import Job Status",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.2,
      "position": [
        1540,
        300
      ]
    }
  ],
  "connections": {
    "When clicking ‘Test workflow’": {
      "main": [
        [
          {
            "node": "Set Course Configuration",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Set Course Configuration": {
      "main": [
        [
          {
            "node": "Package SCORM ZIP",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Package SCORM ZIP": {
      "main": [
        [
          {
            "node": "Read ZIP from Disk",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Read ZIP from Disk": {
      "main": [
        [
          {
            "node": "Upload to SCORM Cloud API v2",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Upload to SCORM Cloud API v2": {
      "main": [
        [
          {
            "node": "Wait for Processing",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Wait for Processing": {
      "main": [
        [
          {
            "node": "Check Import Job Status",
            "type": "main",
            "index": 0
          }
        ]
      ]
    }
  },
  "active": false,
  "settings": {
    "executionOrder": "v1"
  }
}
Hardware & Performance BenchmarksSpecificationStandard Definition (SD / 480p)High Definition (HD / 720p)Keyframe Resolution$576 \times 320$$1024 \times 576$Diffusion Steps (T2I / I2V)20 / 20 steps30 / 35 stepsPeak VRAM Usage~6.5 GB – 8.5 GB~16 GB – 22 GBGeneration Time / Scene~35 – 60 seconds~2.5 – 4.0 minutesRecommended GPURTX 3060 / 4060 / T4 / L4RTX 3090 / 4090 / A5000 / A100TroubleshootingCUDA Out of Memory (OOM): Ensure RENDER_WIDTH and RENDER_HEIGHT are set to 576 and 320 in .env. pipeline.py will also automatically step down resolution and clear the CUDA cache on memory errors.Ollama Connection Refused: Ensure the Ollama daemon is running with ollama serve or systemctl status ollama.SCORM Cloud Upload Fails (401 Unauthorized): Verify that scormAppId and scormSecretKey in the Set Course Configuration node are valid credentials generated from SCORM Cloud App Management.FFmpeg Concat Errors: Check that relative file paths inside ./render_output/concat_list.txt exist and are accessible.LicenseThis project is licensed under the Apache 2.0 License.
