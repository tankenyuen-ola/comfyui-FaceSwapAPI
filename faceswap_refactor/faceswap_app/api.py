
import json, uuid
from fastapi import FastAPI, File, UploadFile, HTTPException
from sse_starlette.sse import EventSourceResponse

from .comfyui_client import upload_file_to_comfyui, queue_prompt, monitor_progress_ws
from .workflow_utils import load_and_patch_workflow
from .status_cache import update_workflow_status, get_workflow_status

app = FastAPI(title="Face Swap API", version="3.0")

@app.post("/face-swap")
async def face_swap(video: UploadFile = File(...), image: UploadFile = File(...)):
    video_bytes = await video.read()
    image_bytes = await image.read()
    upload_file_to_comfyui(video_bytes, video.filename)
    upload_file_to_comfyui(image_bytes, image.filename)

    output_prefix = uuid.uuid4().hex[:8]
    workflow = load_and_patch_workflow(video.filename, image.filename, output_prefix)
    prompt_id = queue_prompt(workflow, client_id="face-swap-api")
    update_workflow_status(prompt_id, "QUEUED")

    async def event_stream():
        async for evt in monitor_progress_ws(prompt_id):
            update_workflow_status(prompt_id, evt.get("status", "RUNNING"), evt)
            yield {"event": "status", "data": json.dumps(evt)}

    return EventSourceResponse(event_stream())

@app.get("/status/{prompt_id}")
async def status(prompt_id: str):
    doc = get_workflow_status(prompt_id)
    if not doc:
        raise HTTPException(404, detail="Unknown prompt_id")
    return doc

@app.get("/health")
async def health():
    return {"status": "ok"}
