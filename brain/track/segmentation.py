"""
Track segmentation: detects corners and straights from track geometry curvature.

Works on any circuit — no hardcoded corner positions or names.
"""

import logging
from dataclasses import dataclass

import numpy as np

from brain.config import (
    CURVATURE_CORNER_THRESHOLD,
    MIN_CORNER_LENGTH_M,
    MIN_STRAIGHT_LENGTH_M,
    CHICANE_MERGE_GAP_M,
)
from brain.track.boundaries import TrackGeometry

logger = logging.getLogger(__name__)


@dataclass
class TrackSegment:
    """A single corner or straight segment on the track."""
    segment_id: str         # e.g. "Turn_1", "Straight_3"
    segment_type: str       # "corner" or "straight"
    start_idx: int          # Index into track geometry arrays
    end_idx: int            # Index into track geometry arrays
    start_dist_m: float     # Meters along centerline
    end_dist_m: float       # Meters along centerline
    length_m: float         # Segment length
    direction: str          # "left", "right", or "straight"
    avg_curvature: float    # Mean absolute curvature (corners only)
    peak_curvature: float   # Max absolute curvature (corners only)
    apex_idx: int           # Index of peak curvature (corners only)
    apex_dist_m: float      # Distance at apex


def detect_segments(track: TrackGeometry) -> list[TrackSegment]:
    """Detect corners and straights from track curvature.

    Algorithm:
    1. Threshold absolute curvature to classify each point as corner/straight.
    2. Extract contiguous runs.
    3. Merge short gaps between corners (chicane handling).
    4. Filter out segments shorter than minimums.
    5. Assign IDs.
    """
    abs_kappa = np.abs(track.curvature)
    is_corner = abs_kappa > CURVATURE_CORNER_THRESHOLD

    # Extract contiguous runs of corner/straight
    raw_segments = _extract_runs(is_corner, track)

    # Merge nearby corners (chicane handling)
    merged = _merge_chicane_gaps(raw_segments, track)

    # Filter too-short segments
    filtered = _filter_short_segments(merged)

    # Assign IDs
    turn_num = 0
    straight_num = 0
    for seg in filtered:
        if seg.segment_type == "corner":
            turn_num += 1
            seg.segment_id = f"Turn_{turn_num}"
        else:
            straight_num += 1
            seg.segment_id = f"Straight_{straight_num}"

    logger.info(
        f"Track segmentation: {turn_num} corners, {straight_num} straights "
        f"over {track.total_length:.0f}m"
    )

    return filtered


def _extract_runs(
    is_corner: np.ndarray, track: TrackGeometry
) -> list[TrackSegment]:
    """Extract contiguous runs of corner/straight classification."""
    segments = []
    n = len(is_corner)
    i = 0

    while i < n:
        current = is_corner[i]
        j = i
        while j < n and is_corner[j] == current:
            j += 1

        start_idx = i
        end_idx = j - 1
        seg_type = "corner" if current else "straight"

        start_dist = track.distance[start_idx]
        end_dist = track.distance[end_idx]
        length = end_dist - start_dist

        # Curvature stats for corners
        seg_kappa = track.curvature[start_idx:j]
        abs_kappa = np.abs(seg_kappa)
        avg_curv = float(abs_kappa.mean()) if len(abs_kappa) > 0 else 0.0
        peak_curv = float(abs_kappa.max()) if len(abs_kappa) > 0 else 0.0

        # Apex = point of maximum absolute curvature
        apex_local = int(abs_kappa.argmax()) if len(abs_kappa) > 0 else 0
        apex_idx = start_idx + apex_local
        apex_dist = track.distance[apex_idx]

        # Direction from sign of curvature at apex
        if seg_type == "corner":
            sign = track.curvature[apex_idx]
            direction = "left" if sign > 0 else "right"
        else:
            direction = "straight"

        segments.append(TrackSegment(
            segment_id="",
            segment_type=seg_type,
            start_idx=start_idx,
            end_idx=end_idx,
            start_dist_m=start_dist,
            end_dist_m=end_dist,
            length_m=length,
            direction=direction,
            avg_curvature=avg_curv,
            peak_curvature=peak_curv,
            apex_idx=apex_idx,
            apex_dist_m=apex_dist,
        ))

        i = j

    return segments


def _merge_chicane_gaps(
    segments: list[TrackSegment], track: TrackGeometry
) -> list[TrackSegment]:
    """Merge corners separated by gaps shorter than CHICANE_MERGE_GAP_M."""
    if len(segments) < 3:
        return segments

    merged = [segments[0]]

    for seg in segments[1:]:
        prev = merged[-1]

        # If previous and current are both corners separated by a short straight
        if (
            prev.segment_type == "corner"
            and seg.segment_type == "corner"
        ):
            gap = seg.start_dist_m - prev.end_dist_m
            if gap < CHICANE_MERGE_GAP_M:
                # Merge: extend previous corner to include current
                prev.end_idx = seg.end_idx
                prev.end_dist_m = seg.end_dist_m
                prev.length_m = prev.end_dist_m - prev.start_dist_m

                # Recompute curvature stats for merged region
                kappa = track.curvature[prev.start_idx:prev.end_idx + 1]
                abs_kappa = np.abs(kappa)
                prev.avg_curvature = float(abs_kappa.mean())
                prev.peak_curvature = float(abs_kappa.max())
                apex_local = int(abs_kappa.argmax())
                prev.apex_idx = prev.start_idx + apex_local
                prev.apex_dist_m = track.distance[prev.apex_idx]
                prev.direction = "left" if track.curvature[prev.apex_idx] > 0 else "right"
                continue

        # If previous is a corner and current is a short straight before another corner
        if (
            prev.segment_type == "straight"
            and seg.segment_type == "corner"
            and prev.length_m < CHICANE_MERGE_GAP_M
            and len(merged) >= 2
            and merged[-2].segment_type == "corner"
        ):
            # Remove the short straight and merge corners
            corner_before = merged[-2]
            merged.pop()  # Remove short straight

            corner_before.end_idx = seg.end_idx
            corner_before.end_dist_m = seg.end_dist_m
            corner_before.length_m = corner_before.end_dist_m - corner_before.start_dist_m

            kappa = track.curvature[corner_before.start_idx:corner_before.end_idx + 1]
            abs_kappa = np.abs(kappa)
            corner_before.avg_curvature = float(abs_kappa.mean())
            corner_before.peak_curvature = float(abs_kappa.max())
            apex_local = int(abs_kappa.argmax())
            corner_before.apex_idx = corner_before.start_idx + apex_local
            corner_before.apex_dist_m = track.distance[corner_before.apex_idx]
            corner_before.direction = (
                "left" if track.curvature[corner_before.apex_idx] > 0 else "right"
            )
            continue

        merged.append(seg)

    return merged


def _filter_short_segments(segments: list[TrackSegment]) -> list[TrackSegment]:
    """Remove segments shorter than their type's minimum length."""
    filtered = []
    for seg in segments:
        if seg.segment_type == "corner" and seg.length_m < MIN_CORNER_LENGTH_M:
            continue
        if seg.segment_type == "straight" and seg.length_m < MIN_STRAIGHT_LENGTH_M:
            continue
        filtered.append(seg)
    return filtered


def find_segment_for_distance(
    segments: list[TrackSegment], dist_m: float
) -> TrackSegment | None:
    """Find which segment contains a given track distance."""
    for seg in segments:
        if seg.start_dist_m <= dist_m <= seg.end_dist_m:
            return seg
    return None
