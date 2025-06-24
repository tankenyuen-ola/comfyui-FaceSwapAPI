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
from fastapi import FastAPI, HTTPException, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse
import uvicorn
from datetime import datetime, timezone
import logging

# -----------------------------------------------------------------------------
# Logging Configuration
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("faceswap_api")

# -----------------------------------------------------------------------------
# Configuration

SERVER_ADDRESS = "assessment-vertical-stood-live.trycloudflare.com"
QUEUE_URL = f"https://{SERVER_ADDRESS}/prompt"
HISTORY_URL = f"https://{SERVER_ADDRESS}/history"
WORKFLOW_PATH = "/workspace/FaceSwap-Reactor-OSS-API-FINAL.json"
WORKFLOW_STATUS_CACHE = {}

# FastAPI app
app = FastAPI(title="ComfyUI Face Swap OSS API", version="2.0.0")

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

def detect_workflow_type(data: dict) -> str:
    """
    Decide whether *data* represents a normal ComfyUI GUI workflow
    or an API-style prompt created with “Save (API format)”.
    Returns: "normal", "api", or "unknown".
    """
    # ---------- bullet-proof early exits ----------
    if "nodes" in data and isinstance(data["nodes"], list):
        # Standard GUI export always has a 'nodes' array
        return "normal"

    # ---------- heuristic scores ----------
    api_score, normal_score = 0, 0
    numeric = lambda k: isinstance(k, (str, int)) and str(k).isdigit()

    for k, v in data.items():
        if numeric(k):                                       # "1", "2", …
            api_score += 1
            if isinstance(v, dict):
                if {"class_type", "inputs"} <= v.keys():
                    api_score += 2
                if "_meta" in v:
                    api_score += 1

    for fld in ("links", "groups", "config", "version", "state"):
        normal_score += fld in data

    # ---------- thresholds ----------
    if api_score >= 2 and normal_score == 0:
        return "api"
    if normal_score >= 2:
        return "normal"
    return "unknown"

def validate_workflow_file():
    """
    Confirm the JSON file exists *and* is an API-style prompt.
    Raises:
        FileNotFoundError – path does not exist
        ValueError        – file is not an API workflow
    Returns:
        dict – parsed JSON when OK
    """
    if not Path(WORKFLOW_PATH).exists():
        logger.error(f"Workflow file not found: {WORKFLOW_PATH}")
        raise FileNotFoundError(f"Workflow file not found: {WORKFLOW_PATH}")

    try:
        data = json.loads(Path(WORKFLOW_PATH).read_text())
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in workflow file: {e}")
        raise ValueError(f"Invalid JSON in workflow file: {e}") from None

    wtype = detect_workflow_type(data)
    if wtype != "api":
        logger.error("ComfyUI workflow supplied – please provide an API-exported prompt.")
        raise ValueError(
            f"{wtype.capitalize() if wtype!='unknown' else 'Unrecognised'} "
            "ComfyUI workflow supplied – please provide an API-exported prompt."
        )
    logger.info("✓ API-based ComfyUI workflow detected")

def load_and_patch_workflow(video_filename: str, image_filename: str, output_prefix: str) -> Dict[str, Any]:
    """Load and patch the OSS-based FaceSwap workflow."""
    if not Path(WORKFLOW_PATH).exists():
        logger.error(f"Workflow file not found: {WORKFLOW_PATH}")
        raise ComfyUIError(f"Workflow file not found: {WORKFLOW_PATH}")

    with open(WORKFLOW_PATH, "r", encoding="utf-8") as f:
        wf = json.load(f)

    wf = copy.deepcopy(wf)  # safety – do not mutate original

    # Patch workflow nodes for OSS-based FaceSwap
    try:
        # Node 79 - Load Video from OSS (oss2vid)
        if "79" in wf:
            wf["79"]["inputs"]["filename"] = video_filename
            logger.info(f"✓ Patched Node 79 (oss2vid) with video filename: {video_filename}")
    except Exception as e:
        logger.error(f"⚠ Node 79 (oss2vid) patch failed: {e}")

    try:
        # Node 78 - Load Image from OSS (oss2image)  
        if "78" in wf:
            wf["78"]["inputs"]["filename"] = image_filename
            logger.info(f"✓ Patched Node 78 (oss2image) with image filename: {image_filename}")
    except Exception as e:
        logger.error(f"⚠ Node 78 (oss2image) patch failed: {e}")

    try:
        # Node 9 - Video Output (filename_prefix for local processing)
        if "9" in wf:
            wf["9"]["inputs"]["filename_prefix"] = output_prefix
            logger.info(f"✓ Patched Node 9 (Video Combine) with output prefix: {output_prefix}")
    except Exception as e:
        logger.error(f"⚠ Node 9 (Video Combine) patch failed: {e}")

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
        logger.error(f"Queueing prompt failed: {e}")
        raise ComfyUIError(f"Queueing prompt failed: {e}") from e

    prompt_id = data.get("prompt_id")
    if not prompt_id:
        logger.error("/prompt did not return a prompt_id")
        raise ComfyUIError("/prompt did not return a prompt_id")
    return prompt_id

# Add this helper function to update status cache
def update_workflow_status(prompt_id: str, status: str, progress_data: dict = None, error: str = None, result_url: str = None):
    """Update the workflow status cache."""
    current_time = datetime.now(timezone.utc).isoformat()
    
    if prompt_id not in WORKFLOW_STATUS_CACHE:
        WORKFLOW_STATUS_CACHE[prompt_id] = {
            "prompt_id": prompt_id,
            "status": "QUEUED",
            "progress": {"percentage": 0, "step": "Initializing"},
            "created_at": current_time,
            "updated_at": current_time,
            "result": None,
            "error": None
        }
    
    # Update the status
    WORKFLOW_STATUS_CACHE[prompt_id]["status"] = status
    WORKFLOW_STATUS_CACHE[prompt_id]["updated_at"] = current_time
    
    if progress_data:
        WORKFLOW_STATUS_CACHE[prompt_id]["progress"] = progress_data
    
    if error:
        WORKFLOW_STATUS_CACHE[prompt_id]["error"] = error
        
    if result_url:
        WORKFLOW_STATUS_CACHE[prompt_id]["result"] = result_url

async def process_workflow_background(prompt_id: str, client_id: str, node_titles: Dict[int, str], output_prefix: str):
    """Background task to process workflow when prompt_id_only mode is used."""
    try:
        logger.info(f"[Background] Starting background processing for prompt_id: {prompt_id}")
        
        # Ensure the status is properly initialized
        update_workflow_status(prompt_id, "PROCESSING", {
            "percentage": 0,
            "step": "Starting background processing"
        })
        
        final_status = None
        error_encountered = False
        
        try:
            async for progress_event in monitor_progress_unified(prompt_id, client_id, node_titles):
                # The status cache is updated by monitor_progress_unified
                if progress_event.get("event") == "workflow_status":
                    event_data = json.loads(progress_event["data"])
                    final_status = event_data.get("final_status")
                    logger.info(f"[Background] Received final status: {final_status}")
                    break
                elif progress_event.get("event") == "error":
                    error_data = json.loads(progress_event["data"])
                    error_msg = error_data.get("detail", "Unknown error")
                    update_workflow_status(prompt_id, "FAILED", error=error_msg)
                    logger.info(f"[Background] Error during processing: {error_msg}")
                    error_encountered = True
                    break
        except Exception as monitor_error:
            error_msg = f"Error in monitor_progress_unified: {str(monitor_error)}"
            update_workflow_status(prompt_id, "FAILED", error=error_msg)
            logger.error(f"[Background] Monitor error for prompt_id: {prompt_id}, error: {error_msg}")
            return
        
        if error_encountered:
            return
        
        # Handle completion - for OSS workflow, success means files were uploaded and deleted
        if final_status in {"completed", "finished", "uploaded"}:
            update_workflow_status(prompt_id, "SUCCESS", {
                "percentage": 100,
                "step": "Face swap completed and uploaded to OSS. Local file deleted."
            })
            logger.info(f"[Background] Face swap completed for prompt_id: {prompt_id}")
        elif final_status in {"error", "failed", "cancelled"}:
            error_msg = f"Face swap failed with status: {final_status}"
            update_workflow_status(prompt_id, "FAILED", error=error_msg)
            logger.error(f"[Background] Face swap failed for prompt_id: {prompt_id}, status: {final_status}")
        else:
            # If we exit the monitor loop without a clear final status
            logger.warning(f"[Background] Monitor loop ended without clear final status. Final status: {final_status}")
            # For OSS workflow, we assume success if no errors were encountered
            update_workflow_status(prompt_id, "SUCCESS", {
                "percentage": 100,
                "step": "Face swap processing completed"
            })
            logger.warning(f"[Background] Face swap completed (fallback) for prompt_id: {prompt_id}")
            
    except Exception as e:
        error_msg = f"Unexpected error in background processing: {str(e)}"
        update_workflow_status(prompt_id, "FAILED", error=error_msg) 
        logger.error(f"[Background] Unexpected error for prompt_id: {prompt_id}, error: {error_msg}")

# -----------------------------------------------------------------------------
# WebSocket Progress Monitoring
# -----------------------------------------------------------------------------

async def monitor_progress_unified(
    prompt_id: str, 
    client_id: str, 
    node_titles: Dict[int, str]
):
    """
    Monitor function that yields SSE events for client streaming and updates status cache.
    Modified for OSS workflow to handle upload and deletion events.
    """
    # Initialize status cache
    update_workflow_status(prompt_id, "PROCESSING", {"percentage": 0, "step": "Starting"})
    
    ws_url = f"wss://{SERVER_ADDRESS}/ws?clientId={client_id}"
    last_progress = -1.0
    last_status: Optional[str] = None
    idle = 0
    idle_limit = 60
    workflow_started = False
    workflow_completed = False
    oss_uploaded = False
    files_deleted = False

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
                                logger.error(f"[WS] ERROR: {error_msg}")
                                update_workflow_status(prompt_id, "FAILED", error=error_msg)
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
                                    logger.info(f"[WS] Progress: {pct}%")
                                    # Update status cache
                                    update_workflow_status(prompt_id, "PROCESSING", {
                                        "percentage": pct,
                                        "step": f"Face swap progress: {pct}%"
                                    })
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
                                    
                                    # For OSS workflow, determine final status based on node completion
                                    if oss_uploaded and files_deleted:
                                        final_status = "uploaded"
                                        status_msg = "Face swap completed, uploaded to OSS, and local files deleted"
                                    elif oss_uploaded:
                                        final_status = "uploaded" 
                                        status_msg = "Face swap completed and uploaded to OSS"
                                    else:
                                        final_status = "completed"
                                        status_msg = "Face swap completed"
                                    
                                    logger.info(f"[WS] Terminal status reached: {final_status}. Closing connection.")
                                    update_workflow_status(prompt_id, "SUCCESS", {
                                        "percentage": 100,
                                        "step": status_msg
                                    })
                                    yield {
                                        "event": "workflow_status",
                                        "data": json.dumps({
                                            "final_status": final_status,
                                            "message": f"{status_msg}. Connection closing."
                                        })
                                    }
                                    return
                                else:
                                    logger.info("[WS] Executing: Idle (no active node)")
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
                                    logger.info(f"[WS] Executing: Node {node_label} ({title})")
                                    
                                    # Special handling for OSS workflow nodes
                                    step_message = f"Executing: {title}"
                                    progress_pct = last_progress if last_progress > 0 else 25
                                    
                                    # Node 44: Aliyun OSS Upload File
                                    if node_id == 44:
                                        step_message = "Uploading face-swapped video to Aliyun OSS"
                                        progress_pct = 85
                                        oss_uploaded = True
                                        logger.info("[WS] OSS Upload node executing - marking as uploaded")
                                        
                                    # Node 76: Delete Files
                                    elif node_id == 76:
                                        step_message = "Deleting local temporary files"
                                        progress_pct = 95
                                        files_deleted = True
                                        logger.info("[WS] Delete Files node executing - local file will be deleted")
                                    
                                    # Update status cache with current step
                                    update_workflow_status(prompt_id, "PROCESSING", {
                                        "percentage": progress_pct,
                                        "step": step_message
                                    })
                                    yield {
                                        "event": "executing",
                                        "data": json.dumps({
                                            "node": node_label,
                                            "title": title,
                                            "message": step_message
                                        })
                                    }
                                except (ValueError, TypeError):
                                    logger.error(f"[WS] Executing: Node {node_label} (invalid node ID)")
                                    update_workflow_status(prompt_id, "PROCESSING", {
                                        "percentage": last_progress if last_progress > 0 else 25,
                                        "step": f"Executing Node {node_label}"
                                    })
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
                                logger.info(f"[WS] Status: {status}")
                                yield {
                                    "event": "status_update",
                                    "data": json.dumps({"status": status})
                                }
                                last_status = status
                                
                            # Handle explicit terminal states (error, failed, cancelled)
                            if status in {"error", "failed", "cancelled"}:
                                workflow_completed = True
                                logger.info(f"[WS] Terminal status reached: {status}. Closing connection.")
                                update_workflow_status(prompt_id, "FAILED", {
                                    "percentage": 0,
                                    "step": f"Workflow {status}"
                                }, error=f"Face swap {status}")
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
                logger.warning(f"WS handshake failed ({exc}). retrying in {wait}s")
                await asyncio.sleep(wait)
            except Exception as e:
                error_msg = f"WebSocket connection error: {str(e)}"
                logger.error(f"[WS] ERROR: {error_msg}")
                update_workflow_status(prompt_id, "FAILED", error=error_msg)
                yield {
                    "event": "error", 
                    "data": json.dumps({"detail": error_msg})
                }
    raise RuntimeError("WebSocket handshake failed after retries")

# -----------------------------------------------------------------------------
# API Endpoints
# -----------------------------------------------------------------------------

# Helper function for error responses
async def async_error_generator(error_message: str):
    """Helper to generate a single error event."""
    yield {"event": "error", "data": json.dumps({"detail": error_message})}

@app.post("/face-swap")
async def face_swap_sse(
    video_filename: str = Form(..., description="Video filename in OSS (for oss2vid node)"),
    image_filename: str = Form(..., description="Image filename in OSS (for oss2image node)"),
    output_name: Optional[str] = Form(None, description="Custom output filename prefix"),
    return_prompt_id_only: Optional[bool] = Form(False, description="Return only prompt_id for async processing")
):
    """
    Perform face swap using OSS filenames with real-time progress via Server-Sent Events.
    Set return_prompt_id_only=true to get just the prompt_id for status checking.
    """
    
    # Validate inputs
    if not video_filename or not image_filename:
        if return_prompt_id_only:
            logger.error("Must provide both video_filename and image_filename")
            raise HTTPException(
                status_code=400, 
                detail="Must provide both video_filename and image_filename"
            )
        return EventSourceResponse(
            async_error_generator("Must provide both video_filename and image_filename")
        )
    
    # Pre-process workflow BEFORE creating the async generator
    ts = time.strftime("%Y%m%d_%H%M%S")
    
    try:
        # Validate workflow file
        validate_workflow_file()
        
        output_prefix = output_name or f"faceswap_{ts}"
        
        logger.info(f"Using OSS video filename: {video_filename}")
        logger.info(f"Using OSS image filename: {image_filename}")
        logger.info(f"Output prefix: {output_prefix}")
        
        # Setup workflow
        workflow = load_and_patch_workflow(video_filename, image_filename, output_prefix)
        node_titles = build_node_title_map(workflow)
        
        # Queue workflow and get prompt_idwebs
        client_id = str(uuid.uuid4())
        prompt_id = queue_prompt(workflow, client_id)
        
        logger.info(f"Generated prompt_id: {prompt_id}")
        
        # Initialize status cache IMMEDIATELY after getting prompt_id
        current_time = datetime.now(timezone.utc).isoformat()
        WORKFLOW_STATUS_CACHE[prompt_id] = {
            "prompt_id": prompt_id,
            "status": "QUEUED",
            "progress": {"percentage": 0, "step": "OSS workflow queued, ready to start"},
            "created_at": current_time,
            "updated_at": current_time,
            "result": None,
            "error": None
        }
        
        logger.info(f"Initialized status cache for prompt_id: {prompt_id}")
        
        # If only prompt_id is requested, return it immediately
        if return_prompt_id_only:
            # Start background processing
            asyncio.create_task(process_workflow_background(prompt_id, client_id, node_titles, output_prefix))
            
            return {
                "prompt_id": prompt_id,
                "status": "QUEUED", 
                "message": "Face swap OSS workflow queued successfully. Use /status/{prompt_id} to check progress.",
                "status_url": f"/status/{prompt_id}",
                "output_prefix": output_prefix,
                "video_filename": video_filename,
                "image_filename": image_filename
            }
        
    except Exception as e:
        if return_prompt_id_only:
            logger.error(f"Workflow setup failed: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Workflow setup failed: {str(e)}")
        return EventSourceResponse(
            async_error_generator(f"Workflow setup failed: {str(e)}")
        )
    
    # For SSE streaming (default behavior)
    async def generate_progress_stream():
        try:
            yield {
                "event": "queued",
                "data": json.dumps({
                    "prompt_id": prompt_id, 
                    "message": "Face swap OSS workflow queued successfully!",
                    "status_url": f"/status/{prompt_id}",
                    "video_filename": video_filename,
                    "image_filename": image_filename
                })
            }

            # Stream progress updates
            final_status = None
            async for progress_event in monitor_progress_unified(prompt_id, client_id, node_titles):
                yield progress_event
                if progress_event.get("event") == "workflow_status":
                    event_data = json.loads(progress_event["data"])
                    final_status = event_data.get("final_status")
                    break

            # Handle completion for OSS workflow
            if final_status in {"completed", "finished", "uploaded"}:
                status_message = "🎉 Face swap completed successfully!"
                
                # Add specific messages based on final status
                if final_status == "uploaded":
                    status_message = "🎉 Face swap completed and uploaded to OSS! Local file deleted."
                    
                # Update status cache with final result
                update_workflow_status(prompt_id, "SUCCESS", {
                    "percentage": 100,
                    "step": "Face swap completed and uploaded to OSS"
                })
                yield {
                    "event": "completed",
                    "data": json.dumps({
                        "message": status_message,
                        "prompt_id": prompt_id,
                        "output_prefix": output_prefix,
                        "final_status": final_status,
                        "video_filename": video_filename,
                        "image_filename": image_filename
                    })
                }
            else:
                error_msg = f"Face swap failed with status: {final_status}"
                update_workflow_status(prompt_id, "FAILED", error=error_msg)
                yield {
                    "event": "error",
                    "data": json.dumps({"detail": error_msg})
                }

        except Exception as e:
            if 'prompt_id' in locals():
                update_workflow_status(prompt_id, "FAILED", error=str(e))
            yield {"event": "error", "data": json.dumps({"detail": f"Unexpected error: {str(e)}"})}

    return EventSourceResponse(generate_progress_stream())

@app.get("/status/{prompt_id}")
async def get_workflow_status(prompt_id: str):
    """
    Get the current status of a workflow execution by prompt_id.
    
    Returns the latest status without needing to connect to WebSocket or SSE.
    """
    logger.info(f"Status request for prompt_id: {prompt_id}")
    logger.info(f"Current cache keys: {list(WORKFLOW_STATUS_CACHE.keys())}")
    
    if prompt_id not in WORKFLOW_STATUS_CACHE:
        logger.warning(f"prompt_id {prompt_id} not found in cache, trying ComfyUI history...")
        # Try to fetch from ComfyUI history as fallback
        try:
            history_response = requests.get(f"{HISTORY_URL}/{prompt_id}", headers=HEADERS, timeout=10).json()
            logger.info(f"History response keys: {list(history_response.keys()) if history_response else 'Empty response'}")
            
            if history_response and prompt_id in history_response:
                prompt_data = history_response[prompt_id]
                status_info = prompt_data.get("status", {})
                
                # Determine status from ComfyUI response for OSS workflow
                if status_info.get("completed", False):
                    comfy_status = "SUCCESS"
                    progress_data = {"percentage": 100, "step": "Completed and uploaded to OSS"}
                elif status_info.get("status_str") == "error":
                    comfy_status = "FAILED"
                    progress_data = {"percentage": 0, "step": "Failed"}
                else:
                    comfy_status = "PROCESSING"
                    progress_data = {"percentage": 50, "step": "Processing"}
                
                return {
                    "prompt_id": prompt_id,
                    "status": comfy_status,
                    "progress": progress_data,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "result": "Files uploaded to OSS" if comfy_status == "SUCCESS" else None,
                    "error": status_info.get("error") if comfy_status == "FAILED" else None
                }
            else:
                logger.error(f"prompt_id {prompt_id} not found in ComfyUI history")
                raise HTTPException(status_code=404, detail=f"Workflow with prompt_id '{prompt_id}' not found")
                
        except requests.RequestException as e:
            logger.error(f"Error fetching from ComfyUI history: {e}")
            raise HTTPException(status_code=404, detail=f"Workflow with prompt_id '{prompt_id}' not found")
    
    return WORKFLOW_STATUS_CACHE[prompt_id]

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
        "workflow_type": "OSS-based (no local file downloads)",
        "communication_method": "WebSocket + SSE"
    }

@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "message": "ComfyUI Face Swap OSS API with WebSocket + SSE",
        "version": "2.0.0",
        "description": "OSS-based face swap service using ComfyUI Reactor workflow with Aliyun OSS integration",
        "endpoints": {
            "POST /face-swap": "Perform face swap with real-time progress via SSE",
            "GET /status/{prompt_id}": "Check workflow status by prompt ID",
            "GET /health": "Health check for API and ComfyUI connection",
            "GET /": "API information and documentation"
        },
        "features": [
            "Real-time progress monitoring via Server-Sent Events",
            "Asynchronous processing with prompt_id tracking",
            "Aliyun OSS integration for file handling",
            "WebSocket-based communication with ComfyUI",
            "Automatic file cleanup after processing"
        ],
        "usage": {
            "sync_mode": "POST /face-swap with return_prompt_id_only=false (default)",
            "async_mode": "POST /face-swap with return_prompt_id_only=true, then GET /status/{prompt_id}"
        },
        "workflow_type": "OSS-based (oss2vid, oss2image nodes)",
        "server_address": f"{SERVER_ADDRESS}"
    }

# Added main execution block
if __name__ == "__main__":
    import uvicorn
    logger.info("=" * 60)
    logger.info("🚀 Starting ComfyUI Face Swap OSS API")
    logger.info("=" * 60)
    logger.info(f"▶ API Server: http://0.0.0.0:8000")
    logger.info(f"▶ ComfyUI Server: {SERVER_ADDRESS}")
    logger.info(f"▶ Workflow: OSS-based (oss2vid + oss2image)")
    logger.info(f"▶ Features: WebSocket + SSE monitoring")
    logger.info("=" * 60)
    
    try:
        # Validate workflow file on startup
        validate_workflow_file()
        logger.info("✅ Workflow file validation passed")
    except Exception as e:
        logger.error(f"❌ Workflow validation failed: {e}")
        exit(1)
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
    #uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True, log_level="debug")