"""
Track boundary processing: loads boundary JSON files and computes
centerline, cumulative distance, and curvature for any circuit.

Input format: {"boundaries": {"left_border": [[x,y],...], "right_border": [[x,y],...]}}
"""

import json
import logging
from pathlib import Path
from dataclasses import dataclass

import numpy as np
from scipy.interpolate import interp1d
from scipy.signal import savgol_filter

logger = logging.getLogger(__name__)


@dataclass
class TrackGeometry:
    """Processed track geometry ready for segmentation and projection."""
    left: np.ndarray           # (N, 2) left border points
    right: np.ndarray          # (N, 2) right border points
    centerline: np.ndarray     # (N, 2) centerline points
    distance: np.ndarray       # (N,) cumulative arc length along centerline (m)
    curvature: np.ndarray      # (N,) signed curvature (1/m, positive = left turn)
    width: np.ndarray          # (N,) track width at each point (m)
    total_length: float        # Total track length (m)
    n_points: int              # Number of resampled points


def _cumulative_arc_length(pts: np.ndarray) -> np.ndarray:
    """Compute cumulative arc length for a (N, 2) array of points."""
    diffs = np.diff(pts, axis=0)
    seg_lengths = np.sqrt((diffs ** 2).sum(axis=1))
    return np.concatenate([[0.0], np.cumsum(seg_lengths)])


def _resample_border(pts: np.ndarray, n_out: int) -> np.ndarray:
    """Resample a border to n_out equally spaced points by arc length."""
    s = _cumulative_arc_length(pts)
    s_norm = s / s[-1]  # Normalize to [0, 1]
    t_new = np.linspace(0, 1, n_out)

    fx = interp1d(s_norm, pts[:, 0], kind="cubic")
    fy = interp1d(s_norm, pts[:, 1], kind="cubic")

    return np.column_stack([fx(t_new), fy(t_new)])


def _compute_curvature(pts: np.ndarray, smoothing_window: int = 51) -> np.ndarray:
    """Compute signed curvature via discrete formula with Savitzky-Golay smoothing.

    kappa = (x'*y'' - y'*x'') / (x'^2 + y'^2)^(3/2)

    Positive curvature = turning left.
    """
    # Smooth coordinates first to suppress discretization noise
    if len(pts) < smoothing_window:
        smoothing_window = max(5, len(pts) // 4 * 2 + 1)

    x = savgol_filter(pts[:, 0], smoothing_window, 3)
    y = savgol_filter(pts[:, 1], smoothing_window, 3)

    # First and second derivatives via central differences
    dx = np.gradient(x)
    dy = np.gradient(y)
    ddx = np.gradient(dx)
    ddy = np.gradient(dy)

    # Curvature formula
    numer = dx * ddy - dy * ddx
    denom = (dx**2 + dy**2) ** 1.5

    # Avoid division by zero
    kappa = np.divide(numer, denom, out=np.zeros_like(numer), where=denom > 1e-10)

    # Clip outlier spikes caused by boundary kinks or discretization artifacts.
    # Use a robust percentile-based clip: anything beyond the 99th percentile
    # of |curvature| is clamped to that value (preserving sign).
    p99 = np.percentile(np.abs(kappa), 99)
    if p99 > 0:
        kappa = np.clip(kappa, -p99, p99)

    return kappa


def load_track_boundaries(
    boundary_path: str | Path,
    n_points: int = 6000,
) -> TrackGeometry:
    """Load a track boundary JSON and compute centerline geometry.

    Args:
        boundary_path: Path to the boundary JSON file.
        n_points: Number of resampled points for the centerline.

    Returns:
        TrackGeometry with all derived quantities.
    """
    boundary_path = Path(boundary_path)
    if not boundary_path.exists():
        raise FileNotFoundError(f"Boundary file not found: {boundary_path}")

    with open(boundary_path, "r") as f:
        data = json.load(f)

    boundaries = data.get("boundaries", data)
    left_raw = np.array(boundaries["left_border"], dtype=np.float64)
    right_raw = np.array(boundaries["right_border"], dtype=np.float64)

    logger.info(
        f"Loaded track boundaries: left={len(left_raw)} pts, right={len(right_raw)} pts"
    )

    # Resample both borders to the same number of points
    left = _resample_border(left_raw, n_points)
    right = _resample_border(right_raw, n_points)

    # Centerline = midpoint of left and right borders
    centerline = (left + right) / 2.0

    # Cumulative distance along centerline
    distance = _cumulative_arc_length(centerline)
    total_length = distance[-1]

    # Track width at each point
    width = np.sqrt(((left - right) ** 2).sum(axis=1))

    # Curvature of the centerline
    curvature = _compute_curvature(centerline)

    logger.info(
        f"Track geometry: {total_length:.0f}m length, "
        f"width {width.mean():.1f}m avg, "
        f"max |curvature| = {np.abs(curvature).max():.4f} rad/m"
    )

    return TrackGeometry(
        left=left,
        right=right,
        centerline=centerline,
        distance=distance,
        curvature=curvature,
        width=width,
        total_length=total_length,
        n_points=n_points,
    )


def project_to_centerline(
    track: TrackGeometry,
    xy: np.ndarray,
    max_backward_m: float = 50.0,
    search_window: int = 200,
) -> tuple[np.ndarray, np.ndarray]:
    """Project (x, y) car positions onto the centerline.

    Handles two distinct problems:
    1. **Lap wraparound**: on a circular track the car crosses the start/finish
       line, causing track_dist to jump from ~total_length back to ~0.
       This is legitimate and handled by unwrapping.
    2. **KDTree mis-snaps**: on tracks with parallel sections (hairpins),
       the nearest-point can snap to the wrong segment.
       This is a bug and handled by forward-window re-projection.

    Args:
        track: The processed track geometry.
        xy: (M, 2) array of car positions.
        max_backward_m: Maximum allowed backward jump after unwrapping.
        search_window: Centerline points to search forward when correcting.

    Returns:
        (track_distance, lateral_offset) — both arrays of shape (M,).
        track_distance: meters along the centerline (unwrapped, monotonic).
        lateral_offset: signed distance from centerline (positive = left).
    """
    from scipy.spatial import cKDTree

    tree = cKDTree(track.centerline)
    dists, indices = tree.query(xy)

    track_dist = track.distance[indices].copy()
    L = track.total_length

    # --- Step 1: Unwrap circular track distance ---
    # When the car crosses the start/finish line, track_dist jumps from
    # ~L to ~0. Detect these wraparounds (backward jump > 80% of track
    # length) and add L to all subsequent samples.
    wrap_offset = 0.0
    unwrapped = np.empty_like(track_dist)
    unwrapped[0] = track_dist[0]

    for i in range(1, len(track_dist)):
        delta = track_dist[i] - track_dist[i - 1]
        if delta < -L * 0.8:
            # Legitimate lap wraparound
            wrap_offset += L
        elif delta > L * 0.8:
            # Reverse wraparound (shouldn't happen normally)
            wrap_offset -= L
        unwrapped[i] = track_dist[i] + wrap_offset

    # --- Step 2: Fix KDTree mis-snaps (monotonicity enforcement) ---
    # After unwrapping, any remaining backward jumps > max_backward_m
    # are genuine mis-snaps from parallel track sections.
    n_fixed = 0
    for i in range(1, len(unwrapped)):
        delta = unwrapped[i] - unwrapped[i - 1]
        if delta < -max_backward_m:
            # Re-project within a forward window along the centerline
            prev_idx = indices[i - 1]
            # Search forward, wrapping around the centerline array
            search_indices = np.arange(prev_idx, prev_idx + search_window) % track.n_points
            window = track.centerline[search_indices]

            d = np.sqrt(((window - xy[i]) ** 2).sum(axis=1))
            best_local = int(d.argmin())
            best_global = search_indices[best_local]

            indices[i] = best_global
            new_raw_dist = track.distance[best_global]
            # Maintain the wrap offset
            if new_raw_dist < track_dist[i - 1] - L * 0.8:
                unwrapped[i] = new_raw_dist + wrap_offset + L
            else:
                unwrapped[i] = new_raw_dist + wrap_offset
            track_dist[i] = new_raw_dist
            n_fixed += 1

    if n_fixed > 0:
        logger.info(
            f"  Projection: corrected {n_fixed} KDTree mis-snap(s)"
        )

    n_wraps = int(wrap_offset / L) if L > 0 else 0
    if n_wraps > 0:
        logger.info(
            f"  Projection: unwrapped {n_wraps} lap crossing(s)"
        )

    # Compute signed lateral offset
    # Positive = left of travel direction
    cl_pts = track.centerline[indices]
    offsets = xy - cl_pts

    # Get local tangent direction
    next_idx = np.minimum(indices + 1, track.n_points - 1)
    tangent = track.centerline[next_idx] - cl_pts
    tangent_norm = np.sqrt((tangent**2).sum(axis=1, keepdims=True))
    tangent_norm = np.maximum(tangent_norm, 1e-10)
    tangent = tangent / tangent_norm

    # Normal = 90-degree left rotation of tangent
    normal = np.column_stack([-tangent[:, 1], tangent[:, 0]])

    # Signed lateral offset = dot product with normal
    lateral = (offsets * normal).sum(axis=1)

    return unwrapped, lateral
