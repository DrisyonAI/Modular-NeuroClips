import os
from pathlib import Path

# Prevent libiomp5md.dll clash on Windows / Anaconda environments
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    load_dotenv = None



# Repository root. src/batch_manager.py imports this.
BASE_DIR = Path(__file__).resolve().parent.parent

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./render_output"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CURRICULUM_OUTPUT_DIR = Path(os.getenv("CURRICULUM_OUTPUT_DIR", "./curriculum_output"))
CURRICULUM_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

EXPORTS_DIR = Path(os.getenv("EXPORTS_DIR", "./exports"))
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

ASSETS_DIR = Path(os.getenv("ASSETS_DIR", "./assets_library"))
ASSETS_DIR.mkdir(parents=True, exist_ok=True)

IDENTITIES_DIR = Path("./identities")
IDENTITIES_DIR.mkdir(parents=True, exist_ok=True)

DEVICE = os.getenv("DEVICE", "cuda")
T2I_MODEL = os.getenv("T2I_MODEL", "runwayml/stable-diffusion-v1-5")
I2V_MODEL = os.getenv("I2V_MODEL", "THUDM/CogVideoX-2b-I2V")

RESOLUTION_PROFILES = {
    "16:9_hd": {"name": "16:9 HD Broadcast (1280x720)", "width": 1280, "height": 720, "aspect": "16:9"},
    "16:9_sd": {"name": "16:9 SD Fast Preview (576x320)", "width": 576, "height": 320, "aspect": "16:9"},
    "16:9_fhd": {"name": "16:9 Full HD (1920x1080)", "width": 1920, "height": 1080, "aspect": "16:9"},
    "9:16_vertical": {"name": "9:16 Mobile Shorts (720x1280)", "width": 720, "height": 1280, "aspect": "9:16"},
    "1:1_square": {"name": "1:1 LMS Widget / Square (720x720)", "width": 720, "height": 720, "aspect": "1:1"}
}

RENDER_WIDTH = 1280
RENDER_HEIGHT = 720


def get_resolution_dimensions(resolution: str) -> tuple[int, int]:
    """
    Safely resolves a resolution profile key (e.g. '16:9_hd') or raw dimension
    string (e.g. '1280x720') into (width, height). Defaults to 1280x720.
    """
    if not resolution:
        return (RENDER_WIDTH, RENDER_HEIGHT)
    
    clean = str(resolution).strip().lower()
    if clean in RESOLUTION_PROFILES:
        prof = RESOLUTION_PROFILES[clean]
        return (prof["width"], prof["height"])
    
    if "x" in clean:
        parts = clean.split("x")
        try:
            w, h = int(parts[0]), int(parts[1])
            if w > 0 and h > 0:
                return (w, h)
        except (ValueError, IndexError):
            pass
            
    return (RENDER_WIDTH, RENDER_HEIGHT)


LANGUAGE_PROFILES = {
    "en-US": {
        "name": "English (US)",
        "flag": "🇺🇸",
        "default_voice": "en-US-GuyNeural",
        "voices": [
            {"id": "en-US-GuyNeural", "name": "Guy (Male - Professional)"},
            {"id": "en-US-AriaNeural", "name": "Aria (Female - Clear)"},
            {"id": "en-IN-NeerjaNeural", "name": "Neerja (Female - Indian Accent)"}
        ]
    },
    "te-IN": {
        "name": "Telugu (India)",
        "flag": "🇮🇳",
        "default_voice": "te-IN-MohanNeural",
        "voices": [
            {"id": "te-IN-MohanNeural", "name": "Mohan (Male - Deep Narrator)"},
            {"id": "te-IN-ShrutiNeural", "name": "Shruti (Female - Clear Instructional)"}
        ]
    },
    "ta-IN": {
        "name": "Tamil (India)",
        "flag": "🇮🇳",
        "default_voice": "ta-IN-PallaviNeural",
        "voices": [
            {"id": "ta-IN-PallaviNeural", "name": "Pallavi (Female - Clear Presenter)"},
            {"id": "ta-IN-ValluvarNeural", "name": "Valluvar (Male - Professional)"}
        ]
    },
    "hi-IN": {
        "name": "Hindi (India)",
        "flag": "🇮🇳",
        "default_voice": "hi-IN-MadhurNeural",
        "voices": [
            {"id": "hi-IN-MadhurNeural", "name": "Madhur (Male - Deep Narrator)"},
            {"id": "hi-IN-SwaraNeural", "name": "Swara (Female - Clear)"}
        ]
    },
    "es-ES": {
        "name": "Spanish (Castilian)",
        "flag": "🇪🇸",
        "default_voice": "es-ES-AlvaroNeural",
        "voices": [
            {"id": "es-ES-AlvaroNeural", "name": "Álvaro (Male - Executive)"},
            {"id": "es-ES-ElviraNeural", "name": "Elvira (Female - Instructional)"}
        ]
    },
    "fr-FR": {
        "name": "French (Standard)",
        "flag": "🇫🇷",
        "default_voice": "fr-FR-HenriNeural",
        "voices": [
            {"id": "fr-FR-HenriNeural", "name": "Henri (Male - Clear Accent)"},
            {"id": "fr-FR-DeniseNeural", "name": "Denise (Female - Educational)"}
        ]
    },
    "de-DE": {
        "name": "German (Standard)",
        "flag": "🇩🇪",
        "default_voice": "de-DE-ConradNeural",
        "voices": [
            {"id": "de-DE-ConradNeural", "name": "Conrad (Male - Professional)"},
            {"id": "de-DE-KatjaNeural", "name": "Katja (Female - Presenter)"}
        ]
    },
    "ja-JP": {
        "name": "Japanese (Tokyo)",
        "flag": "🇯🇵",
        "default_voice": "ja-JP-KeitaNeural",
        "voices": [
            {"id": "ja-JP-KeitaNeural", "name": "Keita (Male - Standard)"},
            {"id": "ja-JP-NanamiNeural", "name": "Nanami (Female - Presenter)"}
        ]
    }
}

AVATAR_PROFILES = [
    {
        "id": "maya_fintech",
        "name": "Maya (Senior FinTech Lead)",
        "role": "FinTech & Banking Lead",
        "avatar_url": "https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?q=80&w=400",
        "continuity_anchor": "30-year-old South Asian female FinTech executive with sleek black hair in navy blue tailored corporate blazer, modern trading floor background"
    },
    {
        "id": "alex_ai",
        "name": "Alex (Enterprise AI Architect)",
        "role": "AI Solutions Architect",
        "avatar_url": "https://images.unsplash.com/photo-1560250097-0b93528c311a?q=80&w=400",
        "continuity_anchor": "35-year-old male enterprise AI architect with glasses in charcoal minimalist tech blazer, modern server room command center background"
    },
    {
        "id": "elena_compliance",
        "name": "Elena (Risk & Governance Director)",
        "role": "Regulatory Compliance Officer",
        "avatar_url": "https://images.unsplash.com/photo-1580489944761-15a19d654956?q=80&w=400",
        "continuity_anchor": "40-year-old female compliance director in cream executive suit with gold accessories, high-tech glass boardroom background"
    },
    {
        "id": "david_trainer",
        "name": "David (Global LMS Instructor)",
        "role": "Instructional Specialist",
        "avatar_url": "https://images.unsplash.com/photo-1519085360753-af0119f7cbe7?q=80&w=400",
        "continuity_anchor": "38-year-old male instructional specialist in slate blue oxford shirt, modern interactive smart-classroom background"
    },
    {
        "id": "custom_upload",
        "name": "Custom Portrait (User Upload)",
        "role": "Guest Presenter",
        "avatar_url": "/static_renders/custom_avatar.png",
        "continuity_anchor": "professional executive instructor, corporate lighting, consistent character appearance"
    }
]

AVATAR_LAYOUT_MODES = [
    {"id": "pip_bottom_right", "name": "PiP Floating Glass Card (Bottom Right)"},
    {"id": "pip_top_right", "name": "PiP Floating Bubble (Top Right)"},
    {"id": "split_screen", "name": "Split Screen (60% Diagram / 40% Avatar)"},
    {"id": "full_anchor", "name": "Full Anchor (100% Presenter)"},
    {"id": "none", "name": "None (Diagram & B-roll Only)"}
]

ART_STYLE_PRESETS = [
    "Cinematic 35mm (Volumetric Lighting)",
    "Cyberpunk Neon (Futuristic Holograms)",
    "Anime Masterpiece (Studio Ghibli / Makoto Shinkai)",
    "Photorealistic 8K (Architectural / Corporate)",
    "Tech Hologram Data (Fintech Infographics)",
    "3D Pixar Animation (Stylized Characters)",
    "Dark Fantasy Epic (Moody Dramatic Contrast)",
    "Minimalist Vector (Modern Motion Flat 2D)"
]

VOICE_PROFILES = [
    {"id": "en-IN-NeerjaNeural", "name": "Neerja (en-IN, Female - Instructional)", "gender": "Female", "locale": "en-IN"},
    {"id": "en-US-GuyNeural", "name": "Guy (en-US, Male - Professional Narration)", "gender": "Male", "locale": "en-US"},
    {"id": "en-US-AriaNeural", "name": "Aria (en-US, Female - Conversational)", "gender": "Female", "locale": "en-US"},
    {"id": "en-IN-PrabhatNeural", "name": "Prabhat (en-IN, Male - Deep Executive)", "gender": "Male", "locale": "en-IN"},
    {"id": "en-GB-SoniaNeural", "name": "Sonia (en-GB, Female - BBC Accent)", "gender": "Female", "locale": "en-GB"}
]

DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8000"))
