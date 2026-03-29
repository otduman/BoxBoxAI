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
    archetype: str = ""
    trace: list[dict] = field(default_factory=list)


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
    prev_segment_end_m: float | None = None,
) -> CornerAnalysis:
    """Analyze a single corner pass with 4-phase decomposition.

    Args:
        lap_df: DataFrame for the full lap (must have track_dist_m column).
        segment: The corner segment definition.
        lap_number: Which lap this is from.
        prev_segment_end_m: End distance of the previous segment (if any),
            used to limit brake lookback in chicanes so we don't
            re-attribute the previous corner's braking event.
    """
    result = CornerAnalysis(segment=segment, lap_number=lap_number)

    if "track_dist_m" not in lap_df.columns:
        logger.warning("track_dist_m not in lap data - skipping corner analysis")
        return result

    dist = lap_df["track_dist_m"].values

    # Extend the analysis window backward to catch the braking zone.
    # In chicanes, limit lookback to halfway between previous corner end
    # and this corner start to avoid capturing the same brake event twice.
    lookback = BRAKE_ZONE_LOOKBACK_M
    if prev_segment_end_m is not None:
        gap = segment.start_dist_m - prev_segment_end_m
        if gap < lookback:
            lookback = max(gap * 0.5, 10.0)  # at least 10m
    extended_start = segment.start_dist_m - lookback
    # Extend past segment end to capture exit data (especially for short corners
    # where the apex may be at or near the segment boundary)
    EXIT_LOOKAHEAD_M = 100.0
    extended_end = segment.end_dist_m + EXIT_LOOKAHEAD_M
    mask = (dist >= extended_start) & (dist <= extended_end)
    corner_df = lap_df[mask].copy().reset_index(drop=True)

    if len(corner_df) < 10:
        logger.warning(
            f"Insufficient data for corner {segment.segment_id} lap {lap_number} "
            f"(only {len(corner_df)} points)"
        )
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
    yaw = corner_df["wz_radps"].values if "wz_radps" in corner_df.columns else np.zeros(len(corner_df))
    slip = corner_df["beta_rad"].values if "beta_rad" in corner_df.columns else np.zeros(len(corner_df))

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

    # Validate phase order
    if result.apex.start_idx > 0 and result.trail_brake.end_idx > result.apex.start_idx:
        logger.warning(
            f"Phase overlap in {segment.segment_id} lap {lap_number}: "
            f"trail-brake extends past apex"
        )
        
    # Calculate Cross-Track Archetype
    apex_speed = result.apex.min_speed_kmh
    speed_prof = "LowSpeed" if apex_speed < 100 else ("MidSpeed" if apex_speed < 150 else "HighSpeed")
    dir_str = segment.direction.capitalize()
    geo_type = "90Deg"
    if segment.peak_curvature > 0.035: # Tight radius (< ~28m)
        geo_type = "Hairpin"
    elif segment.length_m > 120 and segment.avg_curvature < 0.015:
        geo_type = "Sweeper"
    
    result.archetype = f"{speed_prof}_{dir_str}_{geo_type}"

    # Extract downsampled trajectory trace
    trace = []
    if len(corner_df) >= 10:
        trace_indices = np.linspace(0, len(corner_df) - 1, num=10, dtype=int)
        for idx in trace_indices:
            row = corner_df.iloc[idx]
            bp_val = brake_p_smooth[idx] if len(brake_p_smooth) > idx else 0.0
            sp_val = speed_smooth[idx] * MPS_TO_KMH if len(speed_smooth) > idx else 0.0
            trace.append({
                "d": round(float(row.get("track_dist_m", 0)), 1),
                "v": round(float(sp_val), 1),
                "br": round(float(bp_val), 0),
                "gas": round(float(row.get("gas", 0)), 2),
                "steer": round(float(row.get("delta_wheel_rad", 0)), 3),
                "ax": round(float(ax[idx]), 2) if len(ax) > idx else 0.0,
                "ay": round(float(ay[idx]), 2) if len(ay) > idx else 0.0,
                "yaw": round(float(yaw[idx]), 3) if len(yaw) > idx else 0.0,
                "slip": round(float(slip[idx]), 3) if len(slip) > idx else 0.0,
            })
    result.trace = trace

    return result


def _analyze_braking(df, dist, t, brake_p, ax, segment) -> BrakingMetrics:
    """Detect and measure the braking zone."""
    m = BrakingMetrics()

    brake_on = brake_p > BRAKE_ON_THRESHOLD_PA
    if not brake_on.any():
        return m

    # Find first brake application in the extended window
    m.start_idx = int(np.argmax(brake_on))
    m.brake_point_dist_m = float(dist[m.start_idx])
    m.start_dist_m = m.brake_point_dist_m

    # Find end of heavy braking (search only until corner end to avoid next corner)
    corner_end_mask = dist <= segment.end_dist_m
    if corner_end_mask.any():
        search_end = int(np.where(corner_end_mask)[0][-1]) + 1
    else:
        search_end = len(brake_p)
    
    search_end = min(search_end, len(brake_p))
    if m.start_idx >= search_end:
        return m
        
    peak_idx = m.start_idx + int(brake_p[m.start_idx:search_end].argmax())
    peak = brake_p[peak_idx]
    m.peak_brake_pressure_pa = float(peak)

    trail_threshold = peak * BRAKE_TRAIL_FRACTION
    after_peak = brake_p[peak_idx:search_end]
    below_trail = after_peak < trail_threshold
    if below_trail.any():
        m.end_idx = min(peak_idx + int(np.argmax(below_trail)), len(brake_p) - 1)
    else:
        m.end_idx = min(search_end - 1, len(brake_p) - 1)

    m.end_dist_m = float(dist[m.end_idx])
    m.duration_s = float(t[m.end_idx] - t[m.start_idx]) if m.end_idx > m.start_idx else 0.0

    # Peak deceleration
    if m.start_idx < m.end_idx:
        m.deceleration_g = float(np.abs(ax[m.start_idx:m.end_idx + 1]).max() / G_ACCEL)

    # Initial application rate (time-based, not sample-based)
    TARGET_INIT_TIME = 0.1  # 100ms industry standard
    init_mask = (t >= t[m.start_idx]) & (t <= t[m.start_idx] + TARGET_INIT_TIME) & (np.arange(len(t)) <= m.end_idx)
    init_indices = np.where(init_mask)[0]
    if len(init_indices) > 1:
        dt = t[init_indices[-1]] - t[init_indices[0]]
        dp = brake_p[init_indices[-1]] - brake_p[init_indices[0]]
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
        end = min(start + int(np.argmax(fully_off)), len(brake_p) - 1)
    else:
        end = len(brake_p) - 1

    if end <= start:
        return m

    m.start_idx = start
    m.end_idx = end
    m.start_dist_m = float(dist[start])
    m.end_dist_m = float(dist[end])
    m.duration_s = float(t[end] - t[start])

    # Check if steering is active AND increasing during trail-brake phase
    # (filters out steering unwinding from previous corner)
    steer_slice = steering[start:end + 1]
    steer_active = steer_slice > STEERING_DEADBAND_RAD
    if len(steer_slice) > 1:
        steer_increasing = np.diff(steer_slice) > 0
        m.brake_while_turning = bool(steer_active.any() and steer_increasing.any())
    else:
        m.brake_while_turning = bool(steer_active.any())

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
    """Find the apex: minimum speed (slow corners) or max lateral-g (fast corners)."""
    m = ApexMetrics()

    geo_mask = (dist >= segment.start_dist_m) & (dist <= segment.end_dist_m)
    geo_indices = np.where(geo_mask)[0]

    if len(geo_indices) < 3:
        return m

    # Calculate max lateral g first
    m.max_lateral_g = float(np.abs(ay[geo_indices]).max() / G_ACCEL)

    # Apex detection strategy depends on corner speed
    speeds_in_corner = speed_smooth[geo_indices]
    if m.max_lateral_g > 1.0:
        # Fast corner: use maximum lateral g as apex
        apex_local = int(np.abs(ay[geo_indices]).argmax())
    else:
        # Slow corner: use minimum speed as apex
        apex_local = int(speeds_in_corner.argmin())
    
    apex_i = geo_indices[apex_local]

    m.start_idx = apex_i
    m.end_idx = apex_i
    m.apex_dist_m = float(dist[apex_i])
    m.start_dist_m = m.apex_dist_m
    m.end_dist_m = m.apex_dist_m
    m.min_speed_kmh = float(speed_smooth[apex_i] * MPS_TO_KMH)

    if "sn_n" in df.columns:
        val = df["sn_n"].iloc[apex_i]
        m.lateral_offset_m = float(val) if not np.isnan(val) else 0.0

    # Sideslip: measure in window around apex, not entire corner
    if "beta_rad" in df.columns:
        apex_window_start = max(0, apex_i - 5)
        apex_window_end = min(len(df), apex_i + 6)
        m.peak_sideslip_rad = float(np.abs(df["beta_rad"].iloc[apex_window_start:apex_window_end]).max())

    return m


def _analyze_exit(df, dist, t, gas, steering, brake_p, speed, segment, apex) -> ExitMetrics:
    """Analyze corner exit: throttle application and exit behavior."""
    m = ExitMetrics()

    if apex.start_idx < 0:
        return m

    # Use distance-based window first
    post_apex_mask = (dist >= apex.apex_dist_m) & (dist <= segment.end_dist_m)
    post_indices = np.where(post_apex_mask)[0]

    if len(post_indices) < 3:
        # Short corner or apex at segment edge: extend 100m past segment end
        extended_mask = (dist >= apex.apex_dist_m) & (dist <= segment.end_dist_m + 100)
        post_indices = np.where(extended_mask)[0]

    if len(post_indices) < 3:
        # Fallback: use index-based window from apex (next 50 samples ≈ 1s at 50Hz)
        apex_idx = apex.start_idx
        end_idx = min(apex_idx + 50, len(dist) - 1)
        post_indices = np.arange(apex_idx, end_idx + 1)

    if len(post_indices) < 3:
        return m

    m.start_idx = post_indices[0]
    m.end_idx = post_indices[-1]
    m.start_dist_m = float(dist[m.start_idx])
    m.end_dist_m = float(dist[m.end_idx])
    m.duration_s = float(t[m.end_idx] - t[m.start_idx])
    m.exit_speed_kmh = float(speed[m.end_idx] * MPS_TO_KMH)

    # Throttle application point - first sustained throttle
    throttle_on = gas[post_indices] > THROTTLE_ON_THRESHOLD
    if throttle_on.any():
        throttle_i = post_indices[int(np.argmax(throttle_on))]
        m.throttle_point_dist_m = float(dist[throttle_i])

    # Coast time: gap between last brake-on and first throttle-on
    brake_on_mask = brake_p[post_indices] >= BRAKE_OFF_THRESHOLD_PA
    if throttle_on.any():
        if brake_on_mask.any():
            # Find last point where brakes are still on
            last_brake_on = int(np.where(brake_on_mask)[0][-1])
            brake_off_i = post_indices[min(last_brake_on + 1, len(post_indices) - 1)]
        else:
            # Brakes already off at apex
            brake_off_i = post_indices[0]
        
        throttle_on_i = post_indices[int(np.argmax(throttle_on))]
        if throttle_on_i > brake_off_i:
            m.coast_time_s = float(t[throttle_on_i] - t[brake_off_i])
        else:
            # Throttle before brake fully released (overlap, good!)
            m.coast_time_s = 0.0

    # Rear wheelspin — require sustained event (min_event_duration), not just a single spike
    from brain.config import WHEELSPIN_LAMBDA_THRESHOLD, TARGET_HZ, get_active_profile
    min_samples = max(1, int(get_active_profile().min_event_duration_s * TARGET_HZ))
    for col in ["lambda_rl_perc", "lambda_rr_perc"]:
        if col in df.columns:
            vals = df[col].iloc[post_indices].values
            above = vals > WHEELSPIN_LAMBDA_THRESHOLD
            # Check for min_samples consecutive True values
            if len(above) >= min_samples:
                consecutive = 0
                for v in above:
                    consecutive = consecutive + 1 if v else 0
                    if consecutive >= min_samples:
                        m.rear_wheelspin = True
                        break
            if m.rear_wheelspin:
                break

    return m


def analyze_all_corners(
    lap_df: pd.DataFrame,
    segments: list[TrackSegment],
    lap_number: int,
) -> list[CornerAnalysis]:
    """Analyze all corners for a single lap."""
    results = []
    prev_end: float | None = None
    for seg in segments:
        if seg.segment_type == "corner":
            results.append(analyze_corner(lap_df, seg, lap_number, prev_end))
        prev_end = seg.end_dist_m
    return results
