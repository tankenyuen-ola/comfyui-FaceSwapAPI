
Of course. Here is the full text of the `README.md` file, exported in markdown format.

# ComfyUI Face Swap API with Real-Time Progress

A FastAPI-based service that provides face swapping functionality using ComfyUI's ReActor workflow with real-time progress monitoring via WebSocket and Server-Sent Events (SSE). This API allows you to swap faces in videos by uploading files or providing URLs, with live progress updates throughout the process.

It also supports an asynchronous mode where a job can be submitted, and its status can be polled via a separate endpoint.

## Features

-   **Real-Time Progress**: Monitor face swapping progress via WebSocket or Server-Sent Events.
-   **Asynchronous Processing**: Submit a job and poll a status endpoint, ideal for long-running tasks.
-   **Face Swapping**: Swap faces in videos using state-of-the-art AI models.
-   **Flexible Input**: Support for file uploads or URL-based inputs.
-   **Event-Driven Architecture**: No polling required for real-time updates via WebSocket/SSE.
-   **Face Enhancement**: Built-in face restoration and boosting.
-   **RESTful API**: Clean HTTP API for easy integration.
-   **Dual Communication**: Choose between WebSocket or SSE for progress monitoring.

## Prerequisites

-   Python 3.8+
-   ComfyUI instance with ReActor nodes installed
-   Access to ComfyUI server (local or remote)

## Installation

1.  Clone the repository:
    
    Bash
    
    ```
    git clone https://github.com/yourusername/comfyui-FaceSwapAPI.git
    cd comfyui-FaceSwapAPI
    
    ```
    
2.  Install dependencies:
    
    Bash
    
    ```
    pip install -r requirements.txt
    
    ```
    
3.  Configure the application by editing the following variables in `faceswap-websockets.py`:
    
    Python
    
    ```
    # Update these variables according to your setup
    SERVER_ADDRESS = "your-comfyui-server.com"  # Your ComfyUI server address
    OUTPUT_DIR = Path("/path/to/output")        # Directory for output files
    DOWNLOAD_DIR = Path("/path/to/downloads")   # Directory for downloads
    WORKFLOW_PATH = "/path/to/FaceSwap-Reactor-API.json"  # Path to workflow file
    
    ```
    

## Configuration

### Required Files

-   `FaceSwap-Reactor-API.json`: ComfyUI workflow file (included in repository)
-   Make sure your ComfyUI instance has the following nodes installed:
    -   ReActor Face Swap
    -   ReActor Face Boost
    -   VHS (Video Helper Suite)

### Directory Structure

```
project/
├── faceswap-websockets.py
├── FaceSwap-Reactor-API.json
├── requirements.txt
├── README.md
├── downloads/          # Downloaded/processed files
└── output/            # ComfyUI output directory

```

## Usage

### Starting the Server

Bash

```
python faceswap-websockets.py

```

The API will be available at `http://localhost:8000`.

## API Endpoints

### 1. Face Swap with SSE - `POST /face-swap`

Perform face swapping. By default, it streams real-time progress via Server-Sent Events. It can also operate asynchronously by returning a `prompt_id`.

**Parameters:**

-   `video` (file, optional): Input video file.
-   `image` (file, optional): Source face image file.
-   `video_url` (string, optional): Video URL (alternative to file upload).
-   `image_url` (string, optional): Image URL (alternative to file upload).
-   `output_name` (string, optional): Custom output filename prefix.
-   `return_prompt_id_only` (boolean, optional): If `true`, the server will immediately return a `prompt_id` for asynchronous processing and will not stream real-time progress. The client can then use the `/status/{prompt_id}` endpoint to check the workflow status. Defaults to `false`.

----------

#### Mode 1: Real-Time Progress (SSE Stream)

If `return_prompt_id_only` is `false` (the default), the server sends a stream of Server-Sent Events.

**Server Response (SSE Stream):**

JavaScript

```
// Workflow queued
{
  "event": "queued",
  "data": {
    "prompt_id": "abc123",
    "message": "Face swap workflow queued successfully!"
  }
}
// Progress updates
{
  "event": "progress",
  "data": {
    "percentage": 45.67,
    "current": 123,
    "total": 269,
    "message": "Face swap progress: 45.67%"
  }
}
// Final completion
{
  "event": "completed",
  "data": {
    "message": "🎉 Face swap completed successfully!",
    "filename": "faceswap_20250618_143022.mp4",
    "download_url": "/download/faceswap_20250618_143022.mp4",
  }
}
// Error handling
{
  "event": "error",
  "data": {
    "detail": "Error message here"
  }
}

```

----------

#### Mode 2: Asynchronous Processing

If `return_prompt_id_only` is set to `true`, the server immediately returns a JSON object with the `prompt_id` for the queued task.

**Example Request:**

Bash

```
curl -X POST "http://localhost:8000/face-swap" \
  -F "video=@/workspace/ComfyUI/input/Thomas Shelby - Starboy.mp4" \
  -F "image=@/workspace/ComfyUI/input/image (9).png" \
  -F "output_name=my_faceswap" \
  -F "return_prompt_id_only=true"

```

**Server Response (JSON):**

This response confirms the job has been queued. You must use the `/status/{prompt_id}` endpoint to get the result.

JSON

```
{
  "prompt_id": "a1b2c3d4-e5f6-7890-1234-567890abcdef",
  "status": "QUEUED",
  "message": "Face swap workflow queued successfully. Use /status/{prompt_id} to check progress.",
  "status_url": "/status/a1b2c3d4-e5f6-7890-1234-567890abcdef",
  "output_prefix": "my_faceswap"
}

```

### 2. Get Workflow Status - `GET /status/{prompt_id}`

Get the latest status of a workflow execution by its `prompt_id`. This is used after submitting a job with `return_prompt_id_only=true`.

**Example Request:**

Bash

```
curl http://localhost:8000/status/a1b2c3d4-e5f6-7890-1234-567890abcdef

```

**Server Response (JSON):**

The response shows the current state of the workflow.

-   **While processing:**
    
    JSON
    
    ```
    {
        "prompt_id": "a1b2c3d4-e5f6-7890-1234-567890abcdef",
        "status": "PROCESSING",
        "progress": {
            "percentage": 50,
            "step": "Executing: ReActorFaceSwap"
        },
        "created_at": "2025-06-18T15:00:00.000Z",
        "updated_at": "2025-06-18T15:05:00.000Z",
        "result": null,
        "error": null
    }
    
    ```
    
-   **On success:**
    
    JSON
    
    ```
    {
        "prompt_id": "a1b2c3d4-e5f6-7890-1234-567890abcdef",
        "status": "SUCCESS",
        "progress": {
            "percentage": 100,
            "step": "Face swap completed successfully"
        },
        "created_at": "2025-06-18T15:00:00.000Z",
        "updated_at": "2025-06-18T15:10:00.000Z",
        "result": "/download/my_faceswap.mp4",
        "error": null
    }
    
    ```
    
-   **On failure:**
    
    JSON
    
    ```
    {
        "prompt_id": "a1b2c3d4-e5f6-7890-1234-567890abcdef",
        "status": "FAILED",
        "progress": { ... },
        "created_at": "2025-06-18T15:00:00.000Z",
        "updated_at": "2025-06-18T15:08:00.000Z",
        "result": null,
        "error": "Failed to fetch output file: No video output found in history response"
    }
    
    ```
    

If the `prompt_id` is not found, it will return a `404 Not Found` error.

### 3. Face Swap with WebSocket - `WebSocket /face-swap-ws`

Perform face swapping with real-time progress via WebSocket. (This endpoint does not support the asynchronous `prompt_id` flow).

### 4. Download File - `GET /download/{filename}`

Download a processed video file.

**Example:**

Bash

```
curl -O "http://localhost:8000/download/my_faceswap.mp4"

```

### 5. Health Check - `GET /health`

Check the health status of the API and ComfyUI connection.

### 6. Root - `GET /`

Get API information and usage instructions.