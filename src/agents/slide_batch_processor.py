"""
Slide Batch Audio Processor for Voice Director Agent.
Extracts slide narration from Excel / PPTX decks, builds structured batch queues,
synthesizes neural audio conforming to M{m}_T{t}_L{l}_Slide{s}.mp3, and applies
EBU R128 loudness normalization and companion .srt subtitles.
"""
import re
import json
import zipfile
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from pydantic import BaseModel, Field

from src.agents.voice_director import VoiceDirectorAgent
from src.contracts.persona import PERSONA_CATALOG, PersonaIdentityContract
from src.contracts.script_contract import ScriptContract, ScriptScene


class SlideBatchItem(BaseModel):
    """Normalized audio generation task for a single slide."""
    module_num: int
    topic_num: int
    lesson_num: int
    slide_num: int
    title: str
    narration_text: str
    target_filename: str = Field(..., description="Target filename, e.g., M1_T2_L3_Slide2.mp3")
    source_type: str = "pptx_notes"  # "pptx_notes" or "excel_course_map"


class BatchProcessResult(BaseModel):
    """Result summary of a batch slide audio generation job."""
    total_slides: int
    successful_slides: int
    failed_slides: int
    output_directory: str
    manifest_file: str
    generated_files: List[Dict[str, Any]]


class SlideBatchProcessor:
    """
    Parses curriculum presentations / Excel course maps and orchestrates
    batch neural voice synthesis with exact naming conventions.
    """

    def __init__(self, voice_director: Optional[VoiceDirectorAgent] = None, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or Path("output/batch_slides")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.voice_director = voice_director or VoiceDirectorAgent(output_dir=self.output_dir)

    @staticmethod
    def _get_xml_text(xml_content: bytes) -> str:
        """Extracts text runs from OpenXML drawing or note structures."""
        root = ET.fromstring(xml_content)
        texts = [e.text for e in root.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}t") if e.text]
        return " ".join(texts)

    @staticmethod
    def extract_spoken_narration(raw_notes: str) -> str:
        """
        Cleans instructional metadata (OPEN, TEACH, FRAME, KEY POINT, SLIDE BUILD, stage cues)
        from PPTX presenter notes to produce pure natural spoken narration.
        """
        if not raw_notes or not raw_notes.strip():
            return ""

        # Pre-clean bracketed stage directions like [Click to advance], [Pause 2s], [Slide 3]
        clean_text = re.sub(r'\[[^\]]*\]', '', raw_notes)
        # Pre-clean parenthetical presenter directives
        clean_text = re.sub(r'\((?:pause|click|wait|emphasize|note|transition|build)[^)]*\)', '', clean_text, flags=re.IGNORECASE)

        # Check for structured OPEN / TEACH / FRAME sections
        open_match = re.search(r'OPEN\s+"([^"]+)"', clean_text)
        teach_match = re.search(
            r'TEACH\s+(.*?)(?:KEY POINT|SLIDE BUILD|ASK THE ROOM|TRANSITION|PARTICIPANT|$)',
            clean_text,
            re.IGNORECASE | re.DOTALL
        )
        frame_match = re.search(
            r'FRAME\s+(.*?)(?:TRANSITION|KEY POINT|SLIDE BUILD|PARTICIPANT|$)',
            clean_text,
            re.IGNORECASE | re.DOTALL
        )

        parts = []
        if open_match:
            parts.append(open_match.group(1).strip())
        if teach_match:
            parts.append(teach_match.group(1).strip())
        elif frame_match:
            parts.append(frame_match.group(1).strip())

        if parts:
            narration = " ".join(parts)
        else:
            # Strip metadata headers if present
            clean = re.sub(r'LESSON\s*/\s*TOPIC\s+[^\n]+', '', clean_text)
            clean = re.sub(r'OBJECTIVE\s+[^\n]+', '', clean)
            clean = re.sub(r'TIMING\s+\d+:\d+', '', clean)
            clean = re.sub(r'SLIDE BUILD\s+[^\n]+', '', clean)
            clean = re.sub(r'ASK THE ROOM\s+"[^"]+"', '', clean)
            clean = re.sub(r'TRANSITION\s+[^\n]+', '', clean)
            clean = re.sub(r'PARTICIPANT TAKEAWAY\s+[^\n]+', '', clean)
            narration = clean.strip()

        # Final sanitization: strip any remaining stage cues
        narration = re.sub(r'\[[^\]]*\]', '', narration)
        narration = re.sub(r'\((?:pause|click|wait|emphasize|note|transition|build)[^)]*\)', '', narration, flags=re.IGNORECASE)

        return re.sub(r'\s+', ' ', narration).strip()

    def parse_pptx_deck(
        self,
        pptx_path: Path,
        module_num: Optional[int] = None,
        slide_numbering: str = "lesson_relative"  # "lesson_relative" or "deck_absolute"
    ) -> List[SlideBatchItem]:
        """
        Parses a master PPTX deck into a sequence of SlideBatchItem tasks.
        Uses exact relationship lookup to link slides with their speaker notes.
        """
        if not pptx_path.exists():
            raise FileNotFoundError(f"Presentation deck not found: {pptx_path}")

        # Attempt to infer module from filename (e.g. M01_Timed_Master.pptx -> M1)
        if module_num is None:
            m_fn = re.search(r'M0?(\d+)', pptx_path.name, re.IGNORECASE)
            module_num = int(m_fn.group(1)) if m_fn else 1

        items: List[SlideBatchItem] = []
        with zipfile.ZipFile(pptx_path) as zf:
            namelist = zf.namelist()
            slide_files = [f for f in namelist if f.startswith("ppt/slides/slide") and f.endswith(".xml")]
            # Natural sort by slide index
            slide_files.sort(key=lambda f: int(re.search(r'slide(\d+)\.xml', f).group(1)))

            # Track slide index per (module, lesson) or (module, lesson, topic)
            lesson_slide_counter: Dict[Tuple[int, int], int] = {}

            for slide_rel_name in slide_files:
                slide_num_match = re.search(r'slide(\d+)\.xml', slide_rel_name)
                if not slide_num_match:
                    continue
                deck_slide_num = int(slide_num_match.group(1))

                # Read relationships to find exact notesSlide
                rel_path = f"ppt/slides/_rels/slide{deck_slide_num}.xml.rels"
                notes_target = None
                if rel_path in namelist:
                    r_tree = ET.fromstring(zf.read(rel_path))
                    for rel in r_tree:
                        if "notesSlide" in rel.get("Type", ""):
                            notes_target = rel.get("Target").replace("../notesSlides/", "ppt/notesSlides/")

                slide_text = self._get_xml_text(zf.read(slide_rel_name))
                raw_notes = self._get_xml_text(zf.read(notes_target)) if notes_target and notes_target in namelist else ""

                # Extract Lesson and Topic indices
                mod = module_num
                les = 1
                top = 1

                m_les = re.search(r'Lesson\s*(\d+)\.(\d+)', raw_notes)
                if m_les:
                    mod = int(m_les.group(1))
                    les = int(m_les.group(2))

                m_top = re.search(r'Topic\s*(\d+)', raw_notes)
                if m_top:
                    top = int(m_top.group(1))

                # Calculate slide number
                lesson_key = (mod, les)
                lesson_slide_counter[lesson_key] = lesson_slide_counter.get(lesson_key, 0) + 1

                if slide_numbering == "lesson_relative":
                    final_slide_num = lesson_slide_counter[lesson_key]
                else:
                    final_slide_num = deck_slide_num

                spoken_narration = self.extract_spoken_narration(raw_notes)
                if not spoken_narration:
                    # Fallback to visual slide text if notes are blank
                    spoken_narration = slide_text

                # Build canonical target filename: M1_T2_L3_Slide2.mp3
                filename = f"M{mod}_T{top}_L{les}_Slide{final_slide_num}.mp3"

                title = slide_text[:60].strip() if slide_text else f"Module {mod} Lesson {les} Slide {final_slide_num}"

                items.append(
                    SlideBatchItem(
                        module_num=mod,
                        topic_num=top,
                        lesson_num=les,
                        slide_num=final_slide_num,
                        title=title,
                        narration_text=spoken_narration,
                        target_filename=filename,
                        source_type="pptx_notes"
                    )
                )

        return items

    def parse_excel_course_map(
        self,
        excel_path: Path,
        sheet_name: str = "Course Map"
    ) -> List[SlideBatchItem]:
        """
        Parses an Excel Course Map (like temp-book.xlsx) into SlideBatchItem tasks.
        Slices multi-scene topics into individual slide audio tasks.
        """
        if not excel_path.exists():
            raise FileNotFoundError(f"Excel file not found: {excel_path}")

        items: List[SlideBatchItem] = []
        with zipfile.ZipFile(excel_path) as wb:
            shared_strings = []
            if "xl/sharedStrings.xml" in wb.namelist():
                sroot = ET.fromstring(wb.read("xl/sharedStrings.xml"))
                for si in sroot:
                    text = "".join([t.text for t in si.iter() if t.text])
                    shared_strings.append(text)

            # Locate target sheet xml
            wxml = ET.fromstring(wb.read("xl/workbook.xml"))
            sheet_target = "xl/worksheets/sheet1.xml"
            for s in wxml.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheet"):
                if s.get("name") == sheet_name:
                    rid = s.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
                    rels = ET.fromstring(wb.read("xl/_rels/workbook.xml.rels"))
                    for r in rels:
                        if r.get("Id") == rid:
                            sheet_target = "xl/" + r.get("Target")

            root = ET.fromstring(wb.read(sheet_target))
            rows = []
            for r in root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row"):
                row_vals = []
                for c in r.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"):
                    t = c.get("t")
                    v = c.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
                    val = ""
                    if v is not None and v.text is not None:
                        if t == "s":
                            idx = int(v.text)
                            val = shared_strings[idx] if idx < len(shared_strings) else ""
                        else:
                            val = v.text
                    row_vals.append(val)
                if any(row_vals):
                    rows.append(row_vals)

            if not rows:
                return []

            # Columns: [0:Course, 1:Module, 2:Lesson, 3:Topic, ... 7:Script, 9:Visuals, 10:Shots]
            # Track topics per lesson
            topic_index_map: Dict[Tuple[int, int], int] = {}

            for r in rows[1:]:
                mod_raw = r[1] if len(r) > 1 else ""
                les_raw = r[2] if len(r) > 2 else ""
                top_raw = r[3] if len(r) > 3 else ""
                script = r[7] if len(r) > 7 else ""

                if not script.strip():
                    continue

                # Parse Module number
                m_mod = re.search(r'(\d+)', mod_raw)
                mod_num = int(m_mod.group(1)) if m_mod else 1

                # Parse Lesson number (e.g. 1.2 -> L2)
                m_les = re.search(r'\d+\.(\d+)', les_raw)
                les_num = int(m_les.group(1)) if m_les else 1

                # Topic index within lesson
                lesson_key = (mod_num, les_num)
                topic_index_map[lesson_key] = topic_index_map.get(lesson_key, 0) + 1
                top_num = topic_index_map[lesson_key]

                # Decompose into scenes/slides (by double newline or paragraphs)
                paragraphs = [p.strip() for p in script.split("\n\n") if p.strip()]
                if not paragraphs:
                    paragraphs = [script.strip()]

                for p_idx, para in enumerate(paragraphs, start=1):
                    filename = f"M{mod_num}_T{top_num}_L{les_num}_Slide{p_idx}.mp3"
                    title = f"{top_raw[:40]} (Part {p_idx})" if len(paragraphs) > 1 else top_raw[:50]

                    items.append(
                        SlideBatchItem(
                            module_num=mod_num,
                            topic_num=top_num,
                            lesson_num=les_num,
                            slide_num=p_idx,
                            title=title,
                            narration_text=para,
                            target_filename=filename,
                            source_type="excel_course_map"
                        )
                    )

        return items

    def process_batch(
        self,
        items: List[SlideBatchItem],
        persona_id: str = "maya_fintech",
        speech_rate: float = 1.0,
        pitch: str = "+0Hz",
        target_lufs: float = -14.0,
        output_subfolder: Optional[str] = None,
        skip_existing: bool = True
    ) -> BatchProcessResult:
        """
        Iterates over the batch queue, synthesizes neural voice per slide,
        enforces naming conventions, and generates a manifest file.
        Supports idempotency via skip_existing=True to avoid re-synthesizing valid files.
        """
        dest_dir = self.output_dir
        if output_subfolder:
            dest_dir = dest_dir / output_subfolder
        dest_dir.mkdir(parents=True, exist_ok=True)

        persona = PERSONA_CATALOG.get(persona_id, PERSONA_CATALOG["maya_fintech"])
        generated_files: List[Dict[str, Any]] = []
        successful = 0
        failed = 0
        cached = 0

        for item in items:
            out_file = dest_dir / item.target_filename
            srt_file = out_file.with_suffix(".srt")

            # Check if valid cached version already exists
            if skip_existing and out_file.exists() and out_file.stat().st_size > 1000:
                duration = self.voice_director.probe_audio_duration(out_file)
                successful += 1
                cached += 1
                generated_files.append({
                    "filename": item.target_filename,
                    "module": item.module_num,
                    "topic": item.topic_num,
                    "lesson": item.lesson_num,
                    "slide": item.slide_num,
                    "duration_sec": duration,
                    "duration_ms": int(round(duration * 1000)),
                    "duration_frames": int(round(duration * 30)),
                    "words": len(item.narration_text.split()),
                    "status": "cached",
                    "path": str(out_file)
                })
                continue

            # Construct single-scene script contract
            estimated_sec = round(len(item.narration_text.split()) / 2.5, 2)
            scene = ScriptScene(
                scene_id=item.slide_num,
                title=item.title,
                visual_description=f"Slide visual for {item.title}",
                narration=item.narration_text,
                estimated_duration_sec=estimated_sec
            )
            script_contract = ScriptContract(
                course_title=item.title,
                persona_id=persona.persona_id,
                art_style_preset="corporate_fintech",
                total_word_count=len(item.narration_text.split()),
                estimated_total_runtime_sec=estimated_sec,
                scenes=[scene]
            )

            try:
                # Synthesize via VoiceDirectorAgent
                voice_contract = self.voice_director.synthesize_voice_contract(
                    script=script_contract,
                    persona=persona,
                    speech_rate=speech_rate,
                    pitch=pitch,
                    target_lufs=target_lufs
                )

                # Move/copy synthesized master to exact target filename
                master_src = Path(voice_contract.master_audio_path)
                if master_src.exists():
                    import shutil
                    shutil.copyfile(master_src, out_file)
                    if voice_contract.subtitles_srt_path and Path(voice_contract.subtitles_srt_path).exists():
                        shutil.copyfile(voice_contract.subtitles_srt_path, srt_file)

                duration = self.voice_director.probe_audio_duration(out_file)
                successful += 1
                generated_files.append({
                    "filename": item.target_filename,
                    "module": item.module_num,
                    "topic": item.topic_num,
                    "lesson": item.lesson_num,
                    "slide": item.slide_num,
                    "duration_sec": duration,
                    "duration_ms": int(round(duration * 1000)),
                    "duration_frames": int(round(duration * 30)),
                    "words": len(item.narration_text.split()),
                    "status": "success",
                    "path": str(out_file)
                })
            except Exception as e:
                failed += 1
                generated_files.append({
                    "filename": item.target_filename,
                    "module": item.module_num,
                    "topic": item.topic_num,
                    "lesson": item.lesson_num,
                    "slide": item.slide_num,
                    "status": "error",
                    "error": str(e)
                })

        manifest_path = dest_dir / "batch_manifest.json"
        manifest_data = {
            "total_slides": len(items),
            "successful": successful,
            "cached": cached,
            "failed": failed,
            "persona_used": persona.persona_id,
            "speech_rate": speech_rate,
            "files": generated_files
        }
        manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

        return BatchProcessResult(
            total_slides=len(items),
            successful_slides=successful,
            failed_slides=failed,
            output_directory=str(dest_dir),
            manifest_file=str(manifest_path),
            generated_files=generated_files
        )
