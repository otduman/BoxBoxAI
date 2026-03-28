"""
Straight-line analyzer: top speed, acceleration performance, gear shifts.
"""

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from brain.config import THROTTLE_FULL, MPS_TO_KMH, G_ACCEL
from brain.track.segmentation import TrackSegment

logger = logging.getLogger(__name__)


@dataclass
class StraightAnalysis:
    """Analysis of a single straight segment."""
    segment: TrackSegment
    lap_number: int
    top_speed_kmh: float = 0.0
    entry_speed_kmh: float = 0.0
    exit_speed_kmh: float = 0.0
    max_acceleration_g: float = 0.0
    time_at_full_throttle_pct: float = 0.0
    time_on_straight_s: float = 0.0
    gear_shifts: int = 0
    max_rpm: float = 0.0


def analyze_straight(
    lap_df: pd.DataFrame,
    segment: TrackSegment,
    lap_number: int,
) -> StraightAnalysis:
    """Analyze performance on a single straight."""
    result = StraightAnalysis(segment=segment, lap_number=lap_number)

    if "track_dist_m" not in lap_df.columns:
        return result

    dist = lap_df["track_dist_m"].values
    mask = (dist >= segment.start_dist_m) & (dist <= segment.end_dist_m)
    straight_df = lap_df[mask]

    if len(straight_df) < 5:
        return result

    t = straight_df["t"].values
    result.time_on_straight_s = float(t[-1] - t[0])

    if "v_mps" in straight_df.columns:
        speed = straight_df["v_mps"].values
        result.top_speed_kmh = float(np.nanmax(speed) * MPS_TO_KMH)
        result.entry_speed_kmh = float(speed[0] * MPS_TO_KMH)
        result.exit_speed_kmh = float(speed[-1] * MPS_TO_KMH)

    if "ax_mps2" in straight_df.columns:
        ax = straight_df["ax_mps2"].values
        result.max_acceleration_g = float(np.nanmax(ax) / G_ACCEL)

    if "gas" in straight_df.columns:
        gas = straight_df["gas"].values
        full_throttle = gas > THROTTLE_FULL
        result.time_at_full_throttle_pct = float(full_throttle.sum() / len(gas) * 100)

    if "gear" in straight_df.columns:
        gear = straight_df["gear"].dropna().values
        if len(gear) > 1:
            result.gear_shifts = int(np.sum(np.abs(np.diff(gear.astype(int))) > 0))

    if "rpm" in straight_df.columns:
        result.max_rpm = float(straight_df["rpm"].max())

    return result


def analyze_all_straights(
    lap_df: pd.DataFrame,
    segments: list[TrackSegment],
    lap_number: int,
) -> list[StraightAnalysis]:
    """Analyze all straights for a single lap."""
    straights = [s for s in segments if s.segment_type == "straight"]
    return [analyze_straight(lap_df, seg, lap_number) for seg in straights]
