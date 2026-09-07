# NeuroClips SCORM Framework

## Executive recommendation

Build the package as **one SCORM 1.2 SCO containing a data-driven single-page learner application**. Represent modules and lessons inside the application, not as separate SCORM items.

This is the most reliable architecture for the requested experience: continuous course navigation, unified progress, robust resume, cross-LMS compatibility, and an extensible path to SCORM 2004. A multi-SCO package would improve LMS-level lesson reporting, but creates unreliable cross-SCO navigation and suspend-data behavior, especially on older LMSs. The internal state model should still treat each lesson as a distinct learning unit.

The package is self-contained, uses relative URLs, has no backend dependency, and falls back to in-memory state when the SCORM API is unavailable. Local storage may be used only as a non-authoritative convenience fallback; LMS `cmi.suspend_data` remains authoritative.

## Phase 1 — Architecture

```text
course.json + assets/
        |
        v
Course schema validator
        |
        v
Asset/path validator + manifest builder
        |
        v
Static SCORM package
  index.html
  imsmanifest.xml
  data/course.json
  css/app.css
  js/{scorm,store,quiz,components,player}.js
  assets/**
        |
        v
SCORM 1.2 API adapter
        |
        v
LMS
```

### Separation of concerns

- **Schema:** versioned course contract and component definitions.
- **Validator:** IDs, required fields, supported component types, references, asset paths, and quiz integrity.
- **Asset manager:** copies files, normalizes relative paths, detects duplicates, and reports missing optional assets.
- **Renderer:** renders only defined content blocks through a component registry.
- **Navigation engine:** calculates previous/next units and module boundaries.
- **Progress engine:** computes lesson, module, and course percentages.
- **Completion engine:** evaluates `view`, `video`, `interaction`, `quiz`, `quiz_pass`, and `all_required_components`.
- **Quiz engine:** attempts, scoring, feedback, retries, and pass/fail state.
- **SCORM adapter:** API discovery, safe calls, error handling, commit, finish, and time conversion.
- **State store:** versioned serializable learner state and migration hooks.
- **Package builder:** copies runtime files, writes JSON and manifest, validates, and creates ZIP.

## Phase 2 — Data model

### Example `course.json`

```json
{
  "schemaVersion": "1.0",
  "course": {
    "id": "course-001",
    "version": "1.0.0",
    "title": "AI-Powered HR",
    "description": "A practical introduction to AI-assisted HR workflows.",
    "thumbnail": "assets/images/course.jpg",
    "durationMinutes": 150,
    "audience": "HR professionals, recruiters, and people managers",
    "learningObjectives": [
      "Explain where AI supports HR work",
      "Apply a structured screening workflow",
      "Evaluate AI output with human judgment"
    ],
    "settings": {
      "sequentialModules": false,
      "sequentialLessons": false,
      "showResumePrompt": true,
      "courseCompletion": "all_lessons",
      "autosaveSeconds": 10
    },
    "modules": [
      {
        "id": "module-1",
        "number": 1,
        "title": "Introduction to AI",
        "description": "Core concepts and responsible use.",
        "durationMinutes": 45,
        "lessons": [
          {
            "id": "lesson-1-1",
            "number": "1.1",
            "title": "What is AI?",
            "description": "A short foundation lesson.",
            "durationMinutes": 15,
            "learningMode": "Concept + reading",
            "objectives": ["Define AI in practical terms"],
            "video": {
              "src": "assets/videos/intro.mp4",
              "poster": "assets/images/intro.jpg",
              "captions": "assets/captions/intro.vtt",
              "required": false,
              "completionThreshold": 0.9
            },
            "content": [
              {"type": "heading", "level": 2, "text": "Why it matters"},
              {"type": "paragraph", "text": "AI can support repetitive work while people retain judgment."},
              {"type": "callout", "variant": "key", "title": "Key learning", "text": "AI augments people; it does not remove accountability."},
              {"type": "list", "style": "unordered", "items": ["Search", "Summarize", "Draft"]},
              {"type": "table", "caption": "Workflow", "headers": ["Stage", "Human role"], "rows": [["Prepare", "Set criteria"], ["Evaluate", "Check evidence"]]}
            ],
            "interactions": [
              {"id": "int-1", "type": "accordion", "title": "Explore examples", "items": [{"title": "Recruitment", "content": "Use structured criteria."}]}
            ],
            "quiz": {
              "id": "quiz-1-1",
              "passingScore": 70,
              "maxAttempts": 3,
              "allowRetry": true,
              "questions": [
                {"id": "q-1", "type": "single", "text": "What is AI's appropriate role?", "options": ["Replace judgment", "Support repetitive work", "Remove interviews", "Hide decisions"], "answer": 1, "feedback": "AI should support, not replace, accountable judgment."}
              ]
            },
            "completion": {"type": "quiz_pass", "requiredScore": 70}
          }
        ]
      }
    ]
  }
}
```

### Supported content blocks

`heading`, `paragraph`, `richText` (sanitized before rendering), `list`, `image`, `audio`, `table`, `callout`, `example`, `definition`, `embed` (allowlist only), and `divider`.

### Supported interactions

`accordion`, `tabs`, `flashcards`, `reveal`, `scenario`, `hotspot`, `matching`, `ordering`, and `knowledge_check`. Each component must have a stable ID and expose `isComplete()` plus serializable state.

### State model

```json
{
  "schemaVersion": 1,
  "courseId": "course-001",
  "currentModuleId": "module-1",
  "currentLessonId": "lesson-1-1",
  "startedAt": "2026-09-07T06:53:00.000Z",
  "lastSavedAt": "2026-09-07T07:00:00.000Z",
  "lessons": {
    "lesson-1-1": {
      "status": "completed",
      "visited": true,
      "timeSeconds": 420,
      "videoWatchedRatio": 0.94,
      "interactions": {"int-1": {"opened": true}},
      "quiz": {"attempts": 1, "bestScore": 80, "passed": true, "answers": {"q-1": 1}}
    }
  }
}
```

Use compact keys and bounded lengths because SCORM 1.2 suspend-data capacity varies by LMS. Do not store raw lesson content in suspend data.

## Phase 3 — SCORM strategy

### Manifest strategy

Use one organization and one SCO:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="neuroclips-course-001" version="1.0"
 xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2"
 xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
 xsi:schemaLocation="http://www.imsproject.org/xsd/imscp_rootv1p1p2 ims_xml.xsd http://www.adlnet.org/xsd/adlcp_rootv1p2 adlcp_rootv1p2.xsd">
 <metadata><schema>ADL SCORM</schema><schemaversion>1.2</schemaversion></metadata>
 <organizations default="ORG-1">
  <organization identifier="ORG-1" structure="hierarchical">
   <title>AI-Powered HR</title>
   <item identifier="ITEM-COURSE" identifierref="SCO-COURSE"><title>AI-Powered HR</title></item>
  </organization>
 </organizations>
 <resources>
  <resource identifier="SCO-COURSE" type="webcontent" adlcp:scormtype="sco" href="index.html">
   <file href="index.html"/><file href="css/app.css"/><file href="js/scorm.js"/><file href="js/store.js"/><file href="js/player.js"/><file href="data/course.json"/>
  </resource>
 </resources>
</manifest>
```

A builder should generate the complete file list, including assets, rather than use the abbreviated example above. Use SCORM 1.2 API names exactly: `LMSInitialize`, `LMSFinish`, `LMSGetValue`, `LMSSetValue`, `LMSCommit`, `LMSGetLastError`, `LMSGetErrorString`, and `LMSGetDiagnostic`.

### Mapping

| Internal value | SCORM 1.2 value |
|---|---|
| Not started | `cmi.core.lesson_status = not attempted` |
| In progress | `incomplete` |
| Completed without scored assessment | `completed` |
| Passed assessment | `passed` |
| Failed after final attempt | `failed` |
| Best quiz score | `cmi.core.score.raw` |
| Score bounds | `cmi.core.score.min=0`, `cmi.core.score.max=100` |
| Current unit | `cmi.core.lesson_location` |
| Serialized state | `cmi.suspend_data` |
| Session duration | `cmi.core.session_time` |

Do not set `passed` until the configured final/course assessment passes. If the course has no scored assessment, use `completed`. The one-SCO model gives reliable resume because the LMS resumes one location and one suspend-data record.

## Phase 4 — Runtime

On startup:

1. Discover the SCORM API by walking `window.parent` and `window.opener` with a bounded loop.
2. Call `LMSInitialize("")`.
3. Read `cmi.suspend_data`, `cmi.core.lesson_location`, and `cmi.core.lesson_status`.
4. Validate and migrate the state.
5. Load the course JSON.
6. Show a resume prompt when a saved lesson exists.
7. Render the course home or lesson player.

On every meaningful event and at the configured interval:

- Update state.
- Calculate progress.
- Serialize compact JSON.
- Call `LMSSetValue` for location, status, score, and suspend data.
- Call `LMSCommit("")`.

On unload/pagehide:

- Calculate elapsed session time.
- Save state.
- Call `LMSCommit("")`.
- Call `LMSFinish("")` once.

The runtime must guard against duplicate initialization and finishing. When the API is unavailable, show a non-blocking “LMS connection unavailable” banner and continue in preview mode.

### Completion evaluation

- `view`: first meaningful render marks complete.
- `video`: video ratio must reach threshold.
- `interaction`: all required interaction IDs must report complete.
- `quiz`: quiz submitted, regardless of pass.
- `quiz_pass`: quiz submitted and score meets `requiredScore`.
- `all_required_components`: every required video, interaction, reading acknowledgement, and quiz requirement passes.

Progression is separate from completion. A course can permit free navigation while still requiring completion before the course status becomes completed.

## Phase 5 — UI

### Screens

1. **Course home:** hero, title, description, audience, duration, objectives, overall progress, Start/Continue button, module cards.
2. **Module view:** module metadata, completion percentage, lesson cards, state badges, durations, and lesson selection.
3. **Lesson player:** breadcrumb, lesson title, duration, learning mode, target audience/objectives, progress rail, conditional content sections, video, interaction cards, quiz, completion state, and previous/next controls.
4. **Completion view:** final score if applicable, completed modules, restart/review controls, and LMS-recorded completion message.

### Component hierarchy

```text
AppShell
 ├─ Header
 ├─ ProgressBar
 ├─ CourseHome
 │   └─ ModuleCard
 │       └─ LessonRow
 ├─ ModuleView
 └─ LessonPlayer
     ├─ Breadcrumb
     ├─ LessonMeta
     ├─ VideoBlock
     ├─ ContentRenderer
     ├─ InteractionRenderer
     ├─ QuizBlock
     └─ LessonNavigation
```

Use semantic landmarks, keyboard-operable controls, visible focus, captions, heading hierarchy, status text with `aria-live`, and high contrast. Sanitize rich text with an allowlist parser; never execute content-provided scripts. Permit only `https:` and package-relative media URLs, and allow iframes only from an explicit domain list.

## Phase 6 — Package builder

Recommended repository:

```text
neuroclips-scorm/
├─ package.json
├─ src/
│  ├─ runtime/
│  │  ├─ index.html
│  │  ├─ css/app.css
│  │  └─ js/{scorm,store,components,quiz,player}.js
│  └─ builder/
│     ├─ build.js
│     ├─ validate.js
│     ├─ schema.js
│     └─ manifest.js
├─ examples/course.json
├─ course-source/assets/
├─ tests/
└─ dist/
```

### Build commands

```bash
npm install
npm run validate -- ./examples/course.json ./course-source/assets
npm run build -- ./examples/course.json ./course-source/assets ./dist/neuroclips-course.zip
npm test
```

### Minimal builder implementation (`src/builder/build.js`)

```js
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { validateCourse, collectAssets } from './validate.js';
import { makeManifest } from './manifest.js';

const exec = promisify(execFile);
const [, , courseFile, assetDir, outputZip] = process.argv;
if (!courseFile || !assetDir || !outputZip) throw new Error('Usage: node build.js course.json assets output.zip');

const course = JSON.parse(await fs.readFile(courseFile, 'utf8'));
const report = await validateCourse(course, assetDir);
if (!report.valid) { console.error(JSON.stringify(report, null, 2)); process.exit(1); }

const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'neuroclips-'));
await fs.cp('src/runtime', temp, { recursive: true });
await fs.mkdir(path.join(temp, 'data'), { recursive: true });
await fs.writeFile(path.join(temp, 'data/course.json'), JSON.stringify(course, null, 2));
await fs.cp(assetDir, path.join(temp, 'assets'), { recursive: true });
await fs.writeFile(path.join(temp, 'imsmanifest.xml'), makeManifest(course, report.files));
await fs.mkdir(path.dirname(outputZip), { recursive: true });
await exec(process.platform === 'win32' ? 'tar.exe' : 'zip', process.platform === 'win32'
  ? ['-a', '-c', '-f', path.resolve(outputZip), '-C', temp, '.']
  : ['-qr', path.resolve(outputZip), '.'], { cwd: temp });
console.log(JSON.stringify({ valid: true, outputZip, files: report.files.length }, null, 2));
```

For maximum portability, use a ZIP library such as ` yazl` or `archiver` instead of relying on a platform command. The package root must contain `imsmanifest.xml`, not a nested top-level directory.

### Manifest generator (`src/builder/manifest.js`)

```js
const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
export function makeManifest(course, files) {
  const c = course.course;
  const fileXml = ['index.html','css/app.css','js/scorm.js','js/store.js','js/components.js','js/quiz.js','js/player.js','data/course.json', ...files]
    .filter((v, i, a) => a.indexOf(v) === i)
    .map(f => `<file href="${esc(f)}"/>`).join('');
  return `<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="${esc(c.id)}" version="${esc(c.version || '1.0.0')}" xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2" xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.imsproject.org/xsd/imscp_rootv1p1p2 ims_xml.xsd http://www.adlnet.org/xsd/adlcp_rootv1p2 adlcp_rootv1p2.xsd"><metadata><schema>ADL SCORM</schema><schemaversion>1.2</schemaversion></metadata><organizations default="ORG-1"><organization identifier="ORG-1"><title>${esc(c.title)}</title><item identifier="ITEM-COURSE" identifierref="SCO-COURSE"><title>${esc(c.title)}</title></item></organization></organizations><resources><resource identifier="SCO-COURSE" type="webcontent" adlcp:scormtype="sco" href="index.html">${fileXml}</resource></resources></manifest>`;
}
```

## Phase 7 — Validation

Validation must check:

- JSON parses and schema version is supported.
- Course, module, lesson, interaction, quiz, and question IDs are unique.
- Required titles and arrays exist.
- Completion types and component types are supported.
- Quiz answers are valid for their question type.
- Referenced local assets exist and stay inside the source asset directory.
- No duplicate normalized asset paths exist.
- No absolute URLs are used for core assets.
- Runtime files exist.
- Manifest XML parses and every manifest file exists.
- Internal links resolve.

### Validator skeleton

```js
import fs from 'node:fs/promises';
import path from 'node:path';
const types = new Set(['heading','paragraph','richText','list','image','audio','table','callout','example','definition','embed','divider']);
const completions = new Set(['view','video','interaction','quiz','quiz_pass','all_required_components']);
export async function validateCourse(doc, assetDir) {
  const errors = [], warnings = [], ids = new Set(), files = new Set();
  const c = doc?.course;
  if (doc?.schemaVersion !== '1.0') errors.push('Unsupported schemaVersion');
  if (!c?.id || !c?.title || !Array.isArray(c.modules)) errors.push('course.id, course.title and course.modules are required');
  const addId = (id, label) => { if (!id) errors.push(`${label} has no id`); else if (ids.has(id)) errors.push(`Duplicate id: ${id}`); else ids.add(id); };
  for (const m of c?.modules || []) { addId(m.id, 'module'); for (const l of m.lessons || []) { addId(l.id, 'lesson'); if (l.completion && !completions.has(l.completion.type)) errors.push(`Unsupported completion: ${l.completion.type}`); for (const b of l.content || []) if (!types.has(b.type)) errors.push(`Unsupported content type: ${b.type}`); if (l.video?.src) files.add(l.video.src); if (l.video?.poster) files.add(l.video.poster); if (l.video?.captions) files.add(l.video.captions); for (const q of l.quiz?.questions || []) addId(q.id, 'question'); } }
  for (const f of files) { if (f.startsWith('http') || path.isAbsolute(f) || f.includes('..')) errors.push(`Unsafe asset path: ${f}`); else { try { await fs.access(path.join(assetDir, f.replace(/^assets\//, ''))); } catch { warnings.push(`Missing optional asset: ${f}`); } } }
  return { valid: errors.length === 0, errors, warnings, files: [...files] };
}
export function collectAssets() { return []; }
```

In production, replace the skeleton with JSON Schema validation (Ajv), XML parsing, MIME checks, and ZIP inspection. Missing optional media should be a warning; missing required media should be an error.

## Phase 8 — Testing

Use automated unit tests plus a real-LMS smoke matrix.

| Test | Expected result |
|---|---|
| Text-only lesson | No empty video block; view/read completion works |
| Video lesson | Poster, captions, error fallback, threshold tracking |
| Lesson with no quiz | No quiz UI; configured completion still works |
| Quiz lesson | Score, feedback, pass/fail and status update |
| Failed quiz | Retry follows `maxAttempts`; final failure blocks when configured |
| Passed quiz | Lesson completes and Next becomes available |
| Retry | Answers reset or retain according to policy; best score retained |
| Interaction | Component state serializes and required interaction completes |
| Multiple modules | Correct module percentages and boundaries |
| Sequential off | Available lessons can be selected |
| Sequential on | Locked lesson explains prerequisite |
| Resume | Location, lesson status, quiz state, and interaction state restore |
| Close/reopen | Suspend data is committed before finish |
| Course completion | Final status is `completed` or `passed` as configured |
| Missing optional asset | Warning plus graceful placeholder |
| Missing required asset | Build fails with actionable report |
| SCORM unavailable | Preview mode, no fatal crash |
| LMS error | Error banner/log; learner can continue where safe |
| Mobile/keyboard | Layout and controls remain usable |
| XSS payload | Tags/attributes/scripts are removed or escaped |

For LMS testing, import into Moodle, SCORM Cloud, and at least one target corporate LMS. Test fresh launch, suspend/resume, reopening after `LMSFinish`, score reporting, completion, quiz retries, and package root structure.

## Runtime implementation notes

### SCORM adapter contract

```js
export class Scorm12 {
  constructor(win = window) { this.win = win; this.api = null; this.initialized = false; this.finished = false; }
  findApi() { let w = this.win, n = 0; while (w && n++ < 8) { if (w.API) return w.API; if (w.parent === w) break; w = w.parent; } return null; }
  init() { this.api = this.findApi(); if (!this.api) return false; this.initialized = this.api.LMSInitialize('') === 'true'; return this.initialized; }
  get(k) { return this.initialized ? this.api.LMSGetValue(k) : ''; }
  set(k, v) { return this.initialized && this.api.LMSSetValue(k, String(v)) === 'true'; }
  commit() { return this.initialized && this.api.LMSCommit('') === 'true'; }
  finish() { if (!this.initialized || this.finished) return true; this.commit(); this.finished = true; return this.api.LMSFinish('') === 'true'; }
  error() { return this.initialized ? { code: this.api.LMSGetLastError(), text: this.api.LMSGetErrorString(this.api.LMSGetLastError()), diagnostic: this.api.LMSGetDiagnostic('') } : null; }
}
```

### Compact state precautions

- Keep `suspend_data` under a configurable budget, default 3500 bytes.
- Store IDs and scalar values, not content.
- Prune old answer details if the serialized state exceeds the budget.
- Always include a state version and migrate older versions.
- Commit after completion, quiz submission, navigation, and periodic autosave.

## Phase 9 — Final deliverable plan

The production repository should include:

```text
src/runtime/index.html
src/runtime/css/app.css
src/runtime/js/scorm.js
src/runtime/js/store.js
src/runtime/js/components.js
src/runtime/js/quiz.js
src/runtime/js/player.js
src/builder/build.js
src/builder/validate.js
src/builder/manifest.js
examples/course.json
course-source/assets/
tests/
dist/
```

The runtime should use a component registry such as:

```js
const renderers = { paragraph, heading, list, image, table, callout, accordion, tabs, flashcards, reveal, scenario, matching, ordering };
function renderBlock(block, ctx) { const fn = renderers[block.type]; return fn ? fn(block, ctx) : unsupportedBlock(block.type); }
```

The player must never hardcode course names, module names, lesson names, or question text. All visible labels should come from the course definition or localized runtime defaults.

## SCORM 2004 path

Keep the adapter interface version-neutral:

```text
initialize() / get() / set() / commit() / terminate() / lastError()
```

A later SCORM 2004 adapter can map to `Initialize`, `GetValue`, `SetValue`, `Commit`, `Terminate`, `cmi.completion_status`, `cmi.success_status`, `cmi.location`, `cmi.suspend_data`, and `cmi.score.raw`, without changing the renderer, state model, completion engine, or package builder interfaces.

## Important implementation caveat

A genuinely production-quality generator requires the runtime source files, CSS, sanitization policy, complete schema, tests, and package tooling—not just a manifest and a ZIP command. The design above is the implementation contract and builder foundation. The next engineering step is to place these files in a repository and complete the runtime modules as a tested codebase, then validate generated ZIPs against SCORM Cloud and the target LMS matrix.