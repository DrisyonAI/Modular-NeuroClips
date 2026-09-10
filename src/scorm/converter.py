"""
Converter utilities bridging NeuroClips curriculum, video jobs, and quiz item banks
into the canonical NeuroClips SCORM Course Document (course.json).
"""
import re
from typing import Dict, Any, List, Optional
from pathlib import Path
try:
    from src.quiz_engine import QuizEngine, QuizQuestion
except ImportError:
    from quiz_engine import QuizEngine, QuizQuestion


def build_canonical_course_document(
    course_id: str,
    course_title: str,
    course_description: str = "",
    modules_data: List[Dict[str, Any]] = None,
    default_quiz_module_id: Optional[int] = None,
    pass_percentage: int = 70,
    intro_video_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Builds a fully-featured canonical CourseDocument dict conforming to schemaVersion 1.0.
    Acts as the Single Source of Truth for module and lesson numbers, names, intro video,
    and lightweight 2-3 question understanding checks.
    """
    safe_course_id = re.sub(r'[^a-zA-Z0-9_\-]', '_', course_id or 'course-001')
    quiz_engine = QuizEngine()

    modules_list = []
    total_duration = 0

    for m_idx, mod in enumerate(modules_data or [], start=1):
        m_num = mod.get("module_number") if mod.get("module_number") is not None else (mod.get("number") if mod.get("number") is not None else m_idx)
        # Parse int if purely numeric
        if isinstance(m_num, str) and m_num.strip().isdigit():
            m_num = int(m_num.strip())

        raw_m_title = mod.get("module_title") or mod.get("module_name") or f"Module {m_num}"
        # Prevent stale "Module 1" fallback when module number is different
        if str(raw_m_title).strip() == "Module 1" and str(m_num) != "1":
            m_title = f"Module {m_num}"
        else:
            clean_m_name = re.sub(r"^Module\s*\d+\s*:\s*", "", str(raw_m_title)).strip() or str(raw_m_title)
            m_title = f"Module {m_num}: {clean_m_name}" if not str(raw_m_title).startswith(f"Module {m_num}") else str(raw_m_title)

        m_id = mod.get("module_id") or f"module-{m_num}"
        m_desc = mod.get("description") or ""

        lessons_list = []
        raw_lessons = mod.get("lessons") or []

        for l_idx, les in enumerate(raw_lessons, start=1):
            explicit_l_num = les.get("lesson_number") if les.get("lesson_number") is not None else les.get("number")
            l_num = str(explicit_l_num).strip() if explicit_l_num is not None and str(explicit_l_num).strip() else f"{m_num}.{l_idx}"
            l_id = les.get("lesson_id") or f"lesson-{m_num}-{l_idx}"

            raw_l_title = les.get("lesson_title") or les.get("lesson_name") or f"Lesson {l_num}"
            if str(raw_l_title).strip() in ("Lesson 1.1", "Lesson 1") and l_num != "1.1":
                raw_l_title = f"Lesson {l_num}"

            clean_l_name = re.sub(r"^(Lesson\s*)?\d+(\.\d+)?\s*[:\-]?\s*", "", str(raw_l_title)).strip() or str(raw_l_title)
            if str(raw_l_title).startswith(f"{l_num} ") or str(raw_l_title).startswith(f"Lesson {l_num}"):
                l_title = str(raw_l_title)
            else:
                l_title = f"{l_num} {clean_l_name}"

            l_desc = les.get("description") or ""
            topic = les.get("topic") or l_title
            runtime_sec = les.get("runtime_seconds") or 0.0
            dur_mins = round(runtime_sec / 60, 1) if runtime_sec > 0 else 15
            total_duration += dur_mins

            # Video configuration
            vid_config = None
            if les.get("video_path") or les.get("video_filename"):
                raw_v = les.get("video_path") or les.get("video_filename")
                vid_name = Path(raw_v).name
                vid_config = {
                    "src": f"assets/videos/{vid_name}",
                    "poster": "assets/images/poster.jpg",
                    "captions": "assets/captions/subtitles.vtt" if les.get("srt_path") else None,
                    "required": True,
                    "completionThreshold": 0.85
                }

            # Build content blocks matching reference visual design
            content_blocks = les.get("content") or []
            if not content_blocks:
                content_blocks = [
                    {
                        "type": "heading",
                        "level": 2,
                        "text": f"Overview: {topic}"
                    },
                    {
                        "type": "paragraph",
                        "text": l_desc or f"Explore the core concepts, industry context, and strategic automation techniques for {topic}."
                    },
                    {
                        "type": "pills",
                        "items": [
                            "Streamlining high-volume manual candidate reviews",
                            "Formulating precise, context-aware prompts & job briefs",
                            "Cross-referencing verified credential datasets",
                            "Synthesizing interview observations with human review",
                            "Automating status communications and stakeholder updates",
                            "Preserving strict regulatory auditability and fairness"
                        ]
                    },
                    {
                        "type": "comparison",
                        "cards": [
                            {
                                "title": "Traditional Workflow",
                                "variant": "neutral",
                                "content": "Manual Ingestion → Ad-hoc Search → Unstructured Screening → Fragmented Reporting"
                            },
                            {
                                "title": "AI-Augmented Autonomous Pipeline",
                                "variant": "highlight",
                                "content": "Autonomous Parsing → Semantic Matching → Risk Guardrails → Human Approval & Decision"
                            }
                        ]
                    },
                    {
                        "type": "note",
                        "text": "The critical advantage of modern autonomous architectures is scale with accountability: AI accelerants augment human decision-makers without eliminating human discretion."
                    },
                    {
                        "type": "table",
                        "caption": "Role & Responsibilities Matrix",
                        "headers": ["Operational Phase", "Autonomous System Role", "Human Governance Role"],
                        "rows": [
                            ["Intake & Sourcing", "Extracts structured metadata and evaluates fit score", "Reviews role requirements and calibrates thresholds"],
                            ["Assessment & Ranking", "Executes multi-factor rubric evaluation", "Validates borderline cases and checks bias guards"],
                            ["Final Engagement", "Schedules interviews and compiles evidence dossiers", "Conducts interview and delivers final hiring determination"]
                        ]
                    },
                    {
                        "type": "example",
                        "title": f"EXAMPLE: {topic.upper()} WORKFLOW",
                        "lead": "Consider an enterprise workflow handling hundreds of candidate dossiers under strict compliance standards:",
                        "steps": [
                            "Ingest candidate profiles into the structured knowledge engine.",
                            "Execute semantic extraction against role criteria.",
                            "Flag missing mandatory qualifications and discrepancies.",
                            "Synthesize candidate briefing dossier for hiring committee.",
                            "Review rationale dossier and authorize interview progression."
                        ],
                        "conclusion": "The committee makes the final decision with complete auditability."
                    },
                    {
                        "type": "callout",
                        "variant": "key",
                        "title": "KEY LEARNING",
                        "text": "AI does not replace human judgment. It eliminates repetitive friction so experts can focus on high-impact evaluation."
                    }
                ]

            # Attach lightweight 2-3 question understanding check (Requirement 5)
            quiz_config = None
            q_module_id = les.get("quiz_module_id") or default_quiz_module_id or m_num
            if les.get("include_quiz") is not False:
                custom_questions = les.get("understanding_check") or les.get("quiz_questions")
                if custom_questions and isinstance(custom_questions, list):
                    q_list = custom_questions[:3]
                else:
                    try:
                        raw_questions = quiz_engine.get_module_questions(int(q_module_id) if str(q_module_id).isdigit() else 1)
                    except Exception:
                        raw_questions = []

                    if raw_questions:
                        # Include ONLY 2-3 questions to verify learner understanding
                        sample_q = raw_questions[:min(len(raw_questions), 3)]
                        q_list = []
                        for q in sample_q:
                            opts = [{"key": o.key, "text": o.text} for o in q.options]
                            q_list.append({
                                "id": q.id,
                                "type": "single",
                                "text": q.question,
                                "options": opts,
                                "answer": q.correct_key,
                                "feedback": q.rationale,
                                "source_topic": q.source_topic or topic
                            })
                    else:
                        # Fallback 2 formative understanding check questions
                        q_list = [
                            {
                                "id": f"check_{l_num}_1".replace(".", "_"),
                                "type": "single",
                                "text": f"What is the core architectural principle behind {topic}?",
                                "options": [
                                    {"key": "A", "text": "Operating without governance or human review"},
                                    {"key": "B", "text": "Augmenting expert human judgment with workflow automation"},
                                    {"key": "C", "text": "Eliminating auditability across processes"},
                                    {"key": "D", "text": "Replacing all decision criteria with fixed rules"}
                                ],
                                "answer": "B",
                                "feedback": "Autonomous systems are designed to eliminate repetitive friction while preserving expert governance.",
                                "source_topic": topic
                            },
                            {
                                "id": f"check_{l_num}_2".replace(".", "_"),
                                "type": "single",
                                "text": f"How should outcomes from {topic} be verified?",
                                "options": [
                                    {"key": "A", "text": "Through calibrated human-in-the-loop validation criteria"},
                                    {"key": "B", "text": "By disabling error telemetry"},
                                    {"key": "C", "text": "By deploying without boundary checks"},
                                    {"key": "D", "text": "By ignoring regulatory compliance requirements"}
                                ],
                                "answer": "A",
                                "feedback": "Enterprise architectures require clear human-in-the-loop evaluation and governance criteria.",
                                "source_topic": topic
                            }
                        ]

                quiz_config = {
                    "id": f"check-{l_num}".replace(".", "-"),
                    "title": "Understanding Check",
                    "passingScore": pass_percentage,
                    "maxAttempts": 3,
                    "allowRetry": True,
                    "questions": q_list[:3]  # Strictly 2-3 questions max
                }

            lessons_list.append({
                "id": l_id,
                "number": l_num,
                "title": l_title,
                "name": l_title,
                "description": l_desc,
                "durationMinutes": f"{dur_mins} Min" if isinstance(dur_mins, (int, float)) else str(dur_mins),
                "learningMode": les.get("learningMode") or "Concept + Demonstration + Hands-on Practice + Assessment",
                "objectives": les.get("objectives") or [f"Understand fundamental operations for {topic}"],
                "targetAudience": les.get("targetAudience") or "Professionals, Engineers, Managers, and Practitioners",
                "video": vid_config,
                "content": content_blocks,
                "interactions": les.get("interactions") or [],
                "quiz": quiz_config,
                "understanding_check": quiz_config,
                "completion": {
                    "type": "quiz_pass" if quiz_config else ("video" if vid_config else "view"),
                    "requiredScore": pass_percentage
                }
            })

        modules_list.append({
            "id": m_id,
            "number": m_num,
            "title": m_title,
            "name": m_title,
            "description": m_desc,
            "durationMinutes": sum(int(float(str(l['durationMinutes']).replace(' Min', '').replace(' Hours', ''))) for l in lessons_list if str(l['durationMinutes']).replace(' Min', '').replace(' Hours', '').replace('.', '').isdigit()) or 45,
            "lessons": lessons_list
        })

    course_obj = {
        "id": safe_course_id,
        "version": "1.0.0",
        "title": course_title or "AI-Powered Professional Course",
        "description": course_description or "Comprehensive training course powered by Modular-NeuroClips.",
        "thumbnail": "assets/images/course.jpg",
        "durationMinutes": int(total_duration) or 90,
        "audience": "Professionals, Developers, Decision Makers, and Enterprise Practitioners",
        "learningObjectives": [
            "Master core architectural paradigms and workflow automation",
            "Apply end-to-end practical techniques in realistic operational contexts",
            "Evaluate autonomous outputs with human judgment and governance criteria"
        ],
        "settings": {
            "sequentialModules": False,
            "sequentialLessons": False,
            "showResumePrompt": True,
            "courseCompletion": "all_lessons",
            "autosaveSeconds": 10
        },
        "modules": modules_list
    }

    if intro_video_path:
        course_obj["introBackgroundVideo"] = intro_video_path
        course_obj["intro"] = {"background_video": intro_video_path}

    return {
        "schemaVersion": "1.0",
        "course": course_obj
    }
