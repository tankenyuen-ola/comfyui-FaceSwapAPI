import asyncio
import json
import uuid
import time
import copy
from pathlib import Path
from typing import Optional
import re

import requests
import requests.exceptions
from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.responses import FileResponse
import uvicorn

# Configuration
SERVER_ADDRESS = "collection-aj-baths-vegetables.trycloudflare.com/"
QUEUE_URL = f"https://{SERVER_ADDRESS}/prompt"
VIDEO_URL = f"https://{SERVER_ADDRESS}/view"
UPLOAD_IMAGE_URL = f"https://{SERVER_ADDRESS}/upload/image"
WORKFLOW_PATH = "/workspace/FaceSwap-Reactor-API.json"
OUTPUT_DIR = Path("/workspace/ComfyUI/output")
DOWNLOAD_DIR = Path("/workspace/downloads")

# Polling settings for 3-8 minute workflows
POLL_INTERVAL_SECONDS = 15  # Check every 15 seconds
MAX_POLL_ATTEMPTS = 40      # 40 attempts = 10 minutes max
INITIAL_WAIT_SECONDS = 60   # Wait 1 minute before first poll

# Ensure output directory exists
OUTPUT_DIR.mkdir(exist_ok=True)
DOWNLOAD_DIR.mkdir(exist_ok=True)

# FastAPI app
app = FastAPI(title="ComfyUI Face Swap API", version="1.0.0")

# Headers for requests
HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Cookie": "C.20984754_auth_token=af1ad767732eaa664611af8bf29b2b2cd3598dbeca534b4324748d1a029d2adc",
    "Origin": "https://memory-gate-race-decision.trycloudflare.com",
    "Priority": "u=1, i",
    "Referer": "https://memory-gate-race-decision.trycloudflare.com/",
    "Sec-Ch-Ua": '"Chromium";v="136", "Microsoft Edge";v="136", "Not.A/Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
}

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

def get_available_files() -> List[str]:
    """Get list of available output files from ComfyUI."""
    try:
        # Try to get file list from ComfyUI API
        params = {"type": "output"}
        response = requests.get(LIST_FILES_URL, params=params, headers=HEADERS, timeout=10)
        
        if response.status_code == 200:
            # If the API returns JSON with file list
            try:
                data = response.json()
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict) and 'files' in data:
                    return data['files']
            except json.JSONDecodeError:
                pass
        
        # Fallback: scan local output directory if available
        if OUTPUT_DIR.exists():
            return [f.name for f in OUTPUT_DIR.glob("*.mp4")]
        
        return []
    except Exception as e:
        print(f"Warning: Could not get file list: {e}")
        return []

def find_latest_output_file(output_prefix: str) -> Optional[str]:
    """Find the latest output file with the given prefix."""
    available_files = get_available_files()
    
    # Pattern to match files like: output_prefix_00001.mp4, output_prefix_00002.mp4, etc.
    pattern = rf"^{re.escape(output_prefix)}_(\d+)\.mp4$"
    
    matching_files = []
    for filename in available_files:
        match = re.match(pattern, filename)
        if match:
            sequence_num = int(match.group(1))
            matching_files.append((filename, sequence_num))
    
    if not matching_files:
        return None

def load_and_modify_workflow(video_filename: str, image_filename: str, output_prefix: str) -> dict:
    """Load and modify the ComfyUI workflow."""
    with open(WORKFLOW_PATH, "r") as f:
        workflow_data = json.load(f)
    
    modified_workflow = copy.deepcopy(workflow_data)
    
    # Node 8 - Load Video
    modified_workflow["8"]["inputs"]["video"] = video_filename
    
    # Node 10 - Load Image
    modified_workflow["10"]["inputs"]["image"] = image_filename
    
    # Node 9 - Video Output
    modified_workflow["9"]["inputs"]["filename_prefix"] = output_prefix
    
    return modified_workflow

def queue_prompt(workflow: dict) -> dict:
    """Queue workflow to ComfyUI."""
    client_id = str(uuid.uuid4())
    payload = {"prompt": workflow, "client_id": client_id}
    
    response = requests.post(QUEUE_URL, json=payload, timeout=30, headers=HEADERS)
    response.raise_for_status()
    
    result = response.json()
    result["client_id"] = client_id
    return result

def download_video(filename: str, output_path: Path) -> bool:
    """Download video from ComfyUI."""
    params = {"filename": filename, "type": "output"}
    
    try:
        response = requests.get(VIDEO_URL, params=params, headers=HEADERS, timeout=30)
        response.raise_for_status()
        
        with open(output_path, "wb") as f:
            f.write(response.content)
        print(f"Downloaded: {output_path}")
        return True
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            return False  # Still processing
        else:
            raise e

async def poll_for_video(filename: str, output_path: Path) -> bool:
    """Poll for video completion and download."""
    print(f"Waiting {INITIAL_WAIT_SECONDS} seconds before polling...")
    await asyncio.sleep(INITIAL_WAIT_SECONDS)
    
    for attempt in range(MAX_POLL_ATTEMPTS):
        print(f"Poll attempt {attempt + 1}/{MAX_POLL_ATTEMPTS} for prefix '{output_prefix}'")
        
        # Find the latest output file with the given prefix
        latest_filename = find_latest_output_file(output_prefix)
        
        if latest_filename:
            print(f"Found output file: {latest_filename}")
            
            # Try to download it
            if download_video(latest_filename, output_path):
                return latest_filename
        
        if attempt < MAX_POLL_ATTEMPTS - 1:
            print(f"Not ready, waiting {POLL_INTERVAL_SECONDS} seconds...")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    
    print(f"Timeout after {MAX_POLL_ATTEMPTS * POLL_INTERVAL_SECONDS // 60} minutes")
    return False

@app.post("/face-swap")
async def face_swap(
    video: Optional[UploadFile] = File(None, description="Input video file"),
    image: Optional[UploadFile] = File(None, description="Source face image file"),
    video_url: Optional[str] = Form(None, description="Video URL (alternative to file upload)"),
    image_url: Optional[str] = Form(None, description="Image URL (alternative to file upload)"),
    output_name: Optional[str] = Form(None, description="Custom output filename prefix")
):
    """
    Perform face swap using ComfyUI.
    
    Args:
        video: Input video file (upload)
        image: Source face image file (upload)
        video_url: Video URL (alternative to upload)
        image_url: Image URL (alternative to upload)
        output_name: Optional output filename prefix
        
    Returns:
        Success response with output file information
    """
    try:
        # Validate inputs
        if not ((video or video_url) and (image or image_url)):
            raise HTTPException(
                status_code=400, 
                detail="Must provide either video file or video_url, and either image file or image_url"
            )
        
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
        output_prefix = output_name or f"faceswap_{int(time.time())}"
        
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
        
        print(f"Processing: video + image")
        
        # Upload files
        print("Uploading video...")
        upload_file_to_comfyui(video_content, video_filename)
        
        print("Uploading image...")
        upload_file_to_comfyui(image_content, image_filename)
        
        # Load workflow
        workflow = load_and_modify_workflow(video_filename, image_filename, output_prefix)
        
        # Queue workflow
        print("Queueing workflow...")
        queue_result = queue_prompt(workflow)
        print(f"Queued: {queue_result.get('prompt_id')}")
        
        # Wait for completion
        expected_output = f"{output_prefix}_00001.mp4"
        output_path = OUTPUT_DIR / f"{output_prefix}.mp4"
        
        print("Waiting for processing...")
        success = await poll_for_video(expected_output, output_path)
        
        if success:
            print(f"Success! Output: {output_path}")
            return {
                "message": "Face swap completed successfully",
                "output_file": str(output_path),
                "download_url": f"/download/{output_prefix}.mp4",
                "queue_id": queue_result.get("prompt_id"),
                "client_id": queue_result.get("client_id"),
                "processing_time": f"{INITIAL_WAIT_SECONDS + MAX_POLL_ATTEMPTS * POLL_INTERVAL_SECONDS} seconds max"
            }
        else:
            max_wait_time = INITIAL_WAIT_SECONDS + (MAX_POLL_ATTEMPTS * POLL_INTERVAL_SECONDS)
            raise HTTPException(
                status_code=408,
                detail=f"Workflow timeout after {max_wait_time} seconds ({max_wait_time//60} minutes)"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error during face swap: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
        "max_processing_time": f"{INITIAL_WAIT_SECONDS + MAX_POLL_ATTEMPTS * POLL_INTERVAL_SECONDS} seconds",
        "output_directory": str(OUTPUT_DIR)
    }

@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "message": "ComfyUI Face Swap API",
        "version": "1.0.0",
        "description": "Face swap service using ComfyUI Reactor workflow",
        "endpoints": {
            "face_swap": "POST /face-swap",
            "download": "GET /download/{filename}",
            "health": "GET /health"
        },
        "usage": {
            "file_upload": "Use 'video' and 'image' form fields",
            "url_input": "Use 'video_url' and 'image_url' form fields",
            "mixed": "Can mix file upload and URL (e.g., video file + image URL)",
            "output_name": "Optional custom output filename prefix"
        },
        "settings": {
            "initial_wait": f"{INITIAL_WAIT_SECONDS} seconds",
            "poll_interval": f"{POLL_INTERVAL_SECONDS} seconds",
            "max_attempts": MAX_POLL_ATTEMPTS,
            "timeout": f"{(INITIAL_WAIT_SECONDS + MAX_POLL_ATTEMPTS * POLL_INTERVAL_SECONDS) // 60} minutes"
        }
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)