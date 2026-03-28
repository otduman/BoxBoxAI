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

    # Determine balance tendency using ratio (more robust than absolute count)
    total_balance_events = result.oversteer_count + result.understeer_count
    if total_balance_events >= 3:  # Need enough events to be meaningful
        oversteer_pct = result.oversteer_count / total_balance_events
        if oversteer_pct > 0.65:  # >65% of balance events are oversteer
            result.balance_tendency = "oversteer"
        elif oversteer_pct < 0.35:  # <35% oversteer (i.e., >65% understeer)
            result.balance_tendency = "understeer"
        else:
            result.balance_tendency = "neutral"
    else:
        # Not enough balance events to determine tendency
        result.balance_tendency = "neutral"

    logger.info(
        f"  Dynamics Lap {lap_number}: "
        f"OS={result.oversteer_count} US={result.understeer_count} "
        f"lockup={result.lockup_count} spin={result.wheelspin_count} "
        f"balance={result.balance_tendency}"
    )

    return result


def _compute_gg_metrics(df: pd.DataFrame) -> GGDiagramMetrics:
    """Compute g-g diagram summary metrics (simplified 2D friction circle model).
    
    Note: This assumes a 2D friction circle. In reality, longitudinal and lateral
    forces interact based on vertical load transfer, but this simplified model
    is sufficient for driver coaching.
    """
    m = GGDiagramMetrics()

    # Validate acceleration data exists
    if "ax_mps2" not in df.columns or "ay_mps2" not in df.columns:
        logger.warning("Acceleration data (ax_mps2/ay_mps2) not available for g-g analysis")
        return m

    ax = df["ax_mps2"].values / G_ACCEL
    ay = df["ay_mps2"].values / G_ACCEL

    # Check if data is valid (not all NaN)
    if np.isnan(ax).all() or np.isnan(ay).all():
        logger.warning("Acceleration data is all NaN, skipping g-g analysis")
        return m
    
    # Filter out NaN values for calculations
    valid_mask = ~(np.isnan(ax) | np.isnan(ay))
    ax_valid = ax[valid_mask]
    ay_valid = ay[valid_mask]

    if len(ax_valid) == 0:
        return m

    # Max braking: absolute value of most negative ax
    braking_ax = ax_valid[ax_valid < 0]
    m.max_braking_g = float(abs(braking_ax.min())) if len(braking_ax) > 0 else 0.0
    
    # Max acceleration: most positive ax
    accel_ax = ax_valid[ax_valid > 0]
    m.max_accel_g = float(accel_ax.max()) if len(accel_ax) > 0 else 0.0
    
    # Max lateral: absolute value of ay
    m.max_lateral_g = float(np.abs(ay_valid).max())

    # Combined g (vector magnitude)
    combined = np.sqrt(ax_valid**2 + ay_valid**2)
    m.peak_combined_g = float(combined.max())
    m.avg_combined_g = float(combined.mean())

    # Friction circle utilization: average g as percentage of peak g
    # (This measures how consistently the driver uses the available grip)
    if m.peak_combined_g > 0:
        m.friction_circle_utilization_pct = float((m.avg_combined_g / m.peak_combined_g) * 100)

    return m


def _detect_events_from_signal(
    df: pd.DataFrame,
    signal: np.ndarray,
    threshold: float,
    event_type: str,
    compare: str = "above",
) -> list[DynamicsEvent]:
    """Find contiguous regions where signal crosses threshold.
    
    Args:
        df: DataFrame with time and distance columns
        signal: Array of values to threshold
        threshold: Threshold value (can be negative for lockup)
        event_type: Type of event ("oversteer", "understeer", "lockup", "wheelspin")
        compare: "above" to detect signal > threshold, "below" for signal < threshold
    """
    events = []
    
    # Validate required columns
    if "t" not in df.columns:
        logger.warning(f"Time column 't' missing, cannot detect {event_type} events")
        return []
    
    t = df["t"].values
    dist = df["track_dist_m"].values if "track_dist_m" in df.columns else np.zeros(len(df))

    if compare == "above":
        active = signal > threshold
    else:
        active = signal < threshold

    if not active.any():
        return events

    # Find event boundaries
    diff = np.diff(active.astype(int))
    starts = np.where(diff == 1)[0] + 1
    ends = np.where(diff == -1)[0] + 1

    # Handle events at boundaries
    if active[0]:
        starts = np.concatenate([[0], starts])
    if active[-1]:
        ends = np.concatenate([ends, [len(active) - 1]])  # Use last valid index

    for s, e in zip(starts, ends):
        # e is inclusive, so it's already a valid index
        if e >= len(t):
            e = len(t) - 1
        
        duration = t[e] - t[s]
        if duration < get_active_profile().min_event_duration_s:
            continue

        # Find peak value in event window
        event_slice = signal[s:e + 1]
        peak = float(np.abs(event_slice).max()) if len(event_slice) > 0 else 0.0
        track_d = float(dist[s])

        # Severity based on how far beyond threshold
        severity = "mild"
        if abs(threshold) > 0:
            ratio = abs(peak) / abs(threshold)
            if ratio > 2.0:
                severity = "severe"
            elif ratio > 1.5:
                severity = "moderate"

        events.append(DynamicsEvent(
            event_type=event_type,
            start_time=float(t[s]),
            end_time=float(t[e]),
            duration_s=duration,
            peak_value=peak,
            track_dist_m=track_d,
            severity=severity,
        ))

    return events


def _detect_oversteer(df: pd.DataFrame) -> list[DynamicsEvent]:
    """Detect oversteer events using sideslip angle (beta).
    
    Oversteer occurs when |beta| exceeds threshold, indicating the rear
    is sliding more than the front (car rotating beyond driver input).
    """
    if "beta_rad" not in df.columns:
        return []
    profile = get_active_profile()
    beta = df["beta_rad"].fillna(0).values
    # Use absolute value for threshold comparison while keeping original values
    return _detect_events_from_signal(
        df, np.abs(beta), profile.oversteer_beta_threshold_rad, "oversteer", "above"
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
