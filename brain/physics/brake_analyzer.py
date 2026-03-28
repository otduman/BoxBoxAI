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
        # No significant braking detected, try front/rear combined
        if "front_brake_pressure" in lap_df.columns:
            front = lap_df["front_brake_pressure"].fillna(0).values
            rear = lap_df.get("rear_brake_pressure", pd.Series(0, index=lap_df.index)).fillna(0).values
            total = front + rear
            if total.max() > 0:
                braking_mask = total > total.max() * 0.05
                front_sum = front[braking_mask].sum()
                rear_sum = rear[braking_mask].sum()
                total_sum = front_sum + rear_sum
                if total_sum > 0:
                    result.front_rear_bias_pct = float(front_sum / total_sum * 100)
        return result

    # Front/rear bias during braking
    braking_mask = total > BRAKE_ON_THRESHOLD_PA
    front_total = (fl + fr)[braking_mask]
    rear_total = (rl + rr)[braking_mask]
    combined = front_total + rear_total
    if combined.sum() > 0:
        result.front_rear_bias_pct = float(front_total.sum() / combined.sum() * 100)

    # Left/right imbalance
    left_total = (fl + rl)[braking_mask]
    right_total = (fr + rr)[braking_mask]
    lr_combined = left_total + right_total
    if lr_combined.sum() > 0:
        left_pct = left_total.sum() / lr_combined.sum() * 100
        result.left_right_imbalance_pct = float(abs(left_pct - 50.0))

    # Brake zone detection and peak pressures
    zones = _detect_brake_zones(total)
    result.brake_zone_count = len(zones)

    if zones:
        peaks = [float(total[s:e + 1].max()) for s, e in zones]
        result.avg_peak_pressure_pa = float(np.mean(peaks))

        # Modulation score: smoothness of pressure application
        scores = []
        for s, e in zones:
            if e - s > 5:
                segment = total[s:e + 1]
                # Score = 1 - normalized variance of pressure derivative
                dp = np.diff(segment)
                if dp.std() > 0:
                    normalized_jitter = dp.std() / (abs(dp).mean() + 1e-6)
                    scores.append(max(0, 1 - normalized_jitter / 5.0))
        if scores:
            result.avg_modulation_score = float(np.mean(scores))

    # Total brake time
    t = lap_df["t"].values
    dt = np.median(np.diff(t))
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


def _detect_brake_zones(total_pressure: np.ndarray) -> list[tuple[int, int]]:
    """Detect individual brake application zones."""
    active = total_pressure > BRAKE_ON_THRESHOLD_PA
    zones = []

    diff = np.diff(active.astype(int))
    starts = np.where(diff == 1)[0] + 1
    ends = np.where(diff == -1)[0] + 1

    if active[0]:
        starts = np.concatenate([[0], starts])
    if active[-1]:
        ends = np.concatenate([ends, [len(active)]])

    for s, e in zip(starts, ends):
        if e - s > 3:  # Minimum ~60ms brake application
            zones.append((s, e))

    return zones
