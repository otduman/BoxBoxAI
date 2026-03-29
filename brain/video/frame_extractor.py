"""
Extract video frames from MCAP files at specific timestamps.

Supports extracting frames for coaching verdicts to show visual context
of what happened during each identified issue.
"""

import base64
import logging
from dataclasses import dataclass
from pathlib import Path

from mcap.reader import make_reader

logger = logging.getLogger(__name__)

# Camera topics to check (in priority order)
CAMERA_TOPICS = [
    "/constructor0/sensor/camera_fl/compressed_image",  # Front-left (primary)
    "/constructor0/sensor/camera_r/compressed_image",   # Rear
]


@dataclass
class ExtractedFrame:
    """A single extracted frame."""
    timestamp_ns: int
    camera: str
    format: str  # e.g., "jpeg", "png"
    data: bytes

    def to_data_url(self) -> str:
        """Convert to base64 data URL for embedding in HTML/JSON."""
        b64 = base64.b64encode(self.data).decode("utf-8")
        mime = f"image/{self.format}"
        return f"data:{mime};base64,{b64}"

    def to_dict(self) -> dict:
        """Serialize for JSON (without raw bytes)."""
        return {
            "timestamp_ns": self.timestamp_ns,
            "camera": self.camera,
            "format": self.format,
            "data_url": self.to_data_url(),
        }


def get_available_cameras(mcap_path: Path | str) -> list[str]:
    """List available camera topics in an MCAP file."""
    available = []
    with open(mcap_path, "rb") as f:
        reader = make_reader(f)
        summary = reader.get_summary()
        for channel in summary.channels.values():
            if "compressed_image" in channel.topic.lower():
                available.append(channel.topic)
    return available


def extract_frame_at_timestamp(
    mcap_path: Path | str,
    target_time_s: float,
    camera_topic: str | None = None,
    tolerance_s: float = 0.2,
) -> ExtractedFrame | None:
    """
    Extract the closest frame to a target timestamp.

    Args:
        mcap_path: Path to MCAP file
        target_time_s: Target time in seconds. Can be:
            - Relative to session start (0-100s range)
            - Absolute Unix timestamp (1.7B+ seconds)
            The function auto-detects which format is used.
        camera_topic: Specific camera topic, or None to auto-detect
        tolerance_s: Maximum time difference to accept (default 0.2s)

    Returns:
        ExtractedFrame or None if no frame found within tolerance
    """
    try:
        # Import decoder lazily to avoid import errors if mcap_ros2 not installed
        from mcap_ros2.decoder import DecoderFactory
    except ImportError:
        logger.warning("mcap_ros2 not installed, cannot extract frames")
        return None

    # Determine which topic to use
    if camera_topic is None:
        available = get_available_cameras(mcap_path)
        for preferred in CAMERA_TOPICS:
            if preferred in available:
                camera_topic = preferred
                break
        if camera_topic is None and available:
            camera_topic = available[0]
        if camera_topic is None:
            logger.warning(f"No camera topics found in {mcap_path}")
            return None

    best_frame = None
    best_diff = float("inf")
    session_start_ns = None

    # Auto-detect if timestamp is absolute (Unix epoch) or relative
    # Unix timestamps from 2020+ are > 1.5 billion seconds
    is_absolute_timestamp = target_time_s > 1_500_000_000

    with open(mcap_path, "rb") as f:
        reader = make_reader(f, decoder_factories=[DecoderFactory()])

        for schema, channel, message, decoded in reader.iter_decoded_messages(
            topics=[camera_topic]
        ):
            if session_start_ns is None:
                session_start_ns = message.log_time

            # Compare using either absolute or relative time
            if is_absolute_timestamp:
                # Target is absolute Unix timestamp - compare directly
                msg_time_s = message.log_time / 1e9
                diff = abs(msg_time_s - target_time_s)
            else:
                # Target is relative to session start
                rel_time_s = (message.log_time - session_start_ns) / 1e9
                diff = abs(rel_time_s - target_time_s)

            if diff < best_diff:
                best_diff = diff
                best_frame = ExtractedFrame(
                    timestamp_ns=message.log_time,
                    camera=camera_topic.split("/")[-2],  # e.g., "camera_fl"
                    format=decoded.format,
                    data=bytes(decoded.data),
                )

            # Early exit if we've passed the target by more than tolerance
            if is_absolute_timestamp:
                msg_time_s = message.log_time / 1e9
                if msg_time_s > target_time_s + tolerance_s:
                    break
            else:
                rel_time_s = (message.log_time - session_start_ns) / 1e9
                if rel_time_s > target_time_s + tolerance_s:
                    break

    if best_frame and best_diff <= tolerance_s:
        return best_frame

    return None


def extract_frames_for_verdicts(
    mcap_path: Path | str,
    verdicts: list[dict],
    session_start_time_s: float = 0.0,
) -> dict[str, ExtractedFrame]:
    """
    Extract frames for a list of coaching verdicts.

    Args:
        mcap_path: Path to MCAP file
        verdicts: List of verdict dicts with 'segment' and 'timestamp_s' keys
        session_start_time_s: Offset if verdicts use absolute time

    Returns:
        Dict mapping verdict segment ID to extracted frame
    """
    frames = {}

    for v in verdicts:
        segment = v.get("segment", "unknown")
        timestamp = v.get("timestamp_s", v.get("time_s", 0))

        # Skip if we already have a frame for this segment
        if segment in frames:
            continue

        frame = extract_frame_at_timestamp(
            mcap_path,
            timestamp - session_start_time_s,
        )

        if frame:
            frames[segment] = frame
            logger.debug(f"Extracted frame for {segment} at {timestamp:.2f}s")

    return frames


def extract_frames_batch(
    mcap_path: Path | str,
    timestamps_s: list[float],
    camera_topic: str | None = None,
) -> list[ExtractedFrame | None]:
    """
    Extract multiple frames efficiently in a single pass.

    Args:
        mcap_path: Path to MCAP file
        timestamps_s: List of target timestamps in seconds
        camera_topic: Specific camera topic, or None to auto-detect

    Returns:
        List of ExtractedFrame (or None) for each timestamp
    """
    try:
        from mcap_ros2.decoder import DecoderFactory
    except ImportError:
        logger.warning("mcap_ros2 not installed, cannot extract frames")
        return [None] * len(timestamps_s)

    if not timestamps_s:
        return []

    # Sort timestamps and track original indices
    sorted_times = sorted(enumerate(timestamps_s), key=lambda x: x[1])
    results = [None] * len(timestamps_s)

    # Determine camera topic
    if camera_topic is None:
        available = get_available_cameras(mcap_path)
        for preferred in CAMERA_TOPICS:
            if preferred in available:
                camera_topic = preferred
                break
        if camera_topic is None and available:
            camera_topic = available[0]
        if camera_topic is None:
            return results

    tolerance_s = 0.2
    time_idx = 0  # Current timestamp we're looking for
    session_start_ns = None

    with open(mcap_path, "rb") as f:
        reader = make_reader(f, decoder_factories=[DecoderFactory()])

        for schema, channel, message, decoded in reader.iter_decoded_messages(
            topics=[camera_topic]
        ):
            if time_idx >= len(sorted_times):
                break

            if session_start_ns is None:
                session_start_ns = message.log_time

            rel_time_s = (message.log_time - session_start_ns) / 1e9
            orig_idx, target_time = sorted_times[time_idx]

            diff = abs(rel_time_s - target_time)

            # Check if this frame is better than what we have
            if diff <= tolerance_s:
                current = results[orig_idx]
                if current is None or diff < abs(
                    (current.timestamp_ns - session_start_ns) / 1e9 - target_time
                ):
                    results[orig_idx] = ExtractedFrame(
                        timestamp_ns=message.log_time,
                        camera=camera_topic.split("/")[-2],
                        format=decoded.format,
                        data=bytes(decoded.data),
                    )

            # Move to next timestamp if we've passed current target
            if rel_time_s > target_time + tolerance_s:
                time_idx += 1

    return results
