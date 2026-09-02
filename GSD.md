# 🎯 Get Stuff Done (GSD) Framework: Modular-NeuroClips Studio

Welcome to the **GSD Workflow** for Modular-NeuroClips Studio. This project follows strict autonomous agent invariants, contract-driven architecture, and rapid deployment cadences.

---

## ⚡ Quick Navigation
* [Project Overview & Architectural Pillars](.gsd/PROJECT.md)
* [Development Roadmap & Active Sprints](.gsd/ROADMAP.md)
* [Engineering Standards & Definition of Done](.gsd/STANDARDS.md)
* [Multi-Agent Orchestration Specification](MULTI_AGENT_ORCHESTRATION_SPEC.md)

---

## 🚀 Key Commands

### 1. Run Control Plane Locally
```bash
# Start FastAPI web studio
python -m uvicorn src.dashboard:app --host 0.0.0.0 --port 8000 --reload
```

### 2. Verify Multi-Agent Contracts & Quiz Engine
```bash
# Verify contract models and question bank integrity
python -c "from src.contracts import PERSONA_CATALOG; from src.quiz_engine import QuizEngine; qe = QuizEngine(); print(f'Personas: {len(PERSONA_CATALOG)} | Modules: {len(qe.get_modules_summary())}')"
```

### 3. Deploy to Production VPS
```bash
# Deploy with Docker Compose
docker compose build && docker compose up -d
```
