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

# Minimum samples for valid straight analysis (0.5s at 50Hz)
MIN_STRAIGHT_SAMPLES = 25


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
    # Timestamp when this straight was traversed (relative to session start, seconds)
    start_time_s: float = 0.0


def analyze_straight(
    lap_df: pd.DataFrame,
    segment: TrackSegment,
    lap_number: int,
) -> StraightAnalysis:
    """Analyze performance on a single straight.
    
    Metrics:
    - top_speed_kmh: Maximum speed achieved
    - entry/exit_speed_kmh: Speed at segment boundaries
    - max_acceleration_g: Peak forward acceleration (positive only)
    - time_at_full_throttle_pct: Time spent at >95% throttle
    - gear_shifts: Number of upshifts (acceleration events)
    """
    result = StraightAnalysis(segment=segment, lap_number=lap_number)

    if "track_dist_m" not in lap_df.columns:
        return result

    dist = lap_df["track_dist_m"].values
    mask = (dist >= segment.start_dist_m) & (dist <= segment.end_dist_m)
    straight_df = lap_df[mask]

    if len(straight_df) < MIN_STRAIGHT_SAMPLES:
        logger.debug(
            f"Straight {segment.segment_id} lap {lap_number} too short "
            f"({len(straight_df)} samples, need {MIN_STRAIGHT_SAMPLES}), skipping"
        )
        return result

    t = straight_df["t"].values
    result.time_on_straight_s = float(t[-1] - t[0])
    result.start_time_s = float(t[0])

    # Speed analysis with NaN validation
    if "v_mps" in straight_df.columns:
        speed = straight_df["v_mps"].values
        max_speed = np.nanmax(speed)
        if not np.isnan(max_speed):
            result.top_speed_kmh = float(max_speed * MPS_TO_KMH)
        
        if not np.isnan(speed[0]):
            result.entry_speed_kmh = float(speed[0] * MPS_TO_KMH)
        
        if not np.isnan(speed[-1]):
            result.exit_speed_kmh = float(speed[-1] * MPS_TO_KMH)

    # Acceleration: only consider positive (forward) acceleration
    if "ax_mps2" in straight_df.columns:
        ax = straight_df["ax_mps2"].values
        positive_ax = ax[ax > 0]
        if len(positive_ax) > 0:
            result.max_acceleration_g = float(np.max(positive_ax) / G_ACCEL)

    # Full throttle percentage (>95% throttle)
    if "gas" in straight_df.columns:
        gas = straight_df["gas"].values
        full_throttle = gas > THROTTLE_FULL
        result.time_at_full_throttle_pct = float(full_throttle.sum() / len(gas) * 100)

    # Gear shifts: count upshifts only (forward fill missing data first)
    if "gear" in straight_df.columns:
        gear_series = straight_df["gear"].ffill()  # Forward fill gaps
        gear = gear_series.dropna().values
        if len(gear) > 1:
            gear_changes = np.diff(gear.astype(int))
            # Count only upshifts (positive changes)
            result.gear_shifts = int(np.sum(gear_changes > 0))

    # Max RPM with NaN check
    if "rpm" in straight_df.columns:
        max_rpm = straight_df["rpm"].max()
        if not pd.isna(max_rpm):
            result.max_rpm = float(max_rpm)

    logger.debug(
        f"Straight {segment.segment_id} lap {lap_number}: "
        f"top {result.top_speed_kmh:.1f} km/h, "
        f"{result.gear_shifts} upshifts, "
        f"{result.time_at_full_throttle_pct:.1f}% full throttle"
    )

    return result


def analyze_all_straights(
    lap_df: pd.DataFrame,
    segments: list[TrackSegment],
    lap_number: int,
) -> list[StraightAnalysis]:
    """Analyze all straights for a single lap."""
    straights = [s for s in segments if s.segment_type == "straight"]
    return [analyze_straight(lap_df, seg, lap_number) for seg in straights]
