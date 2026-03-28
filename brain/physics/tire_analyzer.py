"""
Tire analyzer: surface temperature gradients, cross-car deltas,
degradation trends across a session.
"""

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from brain.config import TIRE_TEMP_IMBALANCE_THRESHOLD_C, HPA_TO_BAR

logger = logging.getLogger(__name__)


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

        # Surface temps
        for zone, col in cols.items():
            # Check both direct and prefixed column names
            actual_col = _find_col(lap_df, col)
            if actual_col:
                val = float(lap_df[actual_col].mean())
                setattr(wm, f"{zone}_temp_c", val)

        if wm.outer_temp_c > 0 and wm.inner_temp_c > 0:
            wm.avg_surface_temp_c = (wm.outer_temp_c + wm.center_temp_c + wm.inner_temp_c) / 3
            wm.temp_gradient_c = wm.inner_temp_c - wm.outer_temp_c

            if abs(wm.temp_gradient_c) > TIRE_TEMP_IMBALANCE_THRESHOLD_C:
                if wm.temp_gradient_c > 0:
                    result.warnings.append(
                        f"{pos.upper()}: inner {wm.temp_gradient_c:.1f}C hotter than outer - possible over-camber or overdriving"
                    )
                else:
                    result.warnings.append(
                        f"{pos.upper()}: outer {abs(wm.temp_gradient_c):.1f}C hotter than inner - possible under-camber"
                    )

        # TPMS
        tpms = tpms_map[pos]
        temp_col = _find_col(lap_df, tpms["temp"])
        press_col = _find_col(lap_df, tpms["press"])
        if temp_col:
            wm.avg_carcass_temp_c = float(lap_df[temp_col].mean())
        if press_col:
            raw_press = float(lap_df[press_col].mean())
            # TPMS sensors report in hPa; convert to bar
            wm.avg_pressure_bar = raw_press * HPA_TO_BAR

        result.wheels[pos] = wm

    # Cross-car deltas
    _compute_deltas(result)

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
            if pos.startswith("f"):
                front_temps.append(wm.avg_surface_temp_c)
            else:
                rear_temps.append(wm.avg_surface_temp_c)

            if pos.endswith("l"):
                left_temps.append(wm.avg_surface_temp_c)
            else:
                right_temps.append(wm.avg_surface_temp_c)

    if front_temps and rear_temps:
        result.front_rear_temp_delta_c = np.mean(front_temps) - np.mean(rear_temps)

    if left_temps and right_temps:
        result.left_right_temp_delta_c = np.mean(left_temps) - np.mean(right_temps)


def analyze_tire_degradation(
    lap_analyses: list[TireAnalysis],
) -> str:
    """Determine tire degradation trend across multiple laps."""
    if len(lap_analyses) < 2:
        return "insufficient_data"

    # Track average surface temp across laps
    avg_temps = []
    for ta in lap_analyses:
        temps = [wm.avg_surface_temp_c for wm in ta.wheels.values() if wm.avg_surface_temp_c > 0]
        if temps:
            avg_temps.append(np.mean(temps))

    if len(avg_temps) < 2:
        return "insufficient_data"

    # Simple trend: if temp rises >2C across session, degrading
    temp_change = avg_temps[-1] - avg_temps[0]
    if temp_change > 2.0:
        return "degrading"
    elif temp_change < -2.0:
        return "improving"
    return "stable"
