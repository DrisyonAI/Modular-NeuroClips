# 🎯 GSD Project Overview: Modular-NeuroClips Studio (v2.6)

## 1. Mission Statement
Modular-NeuroClips Studio is an industrial-scale generative production engine engineered to autonomously transform raw curriculum spreadsheets and user prompts into broadcast-grade video courses, high-fidelity neural audio masters, and interactive SCORM 1.2 / 2004 e-learning packages with zero human editing required.

## 2. Core Architectural Pillars
1. **Director-Led Multi-Agent Topology**:
   - Master `DirectorAgent` orchestrates specialized sub-agents (`ScriptwriterAgent`, `VoiceDirectorAgent`, `ImageGeneratorAgent`).
   - Communication is strictly governed by strongly typed Pydantic contracts (`PersonaIdentityContract`, `ScriptContract`, `VoiceContract`, `ImageContract`).

2. **Persona & Demographic Consistency**:
   - Demographic visual anchors, industry domains, and authentic regional voice profiles are bound to canonical identities (Maya Sharma, Alex Vance, Elena Rostova, David Kim, Rajesh Patel).

3. **Exact AV Synchronization (Zero Drift Rule)**:
   - Voiceovers are probed with `ffprobe` to determine exact measured durations in milliseconds.
   - Video scene frame counts are locked 1:1 to audio durations, preventing frozen frames or clipped speech.

4. **LMS & Assessment Conformance**:
   - Ingests certified 224-item question banks from Nipuna FinTech curriculum.
   - Compiles interactive HTML5 SCORM players reporting `cmi.core.score.raw` and `cmi.core.lesson_status` (`passed`/`incomplete`).

## 3. Tech Stack
- **Backend & Control Plane**: Python 3.12, FastAPI, Uvicorn, Pydantic v2
- **Audio & Speech Engine**: Edge-TTS, ElevenLabs API, FFmpeg (MP3, WAV, M4A, OGG, FLAC)
- **Video & Visual Synthesis**: Stable Diffusion v1.5 / SDXL, CogVideoX-2B, Remotion React, FFmpeg subpixel zoompan
- **Packaging & Delivery**: ADL SCORM 1.2, SCORM 2004 4th Edition, HTML5, Tailwind CSS
