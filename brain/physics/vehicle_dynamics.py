"""
Vehicle dynamics analyzer: oversteer/understeer detection, lockup/wheelspin,
g-g diagram metrics, and friction circle utilization.
"""

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from brain.config import (
    G_ACCEL,
    get_active_profile,
)

logger = logging.getLogger(__name__)


@dataclass
class DynamicsEvent:
    """A notable vehicle dynamics event."""
    event_type: str       # "oversteer", "understeer", "lockup", "wheelspin"
    start_time: float
    end_time: float
    duration_s: float
    peak_value: float
    track_dist_m: float
    severity: str         # "mild", "moderate", "severe"


@dataclass
class GGDiagramMetrics:
    """Summary of the g-g diagram (friction circle utilization)."""
    max_lateral_g: float = 0.0
    max_braking_g: float = 0.0
    max_accel_g: float = 0.0
    avg_combined_g: float = 0.0
    friction_circle_utilization_pct: float = 0.0
    peak_combined_g: float = 0.0


@dataclass
class VehicleDynamicsAnalysis:
    """Full dynamics analysis for a lap."""
    lap_number: int
    lap_duration_s: float = 0.0
    gg_metrics: GGDiagramMetrics = field(default_factory=GGDiagramMetrics)
    events: list[DynamicsEvent] = field(default_factory=list)
    oversteer_count: int = 0
    understeer_count: int = 0
    lockup_count: int = 0
    wheelspin_count: int = 0
    balance_tendency: str = "neutral"


def analyze_vehicle_dynamics(
    lap_df: pd.DataFrame,
    lap_number: int,
) -> VehicleDynamicsAnalysis:
    """Analyze vehicle dynamics for a full lap."""
    result = VehicleDynamicsAnalysis(lap_number=lap_number)

    # Lap duration from timestamps
    if "t" in lap_df.columns and len(lap_df) > 1:
        result.lap_duration_s = float(lap_df["t"].iloc[-1] - lap_df["t"].iloc[0])

    result.gg_metrics = _compute_gg_metrics(lap_df)

    os_events = _detect_oversteer(lap_df)
    us_events = _detect_understeer(lap_df)
    lockup_events = _detect_lockup(lap_df)
    wheelspin_events = _detect_wheelspin(lap_df)

    result.events = os_events + us_events + lockup_events + wheelspin_events
    result.oversteer_count = len(os_events)
    result.understeer_count = len(us_events)
    result.lockup_count = len(lockup_events)
    result.wheelspin_count = len(wheelspin_events)

    if result.oversteer_count > result.understeer_count + 2:
        result.balance_tendency = "oversteer"
    elif result.understeer_count > result.oversteer_count + 2:
        result.balance_tendency = "understeer"
    else:
        result.balance_tendency = "neutral"

    logger.info(
        f"  Dynamics Lap {lap_number}: "
        f"OS={result.oversteer_count} US={result.understeer_count} "
        f"lockup={result.lockup_count} spin={result.wheelspin_count} "
        f"balance={result.balance_tendency}"
    )

    return result


def _compute_gg_metrics(df: pd.DataFrame) -> GGDiagramMetrics:
    """Compute g-g diagram summary metrics."""
    m = GGDiagramMetrics()

    ax = df.get("ax_mps2", pd.Series(dtype=float)).fillna(0).values / G_ACCEL
    ay = df.get("ay_mps2", pd.Series(dtype=float)).fillna(0).values / G_ACCEL

    if len(ax) == 0:
        return m

    m.max_braking_g = float(np.abs(ax[ax < 0]).max()) if (ax < 0).any() else 0.0
    m.max_accel_g = float(ax[ax > 0].max()) if (ax > 0).any() else 0.0
    m.max_lateral_g = float(np.abs(ay).max())

    combined = np.sqrt(ax**2 + ay**2)
    m.peak_combined_g = float(combined.max())
    m.avg_combined_g = float(combined.mean())

    max_grip = m.peak_combined_g
    if max_grip > 0:
        utilization = combined / max_grip
        m.friction_circle_utilization_pct = float(utilization.mean() * 100)

    return m


def _detect_events_from_signal(
    df: pd.DataFrame,
    signal: np.ndarray,
    threshold: float,
    event_type: str,
    compare: str = "above",
) -> list[DynamicsEvent]:
    """Find contiguous regions where signal crosses threshold."""
    events = []
    t = df["t"].values
    dist = df["track_dist_m"].values if "track_dist_m" in df.columns else np.zeros(len(df))

    if compare == "above":
        active = signal > threshold
    else:
        active = signal < threshold

    if not active.any():
        return events

    diff = np.diff(active.astype(int))
    starts = np.where(diff == 1)[0] + 1
    ends = np.where(diff == -1)[0] + 1

    if active[0]:
        starts = np.concatenate([[0], starts])
    if active[-1]:
        ends = np.concatenate([ends, [len(active)]])

    # Merge intervals that are within a short gap (oscillation of the same event)
    MERGE_GAP_S = 0.3
    merged_starts = []
    merged_ends = []
    for s, e in zip(starts, ends):
        if merged_starts and t[s] - t[min(merged_ends[-1], len(t) - 1)] < MERGE_GAP_S:
            # Extend the previous event
            merged_ends[-1] = e
        else:
            merged_starts.append(s)
            merged_ends.append(e)

    for s, e in zip(merged_starts, merged_ends):
        duration = t[min(e, len(t) - 1)] - t[s]
        if duration < get_active_profile().min_event_duration_s:
            continue

        peak = float(np.abs(signal[s:e]).max())
        track_d = float(dist[s])

        severity = "mild"
        abs_thresh = abs(threshold)
        if abs_thresh > 0:
            ratio = peak / abs_thresh
            if ratio > 2.0:
                severity = "severe"
            elif ratio > 1.5:
                severity = "moderate"

        events.append(DynamicsEvent(
            event_type=event_type,
            start_time=float(t[s]),
            end_time=float(t[min(e, len(t) - 1)]),
            duration_s=duration,
            peak_value=peak,
            track_dist_m=track_d,
            severity=severity,
        ))

    return events


def _detect_oversteer(df: pd.DataFrame) -> list[DynamicsEvent]:
    if "beta_rad" not in df.columns:
        return []
    profile = get_active_profile()
    beta = np.abs(df["beta_rad"].fillna(0).values)
    return _detect_events_from_signal(
        df, beta, profile.oversteer_beta_threshold_rad, "oversteer", "above"
    )


def _detect_understeer(df: pd.DataFrame) -> list[DynamicsEvent]:
    cols = ["alpha_fl_rad", "alpha_fr_rad"]
    available = [c for c in cols if c in df.columns]
    if not available:
        return []
    profile = get_active_profile()
    front_alpha = np.abs(df[available].fillna(0).values).max(axis=1)
    return _detect_events_from_signal(
        df, front_alpha, profile.slip_angle_warning_rad, "understeer", "above"
    )


def _detect_lockup(df: pd.DataFrame) -> list[DynamicsEvent]:
    cols = ["lambda_fl_perc", "lambda_fr_perc", "lambda_rl_perc", "lambda_rr_perc"]
    available = [c for c in cols if c in df.columns]
    if not available:
        return []
    profile = get_active_profile()
    min_lambda = df[available].fillna(0).values.min(axis=1)
    return _detect_events_from_signal(
        df, min_lambda, profile.lockup_lambda_threshold, "lockup", "below"
    )


def _detect_wheelspin(df: pd.DataFrame) -> list[DynamicsEvent]:
    cols = ["lambda_rl_perc", "lambda_rr_perc"]
    available = [c for c in cols if c in df.columns]
    if not available:
        return []
    profile = get_active_profile()
    max_rear = df[available].fillna(0).values.max(axis=1)
    return _detect_events_from_signal(
        df, max_rear, profile.wheelspin_lambda_threshold, "wheelspin", "above"
    )
