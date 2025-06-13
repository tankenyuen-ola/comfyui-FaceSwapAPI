# ComfyUI Face Swap API

A FastAPI-based service that provides face swapping functionality using ComfyUI's ReActor workflow. This API allows you to swap faces in videos by uploading files or providing URLs.

## Features

- **Face Swapping**: Swap faces in videos using state-of-the-art AI models
- **Flexible Input**: Support for file uploads or URL-based inputs
- **Async Processing**: Non-blocking workflow execution with polling
- **Face Enhancement**: Built-in face restoration and boosting
- **RESTful API**: Clean HTTP API for easy integration

## Prerequisites

- Python 3.8+
- ComfyUI instance with ReActor nodes installed
- Access to ComfyUI server (local or remote)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/comfyui-FaceSwapAPI.git
cd comfyui-FaceSwapAPI
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure the application by editing the following variables in `faceswap-fastapi.py`:

```python
# Update these variables according to your setup
SERVER_ADDRESS = "your-comfyui-server.com"  # Your ComfyUI server address
OUTPUT_DIR = Path("/path/to/output")        # Directory for output files
DOWNLOAD_DIR = Path("/path/to/downloads")   # Directory for downloads
WORKFLOW_PATH = "/path/to/FaceSwap-Reactor-API.json"  # Path to workflow file
```

## Configuration

### Required Files

- `FaceSwap-Reactor-API.json`: ComfyUI workflow file (included in repository)
- Make sure your ComfyUI instance has the following nodes installed:
  - ReActor Face Swap
  - ReActor Face Boost
  - VHS (Video Helper Suite)

### Directory Structure

```
project/
├── faceswap-fastapi.py
├── FaceSwap-Reactor-API.json
├── requirements.txt
├── README.md
├── downloads/          # Downloaded/processed files
└── output/            # ComfyUI output directory
```

## Usage

### Starting the Server

```bash
python faceswap-fastapi.py
```

The API will be available at `http://localhost:8000`

### API Documentation

Once the server is running, visit `http://localhost:8000/docs` for interactive API documentation.

## API Endpoints

### 1. Face Swap - `POST /face-swap`

Perform face swapping on a video using a source face image.

**Parameters:**
- `video` (file, optional): Input video file
- `image` (file, optional): Source face image file  
- `video_url` (string, optional): Video URL (alternative to file upload)
- `image_url` (string, optional): Image URL (alternative to file upload)
- `output_name` (string, optional): Custom output filename prefix

**Request Examples:**

**File Upload:**
```bash
curl -X POST "http://localhost:8000/face-swap" \
  -F "video=@input_video.mp4" \
  -F "image=@source_face.jpg" \
  -F "output_name=my_faceswap"
```

**URL Input:**
```bash
curl -X POST "http://localhost:8000/face-swap" \
  -F "video_url=https://example.com/video.mp4" \
  -F "image_url=https://example.com/face.jpg"
```

**Mixed Input:**
```bash
curl -X POST "http://localhost:8000/face-swap" \
  -F "video=@local_video.mp4" \
  -F "image_url=https://example.com/face.jpg"
```

**Response:**
```json
{
  "message": "Face swap completed successfully",
  "output_file": "/path/to/output/faceswap_1234567890.mp4",
  "download_url": "/download/faceswap_1234567890.mp4",
  "queue_id": "abc123",
  "client_id": "def456",
  "processing_time": "600 seconds max"
}
```

### 2. Download File - `GET /download/{filename}`

Download a processed video file.

**Example:**
```bash
curl -O "http://localhost:8000/download/faceswap_1234567890.mp4"
```

### 3. Health Check - `GET /health`

Check the health status of the API and ComfyUI connection.

**Response:**
```json
{
  "status": "healthy",
  "comfyui_status": "healthy",
  "workflow_status": "valid",
  "server_address": "your-comfyui-server.com",
  "workflow_path": "/path/to/workflow.json",
  "max_processing_time": "600 seconds",
  "output_directory": "/path/to/output"
}
```

### 4. Root - `GET /`

Get API information and usage instructions.

**Response:**
```json
{
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
    "mixed": "Can mix file upload and URL",
    "output_name": "Optional custom output filename prefix"
  }
}
```

## Processing Details

### Workflow Configuration

The API uses a ComfyUI workflow with the following components:

- **ReActor Face Swap**: Core face swapping using inswapper_128.onnx
- **Face Detection**: RetinaFace ResNet50 for accurate face detection
- **Face Restoration**: GFPGAN v1.4 for face quality enhancement
- **Face Boosting**: GPEN-BFR-2048 for additional face enhancement
- **Video Processing**: VHS nodes for video input/output handling

### Processing Times

- **Initial Wait**: 60 seconds before first poll
- **Poll Interval**: 15 seconds between checks
- **Maximum Timeout**: 10 minutes (40 attempts)
- **Typical Processing**: 3-8 minutes depending on video length and complexity

### Supported Formats

- **Input Video**: MP4, AVI, MOV, MKV
- **Input Image**: JPG, PNG, JPEG, BMP
- **Output**: MP4 (H.264, yuv420p)

## Error Handling

The API provides detailed error messages for common issues:

- **400 Bad Request**: Invalid input parameters or file format
- **404 Not Found**: Requested file not found
- **408 Request Timeout**: Processing exceeded maximum time limit
- **500 Internal Server Error**: Server or ComfyUI connection issues

## Development

### Running in Development Mode

```bash
# Install development dependencies
pip install -r requirements.txt

# Run with auto-reload
uvicorn faceswap-fastapi:app --reload --host 0.0.0.0 --port 8000
```

### Testing

```bash
# Test health endpoint
curl http://localhost:8000/health

# Test face swap with sample files
curl -X POST "http://localhost:8000/face-swap" \
  -F "video=@test_video.mp4" \
  -F "image=@test_face.jpg"
```

## Troubleshooting

### Common Issues

1. **ComfyUI Connection Failed**
   - Check SERVER_ADDRESS configuration
   - Ensure ComfyUI is running and accessible
   - Verify network connectivity

2. **Workflow File Not Found**
   - Check WORKFLOW_PATH configuration
   - Ensure FaceSwap-Reactor-API.json exists

3. **Processing Timeout**
   - Increase MAX_POLL_ATTEMPTS for longer videos
   - Check ComfyUI server resources
   - Verify input file formats

4. **Upload Failures**
   - Check file size limits
   - Verify supported formats
   - Ensure sufficient disk space

### Logs

The application logs processing steps to help with debugging:

```
✓ Workflow file validated
Using uploaded video file: input.mp4
Using uploaded image file: face.jpg
Processing: video + image
Uploading video...
Uploading image...
Queueing workflow...
Queued: abc123
Waiting for processing...
Poll attempt 1/40 for prefix 'faceswap_1234567890'
Found output file: faceswap_1234567890_00001.mp4
Downloaded: /path/to/output/faceswap_1234567890.mp4
Success! Output: /path/to/output/faceswap_1234567890.mp4
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- [ComfyUI](https://github.com/comfyanonymous/ComfyUI) - The underlying UI and workflow engine
- [ReActor](https://github.com/Gourieff/comfyui-reactor-node) - Face swapping node
- [FastAPI](https://fastapi.tiangolo.com/) - Modern web framework for building APIs