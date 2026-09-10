"""
Universal Document Parser and Pedagogical Scene Slicer.
Extracts clean narration prose from .txt, .md, .docx, and .pdf documents,
cleans formatting, and decomposes text into bounded pedagogical scenes.
"""
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field


class ParsedDocumentScene(BaseModel):
    """A bounded pedagogical scene derived from raw document text."""
    scene_id: int
    title: str
    narration: str
    word_count: int
    estimated_duration_sec: float = Field(..., description="Estimated duration based on average 150 words per minute")


class DocumentParseResult(BaseModel):
    """Structured parse output representing the entire decomposed document."""
    document_title: str
    total_scenes: int
    total_words: int
    scenes: List[ParsedDocumentScene]


class DocumentParser:
    """Extracts narrative text and slices into pedagogical scenes."""

    @staticmethod
    def extract_text_from_txt_or_md(file_path: Path) -> str:
        """Reads plain text or markdown files and strips formatting artifacts."""
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        # Strip markdown images, links, and bold/italic markup
        text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
        text = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text)
        text = re.sub(r"[*_~`#]", " ", text)
        return text

    @staticmethod
    def extract_text_from_docx(file_path: Path) -> str:
        """Extracts text paragraphs from Word .docx without external dependencies via zip XML."""
        paragraphs = []
        try:
            with zipfile.ZipFile(file_path) as z:
                xml_content = z.read("word/document.xml")
                tree = ET.fromstring(xml_content)
                namespaces = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                for p in tree.iterfind(".//w:p", namespaces):
                    texts = [node.text for node in p.iterfind(".//w:t", namespaces) if node.text]
                    if texts:
                        paragraphs.append("".join(texts))
        except Exception as e:
            raise ValueError(f"Failed to parse .docx file: {e}")
        return "\n".join(paragraphs)

    @staticmethod
    def extract_text_from_pdf(file_path: Path) -> str:
        """Extracts text from PDF using pypdf if available, or fallback basic stream regex."""
        try:
            import pypdf
            reader = pypdf.PdfReader(str(file_path))
            pages_text = [page.extract_text() or "" for page in reader.pages]
            return "\n".join(pages_text)
        except ImportError:
            # Basic fallback for clean textual streams
            content = file_path.read_bytes()
            text_chunks = re.findall(rb"\(([\w\s.,;:!?-]{4,})\)\s*Tj", content)
            if text_chunks:
                return "\n".join(chunk.decode("utf-8", errors="ignore") for chunk in text_chunks)
            raise RuntimeError("pypdf is required for robust PDF text extraction. Run: uv pip install pypdf")

    @classmethod
    def extract_text(cls, file_path: Path) -> str:
        """Dispatcher method based on file suffix."""
        suffix = file_path.suffix.lower()
        if suffix in [".txt", ".md"]:
            return cls.extract_text_from_txt_or_md(file_path)
        elif suffix == ".docx":
            return cls.extract_text_from_docx(file_path)
        elif suffix == ".pdf":
            return cls.extract_text_from_pdf(file_path)
        else:
            raise ValueError(f"Unsupported document format: {suffix}. Supported: .txt, .md, .docx, .pdf")

    @classmethod
    def clean_prose(cls, text: str) -> str:
        """Cleans extracted text, collapses whitespaces, removes tables and page noise."""
        text = re.sub(r"[\r\t\f]", " ", text)
        # Collapse multiple spaces
        text = re.sub(r" +", " ", text)
        # Remove standalone page numbers or headers
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        cleaned_lines = []
        for line in lines:
            if re.match(r"^Page \d+( of \d+)?$", line, flags=re.IGNORECASE) or line.isdigit():
                continue
            cleaned_lines.append(line)
        return " ".join(cleaned_lines)

    @classmethod
    def slice_into_scenes(
        cls,
        raw_text: str,
        document_title: Optional[str] = "Document Overview",
        target_words_per_scene: int = 60,
        max_scenes: int = 50
    ) -> DocumentParseResult:
        """
        Decomposes narrative text into pedagogical scenes bounded by natural sentence breaks.
        Target: ~50-80 words (20-40 seconds per scene).
        """
        clean_text = cls.clean_prose(raw_text)
        if not clean_text:
            return DocumentParseResult(
                document_title=document_title or "Untitled",
                total_scenes=0,
                total_words=0,
                scenes=[]
            )

        # Split into sentences using regex boundary
        sentence_end = re.compile(r"(?<=[.!?])\s+")
        sentences = [s.strip() for s in sentence_end.split(clean_text) if s.strip()]

        scenes: List[ParsedDocumentScene] = []
        current_chunk: List[str] = []
        current_word_count = 0
        scene_counter = 1

        for sentence in sentences:
            sentence_words = len(sentence.split())
            if current_word_count + sentence_words > target_words_per_scene and current_chunk:
                # Seal current scene
                scene_text = " ".join(current_chunk)
                duration = max(round((current_word_count / 150.0) * 60.0, 1), 3.0)
                scenes.append(
                    ParsedDocumentScene(
                        scene_id=scene_counter,
                        title=f"Scene {scene_counter}: {current_chunk[0][:30]}...",
                        narration=scene_text,
                        word_count=current_word_count,
                        estimated_duration_sec=duration
                    )
                )
                scene_counter += 1
                if scene_counter > max_scenes:
                    break
                current_chunk = [sentence]
                current_word_count = sentence_words
            else:
                current_chunk.append(sentence)
                current_word_count += sentence_words

        # Append trailing chunk
        if current_chunk and scene_counter <= max_scenes:
            scene_text = " ".join(current_chunk)
            duration = max(round((current_word_count / 150.0) * 60.0, 1), 3.0)
            scenes.append(
                ParsedDocumentScene(
                    scene_id=scene_counter,
                    title=f"Scene {scene_counter}: {current_chunk[0][:30]}...",
                    narration=scene_text,
                    word_count=current_word_count,
                    estimated_duration_sec=duration
                )
            )

        total_words = sum(sc.word_count for sc in scenes)
        return DocumentParseResult(
            document_title=document_title or "Document Overview",
            total_scenes=len(scenes),
            total_words=total_words,
            scenes=scenes
        )

    @classmethod
    def parse_file(cls, file_path: Path, target_words_per_scene: int = 60, max_scenes: int = 50) -> DocumentParseResult:
        """Extracts text from file and returns decomposed DocumentParseResult."""
        raw_text = cls.extract_text(file_path)
        doc_title = file_path.stem.replace("_", " ").replace("-", " ").title()
        return cls.slice_into_scenes(
            raw_text=raw_text,
            document_title=doc_title,
            target_words_per_scene=target_words_per_scene,
            max_scenes=max_scenes
        )
