"""
Optimal reference builder.

Automatically computes the optimal reference from multiple laps by:
1. Identifying the fastest segments from each lap
2. Combining best-of-each-segment into a "theoretical best"
3. Providing comparison baselines for scoring

This makes the system track-independent and adapts to each driver's capability.
"""

import logging
from dataclasses import dataclass, field
from typing import TypeVar

from brain.physics.corner_analyzer import CornerAnalysis
from brain.physics.straight_analyzer import StraightAnalysis
from brain.track.segmentation import TrackSegment

logger = logging.getLogger(__name__)

T = TypeVar("T", CornerAnalysis, StraightAnalysis)


@dataclass
class SegmentReference:
    """Optimal reference values for a single segment."""
    segment_id: str
    segment_type: str  # "corner" or "straight"

    # Best values observed (from any lap)
    best_time_s: float = 0.0
    best_lap: int = -1

    # For corners
    optimal_entry_speed_kmh: float = 0.0
    optimal_exit_speed_kmh: float = 0.0
    optimal_apex_speed_kmh: float = 0.0
    optimal_brake_point_m: float = 0.0
    optimal_throttle_point_m: float = 0.0
    optimal_trail_brake_r2: float = 0.0
    optimal_deceleration_g: float = 0.0  # NEW: braking intensity
    optimal_lateral_g: float = 0.0  # NEW: grip utilization

    # For straights
    optimal_top_speed_kmh: float = 0.0
    optimal_throttle_pct: float = 0.0
    optimal_max_accel_g: float = 0.0
    optimal_straight_exit_speed_kmh: float = 0.0  # NEW: exit speed from straight

    # Statistical bounds (for percentile ranking)
    all_times_s: list[float] = field(default_factory=list)


@dataclass
class TrackReference:
    """Complete optimal reference for an entire track."""
    track_name: str
    total_laps_analyzed: int
    theoretical_best_s: float  # Sum of best segment times

    # Per-segment references
    segments: dict[str, SegmentReference] = field(default_factory=dict)

    # Best full lap (for comparison)
    best_lap_time_s: float = 0.0
    best_lap_number: int = -1


def build_corner_reference(
    corners: list[CornerAnalysis],
) -> SegmentReference:
    """
    Build optimal reference for a corner from multiple passes.

    Selection criteria (in priority order):
    1. Best exit speed (most important - compounds on straight)
    2. Best time through corner
    3. Highest apex speed

    The reference represents "what's achievable" based on actual data.
    """
    if not corners:
        return SegmentReference(segment_id="", segment_type="corner")

    segment = corners[0].segment
    ref = SegmentReference(
        segment_id=segment.segment_id,
        segment_type="corner",
    )

    # Collect all values
    exit_speeds = []
    times = []
    entry_speeds = []
    apex_speeds = []
    brake_points = []
    throttle_points = []
    trail_brake_r2s = []
    decel_gs = []
    lateral_gs = []

    for c in corners:
        if c.exit.exit_speed_kmh > 0:
            exit_speeds.append((c.exit.exit_speed_kmh, c.lap_number, c))
        if c.time_in_corner_s > 0:
            times.append((c.time_in_corner_s, c.lap_number))
            ref.all_times_s.append(c.time_in_corner_s)
        if c.entry_speed_kmh > 0:
            entry_speeds.append(c.entry_speed_kmh)
        if c.apex.min_speed_kmh > 0:
            apex_speeds.append(c.apex.min_speed_kmh)
        if c.braking.brake_point_dist_m > 0:
            brake_points.append(c.braking.brake_point_dist_m)
        if c.exit.throttle_point_dist_m > 0:
            throttle_points.append(c.exit.throttle_point_dist_m)
        if c.trail_brake.brake_while_turning:
            trail_brake_r2s.append(c.trail_brake.quality_r_squared)
        if c.braking.deceleration_g > 0:
            decel_gs.append(c.braking.deceleration_g)
        if c.apex.max_lateral_g > 0:
            lateral_gs.append(c.apex.max_lateral_g)

    # Select best exit speed lap as primary reference
    if exit_speeds:
        exit_speeds.sort(reverse=True)  # Highest first
        best_exit, best_lap, best_corner = exit_speeds[0]

        ref.optimal_exit_speed_kmh = best_exit
        ref.best_lap = best_lap

        # Use values from that same lap for consistency
        ref.optimal_entry_speed_kmh = best_corner.entry_speed_kmh
        ref.optimal_apex_speed_kmh = best_corner.apex.min_speed_kmh
        ref.optimal_brake_point_m = best_corner.braking.brake_point_dist_m
        ref.optimal_throttle_point_m = best_corner.exit.throttle_point_dist_m
        ref.optimal_trail_brake_r2 = best_corner.trail_brake.quality_r_squared
        ref.optimal_deceleration_g = best_corner.braking.deceleration_g
        ref.optimal_lateral_g = best_corner.apex.max_lateral_g

    # Best time through corner
    if times:
        times.sort()  # Lowest first
        ref.best_time_s = times[0][0]

    # Fallback: use statistical bests if primary reference incomplete
    if ref.optimal_entry_speed_kmh == 0 and entry_speeds:
        ref.optimal_entry_speed_kmh = max(entry_speeds)
    if ref.optimal_apex_speed_kmh == 0 and apex_speeds:
        ref.optimal_apex_speed_kmh = max(apex_speeds)
    if ref.optimal_brake_point_m == 0 and brake_points:
        # Latest brake point = highest value (closest to corner)
        ref.optimal_brake_point_m = max(brake_points)
    if ref.optimal_throttle_point_m == 0 and throttle_points:
        # Earliest throttle = lowest value
        ref.optimal_throttle_point_m = min(throttle_points)
    if ref.optimal_trail_brake_r2 == 0 and trail_brake_r2s:
        ref.optimal_trail_brake_r2 = max(trail_brake_r2s)
    if ref.optimal_deceleration_g == 0 and decel_gs:
        ref.optimal_deceleration_g = max(decel_gs)
    if ref.optimal_lateral_g == 0 and lateral_gs:
        ref.optimal_lateral_g = max(lateral_gs)

    return ref


def build_straight_reference(
    straights: list[StraightAnalysis],
) -> SegmentReference:
    """
    Build optimal reference for a straight from multiple passes.

    Selection criteria:
    1. Highest top speed achieved
    2. Best entry speed (from previous corner exit)
    3. Shortest time
    """
    if not straights:
        return SegmentReference(segment_id="", segment_type="straight")

    segment = straights[0].segment
    ref = SegmentReference(
        segment_id=segment.segment_id,
        segment_type="straight",
    )

    top_speeds = []
    entry_speeds = []
    exit_speeds = []
    times = []
    throttle_pcts = []
    accels = []

    for s in straights:
        if s.top_speed_kmh > 0:
            top_speeds.append((s.top_speed_kmh, s.lap_number, s))
        if s.entry_speed_kmh > 0:
            entry_speeds.append(s.entry_speed_kmh)
        if s.exit_speed_kmh > 0:
            exit_speeds.append(s.exit_speed_kmh)
        if s.time_on_straight_s > 0:
            times.append(s.time_on_straight_s)
            ref.all_times_s.append(s.time_on_straight_s)
        if s.time_at_full_throttle_pct > 0:
            throttle_pcts.append(s.time_at_full_throttle_pct)
        if s.max_acceleration_g > 0:
            accels.append(s.max_acceleration_g)

    # Select best top speed lap as primary reference
    if top_speeds:
        top_speeds.sort(reverse=True)
        best_top, best_lap, best_straight = top_speeds[0]

        ref.optimal_top_speed_kmh = best_top
        ref.best_lap = best_lap
        ref.optimal_entry_speed_kmh = best_straight.entry_speed_kmh
        ref.optimal_straight_exit_speed_kmh = best_straight.exit_speed_kmh
        ref.optimal_throttle_pct = best_straight.time_at_full_throttle_pct
        ref.optimal_max_accel_g = best_straight.max_acceleration_g

    if times:
        ref.best_time_s = min(times)

    # Fallbacks
    if ref.optimal_entry_speed_kmh == 0 and entry_speeds:
        ref.optimal_entry_speed_kmh = max(entry_speeds)
    if ref.optimal_throttle_pct == 0 and throttle_pcts:
        ref.optimal_throttle_pct = max(throttle_pcts)
    if ref.optimal_max_accel_g == 0 and accels:
        ref.optimal_max_accel_g = max(accels)
    if ref.optimal_straight_exit_speed_kmh == 0 and exit_speeds:
        ref.optimal_straight_exit_speed_kmh = max(exit_speeds)

    return ref


def build_track_reference(
    corner_analyses: dict[int, list[CornerAnalysis]],
    straight_analyses: dict[int, list[StraightAnalysis]],
    lap_times: dict[int, float] | None = None,
    track_name: str = "unknown",
) -> TrackReference:
    """
    Build complete track reference from all analyzed laps.

    Groups analyses by segment and computes optimal values for each.
    Also calculates theoretical best time (sum of best segment times).

    Args:
        corner_analyses: Dict of lap_number -> list of corner analyses
        straight_analyses: Dict of lap_number -> list of straight analyses
        lap_times: Optional dict of lap_number -> lap time in seconds
        track_name: Name of the track

    Returns:
        TrackReference with per-segment optimal values
    """
    total_laps = len(set(corner_analyses.keys()) | set(straight_analyses.keys()))

    ref = TrackReference(
        track_name=track_name,
        total_laps_analyzed=total_laps,
        theoretical_best_s=0.0,
    )

    # Group corners by segment
    corners_by_segment: dict[str, list[CornerAnalysis]] = {}
    for lap_corners in corner_analyses.values():
        for corner in lap_corners:
            seg_id = corner.segment.segment_id
            corners_by_segment.setdefault(seg_id, []).append(corner)

    # Group straights by segment
    straights_by_segment: dict[str, list[StraightAnalysis]] = {}
    for lap_straights in straight_analyses.values():
        for straight in lap_straights:
            seg_id = straight.segment.segment_id
            straights_by_segment.setdefault(seg_id, []).append(straight)

    # Build references
    for seg_id, corners in corners_by_segment.items():
        segment_ref = build_corner_reference(corners)
        ref.segments[seg_id] = segment_ref
        if segment_ref.best_time_s > 0:
            ref.theoretical_best_s += segment_ref.best_time_s

    for seg_id, straights in straights_by_segment.items():
        segment_ref = build_straight_reference(straights)
        ref.segments[seg_id] = segment_ref
        if segment_ref.best_time_s > 0:
            ref.theoretical_best_s += segment_ref.best_time_s

    # Find best actual lap
    if lap_times:
        best_lap_num = min(lap_times, key=lap_times.get)
        ref.best_lap_time_s = lap_times[best_lap_num]
        ref.best_lap_number = best_lap_num

    logger.info(
        f"Built track reference: {len(ref.segments)} segments, "
        f"theoretical best: {ref.theoretical_best_s:.2f}s, "
        f"from {total_laps} laps"
    )

    return ref


def get_reference_corner(
    track_ref: TrackReference,
    segment_id: str,
) -> CornerAnalysis | None:
    """
    Create a synthetic CornerAnalysis from reference values.

    This allows using reference values with the existing scoring system.
    """
    seg_ref = track_ref.segments.get(segment_id)
    if not seg_ref or seg_ref.segment_type != "corner":
        return None

    # Create minimal corner analysis with reference values
    # Note: This is a partial analysis used only for comparison
    from brain.physics.corner_analyzer import (
        CornerAnalysis, BrakingMetrics, TrailBrakeMetrics,
        ApexMetrics, ExitMetrics
    )

    corner = CornerAnalysis(
        segment=TrackSegment(
            segment_id=segment_id,
            segment_type="corner",
            start_idx=0, end_idx=0,
            start_dist_m=0, end_dist_m=0,
            length_m=0, direction="",
            avg_curvature=0, peak_curvature=0,
            apex_idx=0, apex_dist_m=0,
        ),
        lap_number=seg_ref.best_lap,
        entry_speed_kmh=seg_ref.optimal_entry_speed_kmh,
        time_in_corner_s=seg_ref.best_time_s,
    )

    corner.braking = BrakingMetrics(
        brake_point_dist_m=seg_ref.optimal_brake_point_m,
        deceleration_g=seg_ref.optimal_deceleration_g,
    )

    corner.trail_brake = TrailBrakeMetrics(
        quality_r_squared=seg_ref.optimal_trail_brake_r2,
        brake_while_turning=seg_ref.optimal_trail_brake_r2 > 0,
    )

    corner.apex = ApexMetrics(
        min_speed_kmh=seg_ref.optimal_apex_speed_kmh,
        max_lateral_g=seg_ref.optimal_lateral_g,
    )

    corner.exit = ExitMetrics(
        exit_speed_kmh=seg_ref.optimal_exit_speed_kmh,
        throttle_point_dist_m=seg_ref.optimal_throttle_point_m,
    )

    return corner


def get_reference_straight(
    track_ref: TrackReference,
    segment_id: str,
) -> StraightAnalysis | None:
    """
    Create a synthetic StraightAnalysis from reference values.
    """
    seg_ref = track_ref.segments.get(segment_id)
    if not seg_ref or seg_ref.segment_type != "straight":
        return None

    from brain.physics.straight_analyzer import StraightAnalysis

    straight = StraightAnalysis(
        segment=TrackSegment(
            segment_id=segment_id,
            segment_type="straight",
            start_idx=0, end_idx=0,
            start_dist_m=0, end_dist_m=0,
            length_m=0, direction="straight",
            avg_curvature=0, peak_curvature=0,
            apex_idx=0, apex_dist_m=0,
        ),
        lap_number=seg_ref.best_lap,
        entry_speed_kmh=seg_ref.optimal_entry_speed_kmh,
        exit_speed_kmh=seg_ref.optimal_straight_exit_speed_kmh,
        top_speed_kmh=seg_ref.optimal_top_speed_kmh,
        time_on_straight_s=seg_ref.best_time_s,
        time_at_full_throttle_pct=seg_ref.optimal_throttle_pct,
        max_acceleration_g=seg_ref.optimal_max_accel_g,
    )

    return straight


def reference_to_dict(ref: TrackReference) -> dict:
    """Serialize TrackReference to JSON-compatible dict."""
    return {
        "track_name": ref.track_name,
        "total_laps_analyzed": ref.total_laps_analyzed,
        "theoretical_best_s": round(ref.theoretical_best_s, 3),
        "best_lap_time_s": round(ref.best_lap_time_s, 3),
        "best_lap_number": ref.best_lap_number,
        "segments": {
            seg_id: {
                "segment_type": seg_ref.segment_type,
                "best_time_s": round(seg_ref.best_time_s, 3),
                "best_lap": seg_ref.best_lap,
                "optimal_entry_speed_kmh": round(seg_ref.optimal_entry_speed_kmh, 1),
                "optimal_exit_speed_kmh": round(seg_ref.optimal_exit_speed_kmh, 1),
                "optimal_apex_speed_kmh": round(seg_ref.optimal_apex_speed_kmh, 1),
                "optimal_brake_point_m": round(seg_ref.optimal_brake_point_m, 1),
                "optimal_top_speed_kmh": round(seg_ref.optimal_top_speed_kmh, 1),
            }
            for seg_id, seg_ref in ref.segments.items()
        },
    }


def compute_percentile(value: float, all_values: list[float], lower_is_better: bool = True) -> float:
    """
    Compute percentile rank of a value within a distribution.

    Returns 0-100 where 100 = best performance.

    Args:
        value: The value to rank
        all_values: All observed values for this metric
        lower_is_better: True for times (lower = better), False for speeds (higher = better)
    """
    if not all_values or len(all_values) < 2:
        return 50.0  # Not enough data

    sorted_vals = sorted(all_values, reverse=not lower_is_better)
    n = len(sorted_vals)

    # Find position
    for i, v in enumerate(sorted_vals):
        if lower_is_better:
            if value <= v:
                return 100.0 * (n - i) / n
        else:
            if value >= v:
                return 100.0 * (n - i) / n

    return 0.0
