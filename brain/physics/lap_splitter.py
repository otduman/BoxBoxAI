"""
Lap splitter: detects lap boundaries from telemetry data.

Primary method: lap_number from BadeniaMisc.
Fallback: sn_idx wraparound detection (track position resets to 0).
"""

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from brain.config import MIN_LAP_DURATION_S

logger = logging.getLogger(__name__)


@dataclass
class Lap:
    """A single lap extracted from session data."""
    lap_number: int
    start_idx: int        # Index into master DataFrame
    end_idx: int
    start_time: float     # Epoch seconds
    end_time: float
    duration_s: float
    start_dist_m: float   # Track distance at start
    end_dist_m: float


def split_laps(
    master: pd.DataFrame,
    raw_dfs: dict[str, pd.DataFrame] | None = None,
) -> list[Lap]:
    """Split session into individual laps.

    Tries BadeniaMisc lap_number first, falls back to sn_idx wraparound.
    
    Args:
        master: Master DataFrame with merged telemetry
        raw_dfs: Reserved for future use (e.g., fallback to raw topic data)
    """
    # Validate input
    if master.empty or len(master) < MIN_LAP_DURATION_S * 50:  # 50Hz assumption
        logger.warning(
            f"Insufficient data for lap detection "
            f"({len(master)} samples, need ~{MIN_LAP_DURATION_S * 50})"
        )
        return []
    
    laps = _split_by_lap_number(master)

    if not laps:
        logger.info("BadeniaMisc lap_number not available, falling back to sn_idx")
        laps = _split_by_sn_wraparound(master)

    if not laps:
        logger.warning("Could not detect lap boundaries — treating entire session as one lap")
        
        # Populate track distance if available
        start_dist = 0.0
        end_dist = 0.0
        if "track_dist_m" in master.columns:
            start_dist = float(master["track_dist_m"].iloc[0])
            end_dist = float(master["track_dist_m"].iloc[-1])
        
        laps = [Lap(
            lap_number=1,
            start_idx=0,
            end_idx=len(master) - 1,
            start_time=float(master["t"].iloc[0]),
            end_time=float(master["t"].iloc[-1]),
            duration_s=float(master["t"].iloc[-1] - master["t"].iloc[0]),
            start_dist_m=start_dist,
            end_dist_m=end_dist,
        )]

    # Filter out incomplete laps
    valid = [lap for lap in laps if lap.duration_s >= MIN_LAP_DURATION_S]
    if len(valid) < len(laps):
        logger.info(
            f"Filtered {len(laps) - len(valid)} short fragments "
            f"(< {MIN_LAP_DURATION_S}s)"
        )

    for lap in valid:
        logger.info(
            f"  Lap {lap.lap_number}: {lap.duration_s:.2f}s "
            f"(idx {lap.start_idx}-{lap.end_idx})"
        )

    return valid


def _split_by_lap_number(master: pd.DataFrame) -> list[Lap]:
    """Split using lap_number from BadeniaMisc topic.
    
    Detects lap transitions instead of grouping by lap number,
    which handles duplicate lap sequences (e.g., two sessions in one file).
    """
    # Check if lap_number is in master (merged from badenia_misc)
    col = None
    for candidate in ["lap_number", "badenia_misc__lap_number"]:
        if candidate in master.columns:
            col = candidate
            break

    if col is None:
        return []

    lap_numbers = master[col].dropna()
    if lap_numbers.empty:
        return []

    # Forward/backward fill and convert to int
    master_ln = master[col].ffill().bfill().astype(int)
    
    # Find lap transitions (where lap number changes)
    lap_changes = np.concatenate([[True], np.diff(master_ln.values) != 0, [True]])
    lap_boundaries = np.where(lap_changes)[0]
    
    if len(lap_boundaries) < 2:
        return []

    laps = []
    for i in range(len(lap_boundaries) - 1):
        start_pos = lap_boundaries[i]
        end_pos = lap_boundaries[i + 1] - 1
        
        if end_pos - start_pos < 10:
            continue
        
        ln = master_ln.iloc[start_pos]

        # Track distance if available
        start_dist = 0.0
        end_dist = 0.0
        if "track_dist_m" in master.columns:
            start_dist = float(master["track_dist_m"].iloc[start_pos])
            end_dist = float(master["track_dist_m"].iloc[end_pos])

        laps.append(Lap(
            lap_number=int(ln),
            start_idx=int(start_pos),
            end_idx=int(end_pos),
            start_time=float(master["t"].iloc[start_pos]),
            end_time=float(master["t"].iloc[end_pos]),
            duration_s=float(master["t"].iloc[end_pos] - master["t"].iloc[start_pos]),
            start_dist_m=start_dist,
            end_dist_m=end_dist,
        ))

    # Validate sequential lap numbers
    if laps:
        lap_nums = [lap.lap_number for lap in laps]
        unique_nums = sorted(set(lap_nums))
        if len(unique_nums) > 1:
            expected = list(range(unique_nums[0], unique_nums[-1] + 1))
            if unique_nums != expected:
                missing = set(expected) - set(unique_nums)
                logger.warning(f"Non-sequential lap numbers detected. Missing: {missing}")

    return laps


def _split_by_sn_wraparound(master: pd.DataFrame) -> list[Lap]:
    """Split using sn_idx wraparound (track position resets near start/finish).
    
    Detects wraparound using both magnitude and value criteria to avoid false positives.
    """
    if "sn_idx" not in master.columns:
        return []

    sn = master["sn_idx"].values
    if np.isnan(sn).all():
        return []

    # Detect wraparound with more robust criteria
    max_sn = np.nanmax(sn)
    min_sn = np.nanmin(sn)
    if max_sn < 10:
        return []

    diff = np.diff(sn)
    # Wraparound must satisfy TWO conditions:
    # 1. Large negative jump (>30% of max)
    # 2. New value must be near minimum (within 10% of range from min)
    threshold = -max_sn * 0.3
    sn_range = max_sn - min_sn
    wraparound_mask = (diff < threshold) & (sn[1:] < min_sn + sn_range * 0.1)
    wrap_points = np.where(wraparound_mask)[0] + 1  # +1 for index after diff

    if len(wrap_points) == 0:
        return []

    # Build lap boundaries (end is exclusive in slice, so don't subtract 1)
    boundaries = [0] + list(wrap_points) + [len(master)]
    laps = []
    for i in range(len(boundaries) - 1):
        start_idx = boundaries[i]
        end_idx = boundaries[i + 1] - 1  # Inclusive end index
        
        if end_idx - start_idx < 10:
            continue

        # Populate track distance if available
        start_dist = 0.0
        end_dist = 0.0
        if "track_dist_m" in master.columns:
            start_dist = float(master["track_dist_m"].iloc[start_idx])
            end_dist = float(master["track_dist_m"].iloc[end_idx])

        laps.append(Lap(
            lap_number=i + 1,
            start_idx=int(start_idx),
            end_idx=int(end_idx),
            start_time=float(master["t"].iloc[start_idx]),
            end_time=float(master["t"].iloc[end_idx]),
            duration_s=float(master["t"].iloc[end_idx] - master["t"].iloc[start_idx]),
            start_dist_m=start_dist,
            end_dist_m=end_dist,
        ))

    return laps


def get_lap_data(master: pd.DataFrame, lap: Lap) -> pd.DataFrame:
    """Extract the master DataFrame slice for a single lap.
    
    Args:
        master: Master DataFrame with full session data
        lap: Lap object with start/end indices
        
    Returns:
        DataFrame slice for the lap, with index reset to 0
    """
    # Validate lap indices
    if lap.end_idx >= len(master):
        logger.warning(
            f"Lap {lap.lap_number} end_idx ({lap.end_idx}) exceeds data length ({len(master)}). "
            f"Truncating to available data."
        )
        lap.end_idx = len(master) - 1
    
    if lap.start_idx < 0 or lap.start_idx >= len(master):
        logger.error(f"Lap {lap.lap_number} has invalid start_idx ({lap.start_idx})")
        return pd.DataFrame()
    
    return master.iloc[lap.start_idx:lap.end_idx + 1].copy().reset_index(drop=True)
