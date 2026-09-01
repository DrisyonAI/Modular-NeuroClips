"""
Interactive Quiz & Assessment Engine.
Parses Item Bank questions from Nipuna Course spreadsheets, manages question banks,
and compiles SCORM 1.2 / HTML5 interactive assessment packages with LMS tracking.
"""
import re
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

try:
    import openpyxl
except ImportError:
    openpyxl = None


class QuizOption(BaseModel):
    key: str  # 'A', 'B', 'C', 'D'
    text: str


class QuizQuestion(BaseModel):
    id: str
    module_id: int
    question_type: str = "Knowledge"  # Knowledge, Scenario, Applied
    question: str
    options: List[QuizOption]
    correct_key: str
    marks: int = 1
    rationale: str = ""
    source_topic: str = ""


class QuizModuleSummary(BaseModel):
    module_id: int
    title: str
    total_questions: int
    knowledge_count: int
    scenario_count: int
    applied_count: int


MODULE_TITLES: Dict[int, str] = {
    1: "Module 1: Traditional AI vs GenAI vs Agents & Autonomy",
    2: "Module 2: Agent Architecture, Planning & Tool Integration",
    3: "Module 3: Retrieval-Augmented Generation & Financial Memory",
    4: "Module 4: Multi-Agent Collaboration & Dispute Resolution",
    5: "Module 5: Risk, Guardrails, Compliance & Governance",
    6: "Module 6: Enterprise Deployment, Observability & Telemetry",
    7: "Module 7: Algorithmic Execution, Settlement & Real-Time Trading"
}


class QuizEngine:
    """
    Manages question banks and compiles SCORM-compliant interactive quiz players.
    """

    def __init__(self, excel_path: Optional[Path] = None):
        self.excel_path = excel_path or Path("Nipuna_AI_Agents_in_FinTech_15_Hour_Course-updated-v3.xlsx")
        self.json_path = Path(__file__).parent / "nipuna_item_bank.json"
        self._cache: Dict[int, List[QuizQuestion]] = {}
        
        # 1. Try bundled JSON first (ultra-fast, zero dependencies)
        if self.json_path.exists():
            self.load_from_json(self.json_path)
        
        # 2. Fallback or update from Excel if available
        if not self._cache and self.excel_path.exists() and openpyxl:
            self.load_from_excel(self.excel_path)

    def load_from_json(self, json_path: Path):
        """Loads question bank from bundled JSON file."""
        self._cache.clear()
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for mod_str, q_list in data.items():
                mod_id = int(mod_str)
                self._cache[mod_id] = [QuizQuestion(**q) for q in q_list]
        except Exception as e:
            print(f"[QuizEngine] Error loading JSON item bank: {e}")

    def parse_options_string(self, raw_options: str) -> List[QuizOption]:
        """Parses options like 'A. Option 1 | B. Option 2 | C. Option 3 | D. Option 4'."""
        if not raw_options:
            return []
        
        parts = [p.strip() for p in raw_options.split("|") if p.strip()]
        options = []
        for p in parts:
            match = re.match(r"^([A-D])\.\s*(.+)$", p)
            if match:
                options.append(QuizOption(key=match.group(1).upper(), text=match.group(2).strip()))
            else:
                options.append(QuizOption(key=f"OPT_{len(options)+1}", text=p))
        return options

    def load_from_excel(self, excel_path: Path):
        """Loads and parses all items from the Excel 'Item Bank' worksheet."""
        if not openpyxl:
            return
        self._cache.clear()
        try:
            wb = openpyxl.load_workbook(excel_path, data_only=True)
            if "Item Bank" not in wb.sheetnames:
                return

            ws = wb["Item Bank"]
            rows = list(ws.iter_rows(values_only=True))[3:]
            if not rows:
                return

            for r in rows[1:]:
                if len(r) < 8 or not r[1]:
                    continue

                q_id = str(r[1]).strip()
                try:
                    mod_id = int(r[2]) if r[2] is not None else 1
                except ValueError:
                    mod_id = 1

                q_type = str(r[3]).strip() if r[3] else "Knowledge"
                question_text = str(r[4]).strip() if r[4] else ""
                options_raw = str(r[5]).strip() if r[5] else ""
                correct_key = str(r[6]).strip().upper() if r[6] else "A"
                
                try:
                    marks = int(r[7]) if r[7] is not None else 1
                except ValueError:
                    marks = 1

                rationale = str(r[8]).strip() if len(r) > 8 and r[8] else ""
                source_topic = str(r[9]).strip() if len(r) > 9 and r[9] else ""

                if not question_text:
                    continue

                parsed_options = self.parse_options_string(options_raw)

                q = QuizQuestion(
                    id=q_id,
                    module_id=mod_id,
                    question_type=q_type,
                    question=question_text,
                    options=parsed_options,
                    correct_key=correct_key,
                    marks=marks,
                    rationale=rationale,
                    source_topic=source_topic
                )

                if mod_id not in self._cache:
                    self._cache[mod_id] = []
                self._cache[mod_id].append(q)

        except Exception as e:
            print(f"[QuizEngine] Error loading Excel item bank: {e}")

    def get_modules_summary(self) -> List[QuizModuleSummary]:
        """Returns statistical overview of all available module question banks."""
        summaries = []
        for mod_id in sorted(self._cache.keys()):
            questions = self._cache[mod_id]
            k_cnt = sum(1 for q in questions if "knowledge" in q.question_type.lower())
            s_cnt = sum(1 for q in questions if "scenario" in q.question_type.lower())
            a_cnt = sum(1 for q in questions if "applied" in q.question_type.lower())
            title = MODULE_TITLES.get(mod_id, f"Module {mod_id}: AI Agents in FinTech")
            summaries.append(
                QuizModuleSummary(
                    module_id=mod_id,
                    title=title,
                    total_questions=len(questions),
                    knowledge_count=k_cnt,
                    scenario_count=s_cnt,
                    applied_count=a_cnt
                )
            )
        return summaries

    def get_module_questions(self, module_id: int) -> List[QuizQuestion]:
        """Retrieves questions for a specific module ID."""
        return self._cache.get(module_id, self._cache.get(1, []))

    def generate_interactive_scorm_html(
        self,
        video_filename: str,
        module_id: int,
        pass_percentage: int = 70
    ) -> str:
        """
        Compiles an interactive SCORM 1.2 / LMS web player combining:
        1. 🎬 Video Lesson Player
        2. 📝 Interactive Knowledge Check & Quiz with real-time scoring
        3. 💡 Rationale & Pedagogical Feedback
        4. 📡 SCORM API CMI status tracking (LMSSetValue, LMSCommit)
        """
        questions = self.get_module_questions(module_id)
        module_title = MODULE_TITLES.get(module_id, f"Module {module_id}: AI Agents in FinTech")
        questions_json = json.dumps([q.model_dump() for q in questions])

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{module_title} | Modular-NeuroClips LMS</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <script>
        tailwind.config = {{
            theme: {{
                extend: {{
                    fontFamily: {{
                        sans: ['Inter', 'sans-serif'],
                        mono: ['JetBrains Mono', 'monospace']
                    }},
                    colors: {{
                        brand: {{ 500: '#0ea5e9', 600: '#0284c7', glow: '#38bdf8' }}
                    }}
                }}
            }}
        }}
    </script>
    <style>
        body {{ background: #090d16; color: #f1f5f9; }}
        .glass-panel {{ background: rgba(15, 23, 42, 0.85); backdrop-filter: blur(16px); border: 1px solid rgba(255, 255, 255, 0.08); }}
    </style>
</head>
<body class="min-h-screen flex flex-col font-sans">

    <!-- Top Navigation Header -->
    <header class="border-b border-slate-800 bg-slate-950/80 px-6 py-3.5 flex items-center justify-between sticky top-0 z-50">
        <div class="flex items-center space-x-3">
            <span class="text-xl">⚡</span>
            <div>
                <h1 class="text-sm font-bold text-white tracking-wide">{module_title}</h1>
                <span class="text-[11px] text-slate-400 font-mono">SCORM 1.2 Enterprise Edition • Passing Score: {pass_percentage}%</span>
            </div>
        </div>
        <div class="flex items-center space-x-3">
            <span id="lms-status-badge" class="px-2.5 py-1 rounded-full text-xs font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30">
                🟡 In Progress
            </span>
        </div>
    </header>

    <!-- Main Content Container -->
    <main class="flex-1 max-w-6xl w-full mx-auto p-4 md:p-6 space-y-6">
        
        <!-- Tab Navigation -->
        <div class="flex space-x-2 border-b border-slate-800 pb-2">
            <button onclick="switchTab('video')" id="tab-btn-video" class="px-4 py-2 rounded-lg bg-brand-600 text-white text-xs font-bold flex items-center gap-2 transition-all">
                <span>🎬</span> <span>Video Lecture</span>
            </button>
            <button onclick="switchTab('quiz')" id="tab-btn-quiz" class="px-4 py-2 rounded-lg bg-slate-800 text-slate-300 text-xs font-bold flex items-center gap-2 hover:bg-slate-700 transition-all">
                <span>📝</span> <span>Knowledge Check & Quiz ({len(questions)} Questions)</span>
            </button>
        </div>

        <!-- TAB 1: VIDEO LESSON -->
        <section id="tab-video" class="space-y-4">
            <div class="glass-panel p-4 rounded-2xl">
                <video id="course-video" controls class="w-full max-h-[580px] rounded-xl bg-black shadow-2xl" onended="onVideoComplete()">
                    <source src="{video_filename}" type="video/mp4">
                    Your browser does not support the video tag.
                </video>
            </div>
            <div class="glass-panel p-4 rounded-xl flex items-center justify-between text-xs">
                <span class="text-slate-400">💡 Complete the video and proceed to the Knowledge Check to earn your completion certification.</span>
                <button onclick="switchTab('quiz')" class="px-4 py-2 rounded-lg bg-brand-500 hover:bg-brand-600 text-white font-bold transition-all">
                    Proceed to Quiz ➔
                </button>
            </div>
        </section>

        <!-- TAB 2: INTERACTIVE KNOWLEDGE CHECK -->
        <section id="tab-quiz" class="hidden space-y-6">
            
            <!-- Quiz Summary Banner -->
            <div class="glass-panel p-5 rounded-2xl flex flex-col md:flex-row items-center justify-between gap-4 border border-brand-500/20">
                <div class="space-y-1">
                    <h2 class="text-base font-bold text-white flex items-center gap-2">
                        <span>📝</span> <span>Module Assessment & Item Bank</span>
                    </h2>
                    <p class="text-xs text-slate-400">Answer the questions below. Instant rationale and LMS gradebook commit upon submission.</p>
                </div>
                <div id="score-display-card" class="hidden px-4 py-2.5 rounded-xl bg-slate-900 border border-slate-700 text-center font-mono">
                    <span class="text-[10px] text-slate-400 block uppercase">Final Score</span>
                    <span id="final-score-val" class="text-lg font-bold text-brand-glow">0%</span>
                </div>
            </div>

            <!-- Questions Form -->
            <form id="quiz-form" onsubmit="submitQuiz(event)" class="space-y-4">
                <div id="questions-container" class="space-y-4"></div>

                <!-- Submit Button Bar -->
                <div class="glass-panel p-4 rounded-xl flex items-center justify-between sticky bottom-4 z-40">
                    <span id="quiz-completion-count" class="text-xs text-slate-400 font-mono">0 of {len(questions)} answered</span>
                    <button type="submit" id="submit-quiz-btn" class="px-6 py-2.5 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 text-white text-xs font-bold hover:brightness-110 shadow-lg shadow-emerald-600/30 transition-all flex items-center gap-2">
                        <span>✅</span> <span>Submit & Commit Gradebook</span>
                    </button>
                </div>
            </form>
        </section>
    </main>

    <script>
        const QUESTIONS = {questions_json};
        const PASS_PERCENTAGE = {pass_percentage};
        let userAnswers = {{}};
        let quizSubmitted = false;

        // SCORM 1.2 Standard API Connector
        let scormAPI = null;
        function findScormAPI(win) {{
            let findAttempts = 0;
            while ((win.API == null) && (win.parent != null) && (win.parent != win)) {{
                findAttempts++;
                if (findAttempts > 7) return null;
                win = win.parent;
            }}
            return win.API;
        }}

        function initSCORM() {{
            try {{
                scormAPI = findScormAPI(window);
                if (scormAPI) {{
                    scormAPI.LMSInitialize("");
                    scormAPI.LMSSetValue("cmi.core.lesson_status", "incomplete");
                    scormAPI.LMSCommit("");
                }}
            }} catch(e) {{}}
        }}

        function commitSCORM(score, passed) {{
            if (!scormAPI) return;
            try {{
                scormAPI.LMSSetValue("cmi.core.score.raw", score.toString());
                scormAPI.LMSSetValue("cmi.core.lesson_status", passed ? "passed" : "incomplete");
                scormAPI.LMSCommit("");
            }} catch(e) {{}}
        }}

        function switchTab(tab) {{
            const vTab = document.getElementById('tab-video');
            const qTab = document.getElementById('tab-quiz');
            const btnV = document.getElementById('tab-btn-video');
            const btnQ = document.getElementById('tab-btn-quiz');

            if (tab === 'video') {{
                vTab.classList.remove('hidden');
                qTab.classList.add('hidden');
                btnV.className = "px-4 py-2 rounded-lg bg-brand-600 text-white text-xs font-bold flex items-center gap-2 transition-all";
                btnQ.className = "px-4 py-2 rounded-lg bg-slate-800 text-slate-300 text-xs font-bold flex items-center gap-2 hover:bg-slate-700 transition-all";
            }} else {{
                qTab.classList.remove('hidden');
                vTab.classList.add('hidden');
                btnQ.className = "px-4 py-2 rounded-lg bg-brand-600 text-white text-xs font-bold flex items-center gap-2 transition-all";
                btnV.className = "px-4 py-2 rounded-lg bg-slate-800 text-slate-300 text-xs font-bold flex items-center gap-2 hover:bg-slate-700 transition-all";
            }}
        }}

        function renderQuestions() {{
            const container = document.getElementById('questions-container');
            container.innerHTML = QUESTIONS.map((q, idx) => `
                <div class="glass-panel p-5 rounded-xl space-y-3 border border-slate-800" id="q-card-${{q.id}}">
                    <div class="flex items-center justify-between border-b border-slate-800/80 pb-2">
                        <span class="text-xs font-bold text-brand-glow font-mono">${{q.id}} • ${{q.question_type}} Check</span>
                        <span class="text-[10px] text-slate-400 font-mono">${{q.source_topic}}</span>
                    </div>
                    <p class="text-sm font-semibold text-slate-100 leading-relaxed">${{idx + 1}}. ${{q.question}}</p>
                    <div class="space-y-2 pt-1">
                        ${{q.options.map(opt => `
                            <label class="flex items-center space-x-3 p-3 rounded-lg bg-slate-900/90 border border-slate-800 hover:border-brand-500/50 cursor-pointer transition-all text-xs text-slate-200" id="label-${{q.id}}-${{opt.key}}">
                                <input type="radio" name="q_${{q.id}}" value="${{opt.key}}" onchange="recordAnswer('${{q.id}}', '${{opt.key}}')" class="accent-brand-500">
                                <span><strong class="font-mono text-brand-glow">${{opt.key}}.</strong> ${{opt.text}}</span>
                            </label>
                        `).join('')}}
                    </div>
                    <div id="rationale-${{q.id}}" class="hidden p-3 rounded-lg text-xs leading-relaxed"></div>
                </div>
            `).join('');
        }}

        function recordAnswer(qId, key) {{
            userAnswers[qId] = key;
            const cnt = Object.keys(userAnswers).length;
            document.getElementById('quiz-completion-count').innerText = `${{cnt}} of ${{QUESTIONS.length}} answered`;
        }}

        function submitQuiz(e) {{
            e.preventDefault();
            if (quizSubmitted) return;

            let correctCount = 0;
            QUESTIONS.forEach(q => {{
                const userChoice = userAnswers[q.id];
                const card = document.getElementById(`q-card-${{q.id}}`);
                const ratBox = document.getElementById(`rationale-${{q.id}}`);
                ratBox.classList.remove('hidden');

                if (userChoice === q.correct_key) {{
                    correctCount++;
                    ratBox.className = "p-3 rounded-lg text-xs leading-relaxed bg-emerald-500/10 border border-emerald-500/30 text-emerald-300";
                    ratBox.innerHTML = `<strong>✅ Correct!</strong> ${{q.rationale}}`;
                }} else {{
                    ratBox.className = "p-3 rounded-lg text-xs leading-relaxed bg-red-500/10 border border-red-500/30 text-red-300";
                    ratBox.innerHTML = `<strong>❌ Incorrect. Correct Answer: ${{q.correct_key}}</strong><br>${{q.rationale}}`;
                }}
            }});

            const scorePercent = Math.round((correctCount / QUESTIONS.length) * 100);
            const passed = scorePercent >= PASS_PERCENTAGE;

            quizSubmitted = true;
            document.getElementById('score-display-card').classList.remove('hidden');
            document.getElementById('final-score-val').innerText = `${{scorePercent}}% (${{correctCount}}/${{QUESTIONS.length}})`;

            const badge = document.getElementById('lms-status-badge');
            if (passed) {{
                badge.className = "px-2.5 py-1 rounded-full text-xs font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30";
                badge.innerText = "🟢 PASSED (" + scorePercent + "%)";
            }} else {{
                badge.className = "px-2.5 py-1 rounded-full text-xs font-bold bg-red-500/20 text-red-300 border border-red-500/30";
                badge.innerText = "🔴 FAILED (" + scorePercent + "%)";
            }}

            document.getElementById('submit-quiz-btn').disabled = true;
            document.getElementById('submit-quiz-btn').innerText = "Gradebook Committed";

            commitSCORM(scorePercent, passed);
        }}

        function onVideoComplete() {{
            const badge = document.getElementById('lms-status-badge');
            if (!quizSubmitted) {{
                badge.innerText = "🟡 Video Complete • Complete Quiz";
            }}
        }}

        window.onload = function() {{
            initSCORM();
            renderQuestions();
        }};
    </script>
</body>
</html>
"""
