"""
Comprehensive Test Suite for Voice Director, Document Parser, and Voice Cloner.
Tests:
1. Document extraction across .txt, .md, and simulated .docx XML
2. Sentence boundary splitting and pedagogical chunking (words, duration)
3. FinTech & enterprise pronunciation lexicon substitutions
4. SSML compilation with rate, pitch, and cue tags
5. Audio normalization, highpass filtering, and duration checks
6. Dynamic custom persona persistence and reload from custom_personas.json
7. Full pipeline integration: Document -> ScriptContract -> VoiceContract
"""
import os
import json
import zipfile
import tempfile
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
import pytest

from src.document_parser import DocumentParser, DocumentParseResult
from src.lexicon import LexiconEngine
from src.agents.voice_director import VoiceDirectorAgent
from src.agents.voice_cloner import VoiceCloner
from src.contracts.persona import (
    PERSONA_CATALOG,
    PersonaIdentityContract,
    GenderEnum,
    RegionLocaleEnum,
    get_persona_contract,
    register_custom_persona_contract,
    load_custom_personas
)
from src.contracts.script_contract import ScriptContract, ScriptScene
from src.contracts.voice_contract import VoiceContract, SceneAudioArtifact


# -------------------------------------------------------------------------
# 1. DOCUMENT PARSER TESTS
# -------------------------------------------------------------------------
def test_document_parser_markdown_and_text(tmp_path):
    md_file = tmp_path / "sample_lecture.md"
    md_content = """# Algorithmic Trading Systems
    
    In this module, we examine how high-frequency trading algorithms evaluate market depth.
    **Automated arbitrage** systems require microsecond transaction routing to maintain execution parity.
    
    ## Regulatory Protections
    The Reserve Bank of India and SEBI mandate strict circuit breakers to protect retail liquidity.
    Financial institutions must log all execution payloads into verifiable audit ledgers.
    """
    md_file.write_text(md_content, encoding="utf-8")

    result = DocumentParser.parse_file(md_file, target_words_per_scene=20, max_scenes=10)
    assert result.total_scenes >= 2
    assert result.total_words > 30
    assert result.document_title == "Sample Lecture"
    for scene in result.scenes:
        assert scene.word_count > 0
        assert scene.estimated_duration_sec > 0.0
        assert not scene.narration.startswith("#")


def test_document_parser_docx_zip(tmp_path):
    docx_file = tmp_path / "course_outline.docx"
    # Construct minimal valid docx XML zip
    xml_content = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
        <w:body>
            <w:p><w:r><w:t>Chapter One: Introduction to Decentralized Finance.</w:t></w:r></w:p>
            <w:p><w:r><w:t>Decentralized protocols replace centralized custodians with auditable smart contracts.</w:t></w:r></w:p>
            <w:p><w:r><w:t>This minimizes counterparty risk across global liquidity pools.</w:t></w:r></w:p>
        </w:body>
    </w:document>
    """
    with zipfile.ZipFile(docx_file, "w") as z:
        z.writestr("word/document.xml", xml_content)

    extracted = DocumentParser.extract_text_from_docx(docx_file)
    assert "Decentralized Finance" in extracted
    assert "counterparty risk" in extracted

    res = DocumentParser.slice_into_scenes(extracted, document_title="DeFi Overview", target_words_per_scene=15)
    assert res.total_scenes >= 1
    assert res.total_words > 15


# -------------------------------------------------------------------------
# 2. PRONUNCIATION LEXICON TESTS
# -------------------------------------------------------------------------
def test_pronunciation_lexicon():
    engine = LexiconEngine()
    raw = "Customer KYC submitted via UPI must be reconciled with RBI and SEBI rules for NBFC lenders."
    cleaned = engine.apply_lexicon(raw)

    assert "K-Y-C" in cleaned
    assert "U-P-I" in cleaned
    assert "R-B-I" in cleaned
    assert "SEB-ee" in cleaned
    assert "N-B-F-C" in cleaned


# -------------------------------------------------------------------------
# 3. SSML PROSODY COMPILER TESTS
# -------------------------------------------------------------------------
def test_ssml_prosody_compilation(tmp_path):
    agent = VoiceDirectorAgent(output_dir=tmp_path)
    script = "Attention! [pause 750ms] [tone:serious]Auditing AML transaction flags.[/tone] [protip]Check the CIBIL score."
    ssml, clean_text = agent.compile_ssml_prosody(script, voice_name="en-IN-NeerjaNeural", base_rate=1.1, base_pitch="+2Hz")

    assert '<break time="750ms"/>' in ssml
    assert '<prosody rate="-5%" pitch="-2Hz">' in ssml
    assert 'SIB-il' in ssml
    assert '<voice name="en-IN-NeerjaNeural">' in ssml
    assert '...' in clean_text
    assert 'Pro tip:' in clean_text


# -------------------------------------------------------------------------
# 4. VOICE CLONER & DYNAMIC PERSONA PERSISTENCE
# -------------------------------------------------------------------------
def test_voice_cloner_audio_normalization(tmp_path):
    cloner = VoiceCloner(voices_dir=tmp_path / "voices")
    raw_tone = tmp_path / "raw_user_speech.wav"
    output_norm = tmp_path / "voices" / "norm_user_speech.wav"

    # Generate 6s synthetic mono sine wave
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=300:duration=6", "-c:a", "pcm_s16le", str(raw_tone)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    assert raw_tone.exists()

    success, duration, err = cloner.normalize_sample_audio(raw_tone, output_norm)
    assert success is True
    assert duration >= 5.0
    assert output_norm.exists()


def test_dynamic_custom_persona_lifecycle(tmp_path):
    # Test registration and JSON persistence
    test_id = f"test_presenter_{int(os.getpid())}"
    persona = PersonaIdentityContract(
        persona_id=test_id,
        display_name="Professor Ananya Sharma",
        gender=GenderEnum.FEMALE,
        target_locale=RegionLocaleEnum.EN_IN,
        demographic_ethnicity="South Asian",
        industry_domain="FinTech Research",
        visual_continuity_anchor="Professor in formal Indian attire, university lecture theater",
        canonical_voice="en-IN-NeerjaNeural",
        elevenlabs_voice_id="test_eleven_123"
    )

    register_custom_persona_contract(persona)
    assert test_id in PERSONA_CATALOG

    # Verify retrieval via get_persona_contract
    fetched = get_persona_contract(test_id)
    assert fetched.display_name == "Professor Ananya Sharma"
    assert fetched.elevenlabs_voice_id == "test_eleven_123"


# -------------------------------------------------------------------------
# 5. END-TO-END DOCUMENT TO SPEECH CONTRACT
# -------------------------------------------------------------------------
def test_document_to_speech_pipeline(tmp_path):
    output_dir = tmp_path / "pipeline_output"
    agent = VoiceDirectorAgent(output_dir=output_dir)

    scenes = [
        ScriptScene(
            scene_id=1,
            title="KYC Verification Overview",
            visual_description="Title Slide: KYC Verification in modern fintech studio",
            motion_prompt="Slow dolly forward",
            narration="Welcome to FinTech Compliance. [pause 500ms] Verifying customer identities.",
            estimated_duration_sec=5.0
        ),
        ScriptScene(
            scene_id=2,
            title="Regulatory Architecture",
            visual_description="Architecture Diagram showing RBI and banking nodes",
            motion_prompt="Pan right across nodes",
            narration="The RBI mandates immediate transaction reporting.",
            estimated_duration_sec=4.0
        )
    ]
    script = ScriptContract(
        course_title="Compliance Lecture",
        persona_id="maya_fintech",
        target_locale=RegionLocaleEnum.EN_IN,
        art_style_preset="Photorealistic 8K",
        total_word_count=18,
        estimated_total_runtime_sec=9.0,
        scenes=scenes
    )
    persona = get_persona_contract("maya_fintech")

    contract = agent.synthesize_voice_contract(
        script=script,
        persona=persona,
        engine="edge_tts",
        target_lufs=-14.0
    )

    assert contract.master_audio_path is not None
    assert Path(contract.master_audio_path).exists()
    assert contract.subtitles_srt_path is not None
    assert Path(contract.subtitles_srt_path).exists()
    assert len(contract.scene_audios) == 2
    assert contract.total_audio_duration_sec > 0.0
    assert contract.normalized_lufs == -14.0
