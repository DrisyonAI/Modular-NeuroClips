"""
Unit tests for SlideBatchProcessor.
Validates naming convention, presenter note cleaning, and slide batch structuring.
"""
import pytest
import re
from pathlib import Path
from unittest.mock import MagicMock

from src.agents.slide_batch_processor import SlideBatchProcessor, SlideBatchItem
from src.contracts.voice_contract import VoiceContract


def test_extract_spoken_narration_structured_teach():
    raw = """
    OPEN "Welcome to corporate valuation."
    TEACH In this lecture we discuss discounted cash flows and why WACC matters.
    KEY POINT WACC is the hurdle rate.
    TRANSITION Next slide shows the formula.
    """
    clean = SlideBatchProcessor.extract_spoken_narration(raw)
    assert clean == "Welcome to corporate valuation. In this lecture we discuss discounted cash flows and why WACC matters."


def test_extract_spoken_narration_bracketed_stage_cues():
    raw = "Let's review the balance sheet. [Click to advance] (Pause 2s) Notice the working capital. [Slide 4]"
    clean = SlideBatchProcessor.extract_spoken_narration(raw)
    assert "[Click to advance]" not in clean
    assert "(Pause 2s)" not in clean
    assert "[Slide 4]" not in clean
    assert clean == "Let's review the balance sheet. Notice the working capital."


def test_target_filename_pattern():
    item = SlideBatchItem(
        module_num=1,
        topic_num=2,
        lesson_num=3,
        slide_num=2,
        title="Discounted Cash Flow",
        narration_text="Sample text",
        target_filename="M1_T2_L3_Slide2.mp3"
    )
    pattern = r"^M(\d+)_T(\d+)_L(\d+)_Slide(\d+)\.mp3$"
    match = re.match(pattern, item.target_filename)
    assert match is not None
    assert int(match.group(1)) == 1
    assert int(match.group(2)) == 2
    assert int(match.group(3)) == 3
    assert int(match.group(4)) == 2


def test_process_batch_cached_skip(tmp_path):
    mock_vd = MagicMock()
    processor = SlideBatchProcessor(voice_director=mock_vd, output_dir=tmp_path)

    # Pre-create a dummy cached file
    test_file = tmp_path / "M1_T1_L1_Slide1.mp3"
    test_file.write_bytes(b"0" * 1500)

    mock_vd.probe_audio_duration.return_value = 5.2

    items = [
        SlideBatchItem(
            module_num=1,
            topic_num=1,
            lesson_num=1,
            slide_num=1,
            title="Intro",
            narration_text="Introduction narration",
            target_filename="M1_T1_L1_Slide1.mp3"
        )
    ]

    result = processor.process_batch(items, skip_existing=True)
    assert result.successful_slides == 1
    assert result.failed_slides == 0
    assert result.generated_files[0]["status"] == "cached"
    assert result.generated_files[0]["duration_frames"] == 156  # 5.2 * 30
    # VoiceDirector should NOT have synthesized
    mock_vd.synthesize_speech.assert_not_called()
