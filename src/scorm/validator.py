"""
Validation utility for NeuroClips SCORM Course Document and Asset references.
"""
import os
from pathlib import Path
from typing import Dict, Any, List, Set, Tuple


SUPPORTED_CONTENT_TYPES: Set[str] = {
    'heading', 'paragraph', 'richText', 'list', 'pills', 'image', 'audio',
    'table', 'callout', 'example', 'comparison', 'definition', 'embed', 'divider', 'note'
}

SUPPORTED_COMPLETION_TYPES: Set[str] = {
    'view', 'video', 'interaction', 'quiz', 'quiz_pass', 'all_required_components'
}


def validate_course_document(doc: Dict[str, Any], asset_base_dir: Path = None) -> Dict[str, Any]:
    """
    Validates a course document against the NeuroClips SCORM contract.
    Returns: { "valid": bool, "errors": list, "warnings": list, "files": list }
    """
    errors: List[str] = []
    warnings: List[str] = []
    ids: Set[str] = set()
    files: Set[str] = set()

    if not isinstance(doc, dict):
        return {"valid": False, "errors": ["Course document must be a JSON object"], "warnings": [], "files": []}

    schema_ver = doc.get("schemaVersion")
    if schema_ver != "1.0":
        errors.append(f"Unsupported schemaVersion '{schema_ver}'. Expected '1.0'.")

    c = doc.get("course")
    if not isinstance(c, dict):
        errors.append("Missing required 'course' object.")
        return {"valid": False, "errors": errors, "warnings": warnings, "files": []}

    course_id = c.get("id")
    if not course_id:
        errors.append("Course must have a non-empty 'id'.")
    elif course_id in ids:
        errors.append(f"Duplicate id: {course_id}")
    else:
        ids.add(course_id)

    if not c.get("title"):
        errors.append("Course must have a non-empty 'title'.")

    modules = c.get("modules")
    if not isinstance(modules, list):
        errors.append("Course 'modules' must be a list.")
        modules = []

    for m_idx, m in enumerate(modules):
        m_id = m.get("id")
        if not m_id:
            errors.append(f"Module index {m_idx} is missing an 'id'.")
        elif m_id in ids:
            errors.append(f"Duplicate module id: '{m_id}'")
        else:
            ids.add(m_id)

        lessons = m.get("lessons")
        if not isinstance(lessons, list):
            errors.append(f"Module '{m_id}' lessons must be a list.")
            lessons = []

        for l_idx, l in enumerate(lessons):
            l_id = l.get("id")
            if not l_id:
                errors.append(f"Lesson index {l_idx} in module '{m_id}' is missing an 'id'.")
            elif l_id in ids:
                errors.append(f"Duplicate lesson id: '{l_id}'")
            else:
                ids.add(l_id)

            comp = l.get("completion")
            if comp and isinstance(comp, dict):
                comp_type = comp.get("type")
                if comp_type and comp_type not in SUPPORTED_COMPLETION_TYPES:
                    errors.append(f"Lesson '{l_id}' has unsupported completion type: '{comp_type}'")

            # Validate content blocks
            content = l.get("content") or []
            for b in content:
                if isinstance(b, dict):
                    b_type = b.get("type")
                    if b_type and b_type not in SUPPORTED_CONTENT_TYPES:
                        warnings.append(f"Lesson '{l_id}' uses unknown content block type: '{b_type}'")
                    if b.get("src"):
                        files.add(b["src"])

            # Validate video
            vid = l.get("video")
            if vid and isinstance(vid, dict):
                if vid.get("src"):
                    files.add(vid["src"])
                if vid.get("poster"):
                    files.add(vid["poster"])
                if vid.get("captions"):
                    files.add(vid["captions"])

            # Validate interactions
            interactions = l.get("interactions") or []
            for inter in interactions:
                if isinstance(inter, dict):
                    inter_id = inter.get("id")
                    if inter_id:
                        if inter_id in ids:
                            errors.append(f"Duplicate interaction id: '{inter_id}'")
                        else:
                            ids.add(inter_id)

            # Validate quiz
            quiz = l.get("quiz")
            if quiz and isinstance(quiz, dict):
                q_id = quiz.get("id")
                if q_id:
                    if q_id in ids:
                        errors.append(f"Duplicate quiz id: '{q_id}'")
                    else:
                        ids.add(q_id)

                for q in quiz.get("questions") or []:
                    if isinstance(q, dict):
                        qid = q.get("id")
                        if qid:
                            if qid in ids:
                                errors.append(f"Duplicate question id: '{qid}'")
                            else:
                                ids.add(qid)

    # Validate asset paths
    for f in list(files):
        if not f or f.startswith("http://") or f.startswith("https://"):
            continue
        if ".." in f or os.path.isabs(f):
            errors.append(f"Unsafe asset path reference: '{f}'")
        elif asset_base_dir:
            normalized_rel = f.replace("assets/", "")
            target_file = asset_base_dir / normalized_rel
            if not target_file.exists():
                warnings.append(f"Referenced asset not found on disk: '{f}'")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "files": sorted(list(files))
    }
