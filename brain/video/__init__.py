"""Video processing utilities for MCAP telemetry files."""

from .frame_extractor import (
    ExtractedFrame,
    extract_frame_at_timestamp,
    extract_frames_batch,
    extract_frames_for_verdicts,
    get_available_cameras,
)

__all__ = [
    "ExtractedFrame",
    "extract_frame_at_timestamp",
    "extract_frames_batch",
    "extract_frames_for_verdicts",
    "get_available_cameras",
]
