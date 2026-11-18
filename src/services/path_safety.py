"""
Path guards for user-supplied filenames and server paths.

Every endpoint that turns request input into a filesystem path goes through
one of these helpers so a value like "../../etc/passwd" can never escape the
directory it was meant for.
"""
import re
import uuid
from pathlib import Path
from typing import Iterable, Optional

from fastapi import HTTPException

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")

# Default cap for uploaded media (bytes). Override per call where needed.
MAX_UPLOAD_BYTES = 500 * 1024 * 1024


def resolve_within(base: Path, name: str) -> Path:
    """Resolve `name` as a direct child of `base`; reject traversal and nested paths."""
    if not name or name in (".", "..") or "/" in name or "\\" in name or "\x00" in name:
        raise HTTPException(status_code=400, detail="Invalid file name")
    base_resolved = base.resolve()
    candidate = (base_resolved / name).resolve()
    if candidate.parent != base_resolved:
        raise HTTPException(status_code=400, detail="Invalid file name")
    return candidate


def resolve_under_roots(raw_path: str, roots: Iterable[Path]) -> Path:
    """Resolve a server path and require it to sit inside one of `roots`."""
    if not raw_path or "\x00" in raw_path:
        raise HTTPException(status_code=400, detail="Invalid path")
    candidate = Path(raw_path).resolve()
    for root in roots:
        root_resolved = root.resolve()
        if candidate == root_resolved or root_resolved in candidate.parents:
            return candidate
    raise HTTPException(status_code=403, detail="Path is outside the allowed directories")


def safe_upload_name(original: Optional[str], allowed_suffixes: Iterable[str]) -> str:
    """Random, collision-free filename that keeps only a whitelisted extension."""
    suffix = Path(original or "").suffix.lower()
    allowed = {s.lower() for s in allowed_suffixes}
    if suffix not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {', '.join(sorted(allowed))}",
        )
    stem = _UNSAFE_CHARS.sub("_", Path(original or "file").stem)[:60] or "file"
    return f"{stem}_{uuid.uuid4().hex[:12]}{suffix}"


async def read_upload_capped(upload, max_bytes: int = MAX_UPLOAD_BYTES) -> bytes:
    """Read an UploadFile in chunks and stop with 413 once it exceeds `max_bytes`."""
    chunks = []
    total = 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail=f"File exceeds {max_bytes // (1024 * 1024)} MB limit")
        chunks.append(chunk)
    return b"".join(chunks)
