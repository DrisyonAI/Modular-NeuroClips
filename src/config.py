import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./render_output"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DEVICE = os.getenv("DEVICE", "cuda")
T2I_MODEL = os.getenv("T2I_MODEL", "runwayml/stable-diffusion-v1-5")
I2V_MODEL = os.getenv("I2V_MODEL", "THUDM/CogVideoX-2b-I2V")

# SD / 480p resolution profile
RENDER_WIDTH = int(os.getenv("RENDER_WIDTH", "576"))
RENDER_HEIGHT = int(os.getenv("RENDER_HEIGHT", "320"))

DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8000"))