"""
Tire analyzer: surface temperature gradients, cross-car deltas,
degradation trends across a session.
"""

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.stats import linregress

from brain.config import TIRE_TEMP_IMBALANCE_THRESHOLD_C, HPA_TO_BAR

logger = logging.getLogger(__name__)

# Tire temperature operating windows (°C)
TIRE_TEMP_COLD_THRESHOLD = 60.0
TIRE_TEMP_HOT_THRESHOLD = 100.0


@dataclass
class WheelTireMetrics:
    """Temperature and pressure metrics for a single wheel."""
    position: str             # "fl", "fr", "rl", "rr"
    avg_surface_temp_c: float = 0.0
    outer_temp_c: float = 0.0
    center_temp_c: float = 0.0
    inner_temp_c: float = 0.0
    temp_gradient_c: float = 0.0   # inner - outer (positive = hotter inside)
    avg_pressure_bar: float = 0.0
    avg_carcass_temp_c: float = 0.0


@dataclass
class TireAnalysis:
    """Full tire analysis for a lap or session."""
    lap_number: int
    wheels: dict[str, WheelTireMetrics] = field(default_factory=dict)
    front_rear_temp_delta_c: float = 0.0
    left_right_temp_delta_c: float = 0.0
    degradation_trend: str = "stable"  # "stable", "degrading", "improving"
    warnings: list[str] = field(default_factory=list)


def analyze_tires(
    lap_df: pd.DataFrame,
    lap_number: int,
) -> TireAnalysis:
    """Analyze tire temperatures and pressures for a lap."""
    result = TireAnalysis(lap_number=lap_number)

    # Surface temps: outer/center/inner per wheel
    wheel_configs = {
        "fl": {"outer": "outer_fl", "center": "center_fl", "inner": "inner_fl"},
        "fr": {"outer": "outer_fr", "center": "center_fr", "inner": "inner_fr"},
        "rl": {"outer": "outer_rl", "center": "center_rl", "inner": "inner_rl"},
        "rr": {"outer": "outer_rr", "center": "center_rr", "inner": "inner_rr"},
    }

    # TPMS columns (carcass temp and pressure)
    tpms_map = {
        "fl": {"temp": "tpr4_temp_fl", "press": "tpr4_abs_press_fl"},
        "fr": {"temp": "tpr4_temp_fr", "press": "tpr4_abs_press_fr"},
        "rl": {"temp": "tpr4_temp_rl", "press": "tpr4_abs_press_rl"},
        "rr": {"temp": "tpr4_temp_rr", "press": "tpr4_abs_press_rr"},
    }

    for pos, cols in wheel_configs.items():
        wm = WheelTireMetrics(position=pos)

        # Surface temps with NaN validation
        for zone, col in cols.items():
            # Check both direct and prefixed column names
            actual_col = _find_col(lap_df, col)
            if actual_col:
                val = lap_df[actual_col].mean()
                if not pd.isna(val):
                    val = float(val)
                    # Explicit assignment instead of setattr for safety
                    if zone == "outer":
                        wm.outer_temp_c = val
                    elif zone == "center":
                        wm.center_temp_c = val
                    elif zone == "inner":
                        wm.inner_temp_c = val

        # Calculate average from valid temps only
        temps = [wm.outer_temp_c, wm.center_temp_c, wm.inner_temp_c]
        valid_temps = [t for t in temps if t > 0]
        if len(valid_temps) >= 2:  # Need at least 2 of 3 zones
            wm.avg_surface_temp_c = float(np.mean(valid_temps))
            
            # Gradient calculation (only if both outer and inner valid)
            if wm.outer_temp_c > 0 and wm.inner_temp_c > 0:
                wm.temp_gradient_c = wm.inner_temp_c - wm.outer_temp_c

                if abs(wm.temp_gradient_c) > TIRE_TEMP_IMBALANCE_THRESHOLD_C:
                    if wm.temp_gradient_c > 0:
                        result.warnings.append(
                            f"{pos.upper()}: inner {wm.temp_gradient_c:.1f}°C hotter than outer "
                            f"- possible over-camber or overdriving"
                        )
                    else:
                        result.warnings.append(
                            f"{pos.upper()}: outer {abs(wm.temp_gradient_c):.1f}°C hotter than inner "
                            f"- possible under-camber"
                        )
            
            # Absolute temperature warnings
            if wm.avg_surface_temp_c < TIRE_TEMP_COLD_THRESHOLD:
                result.warnings.append(
                    f"{pos.upper()}: cold ({wm.avg_surface_temp_c:.1f}°C), tire not up to operating temp"
                )
            elif wm.avg_surface_temp_c > TIRE_TEMP_HOT_THRESHOLD:
                result.warnings.append(
                    f"{pos.upper()}: overheating ({wm.avg_surface_temp_c:.1f}°C), risk of blistering/degradation"
                )

        # TPMS (carcass temp and pressure)
        tpms = tpms_map[pos]
        temp_col = _find_col(lap_df, tpms["temp"])
        press_col = _find_col(lap_df, tpms["press"])
        
        if temp_col:
            carcass_temp = lap_df[temp_col].mean()
            if not pd.isna(carcass_temp):
                wm.avg_carcass_temp_c = float(carcass_temp)
        
        if press_col:
            raw_press = lap_df[press_col].mean()
            if not pd.isna(raw_press):
                raw_press = float(raw_press)
                # Auto-detect units and convert to bar
                # Typical tire pressure: 1.5-3.5 bar (22-51 PSI, 150-350 kPa, 1500-3500 hPa)
                if raw_press > 100:  # Likely hPa (1500-3500 range)
                    wm.avg_pressure_bar = raw_press * HPA_TO_BAR
                elif raw_press > 10:  # Likely PSI (22-51 range)
                    wm.avg_pressure_bar = raw_press * 0.0689476
                else:  # Already bar (1.5-3.5 range)
                    wm.avg_pressure_bar = raw_press

        result.wheels[pos] = wm

    # Check if we have any tire data
    if not result.wheels or all(w.avg_surface_temp_c == 0 for w in result.wheels.values()):
        logger.warning(f"No tire temperature data available for lap {lap_number}")
        return result

    # Cross-car deltas
    _compute_deltas(result)

    # Log summary
    logger.debug(
        f"Tire analysis lap {lap_number}: "
        f"avg temps FL={result.wheels.get('fl', WheelTireMetrics('fl')).avg_surface_temp_c:.1f}°C, "
        f"FR={result.wheels.get('fr', WheelTireMetrics('fr')).avg_surface_temp_c:.1f}°C, "
        f"F/R delta={result.front_rear_temp_delta_c:+.1f}°C, "
        f"L/R delta={result.left_right_temp_delta_c:+.1f}°C, "
        f"{len(result.warnings)} warnings"
    )

    return result


def _find_col(df: pd.DataFrame, col_name: str) -> str | None:
    """Find a column by name, checking both direct and prefixed variants."""
    if col_name in df.columns:
        return col_name
    for c in df.columns:
        if c.endswith(f"__{col_name}"):
            return c
    return None


def _compute_deltas(result: TireAnalysis) -> None:
    """Compute front/rear and left/right temperature deltas."""
    wheels = result.wheels

    front_temps = []
    rear_temps = []
    left_temps = []
    right_temps = []

    for pos, wm in wheels.items():
        if wm.avg_surface_temp_c > 0:
            # Explicit position checks instead of string parsing
            if pos in ["fl", "fr"]:
                front_temps.append(wm.avg_surface_temp_c)
            elif pos in ["rl", "rr"]:
                rear_temps.append(wm.avg_surface_temp_c)

            if pos in ["fl", "rl"]:
                left_temps.append(wm.avg_surface_temp_c)
            elif pos in ["fr", "rr"]:
                right_temps.append(wm.avg_surface_temp_c)

    if front_temps and rear_temps:
        result.front_rear_temp_delta_c = float(np.mean(front_temps) - np.mean(rear_temps))

    if left_temps and right_temps:
        result.left_right_temp_delta_c = float(np.mean(left_temps) - np.mean(right_temps))


def analyze_tire_degradation(
    lap_analyses: list[TireAnalysis],
) -> str:
    """Determine tire degradation trend across multiple laps using linear regression.
    
    Returns:
        "degrading": Temperature increasing >0.5°C per lap
        "improving": Temperature decreasing >0.5°C per lap (tires coming in)
        "stable": Temperature stable
        "insufficient_data": Need at least 3 laps for trend analysis
    """
    if len(lap_analyses) < 3:
        return "insufficient_data"

    # Track average surface temp across laps
    avg_temps = []
    for ta in lap_analyses:
        temps = [wm.avg_surface_temp_c for wm in ta.wheels.values() if wm.avg_surface_temp_c > 0]
        if temps:
            avg_temps.append(np.mean(temps))

    if len(avg_temps) < 3:
        return "insufficient_data"

    # Use linear regression to determine trend (more robust than first-to-last)
    x = np.arange(len(avg_temps))
    slope, _, _, _, _ = linregress(x, avg_temps)
    
    # Slope is °C per lap
    if slope > 0.5:
        logger.info(f"Tire degradation detected: {slope:.2f}°C per lap increase")
        return "degrading"
    elif slope < -0.5:
        logger.info(f"Tires improving: {slope:.2f}°C per lap decrease (coming up to temp)")
        return "improving"
    
    return "stable"
