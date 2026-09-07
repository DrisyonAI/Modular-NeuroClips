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
    pass_percentage: int = 70
) -> Dict[str, Any]:
    """
    Builds a fully-featured canonical CourseDocument dict conforming to schemaVersion 1.0.
    """
    safe_course_id = re.sub(r'[^a-zA-Z0-9_\-]', '_', course_id or 'course-001')
    quiz_engine = QuizEngine()

    modules_list = []
    total_duration = 0

    for m_idx, mod in enumerate(modules_data or [], start=1):
        m_id = mod.get("module_id") or f"module-{m_idx}"
        m_title = mod.get("module_title") or f"Module {m_idx}"
        m_desc = mod.get("description") or ""

        lessons_list = []
        raw_lessons = mod.get("lessons") or []

        for l_idx, les in enumerate(raw_lessons, start=1):
            l_id = les.get("lesson_id") or f"lesson-{m_idx}-{l_idx}"
            l_num = f"{m_idx}.{l_idx}"
            l_title = les.get("lesson_title") or f"Lesson {l_num}"
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

            # Attach quiz if specified or from item bank
            quiz_config = None
            q_module_id = les.get("quiz_module_id") or default_quiz_module_id or m_idx
            if les.get("include_quiz") is not False:
                raw_questions = quiz_engine.get_module_questions(q_module_id)
                if raw_questions:
                    sample_q = raw_questions[:min(len(raw_questions), 10)]
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
                    quiz_config = {
                        "id": f"quiz-{l_id}",
                        "title": f"Knowledge Check: {topic}",
                        "passingScore": pass_percentage,
                        "maxAttempts": 3,
                        "allowRetry": True,
                        "questions": q_list
                    }

            lessons_list.append({
                "id": l_id,
                "number": l_num,
                "title": l_title,
                "description": l_desc,
                "durationMinutes": f"{dur_mins} Min" if isinstance(dur_mins, (int, float)) else str(dur_mins),
                "learningMode": les.get("learningMode") or "Concept + Demonstration + Hands-on Practice + Assessment",
                "objectives": les.get("objectives") or [f"Understand fundamental operations for {topic}"],
                "targetAudience": les.get("targetAudience") or "Professionals, Engineers, Managers, and Practitioners",
                "video": vid_config,
                "content": content_blocks,
                "interactions": les.get("interactions") or [],
                "quiz": quiz_config,
                "completion": {
                    "type": "quiz_pass" if quiz_config else ("video" if vid_config else "view"),
                    "requiredScore": pass_percentage
                }
            })

        modules_list.append({
            "id": m_id,
            "number": m_idx,
            "title": m_title,
            "description": m_desc,
            "durationMinutes": sum(int(float(str(l['durationMinutes']).replace(' Min', '').replace(' Hours', ''))) for l in lessons_list if str(l['durationMinutes']).replace(' Min', '').replace(' Hours', '').replace('.', '').isdigit()) or 45,
            "lessons": lessons_list
        })

    return {
        "schemaVersion": "1.0",
        "course": {
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
    }
