"""
FastAPI server: accepts MCAP + boundary file uploads, runs the pipeline,
and returns viz_data + session_summary as JSON.

Usage:
    uvicorn brain.server:app --reload --port 8000
"""

import json
import logging
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from brain.main import run_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("brain.server")

app = FastAPI(title="Pocket Race Engineer API", version="0.1.0")

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
    """
    if not mcap.filename or not mcap.filename.endswith(".mcap"):
        raise HTTPException(400, "Expected a .mcap file")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # Save uploaded MCAP
        mcap_path = tmp_path / mcap.filename
        mcap_bytes = await mcap.read()
        mcap_path.write_bytes(mcap_bytes)

        # Save or use default boundary file
        if boundaries and boundaries.filename:
            bnd_path = tmp_path / boundaries.filename
            bnd_bytes = await boundaries.read()
            bnd_path.write_bytes(bnd_bytes)
        else:
            if not DEFAULT_BOUNDARY.exists():
                raise HTTPException(400, "No boundary file uploaded and no default found")
            bnd_path = DEFAULT_BOUNDARY

        # Run pipeline
        output_path = tmp_path / "session_summary.json"
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

        viz_path = tmp_path / "viz_data.json"
        if not viz_path.exists():
            raise HTTPException(500, "Pipeline did not produce viz_data.json")
        viz_data = json.loads(viz_path.read_text())

    return JSONResponse({
        "viz_data": viz_data,
        "session_summary": summary,
    })


@app.get("/api/health")
async def health():
    return {"status": "ok"}
