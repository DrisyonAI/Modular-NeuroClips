"""
NeuroClips SCORM Framework & Packaging Engine.
"""
from .models import (
    CourseDocument,
    Course,
    Module,
    Lesson,
    Quiz,
    QuizQuestion,
    QuizOption,
    ContentBlock,
    Interaction,
    VideoMeta,
    CompletionRule,
    CourseSettings
)
from .validator import validate_course_document
from .manifest import generate_scorm_manifest
from .packager import SCORMPackageBuilder
from .converter import build_canonical_course_document

__all__ = [
    "CourseDocument",
    "Course",
    "Module",
    "Lesson",
    "Quiz",
    "QuizQuestion",
    "QuizOption",
    "ContentBlock",
    "Interaction",
    "VideoMeta",
    "CompletionRule",
    "CourseSettings",
    "validate_course_document",
    "generate_scorm_manifest",
    "SCORMPackageBuilder",
    "build_canonical_course_document"
]
