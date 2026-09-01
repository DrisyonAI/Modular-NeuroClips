# 📏 GSD Standards & Definition of Done (DoD)

## 1. Definition of Done (DoD)
A feature or pull request is considered **DONE** only when:
1. **Contract Validity**: All schemas in `src/contracts/` pass Pydantic validation with 100% strict typing.
2. **Zero Audio-Video Desync**: Audio files synthesized by `VoiceDirectorAgent` must be duration-probed via `ffprobe` and match video frame counts within 100ms tolerance.
3. **SCORM Conformance**: Generated `.zip` packages must contain valid `imsmanifest.xml` and pass SCORM 1.2 / 2004 CMI validation (`cmi.core.score.raw`, `cmi.core.lesson_status`).
4. **Code Quality**: Clean passing imports, zero deprecated package warnings, and CodeRabbit review compliance.
5. **Production VPS Health**: Container launches cleanly in rootless Docker and returns `HTTP 200 OK` on health checks.

## 2. Multi-Agent Directorial Rules
- Never pass raw, un-parsed user queries directly to TTS engines.
- `ScriptwriterAgent` must always decompose content into 1–16 pedagogical scene chunks with prosody cues (`[pause 500ms]`, `[emphasis]`, `[protip]`).
- Visual prompts must contain demographic continuity tokens matching the selected presenter identity.
