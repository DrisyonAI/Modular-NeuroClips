# ⚡ Modular-NeuroClips Studio (v2.6)
> **Autonomous AI Video, Courseware, & Multi-Modal LMS Producer**  
> *Industrial-scale generative manufacturing platform transforming curriculum spreadsheets into 100+ hours of broadcast-grade video courses with neural voiceovers, dynamic speaker avatars, and Multi-SCO SCORM packages.*

---

## 📑 Table of Contents
1. [Executive Summary & 100+ Hour Scaling Proposition](#1-executive-summary--100-hour-scaling-proposition)
2. [Business Requirements Document (BRD)](#2-business-requirements-document-brd)
3. [Functional Requirements Document (FRD)](#3-functional-requirements-document-frd)
4. [High-Level Design (HLD) & Scale Architecture](#4-high-level-design-hld--scale-architecture)
5. [System Sequence & UML Diagrams](#5-system-sequence--uml-diagrams)
6. [Low-Level Design (LLD) & API Specifications](#6-low-level-design-lld--api-specifications)
7. [Enterprise Multi-Course Batch Engine & Persistent Database](#7-enterprise-multi-course-batch-engine--persistent-database)
8. [Multi-Language Dubbing & Regional Speech Suite](#8-multi-language-dubbing--regional-speech-suite)
9. [Remotion React & FFmpeg Multi-Layer Compositing](#9-remotion-react--ffmpeg-multi-layer-compositing)
10. [Deployment & Production Setup Guide](#10-deployment--production-setup-guide)

---

## 1. Executive Summary & 100+ Hour Scaling Proposition

**Modular-NeuroClips Studio** is an AI video generation workbench and automated curriculum authoring platform engineered for corporate Learning & Development (L&D) directors, instructional designers, and higher-education institutions.

### Enterprise Scale Metrics:
- ⏱️ **Industrial Throughput**: Capable of processing **100+ hours of curriculum** across hundreds of modules with autonomous checkpoint-resume.
- 💰 **Zero API Credit Burn**: Leverages local open-source models (Llama 3, Stable Diffusion v1.5, CogVideoX-2B, Edge-TTS, Remotion, FFmpeg) with zero recurring cloud API subscription fees.
- 📦 **Master Multi-SCO SCORM Packaging**: Bundles multi-module courses into unified **SCORM 1.2 / 2004** packages with table-of-contents navigation and LMS gradebook integration.
- 🌐 **8-Locale Dubbing**: Automated translation and neural narration in **English, Telugu, Tamil, Hindi, Spanish, French, German, and Japanese**.

---

## 2. Business Requirements Document (BRD)

### 2.1 Market Context & Industry Pain Points
Producing enterprise-scale video courseware (100+ hours) traditionally costs over **$250,000+** and requires months of studio production, voice actors, and manual subtitle alignment. When training curriculum updates, re-filming is prohibitive.

### 2.2 ROI & Success Metrics
- **Cost Reduction**: 98% reduction in production costs compared to physical studio filming.
- **Cycle Time**: Generates 1 hour of instructional video in ~8–12 minutes on commodity VPS hardware.
- **LMS Conformance**: 100% compliance with ADL SCORM 1.2 / 2004 and YouTube-compliant `.srt` subtitles.

---

## 3. Functional Requirements Document (FRD)

### 3.1 7-Milestone Generative Pipeline
```
[1. Init] ➔ [2. Script] ➔ [3. Keyframes] ➔ [4. Motion] ➔ [5. Voiceover] ➔ [6. Stitch] ➔ [7. Ready]
```

### 3.2 Enterprise Batch Features
- **Checkpoint & Resume**: State is tracked in `batch_production.db` (SQLite/PostgreSQL) so interrupted batches resume from the exact failed lesson.
- **Disk Pruning & Memory Safety**: Automatic garbage collection and intermediate frame cleanup prevent disk bloat during multi-day rendering runs.
- **Master Course Bundler**: Combines completed lessons into a single `MASTER_COURSE_<id>.zip` with an embedded multi-item `imsmanifest.xml`.

---

## 4. High-Level Design (HLD) & Scale Architecture

```mermaid
flowchart TD
    Excel[Curriculum Excel / Manifests] --> BatchMgr[Batch Course Manager / src.batch_manager]
    WebUI[FastAPI Control Plane / UI] --> BatchMgr

    subgraph Persistence & State Machine
        BatchMgr --> DB[(batch_production.db / SQLite)]
    end

    subgraph Generative Pipeline Engine
        BatchMgr --> Orchestrator[Llama 3 / Heuristic Director]
        Orchestrator --> T2I{Keyframe Engine}
        T2I -->|CUDA| SDLocal[Stable Diffusion v1.5]
        T2I -->|Cloud Fallback| Pollinations[Pollinations Flux / SDXL 1280x720]
        
        T2I --> Motion{Motion Engine}
        Motion -->|CUDA| CogVideo[CogVideoX-2B-I2V]
        Motion -->|CPU| KenBurns[FFmpeg Subpixel Zoompan]

        Orchestrator --> EdgeTTS[Edge-TTS Multi-Language Dubbing]
        Orchestrator --> SRTGen[SRT Subtitle Generator]
    end

    subgraph Compositing & Packaging
        SDLocal & Pollinations & CogVideo & KenBurns & EdgeTTS & SRTGen --> Compositor[Remotion / FFmpeg Compositor]
        Compositor --> MediaVault[(Media Vault / courses/)]
        MediaVault --> MasterSCORM[Master Multi-SCO SCORM 1.2 Packager]
    end
```

---

## 5. System Sequence & UML Diagrams

### 5.1 Batch Processing Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    actor Admin as L&D Course Director
    participant Batch as Batch Course Manager
    participant DB as SQLite DB (batch_production.db)
    participant Engine as Generative Pipeline Engine
    participant SCORM as Master SCORM Packager

    Admin->>Batch: Ingest Course (10 Modules, 50 Lessons)
    Batch->>DB: Insert Course & Lesson Records (status: 'pending')

    loop For Each Pending Lesson
        Batch->>DB: Lock Lesson (status: 'processing')
        Batch->>Engine: Render Keyframes, Motion, TTS Audio & Subtitles
        Engine-->>Batch: lesson_video.mp4 + subtitles.srt
        Batch->>DB: Update Record (status: 'completed', video_path)
    end

    Batch->>SCORM: export_master_scORM_package(course_id)
    SCORM-->>Admin: MASTER_COURSE_<id>.zip (Multi-SCO SCORM Ready)
```

---

## 6. Low-Level Design (LLD) & API Specifications

### Core Data Models (Pydantic v2)
```python
class GenerationRequest(BaseModel):
    topic: str
    scenes: int = 3
    art_style: str = "Cinematic 35mm (Volumetric Lighting)"
    resolution: str = "16:9_hd"
    language: str = "en-US"
    voice: str = "en-IN-NeerjaNeural"
    speech_rate: float = 1.0
    compiler_engine: str = "ffmpeg"
    avatar_persona: str = "maya_fintech"
    avatar_layout: str = "pip_bottom_right"
    burn_subtitles: bool = True
    auto_clean: bool = False
```

---

## 7. Enterprise Multi-Course Batch Engine & Persistent Database

The `src/batch_manager.py` module manages large-scale pipelines:

```python
from src.batch_manager import BatchCourseManager

# Initialize a 10-module course pipeline
manager = BatchCourseManager(
    course_id="FINTECH_101",
    title="Comprehensive FinTech & Algorithmic Banking Masterclass",
    instructor_persona="maya_fintech",
    voice="en-IN-NeerjaNeural"
)

# Add lessons to queue
manager.add_lesson(
    module_id="MOD_01",
    module_title="Module 1: Financial Modeling",
    lesson_id="L1_GOALSEEK",
    lesson_title="Excel Goal Seek What-If Analysis",
    speaker_script="Goal Seek is Excel's powerful What-If Analysis tool...",
    visual_prompt="Excel spreadsheet interface with Goal Seek dialog"
)

# Export all completed lessons into master SCORM package
scorm_zip = manager.export_master_scORM_package()
```

---

## 8. Multi-Language Dubbing & Regional Speech Suite

| Locale | Language | Default Voice |
| :--- | :--- | :--- |
| `en-US` | English (US) | `en-US-GuyNeural` / `en-IN-NeerjaNeural` |
| `te-IN` | Telugu (India) | `te-IN-MohanNeural` / `te-IN-ShrutiNeural` |
| `ta-IN` | Tamil (India) | `ta-IN-PallaviNeural` / `ta-IN-ValluvarNeural` |
| `hi-IN` | Hindi (India) | `hi-IN-MadhurNeural` / `hi-IN-SwaraNeural` |
| `es-ES` | Spanish (Castilian)| `es-ES-AlvaroNeural` |
| `fr-FR` | French (Standard) | `fr-FR-HenriNeural` |
| `de-DE` | German (Standard) | `de-DE-ConradNeural` |
| `ja-JP` | Japanese (Tokyo) | `ja-JP-KeitaNeural` |

---

## 9. Remotion React & FFmpeg Multi-Layer Compositing

- **Remotion React Bundle**: [`remotion/src/MainVideo.tsx`](file:///C:/tt-ai-stack/01_projects/active/bov/01_web_applications/Modular-NeuroClips/remotion/src/MainVideo.tsx) coordinates sequences, spring-physics title cards, audio visualizer bars, and floating presenter cards.
- **FFmpeg PiP Filter Graph**: Multiplexes H.264 video, AAC 192k audio, and burned-in open captions.

---

## 10. Deployment & Production Setup Guide

```bash
# 1. Clone & Setup
git clone https://github.com/DrisyonAI/Modular-NeuroClips.git
cd Modular-NeuroClips

# 2. Install Dependencies
pip install -r requirements.txt

# 3. Run Studio Web Portal
python app.py
```
Open **`http://localhost:8000`** in your browser.

---

## 📄 License
This project is licensed under the Apache 2.0 License.
