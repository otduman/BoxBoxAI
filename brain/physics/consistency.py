"""
Consistency analyzer: lap-to-lap variation scoring and segment-level comparison.

Sign conventions for lap comparison deltas:
- time_delta_s: POSITIVE = comparison lap (b) was SLOWER (losing time)
- brake_delta_m: POSITIVE = comparison lap (b) braked LATER (smaller distance to corner)
- speed deltas: POSITIVE = comparison lap (b) was FASTER (higher speed = better)
"""

import logging
from dataclasses import dataclass, field

import numpy as np

from brain.physics.corner_analyzer import CornerAnalysis
from brain.physics.straight_analyzer import StraightAnalysis

logger = logging.getLogger(__name__)

# Minimum laps required for meaningful consistency analysis
MIN_LAPS_FOR_CONSISTENCY = 3


@dataclass
class SegmentConsistency:
    """Consistency metrics for a single segment across laps."""
    segment_id: str
    segment_type: str
    lap_times: list[float] = field(default_factory=list)
    mean_time_s: float = 0.0
    std_time_s: float = 0.0
    consistency_score: float = 0.0  # 0-100, higher = more consistent
    best_lap: int = 0
    worst_lap: int = 0
    time_spread_s: float = 0.0


@dataclass
class LapComparisonDelta:
    """Per-segment delta between two laps (lap_a = reference, lap_b = comparison).
    
    Sign conventions:
    - time_delta_s: POSITIVE = lap_b slower (losing time vs reference)
    - brake_delta_m: POSITIVE = lap_b braked LATER (closer to corner)
    - speed deltas: POSITIVE = lap_b faster (higher speed = better)
    """
    segment_id: str
    segment_type: str
    time_delta_s: float = 0.0       # Positive = lap_b slower than lap_a
    brake_delta_m: float = 0.0      # Positive = lap_b braked later (closer to corner)
    apex_speed_delta_kmh: float = 0.0  # Positive = lap_b faster (better)
    exit_speed_delta_kmh: float = 0.0  # Positive = lap_b faster (better)
    top_speed_delta_kmh: float = 0.0   # Positive = lap_b faster (better)


@dataclass
class ConsistencyAnalysis:
    """Full consistency analysis across all laps."""
    segment_scores: list[SegmentConsistency] = field(default_factory=list)
    overall_consistency_score: float = 0.0
    weakest_segment_id: str = ""
    strongest_segment_id: str = ""


def analyze_consistency(
    corner_analyses: dict[int, list[CornerAnalysis]],
    straight_analyses: dict[int, list[StraightAnalysis]],
) -> ConsistencyAnalysis:
    """Analyze consistency across all laps.

    Args:
        corner_analyses: {lap_number: [CornerAnalysis, ...]}
        straight_analyses: {lap_number: [StraightAnalysis, ...]}
    """
    result = ConsistencyAnalysis()

    if len(corner_analyses) < MIN_LAPS_FOR_CONSISTENCY:
        logger.info(
            f"Need at least {MIN_LAPS_FOR_CONSISTENCY} laps for consistency analysis "
            f"(have {len(corner_analyses)})"
        )
        return result

    # Group corner times by segment
    corner_times: dict[str, dict[int, float]] = {}
    for lap_num, analyses in corner_analyses.items():
        for ca in analyses:
            sid = ca.segment.segment_id
            if sid not in corner_times:
                corner_times[sid] = {}
            if ca.time_in_corner_s > 0:
                corner_times[sid][lap_num] = ca.time_in_corner_s

    # Group straight times by segment
    straight_times: dict[str, dict[int, float]] = {}
    for lap_num, analyses in straight_analyses.items():
        for sa in analyses:
            sid = sa.segment.segment_id
            if sid not in straight_times:
                straight_times[sid] = {}
            if sa.time_on_straight_s > 0:
                straight_times[sid][lap_num] = sa.time_on_straight_s

    # Compute consistency per segment
    all_segments = {}
    all_segments.update({k: ("corner", v) for k, v in corner_times.items()})
    all_segments.update({k: ("straight", v) for k, v in straight_times.items()})

    for sid, (stype, lap_time_map) in all_segments.items():
        if len(lap_time_map) < MIN_LAPS_FOR_CONSISTENCY:
            continue

        times = np.array(list(lap_time_map.values()))
        laps = list(lap_time_map.keys())
        
        # Use robust statistics to handle outliers (spins, yellows)
        mean_t = np.mean(times)
        std_t = np.std(times)
        
        # Remove outliers beyond 2 standard deviations for consistency scoring
        if len(times) >= 5 and std_t > 0:
            mask = np.abs(times - mean_t) <= 2 * std_t
            if mask.sum() >= 3:  # Need at least 3 clean laps
                clean_times = times[mask]
                mean_t = np.mean(clean_times)
                std_t = np.std(clean_times)

        # Consistency score using coefficient of variation (CV)
        # CV = std / mean, normalized: CV < 2% = excellent (100), CV > 10% = poor (0)
        if mean_t > 0:
            cv = std_t / mean_t
            # Scale: 0.02 (2%) = 100 points, 0.10 (10%) = 0 points
            score = max(0, min(100, 100 * (1 - cv / 0.10)))
        else:
            score = 0

        best_idx = int(np.argmin(times))
        worst_idx = int(np.argmax(times))

        sc = SegmentConsistency(
            segment_id=sid,
            segment_type=stype,
            lap_times=times.tolist(),
            mean_time_s=float(mean_t),
            std_time_s=float(std_t),
            consistency_score=float(score),
            best_lap=laps[best_idx],
            worst_lap=laps[worst_idx],
            time_spread_s=float(times.max() - times.min()),
        )
        result.segment_scores.append(sc)

    if result.segment_scores:
        scores = [s.consistency_score for s in result.segment_scores]
        result.overall_consistency_score = float(np.mean(scores))

        # Weakest segment: prioritize high variation + longer segments (bigger time loss potential)
        # Priority = std * mean (absolute variation in seconds)
        weakest = max(result.segment_scores, key=lambda s: s.std_time_s * s.mean_time_s)
        strongest = max(result.segment_scores, key=lambda s: s.consistency_score)
        result.weakest_segment_id = weakest.segment_id
        result.strongest_segment_id = strongest.segment_id

    logger.info(
        f"Consistency analysis: {len(result.segment_scores)} segments, "
        f"overall score: {result.overall_consistency_score:.1f}, "
        f"weakest: {result.weakest_segment_id}, strongest: {result.strongest_segment_id}"
    )

    return result


def compare_laps(
    corners_a: list[CornerAnalysis],
    corners_b: list[CornerAnalysis],
    straights_a: list[StraightAnalysis],
    straights_b: list[StraightAnalysis],
) -> list[LapComparisonDelta]:
    """Compare two laps segment-by-segment (a = reference/faster, b = comparison/slower).

    Sign conventions (motorsport standard):
    - Positive time delta = lap_b is SLOWER (losing time)
    - Positive brake delta = lap_b braked LATER (closer to corner)
    - Positive speed delta = lap_b is FASTER (higher speed = better)
    
    Returns deltas sorted by absolute time loss (biggest first).
    """
    deltas = []

    # Match corners by segment_id
    corners_b_map = {ca.segment.segment_id: ca for ca in corners_b}
    for ca_a in corners_a:
        sid = ca_a.segment.segment_id
        ca_b = corners_b_map.get(sid)
        if ca_b is None:
            logger.warning(f"Corner segment {sid} from reference lap not found in comparison lap")
            continue

        # Time delta: positive = lap_b slower
        delta = LapComparisonDelta(
            segment_id=sid,
            segment_type="corner",
            time_delta_s=ca_b.time_in_corner_s - ca_a.time_in_corner_s,
            apex_speed_delta_kmh=ca_b.apex.min_speed_kmh - ca_a.apex.min_speed_kmh,
            exit_speed_delta_kmh=ca_b.exit.exit_speed_kmh - ca_a.exit.exit_speed_kmh,
        )

        # Brake point delta: positive = lap_b braked later (smaller distance to corner entry)
        # Note: brake_point_dist_m is cumulative distance along track
        # Later braking = higher dist_m value (closer to corner geographically)
        if ca_a.braking.brake_point_dist_m > 0 and ca_b.braking.brake_point_dist_m > 0:
            delta.brake_delta_m = ca_b.braking.brake_point_dist_m - ca_a.braking.brake_point_dist_m

        deltas.append(delta)

    # Match straights by segment_id
    straights_b_map = {sa.segment.segment_id: sa for sa in straights_b}
    for sa_a in straights_a:
        sid = sa_a.segment.segment_id
        sa_b = straights_b_map.get(sid)
        if sa_b is None:
            logger.warning(f"Straight segment {sid} from reference lap not found in comparison lap")
            continue

        deltas.append(LapComparisonDelta(
            segment_id=sid,
            segment_type="straight",
            time_delta_s=sa_b.time_on_straight_s - sa_a.time_on_straight_s,
            top_speed_delta_kmh=sa_b.top_speed_kmh - sa_a.top_speed_kmh,
        ))

    # Sort by absolute time loss (biggest losses first)
    deltas.sort(key=lambda d: abs(d.time_delta_s), reverse=True)

    logger.info(
        f"Lap comparison: {len(deltas)} segments matched, "
        f"total delta: {sum(d.time_delta_s for d in deltas):.3f}s"
    )

    return deltas
