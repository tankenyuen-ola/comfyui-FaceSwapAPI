import asyncio
import json
import uuid
import time
import copy
from pathlib import Path
from typing import Optional, Dict, Any, AsyncGenerator
import re
import os

import requests
import requests.exceptions
import websockets
from fastapi import FastAPI, File, UploadFile, HTTPException, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse
import uvicorn

# Configuration
SERVER_ADDRESS = "interview-excellent-fp-providers.trycloudflare.com"
QUEUE_URL = f"https://{SERVER_ADDRESS}/prompt"
HISTORY_URL = f"https://{SERVER_ADDRESS}/history"
VIDEO_URL = f"https://{SERVER_ADDRESS}/view"
UPLOAD_IMAGE_URL = f"https://{SERVER_ADDRESS}/upload/image"
WORKFLOW_PATH = "/workspace/FaceSwap-Reactor-API.json"
OUTPUT_DIR = Path("/workspace/ComfyUI/output")
DOWNLOAD_DIR = Path("/workspace/downloads")

# Ensure output directory exists
OUTPUT_DIR.mkdir(exist_ok=True)
DOWNLOAD_DIR.mkdir(exist_ok=True)

# FastAPI app
app = FastAPI(title="ComfyUI Face Swap API with WebSocket", version="2.0.0")

# Headers for requests
HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Cookie": "C.20984754_auth_token=af1ad767732eaa664611af8bf29b2b2cd3598dbeca534b4324748d1a029d2adc",
    "Origin": f"https://{SERVER_ADDRESS}",
    "Priority": "u=1, i",
    "Referer": f"https://{SERVER_ADDRESS}/",
    "Sec-Ch-Ua": '"Chromium";v="136", "Microsoft Edge";v="136", "Not.A/Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
}

WS_OPEN_TIMEOUT   = int(os.getenv("WS_OPEN_TIMEOUT",   "60"))   # seconds
WS_PING_INTERVAL  = int(os.getenv("WS_PING_INTERVAL",  "20"))
WS_PING_TIMEOUT   = int(os.getenv("WS_PING_TIMEOUT",   "20"))
WS_CLOSE_TIMEOUT  = int(os.getenv("WS_CLOSE_TIMEOUT",  "10"))
MAX_RETRIES = 3
BASE_DELAY  = 2  # seconds
WS_SEMAPHORE      = asyncio.Semaphore(int(os.getenv("WS_MAX_CONCURRENCY", "10")))

# -----------------------------------------------------------------------------
# Exceptions
# -----------------------------------------------------------------------------
class ComfyUIError(RuntimeError):
    """Raised for any ComfyUI‑related failure."""

# -----------------------------------------------------------------------------
# Workflow and File Management Functions
# -----------------------------------------------------------------------------

def validate_workflow_file():
    """Validate that the workflow file exists and is valid JSON."""
    if not Path(WORKFLOW_PATH).exists():
        raise FileNotFoundError(f"Workflow file not found: {WORKFLOW_PATH}")
    
    try:
        with open(WORKFLOW_PATH, "r") as f:
            json.load(f)
        print("✓ Workflow file validated")
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in workflow file: {e}")

def download_file_from_url(url: str) -> bytes:
    """Download file content from URL."""
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        return response.content
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Failed to download from URL: {str(e)}")

def upload_file_to_comfyui(file_content: bytes, uploaded_filename: str) -> bool:
    """Upload a file to ComfyUI."""
    payload = {
        "overwrite": "true",
        "type": "input",
        "subfolder": "",
    }
    
    files = [("image", (uploaded_filename, file_content, "application/octet-stream"))]
    response = requests.post(UPLOAD_IMAGE_URL, data=payload, files=files, headers=HEADERS)
    response.raise_for_status()
    return True

def load_and_patch_workflow(video_filename: str, image_filename: str, output_prefix: str) -> Dict[str, Any]:
    """Load and patch the FaceSwap workflow."""
    if not Path(WORKFLOW_PATH).exists():
        raise ComfyUIError(f"Workflow file not found: {WORKFLOW_PATH}")

    with open(WORKFLOW_PATH, "r", encoding="utf-8") as f:
        wf = json.load(f)

    wf = copy.deepcopy(wf)  # safety – do not mutate original

    # Patch workflow nodes for FaceSwap
    try:
        # Node 8 - Load Video
        wf["8"]["inputs"]["video"] = video_filename
    except Exception:
        print("⚠ Node 8 missing – skipping video patch")

    try:
        # Node 10 - Load Image
        wf["10"]["inputs"]["image"] = image_filename
    except Exception:
        print("⚠ Node 10 missing – skipping image patch")

    try:
        # Node 9 - Video Output
        wf["9"]["inputs"]["filename_prefix"] = output_prefix
    except Exception:
        print("⚠ Node 9 missing – skipping output prefix patch")

    return wf

def build_node_title_map(workflow: Dict[str, Any]) -> Dict[int, str]:
    """Return {node_id: 'Human-readable title'} extracted from _meta.title."""
    return {
        int(nid): node.get("_meta", {}).get("title", f"Node {nid}")
        for nid, node in workflow.items()
    }

def queue_prompt(workflow: Dict[str, Any], client_id: str) -> str:
    """POST to /prompt and get back the prompt_id."""
    payload = {"prompt": workflow, "client_id": client_id}
    try:
        resp = requests.post(QUEUE_URL, json=payload, timeout=30, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise ComfyUIError(f"Queueing prompt failed: {e}") from e

    prompt_id = data.get("prompt_id")
    if not prompt_id:
        raise ComfyUIError("/prompt did not return a prompt_id")
    return prompt_id

# -----------------------------------------------------------------------------
# WebSocket Progress Monitoring
# -----------------------------------------------------------------------------

async def monitor_progress_unified(
    prompt_id: str, 
    client_id: str, 
    node_titles: Dict[int, str]
):
    """
    Monitor function that yields SSE events for client streaming.
    """
    ws_url = f"wss://{SERVER_ADDRESS}/ws?clientId={client_id}"
    last_progress = -1.0
    last_status: Optional[str] = None
    idle = 0
    idle_limit = 60
    workflow_started = False
    workflow_completed = False

    async with WS_SEMAPHORE:
        for attempt in range(MAX_RETRIES):
            try:
                async with websockets.connect(
                    ws_url, 
                    additional_headers=HEADERS, 
                    max_size=None,
                    open_timeout=WS_OPEN_TIMEOUT,
                    ping_interval=WS_PING_INTERVAL,
                    ping_timeout=WS_PING_TIMEOUT,
                    close_timeout=WS_CLOSE_TIMEOUT
                ) as ws:
                    while True:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=5)
                            idle = 0
                        except asyncio.TimeoutError:
                            idle += 1
                            if idle > idle_limit:
                                error_msg = "WebSocket idle timeout exceeded"
                                print(f"[WS] ERROR: {error_msg}")
                                yield {
                                    "event": "error",
                                    "data": json.dumps({"detail": error_msg})
                                }
                                return
                            continue
        
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
        
                        mtype = msg.get("type")
                        data = msg.get("data", {})
        
                        # filter for our prompt
                        if data.get("prompt_id") not in (None, prompt_id):
                            continue
        
                        if mtype == "progress":
                            workflow_started = True
                            v, m = data.get("value", 0), data.get("max", 1)
                            if m:
                                pct = round(v / m * 100, 2)
                                if pct != last_progress:
                                    print(f"[WS] Progress: {pct}%")
                                    yield {
                                        "event": "progress",
                                        "data": json.dumps({
                                            "percentage": pct,
                                            "current": v,
                                            "total": m,
                                            "message": f"Face swap progress: {pct}%"
                                        })
                                    }
                                    last_progress = pct
                                    
                        elif mtype == "executing":
                            node_label = data.get("node_label") or data.get("node")
                            if node_label is None:
                                # Workflow is idle - if it was started before, it means completion
                                if workflow_started and not workflow_completed:
                                    workflow_completed = True
                                    print(f"[WS] Terminal status reached: completed. Closing connection.")
                                    yield {
                                        "event": "workflow_status",
                                        "data": json.dumps({
                                            "final_status": "completed",
                                            "message": "Face swap completed successfully. Connection closing."
                                        })
                                    }
                                    return
                                else:
                                    print("[WS] Executing: Idle (no active node)")
                                    yield {
                                        "event": "executing",
                                        "data": json.dumps({
                                            "node": "idle",
                                            "message": "Workflow idle (no active node)"
                                        })
                                    }
                            else:
                                workflow_started = True
                                try:
                                    node_id = int(node_label)
                                    title = node_titles.get(node_id, f"Node {node_label}")
                                    print(f"[WS] Executing: Node {node_label} ({title})")
                                    yield {
                                        "event": "executing",
                                        "data": json.dumps({
                                            "node": node_label,
                                            "title": title,
                                            "message": f"Executing: {title}"
                                        })
                                    }
                                except (ValueError, TypeError):
                                    print(f"[WS] Executing: Node {node_label} (invalid node ID)")
                                    yield {
                                        "event": "executing",
                                        "data": json.dumps({
                                            "node": str(node_label),
                                            "message": f"Executing Node {node_label}"
                                        })
                                    }
                                    
                        elif mtype == "status":
                            raw_status = data.get("status")
                            status = (
                                raw_status.get("status")
                                if isinstance(raw_status, dict)
                                else raw_status
                            )
                            if status != last_status:
                                print(f"[WS] Status: {status}")
                                yield {
                                    "event": "status_update",
                                    "data": json.dumps({"status": status})
                                }
                                last_status = status
                                
                            # Handle explicit terminal states (error, failed, cancelled)
                            if status in {"error", "failed", "cancelled"}:
                                workflow_completed = True
                                print(f"[WS] Terminal status reached: {status}. Closing connection.")
                                yield {
                                    "event": "workflow_status",
                                    "data": json.dumps({
                                        "final_status": status,
                                        "message": f"Face swap {status}. Connection closing."
                                    })
                                }
                                return
            except (asyncio.TimeoutError, websockets.InvalidStatusCode) as exc:
                wait = BASE_DELAY * 2 ** attempt
                logger.warning("WS handshake failed (%s). retrying in %ss", exc, wait)
                await asyncio.sleep(wait)
            except Exception as e:
                error_msg = f"WebSocket connection error: {str(e)}"
                print(f"[WS] ERROR: {error_msg}")
                yield {
                    "event": "error", 
                    "data": json.dumps({"detail": error_msg})
                }
    raise RuntimeError("WebSocket handshake failed after retries")

# -----------------------------------------------------------------------------
# Output File Retrieval
# -----------------------------------------------------------------------------

def fetch_output_file(prompt_id: str, output_prefix: str) -> Path:
    """Locate and download the generated video to DOWNLOAD_DIR."""
    try:
        history_response = requests.get(f"{HISTORY_URL}/{prompt_id}", headers=HEADERS, timeout=30).json()
    except Exception as e:
        raise ComfyUIError(f"Fetching /history failed: {e}") from e

    # The history response structure is: {prompt_id: {outputs: {...}, status: {...}, meta: {...}}}
    if not history_response:
        raise ComfyUIError("Empty history response")
    
    # Get the prompt data (should be the prompt_id key)
    prompt_data = history_response.get(prompt_id)
    if not prompt_data:
        # Fallback: try to get the first entry if prompt_id key doesn't exist
        prompt_data = next(iter(history_response.values()), None)
    
    if not prompt_data:
        raise ComfyUIError("No prompt data found in history response")
    
    outputs = prompt_data.get("outputs", {})
    if not outputs:
        raise ComfyUIError("No outputs present in history response")

    # Look for the video output - typically in node 9 for FaceSwap workflow
    video_output = None
    
    # First try node 9 (Video Output)
    if "9" in outputs:
        node_9_outputs = outputs["9"]
        # Look for different possible output types
        for output_type in ["gifs", "videos", "images"]:
            if output_type in node_9_outputs and node_9_outputs[output_type]:
                video_output = node_9_outputs[output_type][0]
                break
    
    if not video_output:
        # Fallback: search all outputs for video files
        for node_id, node_outputs in outputs.items():
            for output_type, output_list in node_outputs.items():
                if output_list and isinstance(output_list, list):
                    for item in output_list:
                        if isinstance(item, dict):
                            # Check if it's a video file by extension or format
                            filename = item.get("filename", "")
                            file_format = item.get("format", "")
                            if (filename.lower().endswith(('.mp4', '.avi', '.mov', '.mkv')) or 
                                file_format.startswith("video/")):
                                video_output = item
                                break
                    if video_output:
                        break
            if video_output:
                break
    
    if not video_output:
        raise ComfyUIError("No video output found in history response")

    filename = video_output.get("filename")
    subfolder = video_output.get("subfolder", "")

    if not filename:
        raise ComfyUIError("Filename missing in video output")

    # Construct the view URL
    params = {"filename": filename, "type": "output"}
    if subfolder:
        params["subfolder"] = subfolder
    
    # Build URL with parameters
    url_params = "&".join([f"{k}={v}" for k, v in params.items()])
    url = f"{VIDEO_URL}?{url_params}"
    
    # Use the output prefix for the downloaded file name
    target = DOWNLOAD_DIR / f"{output_prefix}.mp4"

    try:
        with requests.get(url, stream=True, headers=HEADERS, timeout=60) as r:
            r.raise_for_status()
            with target.open("wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
    except Exception as e:
        raise ComfyUIError(f"Failed to download video file: {e}") from e
        
    return target

# -----------------------------------------------------------------------------
# API Endpoints
# -----------------------------------------------------------------------------

# Helper function for error responses
async def async_error_generator(error_message: str):
    """Helper to generate a single error event."""
    yield {"event": "error", "data": json.dumps({"detail": error_message})}

@app.post("/face-swap")
async def face_swap_sse(
    video: Optional[UploadFile] = File(None, description="Input video file"),
    image: Optional[UploadFile] = File(None, description="Source face image file"),
    video_url: Optional[str] = Form(None, description="Video URL (alternative to file upload)"),
    image_url: Optional[str] = Form(None, description="Image URL (alternative to file upload)"),
    output_name: Optional[str] = Form(None, description="Custom output filename prefix")
):
    """
    Perform face swap with real-time progress via Server-Sent Events.
    """
    
    # Validate inputs
    if not ((video or video_url) and (image or image_url)):
        return EventSourceResponse(
            lambda: async_error_generator("Must provide either video file or video_url, and either image file or image_url")
        )
    
    # Pre-process files BEFORE creating the async generator
    ts = time.strftime("%Y%m%d_%H%M%S")
    
    try:
        # Validate workflow file
        validate_workflow_file()
        
        # Generate unique filenames to avoid conflicts
        video_suffix = '.mp4'
        image_suffix = '.png'
        
        if video:
            video_suffix = Path(video.filename).suffix or '.mp4'
        if image:
            image_suffix = Path(image.filename).suffix or '.png'
        
        video_filename = f"input_video_{uuid.uuid4()}{video_suffix}"
        image_filename = f"input_image_{uuid.uuid4()}{image_suffix}"
        output_prefix = output_name or f"faceswap_{ts}"
        
        # Get video content
        if video:
            video_content = await video.read()
            print(f"Using uploaded video file: {video.filename}")
        else:
            print(f"Downloading video from URL: {video_url}")
            video_content = download_file_from_url(video_url)
        
        # Get image content
        if image:
            image_content = await image.read()
            print(f"Using uploaded image file: {image.filename}")
        else:
            print(f"Downloading image from URL: {image_url}")
            image_content = download_file_from_url(image_url)
        
    except Exception as e:
        return EventSourceResponse(
            lambda: async_error_generator(f"File processing failed: {str(e)}")
        )
    
    async def generate_progress_stream():
        try:
            # Setup phase
            yield {"event": "status", "data": json.dumps({"message": "Setting up face swap processing..."})}
            
            # Upload files
            yield {"event": "status", "data": json.dumps({"message": "Uploading video file..."})}
            upload_file_to_comfyui(video_content, video_filename)
            
            yield {"event": "status", "data": json.dumps({"message": "Uploading image file..."})}
            upload_file_to_comfyui(image_content, image_filename)
            
            # Workflow preparation
            yield {"event": "status", "data": json.dumps({"message": "Preparing ComfyUI workflow..."})}
            
            workflow = load_and_patch_workflow(video_filename, image_filename, output_prefix)
            node_titles = build_node_title_map(workflow)

            # Queue workflow
            yield {"event": "status", "data": json.dumps({"message": "Queueing face swap workflow..."})}
            
            client_id = str(uuid.uuid4())
            try:
                prompt_id = queue_prompt(workflow, client_id)
                yield {
                    "event": "queued",
                    "data": json.dumps({
                        "prompt_id": prompt_id, 
                        "message": "Face swap workflow queued successfully!"
                    })
                }
            except ComfyUIError as e:
                yield {"event": "error", "data": json.dumps({"detail": str(e)})}
                return

            # Stream progress updates
            final_status = None
            async for progress_event in monitor_progress_unified(prompt_id, client_id, node_titles):
                yield progress_event
                if progress_event.get("event") == "workflow_status":
                    event_data = json.loads(progress_event["data"])
                    final_status = event_data.get("final_status")
                    break

            # Handle completion
            if final_status in {"completed", "finished"}:
                yield {"event": "status", "data": json.dumps({"message": "Retrieving face-swapped video..."})}
                try:
                    out_file = fetch_output_file(prompt_id, output_prefix)
                    yield {
                        "event": "completed",
                        "data": json.dumps({
                            "message": "🎉 Face swap completed successfully!",
                            "filename": out_file.name,
                            "download_url": f"/download/{out_file.name}",
                            "prompt_id": prompt_id,
                            "output_prefix": output_prefix
                        })
                    }
                except ComfyUIError as e:
                    yield {"event": "error", "data": json.dumps({"detail": str(e)})}
            else:
                yield {
                    "event": "error",
                    "data": json.dumps({"detail": f"Face swap failed with status: {final_status}"})
                }

        except Exception as e:
            yield {"event": "error", "data": json.dumps({"detail": f"Unexpected error: {str(e)}"})}

    return EventSourceResponse(generate_progress_stream())

@app.websocket("/face-swap-ws")
async def face_swap_websocket(ws: WebSocket):
    """WebSocket endpoint for face swap with real-time progress."""
    await ws.accept()
    try:
        # Receive parameters
        msg = await ws.receive_text()
        params = json.loads(msg)
        
        video_input = params.get("video_url") or params.get("video_path")
        image_input = params.get("image_url") or params.get("image_path")
        output_name = params.get("output_name")
        
        if not video_input or not image_input:
            await ws.send_text(json.dumps({
                "type": "error", 
                "detail": "Both video_input and image_input are required"
            }))
            return
        
        ts = time.strftime("%Y%m%d_%H%M%S")
        output_prefix = output_name or f"faceswap_{ts}"
        
        # Download files if URLs provided
        if video_input.startswith("http"):
            video_content = download_file_from_url(video_input)
            video_filename = f"input_video_{ts}.mp4"
        else:
            # Assume local file path
            with open(video_input, "rb") as f:
                video_content = f.read()
            video_filename = f"input_video_{ts}{Path(video_input).suffix}"
        
        if image_input.startswith("http"):
            image_content = download_file_from_url(image_input)
            image_filename = f"input_image_{ts}.png"
        else:
            # Assume local file path
            with open(image_input, "rb") as f:
                image_content = f.read()
            image_filename = f"input_image_{ts}{Path(image_input).suffix}"
        
        # Upload files
        upload_file_to_comfyui(video_content, video_filename)
        upload_file_to_comfyui(image_content, image_filename)
        
        # Prepare workflow
        workflow = load_and_patch_workflow(video_filename, image_filename, output_prefix)
        node_titles = build_node_title_map(workflow)
        
        # Queue workflow
        client_id = str(uuid.uuid4())
        prompt_id = queue_prompt(workflow, client_id)
        
        await ws.send_text(json.dumps({"type": "queued", "prompt_id": prompt_id}))
        
        # Monitor progress
        final_status = None
        async for progress_event in monitor_progress_unified(prompt_id, client_id, node_titles):
            await ws.send_text(json.dumps(progress_event))
            if progress_event.get("event") == "workflow_status":
                event_data = json.loads(progress_event["data"])
                final_status = event_data.get("final_status")
                break
        
        # Send final result
        if final_status in {"completed", "finished"}:
            out_file = fetch_output_file(prompt_id, output_prefix)
            await ws.send_text(json.dumps({
                "type": "completed",
                "filename": out_file.name,
                "download_url": f"/download/{out_file.name}",
                "prompt_id": prompt_id
            }))
            
            # Optionally send the file as bytes
            with out_file.open("rb") as f:
                await ws.send_bytes(f.read())
        
    except WebSocketDisconnect:
        return
    except Exception as e:
        await ws.send_text(json.dumps({"type": "error", "detail": str(e)}))
    finally:
        await ws.close()

@app.get("/download/{filename}")
async def download_file(filename: str):
    """Download a processed video file."""
    file_path = DOWNLOAD_DIR / filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(
        path=file_path,
        media_type="video/mp4",
        filename=filename
    )

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        # Test connection to ComfyUI
        response = requests.get(f"https://{SERVER_ADDRESS}/", timeout=5, headers=HEADERS)
        comfyui_status = "healthy" if response.status_code == 200 else "unhealthy"
    except:
        comfyui_status = "unreachable"
    
    # Check workflow file
    try:
        validate_workflow_file()
        workflow_status = "valid"
    except:
        workflow_status = "invalid"
    
    return {
        "status": "healthy",
        "comfyui_status": comfyui_status,
        "workflow_status": workflow_status,
        "server_address": SERVER_ADDRESS,
        "workflow_path": WORKFLOW_PATH,
        "communication_method": "WebSocket + SSE",
        "output_directory": str(OUTPUT_DIR)
    }

@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "message": "ComfyUI Face Swap API with WebSocket + SSE",
        "version": "2.0.0",
        "description": "Face swap service using ComfyUI Reactor workflow with real-time progress",
        "endpoints": {
            "face_swap_sse": "POST /face-swap (Server-Sent Events)",
            "face_swap_ws": "WebSocket /face-swap-ws",
            "download": "GET /download/{filename}",
            "health": "GET /health"
        },
        "usage": {
            "sse_endpoint": {
                "method": "POST /face-swap",
                "description": "Real-time progress via Server-Sent Events",
                "file_upload": "Use 'video' and 'image' form fields",
                "url_input": "Use 'video_url' and 'image_url' form fields",
                "output_name": "Optional custom output filename prefix"
            },
            "websocket_endpoint": {
                "method": "WebSocket /face-swap-ws",
                "description": "Real-time progress via WebSocket",
                "parameters": {
                    "video_url": "URL or local path to video",
                    "image_url": "URL or local path to image",
                    "output_name": "Optional output filename prefix"
                }
            }
        },
        "features": [
            "Real-time progress monitoring",
            "WebSocket and SSE support",
            "Automatic file upload to ComfyUI",
            "Error handling and recovery",
            "No polling - event-driven architecture"
        ]
    }

if __name__ == "__main__":
    print(f"▶ Starting FaceSwap API with WebSocket + SSE on http://0.0.0.0:8000")
    print(f"▶ ComfyUI Server: {SERVER_ADDRESS}")
    uvicorn.run(app, host="0.0.0.0", port=8000)