"""
Brake analyzer: front/rear bias, left/right balance, modulation quality.
"""

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.signal import medfilt

from brain.config import BRAKE_ON_THRESHOLD_PA, MEDIAN_FILTER_WINDOW

logger = logging.getLogger(__name__)


@dataclass
class BrakeAnalysis:
    """Brake system analysis for a lap."""
    lap_number: int
    front_rear_bias_pct: float = 50.0    # % of total pressure on front axle
    left_right_imbalance_pct: float = 0.0
    avg_peak_pressure_pa: float = 0.0
    brake_zone_count: int = 0
    avg_modulation_score: float = 0.0     # 0-1, higher = smoother
    total_brake_time_s: float = 0.0
    total_brake_time_pct: float = 0.0


def analyze_brakes(
    lap_df: pd.DataFrame,
    lap_number: int,
) -> BrakeAnalysis:
    """Analyze braking performance for a lap."""
    result = BrakeAnalysis(lap_number=lap_number)

    # Per-wheel brake pressures
    fl = _get_brake_col(lap_df, "cba_actual_pressure_fl_pa")
    fr = _get_brake_col(lap_df, "cba_actual_pressure_fr_pa")
    rl = _get_brake_col(lap_df, "cba_actual_pressure_rl_pa")
    rr = _get_brake_col(lap_df, "cba_actual_pressure_rr_pa")

    total = fl + fr + rl + rr

    if total.max() < BRAKE_ON_THRESHOLD_PA:
        # No significant braking detected, try front/rear combined fallback
        if "front_brake_pressure" in lap_df.columns:
            front = lap_df["front_brake_pressure"].fillna(0).values
            rear = lap_df.get("rear_brake_pressure", pd.Series(0, index=lap_df.index)).fillna(0).values
            total_fallback = front + rear
            if total_fallback.max() > 0:
                braking_mask = total_fallback > total_fallback.max() * 0.05
                combined_fallback = front[braking_mask] + rear[braking_mask]
                valid_samples = combined_fallback > 0
                if valid_samples.any():
                    bias_per_sample = front[braking_mask][valid_samples] / combined_fallback[valid_samples] * 100
                    result.front_rear_bias_pct = float(bias_per_sample.mean())
        return result

    # Front/rear bias during braking - calculate per-sample then average
    braking_mask = total > BRAKE_ON_THRESHOLD_PA
    if not braking_mask.any():
        return result

    front_total = (fl + fr)[braking_mask]
    rear_total = (rl + rr)[braking_mask]
    combined = front_total + rear_total

    valid_samples = combined > 0
    if valid_samples.any():
        bias_per_sample = front_total[valid_samples] / combined[valid_samples] * 100
        result.front_rear_bias_pct = float(bias_per_sample.mean())

    # Left/right imbalance - calculate per-sample then average
    left_total = (fl + rl)[braking_mask]
    right_total = (fr + rr)[braking_mask]
    lr_combined = left_total + right_total
    
    lr_valid_samples = lr_combined > 0
    if lr_valid_samples.any():
        lr_bias_per_sample = left_total[lr_valid_samples] / lr_combined[lr_valid_samples] * 100
        result.left_right_imbalance_pct = float(abs(lr_bias_per_sample.mean() - 50.0))

    # Brake zone detection and peak pressures
    t = lap_df["t"].values
    dt = np.median(np.diff(t))
    zones = _detect_brake_zones(total, dt)
    result.brake_zone_count = len(zones)

    if zones:
        # Note: zones now use exclusive end index
        peaks = [float(total[s:e].max()) for s, e in zones]
        result.avg_peak_pressure_pa = float(np.mean(peaks))

        # Modulation score: smoothness based on jerk (rate of change of acceleration)
        scores = []
        for s, e in zones:
            zone_duration = e - s
            if zone_duration > 5:
                segment = total[s:e]
                # Calculate jerk: derivative of the derivative
                dp = np.diff(segment)
                jerk = np.abs(np.diff(dp))
                
                if len(jerk) > 0 and segment.max() > 0:
                    # Normalize jerk by peak pressure to make score dimensionless
                    # Lower jerk = smoother braking = higher score
                    normalized_jerk = jerk.mean() / segment.max()
                    smoothness = 1.0 / (1.0 + normalized_jerk * 100)  # Scale factor tuned for typical brake profiles
                    scores.append(float(smoothness))
        
        if scores:
            result.avg_modulation_score = float(np.mean(scores))

    # Total brake time
    result.total_brake_time_s = float(braking_mask.sum() * dt)
    lap_duration = t[-1] - t[0]
    if lap_duration > 0:
        result.total_brake_time_pct = float(result.total_brake_time_s / lap_duration * 100)

    logger.info(
        f"  Brakes Lap {lap_number}: bias={result.front_rear_bias_pct:.1f}% front, "
        f"{result.brake_zone_count} zones, "
        f"modulation={result.avg_modulation_score:.2f}"
    )

    return result


def _get_brake_col(df: pd.DataFrame, col: str) -> np.ndarray:
    """Get brake pressure column with fallback."""
    if col in df.columns:
        arr = df[col].fillna(0).values
        return medfilt(arr, MEDIAN_FILTER_WINDOW)
    return np.zeros(len(df))


def _detect_brake_zones(total_pressure: np.ndarray, dt: float) -> list[tuple[int, int]]:
    """Detect individual brake application zones.
    
    Returns list of (start, end) tuples where end is EXCLUSIVE (Python slice convention).
    """
    active = total_pressure > BRAKE_ON_THRESHOLD_PA
    zones = []

    diff = np.diff(active.astype(int))
    starts = np.where(diff == 1)[0] + 1
    ends = np.where(diff == -1)[0] + 1

    if active[0]:
        starts = np.concatenate([[0], starts])
    if active[-1]:
        # End is exclusive, so use len(active) not len(active) - 1
        ends = np.concatenate([ends, [len(active)]])

    # Minimum brake duration: 60ms, calculated from sample rate
    min_samples = max(3, int(0.06 / dt))
    
    for s, e in zip(starts, ends):
        if e - s >= min_samples:
            zones.append((s, e))

    return zones
