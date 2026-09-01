"""
Contracts and Schemas for Multi-Agent Video Generation Pipeline.
"""
from src.contracts.persona import PersonaIdentityContract, PERSONA_CATALOG, get_persona_contract
from src.contracts.script_contract import ScriptScene, ScriptContract
from src.contracts.voice_contract import SceneAudioArtifact, VoiceContract
from src.contracts.visual_contract import SceneVisualArtifact, ImageContract

__all__ = [
    "PersonaIdentityContract",
    "PERSONA_CATALOG",
    "get_persona_contract",
    "ScriptScene",
    "ScriptContract",
    "SceneAudioArtifact",
    "VoiceContract",
    "SceneVisualArtifact",
    "ImageContract",
]
