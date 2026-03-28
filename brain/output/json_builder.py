"""
JSON builder: assembles all analysis results into session_summary.json.

Produces a structured JSON that serves two purposes:
1. Direct consumption by the LLM for coaching feedback
2. Human-readable session report
"""

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from brain.track.segmentation import TrackSegment
from brain.physics.lap_splitter import Lap
from brain.physics.corner_analyzer import CornerAnalysis
from brain.physics.straight_analyzer import StraightAnalysis
from brain.physics.vehicle_dynamics import VehicleDynamicsAnalysis
from brain.physics.tire_analyzer import TireAnalysis
from brain.physics.brake_analyzer import BrakeAnalysis
from brain.physics.consistency import ConsistencyAnalysis, LapComparisonDelta

logger = logging.getLogger(__name__)

# raw data is also saved as CSV alongside the JSON
class _NumpyEncoder(json.JSONEncoder):
    """JSON encoder that handles numpy types."""
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        return super().default(obj)


def build_session_summary(
    laps: list[Lap],
    segments: list[TrackSegment],
    corner_analyses: dict[int, list[CornerAnalysis]],
    straight_analyses: dict[int, list[StraightAnalysis]],
    dynamics_analyses: dict[int, VehicleDynamicsAnalysis],
    tire_analyses: dict[int, TireAnalysis],
    brake_analyses: dict[int, BrakeAnalysis],
    consistency: ConsistencyAnalysis | None,
    comparison_deltas: list[LapComparisonDelta] | None,
    track_name: str = "unknown",
    mcap_file: str = "",
) -> dict:
    """Assemble the complete session summary."""

    summary = {
        "session": {
            "track": track_name,
            "source_file": mcap_file,
            "total_laps": len(laps),
            "laps": [_serialize_lap(lap) for lap in laps],
        },
        "track_layout": {
            "total_corners": sum(1 for s in segments if s.segment_type == "corner"),
            "total_straights": sum(1 for s in segments if s.segment_type == "straight"),
            "segments": [_serialize_segment(s) for s in segments],
        },
        "lap_analyses": {},
        "coaching_highlights": [],
    }

    # Per-lap analyses
    for lap in laps:
        ln = lap.lap_number
        lap_data = {"lap_number": ln, "duration_s": lap.duration_s}

        # Corners
        if ln in corner_analyses:
            lap_data["corners"] = [
                _serialize_corner(ca) for ca in corner_analyses[ln]
            ]

        # Straights
        if ln in straight_analyses:
            lap_data["straights"] = [
                _serialize_straight(sa) for sa in straight_analyses[ln]
            ]

        # Dynamics
        if ln in dynamics_analyses:
            lap_data["dynamics"] = _serialize_dynamics(dynamics_analyses[ln])

        # Tires
        if ln in tire_analyses:
            lap_data["tires"] = _serialize_tires(tire_analyses[ln])

        # Brakes
        if ln in brake_analyses:
            lap_data["brakes"] = _serialize_brakes(brake_analyses[ln])

        summary["lap_analyses"][str(ln)] = lap_data

    # Consistency
    if consistency and consistency.segment_scores:
        summary["consistency"] = {
            "overall_score": round(consistency.overall_consistency_score, 1),
            "weakest_segment": consistency.weakest_segment_id,
            "strongest_segment": consistency.strongest_segment_id,
            "segments": [
                {
                    "segment_id": sc.segment_id,
                    "mean_time_s": round(sc.mean_time_s, 3),
                    "std_time_s": round(sc.std_time_s, 3),
                    "score": round(sc.consistency_score, 1),
                    "spread_s": round(sc.time_spread_s, 3),
                }
                for sc in consistency.segment_scores
            ],
        }

    # Ghost comparison
    if comparison_deltas:
        summary["lap_comparison"] = [
            {
                "segment_id": d.segment_id,
                "segment_type": d.segment_type,
                "time_delta_s": round(d.time_delta_s, 3),
                "brake_delta_m": round(d.brake_delta_m, 1),
                "apex_speed_delta_kmh": round(d.apex_speed_delta_kmh, 1),
                "exit_speed_delta_kmh": round(d.exit_speed_delta_kmh, 1),
                "top_speed_delta_kmh": round(d.top_speed_delta_kmh, 1),
            }
            for d in comparison_deltas
        ]

    # Generate coaching highlights
    summary["coaching_highlights"] = _generate_highlights(
        laps, corner_analyses, straight_analyses, dynamics_analyses,
        tire_analyses, brake_analyses, comparison_deltas,
    )

    return summary


def save_session_summary(summary: dict, output_path: str | Path, master_df: pd.DataFrame = None) -> None:
    """Write session summary to JSON file and raw data to CSV."""
    output_path = Path(output_path)
    with open(output_path, "w") as f:
        json.dump(summary, f, indent=2, cls=_NumpyEncoder)
    logger.info(f"Session summary saved to {output_path}")

    if master_df is not None:
        csv_path = output_path.with_suffix(".csv")
        master_df.to_csv(csv_path, index=False)
        logger.info(f"Raw telemetry saved to {csv_path}")


def _serialize_lap(lap: Lap) -> dict:
    return {
        "lap_number": lap.lap_number,
        "duration_s": round(lap.duration_s, 3),
    }


def _serialize_segment(seg: TrackSegment) -> dict:
    return {
        "id": seg.segment_id,
        "type": seg.segment_type,
        "direction": seg.direction,
        "start_m": round(seg.start_dist_m, 1),
        "end_m": round(seg.end_dist_m, 1),
        "length_m": round(seg.length_m, 1),
    }


def _serialize_corner(ca: CornerAnalysis) -> dict:
    return {
        "segment_id": ca.segment.segment_id,
        "direction": ca.segment.direction,
        "entry_speed_kmh": round(ca.entry_speed_kmh, 1),
        "time_in_corner_s": round(ca.time_in_corner_s, 3),
        "braking": {
            "brake_point_m": round(ca.braking.brake_point_dist_m, 1),
            "peak_pressure_pa": round(ca.braking.peak_brake_pressure_pa, 0),
            "deceleration_g": round(ca.braking.deceleration_g, 2),
            "duration_s": round(ca.braking.duration_s, 3),
        },
        "trail_brake": {
            "active": ca.trail_brake.brake_while_turning,
            "quality_r2": round(ca.trail_brake.quality_r_squared, 2),
            "duration_s": round(ca.trail_brake.duration_s, 3),
        },
        "apex": {
            "speed_kmh": round(ca.apex.min_speed_kmh, 1),
            "lateral_g": round(ca.apex.max_lateral_g, 2),
            "lateral_offset_m": round(ca.apex.lateral_offset_m, 2),
            "sideslip_rad": round(ca.apex.peak_sideslip_rad, 4),
            "distance_m": round(ca.apex.apex_dist_m, 1),
        },
        "exit": {
            "throttle_point_m": round(ca.exit.throttle_point_dist_m, 1),
            "exit_speed_kmh": round(ca.exit.exit_speed_kmh, 1),
            "coast_time_s": round(ca.exit.coast_time_s, 3),
            "rear_wheelspin": ca.exit.rear_wheelspin,
        },
    }


def _serialize_straight(sa: StraightAnalysis) -> dict:
    return {
        "segment_id": sa.segment.segment_id,
        "top_speed_kmh": round(sa.top_speed_kmh, 1),
        "entry_speed_kmh": round(sa.entry_speed_kmh, 1),
        "exit_speed_kmh": round(sa.exit_speed_kmh, 1),
        "max_accel_g": round(sa.max_acceleration_g, 2),
        "full_throttle_pct": round(sa.time_at_full_throttle_pct, 1),
        "gear_shifts": sa.gear_shifts,
        "time_s": round(sa.time_on_straight_s, 3),
    }


def _serialize_dynamics(da: VehicleDynamicsAnalysis) -> dict:
    return {
        "gg_diagram": {
            "max_lateral_g": round(da.gg_metrics.max_lateral_g, 2),
            "max_braking_g": round(da.gg_metrics.max_braking_g, 2),
            "max_accel_g": round(da.gg_metrics.max_accel_g, 2),
            "friction_utilization_pct": round(da.gg_metrics.friction_circle_utilization_pct, 1),
        },
        "balance": da.balance_tendency,
        "events": {
            "oversteer": da.oversteer_count,
            "understeer": da.understeer_count,
            "lockup": da.lockup_count,
            "wheelspin": da.wheelspin_count,
        },
    }


def _serialize_tires(ta: TireAnalysis) -> dict:
    wheels = {}
    for pos, wm in ta.wheels.items():
        wheels[pos] = {
            "avg_temp_c": round(wm.avg_surface_temp_c, 1),
            "gradient_c": round(wm.temp_gradient_c, 1),
            "pressure_bar": round(wm.avg_pressure_bar, 2),
        }
    return {
        "wheels": wheels,
        "front_rear_delta_c": round(ta.front_rear_temp_delta_c, 1),
        "left_right_delta_c": round(ta.left_right_temp_delta_c, 1),
        "warnings": ta.warnings,
    }


def _serialize_brakes(ba: BrakeAnalysis) -> dict:
    return {
        "front_bias_pct": round(ba.front_rear_bias_pct, 1),
        "lr_imbalance_pct": round(ba.left_right_imbalance_pct, 1),
        "zone_count": ba.brake_zone_count,
        "modulation_score": round(ba.avg_modulation_score, 2),
        "brake_time_pct": round(ba.total_brake_time_pct, 1),
    }


def _generate_highlights(
    laps, corner_analyses, straight_analyses, dynamics_analyses,
    tire_analyses, brake_analyses, comparison_deltas,
) -> list[dict]:
    """Generate rule-based coaching highlights from the analysis data."""
    highlights = []

    # Find best/worst laps
    if len(laps) > 1:
        best = min(laps, key=lambda l: l.duration_s)
        worst = max(laps, key=lambda l: l.duration_s)
        delta = worst.duration_s - best.duration_s
        highlights.append({
            "type": "lap_time",
            "priority": "high",
            "message": (
                f"Best lap: {best.duration_s:.2f}s (Lap {best.lap_number}). "
                f"Worst: {worst.duration_s:.2f}s. Gap: {delta:.2f}s."
            ),
        })

    # Corners with coast time (biggest easy gains)
    for ln, analyses in corner_analyses.items():
        for ca in analyses:
            if ca.exit.coast_time_s > 0.2:
                highlights.append({
                    "type": "coast_time",
                    "priority": "high",
                    "segment": ca.segment.segment_id,
                    "lap": ln,
                    "message": (
                        f"{ca.segment.segment_id} (Lap {ln}): "
                        f"{ca.exit.coast_time_s:.2f}s coast time between brake release and throttle. "
                        f"This is dead time losing speed."
                    ),
                })

    # Trail-braking quality
    for ln, analyses in corner_analyses.items():
        for ca in analyses:
            if not ca.trail_brake.brake_while_turning and ca.braking.duration_s > 0.1:
                highlights.append({
                    "type": "trail_brake",
                    "priority": "medium",
                    "segment": ca.segment.segment_id,
                    "lap": ln,
                    "message": (
                        f"{ca.segment.segment_id} (Lap {ln}): "
                        f"No trail-braking detected. Releasing brake fully before turn-in."
                    ),
                })

    # Dynamics warnings
    for ln, da in dynamics_analyses.items():
        if da.lockup_count > 0:
            highlights.append({
                "type": "lockup",
                "priority": "high",
                "lap": ln,
                "message": f"Lap {ln}: {da.lockup_count} wheel lockup event(s) detected.",
            })
        if da.wheelspin_count > 2:
            highlights.append({
                "type": "wheelspin",
                "priority": "medium",
                "lap": ln,
                "message": f"Lap {ln}: {da.wheelspin_count} rear wheelspin events on corner exit.",
            })

    # Tire warnings
    for ln, ta in tire_analyses.items():
        for warning in ta.warnings:
            highlights.append({
                "type": "tire_temp",
                "priority": "medium",
                "lap": ln,
                "message": f"Lap {ln}: {warning}",
            })

    # Comparison deltas (if available)
    if comparison_deltas:
        biggest_loss = max(comparison_deltas, key=lambda d: d.time_delta_s)
        if biggest_loss.time_delta_s > 0.1:
            highlights.append({
                "type": "comparison",
                "priority": "high",
                "segment": biggest_loss.segment_id,
                "message": (
                    f"Biggest time loss vs reference: {biggest_loss.segment_id} "
                    f"(+{biggest_loss.time_delta_s:.2f}s). "
                    f"Brake {biggest_loss.brake_delta_m:+.0f}m, "
                    f"apex speed {biggest_loss.apex_speed_delta_kmh:+.1f} km/h."
                ),
            })

    # Sort by priority
    priority_order = {"high": 0, "medium": 1, "low": 2}
    highlights.sort(key=lambda h: priority_order.get(h.get("priority", "low"), 2))

    return highlights
