# ComfyUI Face Swap API with Real-Time Progress

A FastAPI-based service that provides face swapping functionality using ComfyUI's ReActor workflow with real-time progress monitoring via WebSocket and Server-Sent Events (SSE). This API allows you to swap faces in videos by uploading files or providing URLs, with live progress updates throughout the process.

## Features

- **Real-Time Progress**: Monitor face swapping progress via WebSocket or Server-Sent Events
- **Face Swapping**: Swap faces in videos using state-of-the-art AI models
- **Flexible Input**: Support for file uploads or URL-based inputs
- **Event-Driven Architecture**: No polling - real-time updates via WebSocket/SSE
- **Face Enhancement**: Built-in face restoration and boosting
- **RESTful API**: Clean HTTP API for easy integration
- **Dual Communication**: Choose between WebSocket or SSE for progress monitoring

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

3. Configure the application by editing the following variables in `faceswap-websockets.py`:

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
├── faceswap-websockets.py
├── FaceSwap-Reactor-API.json
├── requirements.txt
├── README.md
├── downloads/          # Downloaded/processed files
└── output/            # ComfyUI output directory
```

## Usage

### Starting the Server

```bash
python faceswap-websockets.py
```

The API will be available at `http://localhost:8000`

### API Documentation

Once the server is running, visit `http://localhost:8000/docs` for interactive API documentation.

## API Endpoints

### 1. Face Swap with SSE - `POST /face-swap`

Perform face swapping with real-time progress via Server-Sent Events.

**Parameters:**
- `video` (file, optional): Input video file
- `image` (file, optional): Source face image file  
- `video_url` (string, optional): Video URL (alternative to file upload)
- `image_url` (string, optional): Image URL (alternative to file upload)
- `output_name` (string, optional): Custom output filename prefix

**Server Response (SSE Stream):**

The server sends a stream of Server-Sent Events with the following event types:

```javascript
// Setup phase
{
  "event": "status",
  "data": {
    "message": "Setting up face swap processing..."
  }
}

// File upload progress
{
  "event": "status", 
  "data": {
    "message": "Uploading video file..."
  }
}

// Workflow queued
{
  "event": "queued",
  "data": {
    "prompt_id": "abc123",
    "message": "Face swap workflow queued successfully!"
  }
}

// Node execution updates
{
  "event": "executing",
  "data": {
    "node": "8",
    "title": "Load Video (Upload) 🎥🅥🅗🅢",
    "message": "Executing: Load Video (Upload) 🎥🅥🅗🅢"
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
    "prompt_id": "abc123",
    "output_prefix": "faceswap_20250618_143022"
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

**Client-Side Example (JavaScript):**

```javascript
// Using EventSource for SSE
const formData = new FormData();
formData.append('video', videoFile);
formData.append('image', imageFile);
formData.append('output_name', 'my_faceswap');

// Start face swap
fetch('/face-swap', {
    method: 'POST',
    body: formData
}).then(response => {
    if (!response.ok) throw new Error('Failed to start face swap');
    
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    
    function readStream() {
        return reader.read().then(({ done, value }) => {
            if (done) return;
            
            const chunk = decoder.decode(value);
            const lines = chunk.split('\n');
            
            lines.forEach(line => {
                if (line.startsWith('data: ')) {
                    try {
                        const data = JSON.parse(line.slice(6));
                        handleProgressUpdate(data);
                    } catch (e) {
                        console.error('Failed to parse SSE data:', e);
                    }
                }
            });
            
            return readStream();
        });
    }
    
    return readStream();
});

function handleProgressUpdate(data) {
    const { event } = data;
    
    switch(event) {
        case 'status':
            console.log('Status:', data.data.message);
            break;
        case 'progress':
            const progress = JSON.parse(data.data);
            console.log(`Progress: ${progress.percentage}%`);
            // Update progress bar
            break;
        case 'completed':
            const result = JSON.parse(data.data);
            console.log('Completed!', result);
            // Handle completion
            break;
        case 'error':
            const error = JSON.parse(data.data);
            console.error('Error:', error.detail);
            break;
    }
}
```

**Client-Side Example (Python):**

```python
import requests
import json

# File upload
files = {
    'video': open('input_video.mp4', 'rb'),
    'image': open('source_face.jpg', 'rb')
}
data = {'output_name': 'my_faceswap'}

response = requests.post('http://localhost:8000/face-swap', 
                        files=files, data=data, stream=True)

for line in response.iter_lines():
    if line:
        line = line.decode('utf-8')
        if line.startswith('data: '):
            try:
                event_data = json.loads(line[6:])
                event_type = event_data.get('event')
                
                if event_type == 'progress':
                    progress = json.loads(event_data['data'])
                    print(f"Progress: {progress['percentage']}%")
                elif event_type == 'completed':
                    result = json.loads(event_data['data'])
                    print(f"Completed! Download: {result['download_url']}")
                    break
                elif event_type == 'error':
                    error = json.loads(event_data['data'])
                    print(f"Error: {error['detail']}")
                    break
            except json.JSONDecodeError:
                continue
```

### 2. Face Swap with WebSocket - `WebSocket /face-swap-ws`

Perform face swapping with real-time progress via WebSocket.

**Client-Side Example (JavaScript):**

```javascript
const ws = new WebSocket('ws://localhost:8000/face-swap-ws');

ws.onopen = () => {
    // Send parameters
    ws.send(JSON.stringify({
        video_url: 'https://example.com/video.mp4',
        image_url: 'https://example.com/face.jpg',
        output_name: 'my_faceswap'
    }));
};

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    
    switch(data.event || data.type) {
        case 'queued':
            console.log('Queued with ID:', data.prompt_id);
            break;
        case 'progress':
            const progress = JSON.parse(data.data);
            console.log(`Progress: ${progress.percentage}%`);
            break;
        case 'completed':
            console.log('Completed!', data);
            break;
        case 'error':
            console.error('Error:', data.detail);
            break;
    }
};

ws.onerror = (error) => {
    console.error('WebSocket error:', error);
};
```

**Client-Side Example (Python):**

```python
import asyncio
import websockets
import json

async def face_swap_websocket():
    uri = "ws://localhost:8000/face-swap-ws"
    
    async with websockets.connect(uri) as websocket:
        # Send parameters
        params = {
            "video_url": "https://example.com/video.mp4",
            "image_url": "https://example.com/face.jpg",
            "output_name": "my_faceswap"
        }
        await websocket.send(json.dumps(params))
        
        # Listen for updates
        async for message in websocket:
            data = json.loads(message)
            
            if data.get('event') == 'progress':
                progress = json.loads(data['data'])
                print(f"Progress: {progress['percentage']}%")
            elif data.get('type') == 'completed':
                print(f"Completed! File: {data['filename']}")
                break
            elif data.get('event') == 'error':
                error = json.loads(data['data'])
                print(f"Error: {error['detail']}")
                break

# Run the WebSocket client
asyncio.run(face_swap_websocket())
```

### 3. Download File - `GET /download/{filename}`

Download a processed video file.

**Example:**
```bash
curl -O "http://localhost:8000/download/faceswap_20250618_143022.mp4"
```

### 4. Health Check - `GET /health`

Check the health status of the API and ComfyUI connection.

**Response:**
```json
{
  "status": "healthy",
  "comfyui_status": "healthy",
  "workflow_status": "valid",
  "server_address": "your-comfyui-server.com",
  "workflow_path": "/path/to/workflow.json",
  "communication_method": "WebSocket + SSE",
  "output_directory": "/path/to/output"
}
```

### 5. Root - `GET /`

Get API information and usage instructions.

**Response:**
```json
{
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
```

## Processing Details

### Workflow Configuration

The API uses a ComfyUI workflow with the following components:

- **ReActor Face Swap**: Core face swapping using inswapper_128.onnx
- **Face Detection**: RetinaFace ResNet50 for accurate face detection
- **Face Restoration**: GFPGAN v1.4 for face quality enhancement
- **Face Boosting**: GPEN-BFR-2048 for additional face enhancement
- **Video Processing**: VHS nodes for video input/output handling

### Real-Time Progress Events

The API provides detailed progress information through various event types:

#### Server-Sent Events (SSE)
| Event Type | Description | Data Format |
|------------|-------------|-------------|
| `status` | General status updates | `{"message": "Status message"}` |
| `queued` | Workflow queued successfully | `{"prompt_id": "abc123", "message": "..."}` |
| `executing` | Node execution updates | `{"node": "8", "title": "Node Name", "message": "..."}` |
| `progress` | Processing progress | `{"percentage": 45.67, "current": 123, "total": 269}` |
| `workflow_status` | Workflow completion status | `{"final_status": "completed", "message": "..."}` |
| `completed` | Final success result | `{"filename": "output.mp4", "download_url": "/download/..."}` |
| `error` | Error occurred | `{"detail": "Error description"}` |

#### WebSocket Events
WebSocket messages follow the same structure but are sent as individual JSON messages.

### Processing Times

- **Setup Phase**: 1-5 seconds for file uploads and workflow preparation
- **Processing Phase**: 3-15 minutes depending on video length and complexity
- **Real-time Updates**: Progress updates every 1-2 seconds during processing
- **No Polling**: Event-driven architecture eliminates the need for client polling

### Supported Formats

- **Input Video**: MP4, AVI, MOV, MKV
- **Input Image**: JPG, PNG, JPEG, BMP
- **Output**: MP4 (H.264, yuv420p)

## Client Implementation Examples

### Web Frontend (HTML + JavaScript)

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Face Swap with Real-Time Progress</title>
</head>
<body>
    <div id="upload-form">
        <input type="file" id="video" accept="video/*">
        <input type="file" id="image" accept="image/*">
        <input type="text" id="output-name" placeholder="Output name (optional)">
        <button onclick="startFaceSwap()">Start Face Swap</button>
    </div>
    
    <div id="progress-container" style="display: none;">
        <div id="status-message"></div>
        <div id="progress-bar-container">
            <div id="progress-bar" style="width: 0%; background: #4CAF50; height: 20px;"></div>
        </div>
        <div id="node-info"></div>
    </div>
    
    <div id="result-container" style="display: none;">
        <h3>Face Swap Completed! 🎉</h3>
        <a id="download-link" href="#" download>Download Result</a>
        <video id="result-video" controls style="max-width: 100%;"></video>
    </div>

    <script>
        async function startFaceSwap() {
            const videoFile = document.getElementById('video').files[0];
            const imageFile = document.getElementById('image').files[0];
            const outputName = document.getElementById('output-name').value;
            
            if (!videoFile || !imageFile) {
                alert('Please select both video and image files');
                return;
            }
            
            const formData = new FormData();
            formData.append('video', videoFile);
            formData.append('image', imageFile);
            if (outputName) formData.append('output_name', outputName);
            
            // Show progress container
            document.getElementById('upload-form').style.display = 'none';
            document.getElementById('progress-container').style.display = 'block';
            
            try {
                const response = await fetch('/face-swap', {
                    method: 'POST',
                    body: formData
                });
                
                if (!response.ok) {
                    throw new Error('Failed to start face swap');
                }
                
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                
                function readStream() {
                    return reader.read().then(({ done, value }) => {
                        if (done) return;
                        
                        const chunk = decoder.decode(value);
                        const lines = chunk.split('\n');
                        
                        lines.forEach(line => {
                            if (line.startsWith('data: ')) {
                                try {
                                    const eventData = JSON.parse(line.slice(6));
                                    handleProgressUpdate(eventData);
                                } catch (e) {
                                    console.error('Failed to parse SSE data:', e);
                                }
                            }
                        });
                        
                        return readStream();
                    });
                }
                
                readStream();
                
            } catch (error) {
                document.getElementById('status-message').textContent = `Error: ${error.message}`;
            }
        }
        
        function handleProgressUpdate(eventData) {
            const { event, data } = eventData;
            const parsedData = typeof data === 'string' ? JSON.parse(data) : data;
            
            switch(event) {
                case 'status':
                    document.getElementById('status-message').textContent = parsedData.message;
                    break;
                    
                case 'queued':
                    document.getElementById('status-message').textContent = parsedData.message;
                    break;
                    
                case 'executing':
                    document.getElementById('node-info').textContent = parsedData.message;
                    break;
                    
                case 'progress':
                    const progressBar = document.getElementById('progress-bar');
                    progressBar.style.width = `${parsedData.percentage}%`;
                    document.getElementById('status-message').textContent = parsedData.message;
                    break;
                    
                case 'completed':
                    document.getElementById('progress-container').style.display = 'none';
                    document.getElementById('result-container').style.display = 'block';
                    
                    const downloadLink = document.getElementById('download-link');
                    downloadLink.href = parsedData.download_url;
                    downloadLink.textContent = `Download ${parsedData.filename}`;
                    
                    const video = document.getElementById('result-video');
                    video.src = parsedData.download_url;
                    break;
                    
                case 'error':
                    document.getElementById('status-message').textContent = `Error: ${parsedData.detail}`;
                    document.getElementById('status-message').style.color = 'red';
                    break;
            }
        }
    </script>
</body>
</html>
```

### Python Client with Progress Bar

```python
import requests
import json
from tqdm import tqdm
import time

def face_swap_with_progress(video_path, image_path, output_name=None):
    """Face swap with real-time progress bar using SSE."""
    
    # Prepare files
    files = {
        'video': open(video_path, 'rb'),
        'image': open(image_path, 'rb')
    }
    data = {}
    if output_name:
        data['output_name'] = output_name
    
    print("🚀 Starting face swap...")
    
    try:
        response = requests.post(
            'http://localhost:8000/face-swap',
            files=files,
            data=data,
            stream=True,
            timeout=None
        )
        response.raise_for_status()
        
        progress_bar = None
        
        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    try:
                        event_data = json.loads(line[6:])
                        event_type = event_data.get('event')
                        data_content = json.loads(event_data.get('data', '{}'))
                        
                        if event_type == 'status':
                            print(f"📋 {data_content.get('message', '')}")
                            
                        elif event_type == 'queued':
                            print(f"✅ {data_content.get('message', '')} (ID: {data_content.get('prompt_id', '')})")
                            
                        elif event_type == 'executing':
                            print(f"⚙️  {data_content.get('message', '')}")
                            
                        elif event_type == 'progress':
                            percentage = data_content.get('percentage', 0)
                            current = data_content.get('current', 0)
                            total = data_content.get('total', 1)
                            
                            if progress_bar is None:
                                progress_bar = tqdm(total=100, desc="Face Swap Progress", unit="%")
                            
                            progress_bar.update(percentage - progress_bar.n)
                            
                        elif event_type == 'completed':
                            if progress_bar:
                                progress_bar.close()
                            print(f"🎉 {data_content.get('message', '')}")
                            print(f"📁 File: {data_content.get('filename', '')}")
                            print(f"🔗 Download: http://localhost:8000{data_content.get('download_url', '')}")
                            return data_content
                            
                        elif event_type == 'error':
                            if progress_bar:
                                progress_bar.close()
                            print(f"❌ Error: {data_content.get('detail', '')}")
                            return None
                            
                    except json.JSONDecodeError:
                        continue
                        
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")
        return None
    finally:
        # Close files
        for file_obj in files.values():
            file_obj.close()

# Usage example
if __name__ == "__main__":
    result = face_swap_with_progress(
        video_path="input_video.mp4",
        image_path="source_face.jpg",
        output_name="my_awesome_faceswap"
    )
    
    if result:
        print(f"Success! Output saved as: {result['filename']}")
    else:
        print("Face swap failed.")
```

### React Component Example

```jsx
import React, { useState, useCallback } from 'react';

const FaceSwapComponent = () => {
    const [progress, setProgress] = useState(0);
    const [status, setStatus] = useState('');
    const [isProcessing, setIsProcessing] = useState(false);
    const [result, setResult] = useState(null);
    const [error, setError] = useState(null);

    const handleFaceSwap = useCallback(async (videoFile, imageFile, outputName) => {
        setIsProcessing(true);
        setProgress(0);
        setStatus('');
        setError(null);
        setResult(null);

        const formData = new FormData();
        formData.append('video', videoFile);
        formData.append('image', imageFile);
        if (outputName) formData.append('output_name', outputName);

        try {
            const response = await fetch('/face-swap', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                throw new Error('Failed to start face swap');
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();

            const readStream = async () => {
                const { done, value } = await reader.read();
                if (done) return;

                const chunk = decoder.decode(value);
                const lines = chunk.split('\n');

                lines.forEach(line => {
                    if (line.startsWith('data: ')) {
                        try {
                            const eventData = JSON.parse(line.slice(6));
                            const { event, data } = eventData;
                            const parsedData = typeof data === 'string' ? JSON.parse(data) : data;

                            switch(event) {
                                case 'status':
                                case 'queued':
                                case 'executing':
                                    setStatus(parsedData.message || '');
                                    break;

                                case 'progress':
                                    setProgress(parsedData.percentage || 0);
                                    setStatus(parsedData.message || '');
                                    break;

                                case 'completed':
                                    setResult(parsedData);
                                    setIsProcessing(false);
                                    setStatus('Face swap completed successfully! 🎉');
                                    return;

                                case 'error':
                                    setError(parsedData.detail || 'Unknown error');
                                    setIsProcessing(false);
                                    return;
                            }
                        } catch (e) {
                            console.error('Failed to parse SSE data:', e);
                        }
                    }
                });

                await readStream();
            };

            await readStream();

        } catch (error) {
            setError(error.message);
            setIsProcessing(false);
        }
    }, []);

    return (
        <div className="face-swap-component">
            <h2>Face Swap with Real-Time Progress</h2>
            
            {!isProcessing && !result && (
                <FileUploadForm onSubmit={handleFaceSwap} />
            )}
            
            {isProcessing && (
                <div className="progress-container">
                    <div className="status-message">{status}</div>
                    <div className="progress-bar">
                        <div 
                            className="progress-fill" 
                            style={{ width: `${progress}%` }}
                        />
                    </div>
                    <div className="progress-text">{progress.toFixed(1)}%</div>
                </div>
            )}
            
            {error && (
                <div className="error-message">
                    ❌ Error: {error}
                </div>
            )}
            
            {result && (
                <div className="result-container">
                    <h3>Face Swap Completed! 🎉</h3>
                    <a 
                        href={result.download_url} 
                        download={result.filename}
                        className="download-button"
                    >
                        Download {result.filename}
                    </a>
                    <video 
                        src={result.download_url} 
                        controls 
                        className="result-video"
                    />
                </div>
            )}
        </div>
    );
};

const FileUploadForm = ({ onSubmit }) => {
    const [videoFile, setVideoFile] = useState(null);
    const [imageFile, setImageFile] = useState(null);
    const [outputName, setOutputName] = useState('');

    const handleSubmit = (e) => {
        e.preventDefault();
        if (videoFile && imageFile) {
            onSubmit(videoFile, imageFile, outputName);
        } else {
            alert('Please select both video and image files');
        }
    };

    return (
        <form onSubmit={handleSubmit} className="upload-form">
            <div className="file-input">
                <label>Video File:</label>
                <input 
                    type="file" 
                    accept="video/*" 
                    onChange={(e) => setVideoFile(e.target.files[0])}
                />
            </div>
            
            <div className="file-input">
                <label>Image File:</label>
                <input 
                    type="file" 
                    accept="image/*" 
                    onChange={(e) => setImageFile(e.target.files[0])}
                />
            </div>
            
            <div className="text-input">
                <label>Output Name (optional):</label>
                <input 
                    type="text" 
                    value={outputName}
                    onChange={(e) => setOutputName(e.target.value)}
                    placeholder="my_faceswap"
                />
            </div>
            
            <button type="submit" className="submit-button">
                Start Face Swap
            </button>
        </form>
    );
};

export default FaceSwapComponent;
```

## WebSocket Configuration

### Environment Variables

The WebSocket connection can be configured using these environment variables:

```bash
# WebSocket timeouts (in seconds)
WS_OPEN_TIMEOUT=60        # Connection establishment timeout
WS_PING_INTERVAL=20       # Ping interval to keep connection alive
WS_PING_TIMEOUT=20        # Ping response timeout
WS_CLOSE_TIMEOUT=10       # Connection close timeout
WS_MAX_CONCURRENCY=10     # Maximum concurrent WebSocket connections
```

### Connection Management

The API includes robust WebSocket connection management:

- **Automatic Reconnection**: Up to 3 retry attempts with exponential backoff
- **Connection Pooling**: Semaphore-based concurrency control
- **Idle Detection**: Automatic timeout for idle connections
- **Error Recovery**: Graceful handling of connection failures

## Error Handling

The API provides comprehensive error handling for both SSE and WebSocket connections:

### Common Error Types

| Error Code | Description | Typical Causes |
|------------|-------------|----------------|
| `400 Bad Request` | Invalid input parameters | Missing files, invalid formats |
| `404 Not Found` | Requested file not found | Invalid download URL |
| `408 Request Timeout` | Processing timeout | Long video, server overload |
| `500 Internal Server Error` | Server/ComfyUI issues | Connection failure, workflow error |

### Error Response Format

```json
{
  "event": "error",
  "data": {
    "detail": "Detailed error description",
    "error_type": "connection_error",
    "timestamp": "2025-06-18T14:30:22Z"
  }
}
```

## Development

### Running in Development Mode

```bash
# Install development dependencies
pip install -r requirements.txt

# Run with auto-reload
python faceswap-websockets.py
```

### Testing Real-Time Features

#### Test SSE Endpoint
```bash
# Test with curl (will show SSE stream)
curl -X POST "http://localhost:8000/face-swap" \
  -F "video=@test_video.mp4" \
  -F "image=@test_face.jpg" \
  -N  # Don't buffer output
```

#### Test WebSocket Endpoint
```bash
# Using wscat (install with: npm install -g wscat)
wscat -c ws://localhost:8000/face-swap-ws

# Then send JSON message:
{"video_url": "https://example.com/video.mp4", "image_url": "https://example.com/face.jpg"}
```

#### Test Health Endpoint
```bash
curl http://localhost:8000/health
```

## Troubleshooting

### Common Issues

1. **WebSocket Connection Failed**
   ```
   Error: WebSocket handshake failed after retries
   ```
   - Check SERVER_ADDRESS configuration
   - Verify ComfyUI WebSocket endpoint accessibility
   - Check firewall settings

2. **SSE Stream Interrupted**
   ```
   Error: Failed to parse SSE data
   ```
   - Check network stability
   - Verify client SSE parsing logic
   - Check for proxy interference

3. **Progress Updates Stop**
   ```
   Last event: executing, then silence
   ```
   - Check ComfyUI server resources
   - Verify workflow node configuration
   - Check for processing timeouts

4. **File Upload Failures**
   ```
   Error: Failed to upload to ComfyUI
   ```
   - Check file size limits
   - Verify supported formats
   - Ensure ComfyUI upload endpoint is accessible

### Debug Logging

Enable detailed logging by setting environment variables:

```bash
export PYTHONPATH=/path/to/project
export LOG_LEVEL=DEBUG
python faceswap-websockets.py
```

### Performance Optimization

For better performance with large files or high concurrency:

```python
# Increase WebSocket concurrency
WS_MAX_CONCURRENCY=20

# Adjust timeouts for slower networks
WS_OPEN_TIMEOUT=120
WS_PING_TIMEOUT=30

# Optimize file handling
CHUNK_SIZE=16384  # Larger chunks for big files
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add real-time progress tests
4. Ensure WebSocket/SSE compatibility
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- [ComfyUI](https://github.com/comfyanonymous/ComfyUI) - The underlying UI and workflow engine
- [ReActor](https://github.com/Gourieff/comfyui-reactor-node) - Face swapping node
- [FastAPI](https://fastapi.tiangolo.com/) - Modern web framework for building APIs
- [websockets](https://websockets.readthedocs.io/) - WebSocket implementation for Python
- [sse-starlette](https://github.com/sysid/sse-starlette) - Server-Sent Events for FastAPI