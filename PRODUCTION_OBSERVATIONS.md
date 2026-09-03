# Production-Grade Readiness Audit & Engineering Roadmap
**Project:** Modular-NeuroClips (Autonomous Video Course & SCORM Engine)  
**Date:** September 2026  
**Status:** Advanced Functional Pilot / Workstation Prototype  

---

## 1. Executive Summary

Modular-NeuroClips has successfully achieved **high-fidelity functional maturity** for role-based multi-agent course synthesis, neural voice mastering, keyframe directing, and SCORM 1.2/2004 packaging with external video attachments. 

However, moving from a **local workstation / single-node pilot** to an **enterprise-hardened SaaS production system** requires addressing key architectural boundaries across persistence, asynchronous concurrency, cloud storage, authentication, and GPU infrastructure.

---

## 2. Readiness Matrix: Current State vs. Production Grade

| Domain | Current Implementation (Pilot Grade) | Enterprise Production Grade Target | Readiness Gap / Risk |
| :--- | :--- | :--- | :--- |
| **Data Persistence** | In-memory dictionary (`JOBS_DB`), local JSON files (`identities/`, `nipuna_item_bank.json`) | Relational database (PostgreSQL / Supabase) with ACID transactions & migrations | **High**: Server restarts purge active job history and telemetry logs. |
| **Multi-Tenancy & Auth** | Unauthenticated, open control plane on `localhost:8000` | OAuth2 / OIDC / SAML SSO, JWT tokens, RBAC (Role-Based Access Control) | **Critical**: Any client on network can trigger GPU jobs, delete media, or alter avatars. |
| **Task Queue & Async Workers** | Local FastAPI `BackgroundTasks` executing on the main application process | Distributed task queue (**Celery + Redis** or **Temporal.io**) with decoupled worker pools | **High**: Long-running Remotion / Diffusion jobs can choke the API event loop and fail ungracefully. |
| **Media & Asset Storage** | Local filesystem (`./render_output`, `./assets_library`, `./exports`) | Object Storage (**AWS S3**, **Cloudflare R2**, **Google Cloud Storage**) + CDN | **Medium**: Local disk fills rapidly with 1080p MP4 exports and ZIP archives; no horizontal scalability. |
| **GPU & Compute Orchestration** | Single local CUDA GPU / CPU fallback via `VRAMGuard` | Auto-scaling serverless GPU clusters (**Modal**, **RunPod**, **Triton**, **SageMaker**) | **High**: Concurrency is limited to 1 generation job at a time to prevent CUDA Out-Of-Memory (OOM). |
| **SCORM & LMS Conformance** | Compliant XML manifest, ADLCP namespaces, HTML5 player with SCORM 1.2 CMI data model | SCORM 1.2, SCORM 2004 4th Ed, xAPI (Experience API / Tin Can), and LTI 1.3 | **Low**: Packaging and player tracking are fully spec-compliant and verified. |
| **Observability & Health** | In-process system telemetry via Server-Sent Events (`/metrics/stream`) | OpenTelemetry, Prometheus metrics, structured JSON logging, Sentry error tracking | **Medium**: No centralized log aggregation, alert webhooks, or distributed tracing. |

---

## 3. Detailed Architectural Observations

### 3.1 Persistence & Data Model
- **Current State:**
  - Active and historical generation jobs reside in `JOBS_DB: Dict[str, Dict[str, Any]]`.
  - User personas and instructor identities are stored as plain JSON files in `./identities/`.
- **Production Requirements:**
  - Move to an RDBMS (PostgreSQL) with tables: `tenants`, `users`, `jobs`, `scenes`, `assets`, `scorm_packages`, `course_metadata`.
  - Implement soft deletes, audit timestamps (`created_at`, `updated_at`, `deleted_at`), and indexing on `job_id`, `tenant_id`, and `created_at`.

### 3.2 Asynchronous Concurrency & Pipeline Gating
- **Current State:**
  - Video rendering, voice synthesis, and Remotion compilation run in-process via FastAPI's `BackgroundTasks.add_task()`.
  - Simultaneous requests return a HTTP 409 Conflict if a generation job is already active.
- **Production Requirements:**
  - Decouple API web nodes from GPU rendering workers via Redis or RabbitMQ.
  - Implement task priority queues (e.g., fast Voice Auditions on priority queue, 16-scene Remotion renders on standard queue).
  - Implement job heartbeats, automatic retry policies with exponential backoff, and dead-letter queues (DLQ).

### 3.3 Security, Authentication & Input Sanitization
- **Current State:**
  - Endpoints allow file uploads (`/api/v1/assets/upload-video`, `/api/v1/avatar/upload`) with basic file extension filtering.
  - XML escaping for SCORM manifests was recently hardened (`_xml_escape`).
- **Production Requirements:**
  - Enforce upload content inspection (magic byte header validation) and max file size limits (e.g., 500 MB per video).
  - Virus/malware scanning pipeline (ClamAV) for uploaded files before placing in asset library.
  - Rate limiting per API key / IP address via Redis token-bucket algorithm (`slowapi` or Cloudflare WAF).

### 3.4 File Storage & Edge Delivery
- **Current State:**
  - Files are served statically via FastAPI's `StaticFiles` mounting (`/static_renders`, `/static_exports`).
- **Production Requirements:**
  - Upload external videos and rendered outputs directly to S3/R2 with presigned URLs (`PUT` for upload, time-limited `GET` for download).
  - Front video streams with CDN byte-range request streaming (HLS / DASH) instead of raw static file delivery for large courses.

---

## 4. Phase-by-Phase Hardening Roadmap

### Phase 1: Security & Stability (Immediate)
1. **API Authentication:** Add JWT bearer authentication and tenant headers to all API endpoints.
2. **Rate Limiting & Guardrails:** Add upload size limits and request throttling to prevent resource exhaustion.
3. **Database Layer:** Integrate SQLAlchemy / Prisma with PostgreSQL to replace in-memory dictionaries.

### Phase 2: Distributed Execution & Cloud Storage (Near-Term)
1. **Worker Decoupling:** Extract `execute_tracked_generation` and Remotion compilers into Celery / Redis workers.
2. **S3 / R2 Media Storage:** Replace local `./exports` and `./render_output` directories with object storage presigned URLs.
3. **Containerization & CI/CD:** Create multi-stage Dockerfiles separating web API from CUDA rendering workers.

### Phase 3: Enterprise LMS & Analytics (Scale)
1. **xAPI (Tin Can API) & LTI 1.3:** Expand from SCORM 1.2 to live LTI integration directly into Canvas, Blackboard, and Moodle.
2. **Prometheus / Grafana Dashboards:** Expose standard `/metrics` endpoint with GPU utilization, job latency, and error rates.
3. **Automated End-to-End Testing:** Incorporate `test_quality_workflows.py` into GitHub Actions / GitLab CI pipeline.

---

## 5. Verification Checklist

- [x] Role-based modularization (Director, Voice Director, Image Director, SCORM) verified.
- [x] External video ingestion and ZIP bundling validated.
- [x] Manifest hierarchy (`Course` $\rightarrow$ `Module` $\rightarrow$ `Lesson` $\rightarrow$ `Topic`) validated.
- [x] XML escaping and namespace conformance tested.
- [x] Nipuna 224-question fin-tech assessment bank validated.
- [ ] Multi-tenant database integration (Pending Phase 1).
- [ ] Redis / Celery asynchronous queue worker decoupling (Pending Phase 2).
- [ ] Cloud object storage integration (Pending Phase 2).
