# High-Level Design (HLD): Custom Voice Cloning & Universal Document Speech Engine

**Project:** Modular-NeuroClips (01_web_applications/Modular-NeuroClips)  
**Author:** Senior Systems & AI Architect  
**Version:** 1.0.0  
**Status:** Approved for Implementation  

---

## 1. Executive Architecture & System Context

The **Voice Director Sub-System** expands from static pre-configured voice profiles into a dynamic, two-way speech studio:
1. **Inbound Speech Ingestion (Voice Cloning)**: Captures user audio from browser microphones or files, processes audio normalizations, and registers immutable persona assets into a local-first catalog with hybrid cloud/offline fallback.
2. **Inbound Content Ingestion (Universal Document-to-Speech)**: Ingests structured and unstructured enterprise documents (`.txt`, `.md`, `.docx`, `.pdf`), applies pedagogical scene decomposition, injects domain pronunciation lexicons, and synthesizes broadcast-grade audio tracks and SCORM packages using any registered voice.

```mermaid
flowchart TD
    subgraph Client["Creator Client / Browser UI"]
        Mic[🎙️ In-Browser MediaRecorder] --> VoiceLab[Voice Director Studio Portal]
        DocUpload[📄 Document Dropzone .txt, .md, .docx, .pdf] --> VoiceLab
    end

    subgraph APILayer["FastAPI Control Plane (src/dashboard.py)"]
        VoiceLab -->|POST /api/v1/voice/clone| CloneEndpoint[Voice Cloning Endpoint]
        VoiceLab -->|POST /api/v1/voice/synthesize-file| FileSpeechEndpoint[Document Speech Endpoint]
        VoiceLab -->|GET /api/v1/voice/custom-personas| CatalogEndpoint[Persona Query Endpoint]
    end

    subgraph IngestionEngines["Domain Ingestion & Processing Engines"]
        CloneEndpoint --> VoiceCloner[Voice Cloner Engine (src/agents/voice_cloner.py)]
        FileSpeechEndpoint --> DocParser[Document Parser & Slicer (src/document_parser.py)]
        DocParser --> LexiconEngine[FinTech & Domain Lexicon (src/lexicon.py)]
    end

    subgraph StorageAndCatalog["Storage & Contracts"]
        VoiceCloner --> AudioVault[(assets_library/voices/)]
        VoiceCloner --> CustomCatalog[(src/contracts/custom_personas.json)]
        CustomCatalog --> PersonaContract[PERSONA_CATALOG (src/contracts/persona.py)]
    end

    subgraph SynthesisAndDelivery["Synthesis & Packaging Layer"]
        LexiconEngine --> VoiceDirector[Voice Director Agent (src/agents/voice_director.py)]
        PersonaContract --> VoiceDirector
        VoiceDirector --> MasterAudio[Master MP3 (-14 LUFS Normalized)]
        VoiceDirector --> Subtitles[Synchronized Subtitles (.srt / .vtt)]
        MasterAudio --> SCORMPackager[SCORM 1.2 / 2004 Packager (src/scorm_packager.py)]
        Subtitles --> SCORMPackager
        SCORMPackager --> OutputArchive[📦 Deployable SCORM ZIP / Media Vault]
    end
```

---

## 2. Key Architectural Decisions & Principles

1. **Local-First & Zero-Cost Default**:
   - Primary cloud provider for voice cloning is ElevenLabs Instant Voice Clone API (`/v1/voices/add`).
   - Offline fallback computes local reference embeddings (`Kokoro` / `XTTS`), ensuring continuous development without mandatory external API keys.
2. **Pedagogical Scene Slicing Boundary**:
   - Long documents are never processed as single monolithic audio blocks. They are broken into 40–80 word segments (20–40 seconds each) to match cognitive load limits and prevent audio drift.
3. **Contract Immutability**:
   - Every cloned voice conforms to the strict `PersonaIdentityContract`. Once created, a custom persona possesses an immutable ID, demographic metadata, speech rate defaults, and voice bindings.
4. **Broadcast Audio Standards**:
   - All master audio tracks pass through an automated FFmpeg EBU R128 loudness normalization filter to guarantee a consistent -14 LUFS output.

---

## 3. Subsystem Breakdown

### 3.1 Voice Cloner Subsystem (`src/agents/voice_cloner.py`)
- **Input**: Raw audio stream or file (`.wav`, `.mp3`, `.ogg`, `.m4a`), user-specified presenter name, gender, and language locale.
- **Audio Conditioning**:
  - Sample rate conversion to 44.1kHz mono WAV.
  - High-pass noise filter (`highpass=f=80, lowpass=f=12000`) to remove room hum.
  - Duration verification: 10s minimum, 300s maximum.
- **Registration**:
  - Cloud: Submits to ElevenLabs API $\rightarrow$ returns `voice_id`.
  - Local: Saves normalized sample as speaker reference profile in `assets_library/voices/`.
  - Catalog: Appends persona record to `src/contracts/custom_personas.json`.

### 3.2 Document Parser Subsystem (`src/document_parser.py`)
- **Format Support**:
  - Plain Text (`.txt`) and Markdown (`.md`): Native UTF-8 parsing with header/bullet cleanup.
  - Word (`.docx`): Extracted using `python-docx` or zip XML paragraph parsing.
  - PDF (`.pdf`): Extracted using `pypdf` / regex line normalization.
- **Chunking Algorithm**:
  - Identifies natural section headers (`#`, `##`, `Chapter`, `Module`).
  - Groups sentences into semantic scenes of 40–80 words.
  - Generates a typed `ScriptContract` compatible with the Director Agent.

---

## 4. Non-Functional Requirements (NFRs)

| Attribute | Criteria | Verification Method |
| :--- | :--- | :--- |
| **Latency** | Document parsing & slicing < 1.5s for 20-page document (up to 10k words). | Unit benchmark in test suite. |
| **Throughput** | File uploads supported up to 25MB. Audio sample uploads up to 50MB. | FastAPI request body limits. |
| **Reliability** | Zero total failures: If ElevenLabs API is down or key is absent, fallback to local reference engine or Edge-TTS. | Fallback exception handler testing. |
| **Audio Quality** | Signal-to-noise check; final loudness enforced to -14 LUFS (+/- 0.5 LUFS). | FFprobe / FFmpeg `loudnorm` filter pass. |
| **Security** | Strict file extension whitelist; path-traversal prevention on custom persona IDs. | Regex validation on filenames & IDs. |
