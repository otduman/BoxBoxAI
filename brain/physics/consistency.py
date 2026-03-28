"""
Consistency analyzer: lap-to-lap variation scoring and segment-level comparison.
"""

import logging
from dataclasses import dataclass, field

import numpy as np

from brain.physics.corner_analyzer import CornerAnalysis
from brain.physics.straight_analyzer import StraightAnalysis

logger = logging.getLogger(__name__)


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
    """Per-segment delta between two laps."""
    segment_id: str
    segment_type: str
    time_delta_s: float = 0.0       # Negative = faster in lap_b
    brake_delta_m: float = 0.0      # Positive = braked later in lap_b
    apex_speed_delta_kmh: float = 0.0
    exit_speed_delta_kmh: float = 0.0
    top_speed_delta_kmh: float = 0.0


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

    if len(corner_analyses) < 2:
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
        if len(lap_time_map) < 2:
            continue

        times = list(lap_time_map.values())
        laps = list(lap_time_map.keys())
        mean_t = np.mean(times)
        std_t = np.std(times)

        # Consistency score: 100 = zero variation
        # Scale: std < 0.05s = 100, std > 1.0s = 0
        score = max(0, min(100, 100 * (1 - std_t / 1.0)))

        best_idx = int(np.argmin(times))
        worst_idx = int(np.argmax(times))

        sc = SegmentConsistency(
            segment_id=sid,
            segment_type=stype,
            lap_times=times,
            mean_time_s=float(mean_t),
            std_time_s=float(std_t),
            consistency_score=float(score),
            best_lap=laps[best_idx],
            worst_lap=laps[worst_idx],
            time_spread_s=float(max(times) - min(times)),
        )
        result.segment_scores.append(sc)

    if result.segment_scores:
        scores = [s.consistency_score for s in result.segment_scores]
        result.overall_consistency_score = float(np.mean(scores))

        weakest = min(result.segment_scores, key=lambda s: s.consistency_score)
        strongest = max(result.segment_scores, key=lambda s: s.consistency_score)
        result.weakest_segment_id = weakest.segment_id
        result.strongest_segment_id = strongest.segment_id

    return result


def compare_laps(
    corners_a: list[CornerAnalysis],
    corners_b: list[CornerAnalysis],
    straights_a: list[StraightAnalysis],
    straights_b: list[StraightAnalysis],
) -> list[LapComparisonDelta]:
    """Compare two laps segment-by-segment (a = reference, b = comparison).

    Negative deltas mean lap_b was faster/better.
    """
    deltas = []

    # Match corners by segment_id
    corners_b_map = {ca.segment.segment_id: ca for ca in corners_b}
    for ca_a in corners_a:
        sid = ca_a.segment.segment_id
        ca_b = corners_b_map.get(sid)
        if ca_b is None:
            continue

        delta = LapComparisonDelta(
            segment_id=sid,
            segment_type="corner",
            time_delta_s=ca_b.time_in_corner_s - ca_a.time_in_corner_s,
            apex_speed_delta_kmh=ca_b.apex.min_speed_kmh - ca_a.apex.min_speed_kmh,
            exit_speed_delta_kmh=ca_b.exit.exit_speed_kmh - ca_a.exit.exit_speed_kmh,
        )

        # Brake point delta: positive = braked later (closer to corner)
        if ca_a.braking.brake_point_dist_m > 0 and ca_b.braking.brake_point_dist_m > 0:
            delta.brake_delta_m = ca_b.braking.brake_point_dist_m - ca_a.braking.brake_point_dist_m

        deltas.append(delta)

    # Match straights by segment_id
    straights_b_map = {sa.segment.segment_id: sa for sa in straights_b}
    for sa_a in straights_a:
        sid = sa_a.segment.segment_id
        sa_b = straights_b_map.get(sid)
        if sa_b is None:
            continue

        deltas.append(LapComparisonDelta(
            segment_id=sid,
            segment_type="straight",
            time_delta_s=sa_b.time_on_straight_s - sa_a.time_on_straight_s,
            top_speed_delta_kmh=sa_b.top_speed_kmh - sa_a.top_speed_kmh,
        ))

    return deltas
