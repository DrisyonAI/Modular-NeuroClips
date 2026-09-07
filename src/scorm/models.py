"""
NeuroClips SCORM Data Models conforming to schemaVersion 1.0 specifications.
"""
from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel, Field


class ContentBlock(BaseModel):
    type: str  # heading, paragraph, richText, list, pills, comparison, example, callout, table, image, audio, divider, definition, note
    level: Optional[int] = 2
    text: Optional[str] = ""
    html: Optional[str] = ""
    items: Optional[List[str]] = None
    style: Optional[str] = "unordered"  # unordered, ordered, pills, grid
    headers: Optional[List[str]] = None
    rows: Optional[List[List[str]]] = None
    caption: Optional[str] = ""
    src: Optional[str] = ""
    alt: Optional[str] = ""
    title: Optional[str] = ""
    variant: Optional[str] = "info"  # key, info, warning, tip, neutral, highlight
    description: Optional[str] = ""
    lead: Optional[str] = ""
    steps: Optional[List[str]] = None
    conclusion: Optional[str] = ""
    cards: Optional[List[Dict[str, Any]]] = None
    term: Optional[str] = ""
    definition: Optional[str] = ""


class Interaction(BaseModel):
    id: str
    type: str  # accordion, tabs, flashcards, reveal, scenario, matching, ordering, knowledge_check
    title: Optional[str] = ""
    items: Optional[List[Dict[str, Any]]] = None
    tabs: Optional[List[Dict[str, Any]]] = None
    cards: Optional[List[Dict[str, Any]]] = None
    prompt: Optional[str] = ""
    hiddenContent: Optional[str] = ""
    buttonText: Optional[str] = "Reveal Answer"
    options: Optional[List[Dict[str, Any]]] = None


class QuizOption(BaseModel):
    key: str  # 'A', 'B', 'C', 'D'
    text: str


class QuizQuestion(BaseModel):
    id: str
    type: str = "single"  # single, multiple, true_false, Knowledge, Scenario, Applied
    text: str = ""
    options: List[Union[QuizOption, str, Dict[str, Any]]] = Field(default_factory=list)
    answer: Union[str, int] = ""
    feedback: Optional[str] = ""
    source_topic: Optional[str] = ""
    marks: Optional[int] = 1


class Quiz(BaseModel):
    id: str = "quiz-01"
    title: Optional[str] = "Knowledge Check"
    passingScore: int = 70
    maxAttempts: int = 3
    allowRetry: bool = True
    questions: List[QuizQuestion] = Field(default_factory=list)


class VideoMeta(BaseModel):
    src: Optional[str] = None
    poster: Optional[str] = None
    captions: Optional[str] = None
    required: bool = False
    completionThreshold: float = 0.9


class CompletionRule(BaseModel):
    type: str = "view"  # view, video, interaction, quiz, quiz_pass, all_required_components
    requiredScore: Optional[int] = 70


class Lesson(BaseModel):
    id: str
    number: Optional[str] = "1.1"
    title: str
    description: Optional[str] = ""
    durationMinutes: Optional[Union[int, float, str]] = 15
    learningMode: Optional[str] = "Concept + reading"
    objectives: List[str] = Field(default_factory=list)
    targetAudience: Optional[str] = ""
    video: Optional[VideoMeta] = None
    content: List[Union[ContentBlock, Dict[str, Any]]] = Field(default_factory=list)
    interactions: List[Union[Interaction, Dict[str, Any]]] = Field(default_factory=list)
    quiz: Optional[Quiz] = None
    completion: Optional[CompletionRule] = None


class Module(BaseModel):
    id: str
    number: Union[int, str] = 1
    title: str
    description: Optional[str] = ""
    durationMinutes: Optional[Union[int, float]] = 45
    lessons: List[Lesson] = Field(default_factory=list)


class CourseSettings(BaseModel):
    sequentialModules: bool = False
    sequentialLessons: bool = False
    showResumePrompt: bool = True
    courseCompletion: str = "all_lessons"  # all_lessons, quiz_pass, all_required_components
    autosaveSeconds: int = 10


class Course(BaseModel):
    id: str = "course-001"
    version: str = "1.0.0"
    title: str
    description: Optional[str] = ""
    thumbnail: Optional[str] = "assets/images/course.jpg"
    durationMinutes: Optional[Union[int, float]] = 60
    audience: Optional[str] = ""
    learningObjectives: List[str] = Field(default_factory=list)
    settings: CourseSettings = Field(default_factory=CourseSettings)
    modules: List[Module] = Field(default_factory=list)


class CourseDocument(BaseModel):
    schemaVersion: str = "1.0"
    course: Course
