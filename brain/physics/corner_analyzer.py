"""
Corner analyzer: 4-phase decomposition of every corner.

Phase A - Braking Zone
Phase B - Trail-Braking
Phase C - Apex
Phase D - Corner Exit

All thresholds are physics-based and work on any track/car combination.
"""

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.signal import savgol_filter, medfilt
from scipy.stats import linregress

from brain.config import (
    BRAKE_ON_THRESHOLD_PA,
    BRAKE_OFF_THRESHOLD_PA,
    BRAKE_TRAIL_FRACTION,
    STEERING_DEADBAND_RAD,
    THROTTLE_ON_THRESHOLD,
    BRAKE_ZONE_LOOKBACK_M,
    MPS_TO_KMH,
    G_ACCEL,
    SMOOTHING_WINDOW,
    SMOOTHING_ORDER,
    MEDIAN_FILTER_WINDOW,
)
from brain.track.segmentation import TrackSegment

logger = logging.getLogger(__name__)


@dataclass
class CornerPhaseMetrics:
    """Metrics for a single phase within a corner."""
    start_idx: int = -1
    end_idx: int = -1
    start_dist_m: float = 0.0
    end_dist_m: float = 0.0
    duration_s: float = 0.0


@dataclass
class BrakingMetrics(CornerPhaseMetrics):
    """Phase A: Braking zone metrics."""
    peak_brake_pressure_pa: float = 0.0
    deceleration_g: float = 0.0
    brake_point_dist_m: float = 0.0
    initial_application_rate_pa_s: float = 0.0


@dataclass
class TrailBrakeMetrics(CornerPhaseMetrics):
    """Phase B: Trail-braking metrics."""
    quality_r_squared: float = 0.0
    brake_while_turning: bool = False


@dataclass
class ApexMetrics(CornerPhaseMetrics):
    """Phase C: Apex metrics."""
    min_speed_kmh: float = 0.0
    max_lateral_g: float = 0.0
    lateral_offset_m: float = 0.0
    peak_sideslip_rad: float = 0.0
    apex_dist_m: float = 0.0


@dataclass
class ExitMetrics(CornerPhaseMetrics):
    """Phase D: Corner exit metrics."""
    throttle_point_dist_m: float = 0.0
    exit_speed_kmh: float = 0.0
    rear_wheelspin: bool = False
    coast_time_s: float = 0.0


@dataclass
class CornerAnalysis:
    """Full analysis of a single corner pass."""
    segment: TrackSegment
    lap_number: int
    braking: BrakingMetrics = field(default_factory=BrakingMetrics)
    trail_brake: TrailBrakeMetrics = field(default_factory=TrailBrakeMetrics)
    apex: ApexMetrics = field(default_factory=ApexMetrics)
    exit: ExitMetrics = field(default_factory=ExitMetrics)
    entry_speed_kmh: float = 0.0
    time_in_corner_s: float = 0.0


def _total_brake_pressure(df: pd.DataFrame) -> np.ndarray:
    """Sum of per-wheel brake pressures, with median filter for CAN noise."""
    cols = [
        "cba_actual_pressure_fl_pa", "cba_actual_pressure_fr_pa",
        "cba_actual_pressure_rl_pa", "cba_actual_pressure_rr_pa",
    ]
    available = [c for c in cols if c in df.columns]
    if not available:
        if "front_brake_pressure" in df.columns:
            bp = df["front_brake_pressure"].fillna(0) + df.get(
                "rear_brake_pressure", pd.Series(0, index=df.index)
            ).fillna(0)
            return medfilt(bp.values, MEDIAN_FILTER_WINDOW)
        return np.zeros(len(df))

    bp = df[available].fillna(0).sum(axis=1).values
    return medfilt(bp, MEDIAN_FILTER_WINDOW)


def _smooth(arr: np.ndarray) -> np.ndarray:
    """Savitzky-Golay smooth a signal."""
    if len(arr) < SMOOTHING_WINDOW:
        return arr
    return savgol_filter(arr, SMOOTHING_WINDOW, SMOOTHING_ORDER)


def analyze_corner(
    lap_df: pd.DataFrame,
    segment: TrackSegment,
    lap_number: int,
) -> CornerAnalysis:
    """Analyze a single corner pass with 4-phase decomposition.

    Args:
        lap_df: DataFrame for the full lap (must have track_dist_m column).
        segment: The corner segment definition.
        lap_number: Which lap this is from.
    """
    result = CornerAnalysis(segment=segment, lap_number=lap_number)

    if "track_dist_m" not in lap_df.columns:
        logger.warning("track_dist_m not in lap data - skipping corner analysis")
        return result

    dist = lap_df["track_dist_m"].values

    # Extend the analysis window backward to catch the braking zone
    extended_start = segment.start_dist_m - BRAKE_ZONE_LOOKBACK_M
    mask = (dist >= extended_start) & (dist <= segment.end_dist_m)
    corner_df = lap_df[mask].copy().reset_index(drop=True)

    if len(corner_df) < 10:
        return result

    corner_dist = corner_df["track_dist_m"].values
    corner_t = corner_df["t"].values

    # Core signals
    brake_p = _total_brake_pressure(corner_df)
    speed = corner_df["v_mps"].values if "v_mps" in corner_df.columns else np.zeros(len(corner_df))
    gas = corner_df["gas"].values if "gas" in corner_df.columns else np.zeros(len(corner_df))
    steering = (
        np.abs(corner_df["delta_wheel_rad"].values)
        if "delta_wheel_rad" in corner_df.columns
        else np.zeros(len(corner_df))
    )
    ax = corner_df["ax_mps2"].values if "ax_mps2" in corner_df.columns else np.zeros(len(corner_df))
    ay = corner_df["ay_mps2"].values if "ay_mps2" in corner_df.columns else np.zeros(len(corner_df))

    # Smooth signals
    brake_p_smooth = _smooth(brake_p)
    speed_smooth = _smooth(speed)

    # Entry speed (at the geometric corner start)
    geo_start_mask = corner_dist >= segment.start_dist_m
    if geo_start_mask.any():
        geo_start_i = np.argmax(geo_start_mask)
        result.entry_speed_kmh = float(speed[geo_start_i] * MPS_TO_KMH)

    # Total time in geometric corner
    geo_mask = (corner_dist >= segment.start_dist_m) & (corner_dist <= segment.end_dist_m)
    geo_indices = np.where(geo_mask)[0]
    if len(geo_indices) > 1:
        result.time_in_corner_s = float(corner_t[geo_indices[-1]] - corner_t[geo_indices[0]])

    # Phase A: Braking Zone
    result.braking = _analyze_braking(
        corner_df, corner_dist, corner_t, brake_p_smooth, ax, segment
    )

    # Phase B: Trail-Braking
    result.trail_brake = _analyze_trail_brake(
        corner_df, corner_dist, corner_t, brake_p_smooth, steering, result.braking
    )

    # Phase C: Apex
    result.apex = _analyze_apex(
        corner_df, corner_dist, corner_t, speed_smooth, ay, segment
    )

    # Phase D: Corner Exit
    result.exit = _analyze_exit(
        corner_df, corner_dist, corner_t, gas, steering, brake_p_smooth,
        speed, segment, result.apex
    )

    return result


def _analyze_braking(df, dist, t, brake_p, ax, segment) -> BrakingMetrics:
    """Detect and measure the braking zone."""
    m = BrakingMetrics()

    brake_on = brake_p > BRAKE_ON_THRESHOLD_PA
    if not brake_on.any():
        return m

    # Find first brake application before geometric corner start
    pre_corner = dist < segment.start_dist_m
    brake_in_approach = brake_on & pre_corner
    if not brake_in_approach.any():
        brake_in_corner = brake_on & (dist >= segment.start_dist_m)
        if not brake_in_corner.any():
            return m
        m.start_idx = int(np.argmax(brake_in_corner))
    else:
        m.start_idx = int(np.argmax(brake_in_approach))

    m.brake_point_dist_m = float(dist[m.start_idx])
    m.start_dist_m = m.brake_point_dist_m

    # Find end of heavy braking
    peak_idx = m.start_idx + int(brake_p[m.start_idx:].argmax())
    peak = brake_p[peak_idx]
    m.peak_brake_pressure_pa = float(peak)

    trail_threshold = peak * BRAKE_TRAIL_FRACTION
    after_peak = brake_p[peak_idx:]
    below_trail = after_peak < trail_threshold
    if below_trail.any():
        m.end_idx = peak_idx + int(np.argmax(below_trail))
    else:
        m.end_idx = len(brake_p) - 1

    m.end_dist_m = float(dist[min(m.end_idx, len(dist) - 1)])
    m.duration_s = float(t[m.end_idx] - t[m.start_idx]) if m.end_idx > m.start_idx else 0.0

    # Peak deceleration
    if m.start_idx < m.end_idx:
        m.deceleration_g = float(np.abs(ax[m.start_idx:m.end_idx + 1]).max() / G_ACCEL)

    # Initial application rate (Pa/s in first ~100ms = ~5 samples at 50Hz)
    n_init = min(5, m.end_idx - m.start_idx)
    if n_init > 1:
        dt = t[m.start_idx + n_init] - t[m.start_idx]
        dp = brake_p[m.start_idx + n_init] - brake_p[m.start_idx]
        m.initial_application_rate_pa_s = float(dp / dt) if dt > 0 else 0.0

    return m


def _analyze_trail_brake(df, dist, t, brake_p, steering, braking) -> TrailBrakeMetrics:
    """Detect trail-braking: declining brake pressure while turning."""
    m = TrailBrakeMetrics()

    if braking.end_idx <= braking.start_idx:
        return m

    start = braking.end_idx
    after_start = brake_p[start:]
    fully_off = after_start < BRAKE_OFF_THRESHOLD_PA
    if fully_off.any():
        end = start + int(np.argmax(fully_off))
    else:
        end = len(brake_p) - 1

    if end <= start:
        return m

    m.start_idx = start
    m.end_idx = end
    m.start_dist_m = float(dist[start])
    m.end_dist_m = float(dist[min(end, len(dist) - 1)])
    m.duration_s = float(t[end] - t[start])

    m.brake_while_turning = bool(
        (steering[start:end + 1] > STEERING_DEADBAND_RAD).any()
    )

    # Quality: R-squared of linear brake pressure decay
    trail_slice = brake_p[start:end + 1]
    if len(trail_slice) > 3:
        x = np.arange(len(trail_slice))
        try:
            lr = linregress(x, trail_slice)
            m.quality_r_squared = float(lr.rvalue ** 2)
        except Exception:
            m.quality_r_squared = 0.0

    return m


def _analyze_apex(df, dist, t, speed_smooth, ay, segment) -> ApexMetrics:
    """Find the apex: minimum speed within the geometric corner."""
    m = ApexMetrics()

    geo_mask = (dist >= segment.start_dist_m) & (dist <= segment.end_dist_m)
    geo_indices = np.where(geo_mask)[0]

    if len(geo_indices) < 3:
        return m

    speeds_in_corner = speed_smooth[geo_indices]
    apex_local = int(speeds_in_corner.argmin())
    apex_i = geo_indices[apex_local]

    m.start_idx = apex_i
    m.end_idx = apex_i
    m.apex_dist_m = float(dist[apex_i])
    m.start_dist_m = m.apex_dist_m
    m.end_dist_m = m.apex_dist_m
    m.min_speed_kmh = float(speeds_in_corner[apex_local] * MPS_TO_KMH)
    m.max_lateral_g = float(np.abs(ay[geo_indices]).max() / G_ACCEL)

    if "sn_n" in df.columns:
        val = df["sn_n"].iloc[apex_i]
        m.lateral_offset_m = float(val) if not np.isnan(val) else 0.0

    if "beta_rad" in df.columns:
        m.peak_sideslip_rad = float(np.abs(df["beta_rad"].iloc[geo_indices]).max())

    return m


def _analyze_exit(df, dist, t, gas, steering, brake_p, speed, segment, apex) -> ExitMetrics:
    """Analyze corner exit: throttle application and exit behavior."""
    m = ExitMetrics()

    if apex.start_idx < 0:
        return m

    post_apex_mask = (dist >= apex.apex_dist_m) & (dist <= segment.end_dist_m)
    post_indices = np.where(post_apex_mask)[0]

    if len(post_indices) < 3:
        return m

    m.start_idx = post_indices[0]
    m.end_idx = post_indices[-1]
    m.start_dist_m = float(dist[m.start_idx])
    m.end_dist_m = float(dist[m.end_idx])
    m.duration_s = float(t[m.end_idx] - t[m.start_idx])
    m.exit_speed_kmh = float(speed[m.end_idx] * MPS_TO_KMH)

    # Throttle application point
    throttle_on = gas[post_indices] > THROTTLE_ON_THRESHOLD
    if throttle_on.any():
        throttle_i = post_indices[int(np.argmax(throttle_on))]
        m.throttle_point_dist_m = float(dist[throttle_i])

    # Coast time: gap between brake-off and throttle-on
    brake_off = brake_p[post_indices] < BRAKE_OFF_THRESHOLD_PA
    if brake_off.any() and throttle_on.any():
        brake_off_i = post_indices[int(np.argmax(brake_off))]
        throttle_on_i = post_indices[int(np.argmax(throttle_on))]
        if throttle_on_i > brake_off_i:
            m.coast_time_s = float(t[throttle_on_i] - t[brake_off_i])

    # Rear wheelspin (uses config threshold, raw units not 0-1)
    from brain.config import WHEELSPIN_LAMBDA_THRESHOLD
    for col in ["lambda_rl_perc", "lambda_rr_perc"]:
        if col in df.columns:
            vals = df[col].iloc[post_indices].values
            if (vals > WHEELSPIN_LAMBDA_THRESHOLD).any():
                m.rear_wheelspin = True
                break

    return m


def analyze_all_corners(
    lap_df: pd.DataFrame,
    segments: list[TrackSegment],
    lap_number: int,
) -> list[CornerAnalysis]:
    """Analyze all corners for a single lap."""
    corners = [s for s in segments if s.segment_type == "corner"]
    return [analyze_corner(lap_df, seg, lap_number) for seg in corners]
