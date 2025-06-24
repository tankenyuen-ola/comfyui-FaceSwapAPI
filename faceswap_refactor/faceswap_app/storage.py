
from pathlib import Path
import requests

from .exceptions import ComfyUIError
from .config import DOWNLOAD_DIR

def download_file_from_url(url: str) -> bytes:
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.content
    except requests.RequestException as exc:
        raise ComfyUIError(f"Unable to download {url}: {exc}") from exc

def save_file(data: bytes, filename: str, directory: Path | None = None) -> Path:
    directory = directory or DOWNLOAD_DIR
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / filename
    target.write_bytes(data)
    return target
