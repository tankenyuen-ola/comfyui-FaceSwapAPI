
import os
from pathlib import Path

SERVER_ADDRESS = os.getenv("COMFYUI_SERVER", "interview-excellent-fp-providers.trycloudflare.com")
QUEUE_URL = f"https://{SERVER_ADDRESS}/prompt"
HISTORY_URL = f"https://{SERVER_ADDRESS}/history"
VIDEO_URL = f"https://{SERVER_ADDRESS}/view"
UPLOAD_IMAGE_URL = f"https://{SERVER_ADDRESS}/upload/image"

WORKFLOW_TEMPLATE_PATH = Path(os.getenv("WORKFLOW_TEMPLATE_PATH", "/workspace/FaceSwap-Reactor-OSS-API.json"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/workspace/ComfyUI/output"))
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "/workspace/downloads"))

HEADERS = {"User-Agent": "faceswap-app/1.0"}

WS_OPEN_TIMEOUT = int(os.getenv("WS_OPEN_TIMEOUT", "60"))
WS_PING_INTERVAL = int(os.getenv("WS_PING_INTERVAL", "20"))
WS_PING_TIMEOUT = int(os.getenv("WS_PING_TIMEOUT", "20"))
WS_CLOSE_TIMEOUT = int(os.getenv("WS_CLOSE_TIMEOUT", "10"))
