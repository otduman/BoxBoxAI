"""
Track visualization data exporter.

Generates a JSON file containing:
  - Decimated track outline (centerline, left/right borders)
  - Segment regions (corners/straights with start/end XY)
  - Verdict markers with XY positions on the track

This JSON is consumed by the standalone HTML visualizer (viz.html).
"""

import json
import logging
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from brain.track.boundaries import TrackGeometry
from brain.track.segmentation import TrackSegment
from brain.physics.coaching_rules import CoachingVerdicts

logger = logging.getLogger(__name__)


def _decimate(arr: np.ndarray, target_points: int = 500) -> np.ndarray:
    """Decimate a (N, 2) array to ~target_points for lightweight JSON."""
    n = len(arr)
    if n <= target_points:
        return arr
    step = max(1, n // target_points)
    return arr[::step]


def _dist_to_xy(track: TrackGeometry, dist_m: float) -> tuple[float, float]:
    """Convert a track distance (meters) to XY coordinates on the centerline."""
    # Wrap distance to track length
    d = dist_m % track.total_length
    idx = int(np.searchsorted(track.distance, d))
    idx = min(idx, track.n_points - 1)
    return float(track.centerline[idx, 0]), float(track.centerline[idx, 1])


def _snap_to_trajectory(
    x: float, y: float, tree: cKDTree, car_xy: np.ndarray
) -> tuple[float, float]:
    """Snap an (x, y) point to the nearest point on the car trajectory."""
    _, idx = tree.query([x, y])
    return float(car_xy[idx, 0]), float(car_xy[idx, 1])


def build_viz_data(
    track: TrackGeometry,
    segments: list[TrackSegment],
    verdicts: CoachingVerdicts,
    car_xy: np.ndarray | None = None,
) -> dict:
    """Build the visualization data dict.

    Args:
        track: Processed track geometry.
        segments: Detected track segments.
        verdicts: Coaching verdicts with segment IDs.
        car_xy: Optional (M, 2) car trajectory for overlay.

    Returns:
        Dict ready for JSON serialization.
    """
    # Decimate track borders for lightweight rendering
    cl = _decimate(track.centerline)
    left = _decimate(track.left)
    right = _decimate(track.right)

    # Build KD-tree from car trajectory for snapping markers onto the road
    car_tree = cKDTree(car_xy) if car_xy is not None else None

    # Segment regions with XY bounds
    seg_data = []
    for seg in segments:
        sx, sy = _dist_to_xy(track, seg.start_dist_m)
        ex, ey = _dist_to_xy(track, seg.end_dist_m)
        ax, ay = _dist_to_xy(track, seg.apex_dist_m)
        # Snap segment points to car trajectory when available
        if car_tree is not None and car_xy is not None:
            sx, sy = _snap_to_trajectory(sx, sy, car_tree, car_xy)
            ex, ey = _snap_to_trajectory(ex, ey, car_tree, car_xy)
            ax, ay = _snap_to_trajectory(ax, ay, car_tree, car_xy)
        seg_data.append({
            "id": seg.segment_id,
            "type": seg.segment_type,
            "direction": seg.direction,
            "start": [sx, sy],
            "end": [ex, ey],
            "apex": [ax, ay],
            "start_m": round(seg.start_dist_m, 1),
            "end_m": round(seg.end_dist_m, 1),
            "length_m": round(seg.length_m, 1),
        })

    # Verdict markers with XY positions
    # Map segment IDs to their apex/midpoint XY (already snapped if car_xy exists)
    seg_xy_map = {s["id"]: s["apex"] for s in seg_data}

    markers = []
    for v in verdicts.verdicts:
        # Place marker at the segment's apex position, or track center if lap-level
        if v.segment_id and v.segment_id in seg_xy_map:
            mx, my = seg_xy_map[v.segment_id]
        else:
            # Lap-level verdict — snap to car trajectory start, or fallback to centerline
            if car_tree is not None and car_xy is not None:
                mx, my = float(car_xy[0, 0]), float(car_xy[0, 1])
            else:
                mx, my = float(cl[0, 0]), float(cl[0, 1])

        markers.append({
            "x": mx,
            "y": my,
            "segment": v.segment_id or "Lap-level",
            "lap": v.lap_number,
            "category": v.category.value,
            "severity": v.severity.value,
            "finding": v.finding,
            "reasoning": v.reasoning,
            "action": v.action,
            "time_impact_s": round(v.computed_delta_s, 3),
            "measured": round(v.computed_value, 3),
            "target": round(v.reference_value, 3),
            "unit": v.unit,
        })

    data = {
        "track": {
            "centerline": cl.round(2).tolist(),
            "left_border": left.round(2).tolist(),
            "right_border": right.round(2).tolist(),
            "total_length_m": round(track.total_length, 1),
        },
        "segments": seg_data,
        "markers": markers,
    }

    # Optional car trajectory
    if car_xy is not None:
        car_dec = _decimate(car_xy, target_points=800)
        data["car_trajectory"] = car_dec.round(2).tolist()

    return data


def export_viz_json(
    track: TrackGeometry,
    segments: list[TrackSegment],
    verdicts: CoachingVerdicts,
    output_path: str = "viz_data.json",
    car_xy: np.ndarray | None = None,
) -> str:
    """Export visualization JSON file.

    Returns:
        The output file path.
    """
    data = build_viz_data(track, segments, verdicts, car_xy)
    out = Path(output_path)
    with open(out, "w") as f:
        json.dump(data, f)
    logger.info(f"Viz data exported: {out} ({len(data['markers'])} markers)")
    return str(out)
