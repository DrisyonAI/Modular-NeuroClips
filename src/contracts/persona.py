"""
Persona Identity Contract and Canonical Demographic Catalog.
Ensures visual avatars, voice models, accents, and demographic anchors remain harmonized.
"""
from enum import Enum
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field


class GenderEnum(str, Enum):
    FEMALE = "female"
    MALE = "male"
    NON_BINARY = "non_binary"


class RegionLocaleEnum(str, Enum):
    EN_IN = "en-IN"   # South Asian / Indian English
    EN_US = "en-US"   # North American English
    EN_GB = "en-GB"   # British English
    TE_IN = "te-IN"   # Telugu
    TA_IN = "ta-IN"   # Tamil
    HI_IN = "hi-IN"   # Hindi
    ES_ES = "es-ES"   # Castilian Spanish
    FR_FR = "fr-FR"   # French
    DE_DE = "de-DE"   # German
    JA_JP = "ja-JP"   # Japanese


class PersonaIdentityContract(BaseModel):
    """
    Immutable identity anchor distributed to all sub-agents.
    """
    persona_id: str = Field(..., description="Unique key, e.g. 'maya_fintech'")
    display_name: str = Field(..., description="Human-readable presenter name")
    gender: GenderEnum
    target_locale: RegionLocaleEnum
    demographic_ethnicity: str = Field(..., description="Demographic ethnicity, e.g. 'South Asian'")
    industry_domain: str = Field(..., description="Domain expertise, e.g. 'FinTech'")
    visual_continuity_anchor: str = Field(
        ...,
        description="Immutable positive/negative prompt tokens for facial structure, wardrobe, and environment."
    )
    canonical_voice: str = Field(..., description="Primary Edge-TTS voice identifier")
    elevenlabs_voice_id: str = Field(default="21m00Tcm4TlvDq8ikWAM", description="Default ElevenLabs Voice ID")
    default_pitch: str = "+0Hz"
    default_speed: float = 1.0
    recommended_art_style: str = "Photorealistic 8K (Corporate / Tech)"


# Canonical Certified Persona Catalog
PERSONA_CATALOG: Dict[str, PersonaIdentityContract] = {
    "maya_fintech": PersonaIdentityContract(
        persona_id="maya_fintech",
        display_name="Maya (Senior FinTech Lead)",
        gender=GenderEnum.FEMALE,
        target_locale=RegionLocaleEnum.EN_IN,
        demographic_ethnicity="South Asian",
        industry_domain="FinTech & Algorithmic Markets",
        visual_continuity_anchor="30-year-old South Asian female FinTech executive with sleek black hair, tailored navy blue corporate blazer, modern trading floor background, soft studio lighting, ultra-realistic 8k",
        canonical_voice="en-IN-NeerjaNeural",
        elevenlabs_voice_id="21m00Tcm4TlvDq8ikWAM", # Rachel
        default_pitch="+1Hz",
        default_speed=1.0,
        recommended_art_style="Photorealistic 8K (Corporate / Tech)"
    ),
    "alex_ai": PersonaIdentityContract(
        persona_id="alex_ai",
        display_name="Alex (Enterprise AI Architect)",
        gender=GenderEnum.MALE,
        target_locale=RegionLocaleEnum.EN_US,
        demographic_ethnicity="Caucasian",
        industry_domain="Enterprise AI & Cloud Infrastructure",
        visual_continuity_anchor="35-year-old male enterprise AI architect with modern glasses, charcoal minimalist tech blazer, server room command center background, volumetric cinematic lighting",
        canonical_voice="en-US-GuyNeural",
        elevenlabs_voice_id="pNInz6obpgDQGcFmaJgB", # Adam
        default_pitch="-2Hz",
        default_speed=1.0,
        recommended_art_style="Cinematic 35mm (Volumetric Lighting)"
    ),
    "elena_compliance": PersonaIdentityContract(
        persona_id="elena_compliance",
        display_name="Elena (Risk & Governance Director)",
        gender=GenderEnum.FEMALE,
        target_locale=RegionLocaleEnum.EN_US,
        demographic_ethnicity="Hispanic / Latina",
        industry_domain="Regulatory Governance & Risk Compliance",
        visual_continuity_anchor="38-year-old Latina governance and risk director in elegant beige blazer, modern corporate boardroom background with glass panels, warm ambient lighting",
        canonical_voice="en-US-AriaNeural",
        elevenlabs_voice_id="EXAVITQu4vr4xnSDxMaL", # Bella
        default_pitch="+0Hz",
        default_speed=0.95,
        recommended_art_style="Photorealistic 8K (Corporate / Tech)"
    ),
    "david_trainer": PersonaIdentityContract(
        persona_id="david_trainer",
        display_name="David (Global LMS Instructor)",
        gender=GenderEnum.MALE,
        target_locale=RegionLocaleEnum.EN_US,
        demographic_ethnicity="Caucasian",
        industry_domain="Higher Education & Corporate Learning",
        visual_continuity_anchor="42-year-old male corporate learning instructor with friendly expression, navy sweater over collared shirt, modern university amphitheater background",
        canonical_voice="en-US-ChristopherNeural",
        elevenlabs_voice_id="TxGEqnHWrfWFTfGW9XjX", # Josh
        default_pitch="+0Hz",
        default_speed=1.0,
        recommended_art_style="Clean Minimalist Vector (Infographic)"
    ),
    "rajesh_cloud": PersonaIdentityContract(
        persona_id="rajesh_cloud",
        display_name="Rajesh (Principal Cloud Architect)",
        gender=GenderEnum.MALE,
        target_locale=RegionLocaleEnum.EN_IN,
        demographic_ethnicity="South Asian",
        industry_domain="Distributed Systems & Cloud Architecture",
        visual_continuity_anchor="40-year-old South Asian male principal cloud architect, subtle salt-and-pepper hair, formal light blue oxford shirt, modern glass whiteboard tech office background",
        canonical_voice="en-IN-PrabhatNeural",
        elevenlabs_voice_id="ErXwobaYiN019PkySvjV", # Antoni
        default_pitch="-1Hz",
        default_speed=1.0,
        recommended_art_style="Isometric 3D Tech (Cyberpunk / Studio)"
    )
}


def get_persona_contract(persona_id: str) -> PersonaIdentityContract:
    """Returns the canonical persona identity contract, falling back to Maya FinTech."""
    return PERSONA_CATALOG.get(persona_id, PERSONA_CATALOG["maya_fintech"])
