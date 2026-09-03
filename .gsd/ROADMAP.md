# 🗺️ GSD Development Roadmap

## Phase 1: Generative Foundation (Completed ✅)
- [x] End-to-end 7-milestone generative pipeline (Init, Script, Keyframe, Motion, Voiceover, Stitch, Ready).
- [x] Remotion React & FFmpeg subpixel KenBurns zoompan compositing.
- [x] Dual Web UI Portal + REST API control plane on FastAPI.

## Phase 2: Enterprise Batch & Multi-Format Audio (Completed ✅)
- [x] SQLite/Postgres persistent state machine (`batch_production.db`) with checkpoint-resume.
- [x] Document Ingestion (`.txt`, `.md`, `.srt`, `.vtt`, `.json`) for automated script cleaning.
- [x] Multi-format audio master exporter (MP3, WAV 44.1kHz, M4A/AAC, OGG, FLAC) with synced `.srt` subtitles.
- [x] Rootless Docker production deployment on Ubuntu VPS.

## Phase 3: Director-Led Multi-Agent Architecture & Quizzing (Completed ✅)
- [x] Hierarchical multi-agent topology (`DirectorAgent`, `ScriptwriterAgent`, `VoiceDirectorAgent`, `ImageGeneratorAgent`).
- [x] Pydantic `PersonaIdentityContract` catalog (Maya, Alex, Elena, David, Rajesh).
- [x] 224-question assessment engine (`QuizEngine`) across Modules 1–7 from Nipuna Course v3.
- [x] Dedicated **Voice Director Studio** with AI Prompt Expansion, prosody controls, and multi-format audition player.
- [x] Dedicated **Image Director Studio** with visual keyframe synthesis, style presets, and continuity anchors.
- [x] Dedicated **Custom SCORM & LMS Generator** with external video ingestion, curriculum metadata mapping, and CMI data model inspector.
- [x] Automated multi-agent workflow test suite (`test_quality_workflows.py`).

## Phase 4: Next-Horizon Features (In Progress 🚀)
- [ ] **Interactive Branching Scenarios**: Decision-tree module execution based on learner quiz performance.
- [ ] **Headless xAPI (Tin Can) Dispatch**: Real-time statement streaming (`actor`, `verb`, `object`, `result`) to enterprise LRS (Learning Record Stores).
- [ ] **Semantic B-Roll Auto-Matcher**: AI keyword trigger to automatically insert matching screen captures from Video Asset Vault.
