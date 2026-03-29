"""
FastAPI server: accepts MCAP + boundary file uploads, runs the pipeline,
and returns viz_data + session_summary as JSON.

Also provides a chat endpoint for conversational coaching.

Usage:
    uvicorn brain.server:app --reload --port 8000
"""

import json
import logging
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from brain.main import run_pipeline
from brain.chat_service import get_chat_service
from brain.video import extract_frame_at_timestamp, extract_frames_around_timestamp, get_available_cameras

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("brain.server")

app = FastAPI(title="Pocket Race Engineer API", version="0.1.0")

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Default boundary file for Yas Marina
DEFAULT_BOUNDARY = Path(__file__).parent.parent / "driving-data" / "yas_marina_bnd.json"


@app.post("/api/analyze")
async def analyze(
    mcap: UploadFile = File(...),
    boundaries: UploadFile | None = File(None),
    driver_level: str = "intermediate",
    driver_profile: str = "autonomous",
):
    """Run the full pipeline on an uploaded MCAP file.

    Returns { viz_data, session_summary } as a single JSON payload.
    Also persists the MCAP file for video frame extraction.
    """
    global _uploaded_mcap_path

    if not mcap.filename or not mcap.filename.endswith(".mcap"):
        raise HTTPException(400, "Expected a .mcap file")

    # Ensure upload directory exists
    upload_dir = Path(__file__).parent.parent / "uploads"
    upload_dir.mkdir(exist_ok=True)

    # Save uploaded MCAP persistently (for video frame extraction)
    mcap_path = upload_dir / mcap.filename
    mcap_bytes = await mcap.read()
    mcap_path.write_bytes(mcap_bytes)
    _uploaded_mcap_path = mcap_path
    logger.info(f"Saved uploaded MCAP to {mcap_path}")

    # Save or use default boundary file
    if boundaries and boundaries.filename:
        bnd_path = upload_dir / boundaries.filename
        bnd_bytes = await boundaries.read()
        bnd_path.write_bytes(bnd_bytes)
    else:
        if not DEFAULT_BOUNDARY.exists():
            # Try hackathon directory as fallback
            hackathon_bnd = Path(__file__).parent.parent / "hackathon" / "yas_marina_bnd.json"
            if hackathon_bnd.exists():
                bnd_path = hackathon_bnd
            else:
                raise HTTPException(400, "No boundary file uploaded and no default found")
        else:
            bnd_path = DEFAULT_BOUNDARY

    # Output paths - save viz_data to web/public for frontend access
    viz_data_path = Path(__file__).parent.parent / "web" / "public" / "viz_data.json"
    viz_data_path.parent.mkdir(parents=True, exist_ok=True)
    output_path = upload_dir / "session_summary.json"

    # Run pipeline
    try:
        run_pipeline(
            mcap_path=str(mcap_path),
            boundary_path=str(bnd_path),
            output_path=str(output_path),
            driver_level=driver_level,
            driver_profile=driver_profile,
        )
    except Exception as e:
        logger.exception("Pipeline failed")
        raise HTTPException(500, f"Pipeline error: {e}")

    # Read outputs
    summary = json.loads(output_path.read_text())

    # The pipeline saves viz_data alongside the output - copy to web/public
    pipeline_viz_path = output_path.parent / "viz_data.json"
    if pipeline_viz_path.exists():
        viz_data = json.loads(pipeline_viz_path.read_text())
        # Also save to web/public for frontend
        viz_data_path.write_text(json.dumps(viz_data, indent=2))
        logger.info(f"Updated viz_data at {viz_data_path}")
    else:
        raise HTTPException(500, "Pipeline did not produce viz_data.json")

    return JSONResponse({
        "viz_data": viz_data,
        "session_summary": summary,
    })


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Chat API
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    """A single chat message."""
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    """Request body for chat endpoint."""
    message: str
    session_summary: dict | None = None
    conversation_history: list[ChatMessage] | None = None
    stream: bool = False


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """
    Chat with the racing coach AI.

    The AI is strictly limited to racing/coaching topics only.
    Provide session_summary for context-aware responses.
    """
    chat_service = get_chat_service()

    if not chat_service.is_available():
        raise HTTPException(
            503,
            "Chat service unavailable. GEMINI_API_KEY not configured."
        )

    # Convert history to dict format
    history = None
    if request.conversation_history:
        history = [{"role": m.role, "content": m.content} for m in request.conversation_history]

    if request.stream:
        # Stream response
        def generate():
            for chunk in chat_service.chat_stream(
                message=request.message,
                session_summary=request.session_summary,
                conversation_history=history,
            ):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }
        )
    else:
        # Non-streaming response
        response = chat_service.chat(
            message=request.message,
            session_summary=request.session_summary,
            conversation_history=history,
        )
        return JSONResponse({"response": response})


@app.get("/api/chat/status")
async def chat_status():
    """Check if chat service is available."""
    chat_service = get_chat_service()
    return {
        "available": chat_service.is_available(),
        "message": "Ready" if chat_service.is_available() else "GEMINI_API_KEY not set"
    }


# ---------------------------------------------------------------------------
# Video Frame API
# ---------------------------------------------------------------------------

# Store uploaded MCAP path for frame extraction
_uploaded_mcap_path: Path | None = None


@app.get("/api/frame")
async def get_frame(timestamp: float, camera: str | None = None):
    """
    Extract a single frame from the uploaded MCAP at the given timestamp.

    Args:
        timestamp: Time in seconds from session start
        camera: Camera topic (optional, auto-detects if not provided)

    Returns:
        JSON with frame data URL (base64 encoded image)
    """
    global _uploaded_mcap_path

    # Check for uploaded MCAP or use default demo file
    mcap_path = _uploaded_mcap_path
    if mcap_path is None or not mcap_path.exists():
        # Try default hackathon file for demo
        default_mcap = Path(__file__).parent.parent / "hackathon" / "hackathon_fast_laps.mcap"
        if default_mcap.exists():
            mcap_path = default_mcap
        else:
            raise HTTPException(404, "No MCAP file available. Upload one first.")

    frame = extract_frame_at_timestamp(
        mcap_path=mcap_path,
        target_time_s=timestamp,
        camera_topic=camera,
    )

    if frame is None:
        raise HTTPException(404, f"No frame found near timestamp {timestamp}s")

    return JSONResponse({
        "timestamp_s": timestamp,
        "actual_timestamp_ns": frame.timestamp_ns,
        "camera": frame.camera,
        "format": frame.format,
        "data_url": frame.to_data_url(),
    })


@app.get("/api/frames")
async def get_frames(
    timestamp: float,
    num_frames: int = 5,
    span_s: float = 2.0,
    camera: str | None = None,
    mcap_file: str | None = None,
):
    """
    Extract multiple frames around a timestamp for a video snippet carousel.

    Args:
        timestamp: Center timestamp in seconds
        num_frames: Number of frames to extract (default 5)
        span_s: Total time span in seconds (default 2.0s = ±1s around center)
        camera: Camera topic (optional, auto-detects if not provided)
        mcap_file: Specific MCAP filename to use (for demo mode)

    Returns:
        JSON with list of frame data URLs
    """
    global _uploaded_mcap_path

    mcap_path = _uploaded_mcap_path

    # If specific mcap_file requested (demo mode), try hackathon directory
    if mcap_file:
        specific_mcap = Path(__file__).parent.parent / "hackathon" / mcap_file
        if specific_mcap.exists():
            mcap_path = specific_mcap

    if mcap_path is None or not mcap_path.exists():
        default_mcap = Path(__file__).parent.parent / "hackathon" / "hackathon_fast_laps.mcap"
        if default_mcap.exists():
            mcap_path = default_mcap
        else:
            raise HTTPException(404, "No MCAP file available. Upload one first.")

    frames = extract_frames_around_timestamp(
        mcap_path=mcap_path,
        target_time_s=timestamp,
        camera_topic=camera,
        num_frames=num_frames,
        span_s=span_s,
    )

    if not frames:
        raise HTTPException(404, f"No frames found near timestamp {timestamp}s")

    return JSONResponse({
        "center_timestamp_s": timestamp,
        "num_frames": len(frames),
        "span_s": span_s,
        "frames": [
            {
                "timestamp_ns": f.timestamp_ns,
                "camera": f.camera,
                "format": f.format,
                "data_url": f.to_data_url(),
            }
            for f in frames
        ],
    })


@app.get("/api/cameras")
async def list_cameras():
    """List available camera topics in the current MCAP file."""
    global _uploaded_mcap_path

    mcap_path = _uploaded_mcap_path
    if mcap_path is None or not mcap_path.exists():
        default_mcap = Path(__file__).parent.parent / "hackathon" / "hackathon_fast_laps.mcap"
        if default_mcap.exists():
            mcap_path = default_mcap
        else:
            raise HTTPException(404, "No MCAP file available")

    cameras = get_available_cameras(mcap_path)
    return {"cameras": cameras}


# ---------------------------------------------------------------------------
# Moment-specific Coaching API
# ---------------------------------------------------------------------------

class MomentCoachingRequest(BaseModel):
    """Request body for moment-specific coaching."""
    timestamp_s: float
    segment: str
    finding: str


@app.post("/api/moment-coaching")
async def moment_coaching(request: MomentCoachingRequest):
    """
    Get AI coaching for a specific moment in the lap.

    This is used when showing video snippets of mistakes to provide
    context-aware, actionable coaching advice.
    """
    chat_service = get_chat_service()

    if not chat_service.is_available():
        raise HTTPException(
            503,
            "AI coaching unavailable. GEMINI_API_KEY not configured."
        )

    result = chat_service.get_moment_coaching(
        timestamp_s=request.timestamp_s,
        segment=request.segment,
        finding=request.finding,
    )

    return JSONResponse(result)


# ---------------------------------------------------------------------------
# Serve built React frontend (production)
# Must be mounted last so API routes take precedence
# ---------------------------------------------------------------------------

_frontend_dist = Path(__file__).parent.parent / "web" / "dist"
if _frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=str(_frontend_dist / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str):
        """Serve the React SPA for all non-API routes."""
        file = _frontend_dist / full_path
        if file.is_file():
            return FileResponse(str(file))
        # Only serve index.html for app routes (no file extension = SPA route)
        # Return 404 for missing files with extensions (.json, .js, etc.)
        if Path(full_path).suffix:
            raise HTTPException(404, "Not found")
        return FileResponse(str(_frontend_dist / "index.html"))
