
import json
from typing import Dict, Any, AsyncGenerator
import requests, websockets

from .config import (
    QUEUE_URL, UPLOAD_IMAGE_URL, HEADERS, WS_OPEN_TIMEOUT, WS_PING_INTERVAL,
    WS_PING_TIMEOUT, WS_CLOSE_TIMEOUT, SERVER_ADDRESS
)
from .exceptions import ComfyUIError

def upload_file_to_comfyui(file_content: bytes, filename: str) -> None:
    payload = {"overwrite": "true", "type": "input", "subfolder": ""}
    files = [("image", (filename, file_content, "application/octet-stream"))]
    try:
        resp = requests.post(UPLOAD_IMAGE_URL, data=payload, files=files, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise ComfyUIError(f"Failed to upload {filename}: {exc}") from exc

def queue_prompt(workflow: Dict[str, Any], client_id: str) -> str:
    payload = {"prompt": workflow, "client_id": client_id}
    try:
        resp = requests.post(QUEUE_URL, json=payload, timeout=30, headers=HEADERS)
        resp.raise_for_status()
        prompt_id = resp.json().get("prompt_id")
    except requests.RequestException as exc:
        raise ComfyUIError(f"Queueing workflow failed: {exc}") from exc
    if not prompt_id:
        raise ComfyUIError("ComfyUI did not return a prompt_id")
    return prompt_id

async def monitor_progress_ws(prompt_id: str) -> AsyncGenerator[Dict[str, Any], None]:
    ws_url = f"wss://{SERVER_ADDRESS}/ws?prompt_id={prompt_id}"
    async with websockets.connect(
        ws_url,
        ping_interval=WS_PING_INTERVAL,
        ping_timeout=WS_PING_TIMEOUT,
        open_timeout=WS_OPEN_TIMEOUT,
        close_timeout=WS_CLOSE_TIMEOUT,
        max_size=None,
    ) as ws:
        async for message in ws:
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                continue
            yield data
