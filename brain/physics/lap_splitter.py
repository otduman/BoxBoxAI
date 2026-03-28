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
    """
    laps = _split_by_lap_number(master, raw_dfs)

    if not laps:
        logger.info("BadeniaMisc lap_number not available, falling back to sn_idx")
        laps = _split_by_sn_wraparound(master)

    if not laps:
        logger.warning("Could not detect lap boundaries — treating entire session as one lap")
        laps = [Lap(
            lap_number=1,
            start_idx=0,
            end_idx=len(master) - 1,
            start_time=master["t"].iloc[0],
            end_time=master["t"].iloc[-1],
            duration_s=master["t"].iloc[-1] - master["t"].iloc[0],
            start_dist_m=0.0,
            end_dist_m=0.0,
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


def _split_by_lap_number(
    master: pd.DataFrame,
    raw_dfs: dict[str, pd.DataFrame] | None,
) -> list[Lap]:
    """Split using lap_number from BadeniaMisc topic."""
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

    # Round to int
    master_ln = master[col].ffill().bfill().astype(int)
    unique_laps = sorted(master_ln.unique())

    if len(unique_laps) < 1:
        return []

    laps = []
    for ln in unique_laps:
        mask = master_ln == ln
        indices = master.index[mask]
        if len(indices) < 10:
            continue

        start_idx = indices[0]
        end_idx = indices[-1]

        # Track distance if available
        start_dist = 0.0
        end_dist = 0.0
        if "track_dist_m" in master.columns:
            start_dist = master["track_dist_m"].iloc[start_idx]
            end_dist = master["track_dist_m"].iloc[end_idx]

        laps.append(Lap(
            lap_number=int(ln),
            start_idx=int(start_idx),
            end_idx=int(end_idx),
            start_time=float(master["t"].iloc[start_idx]),
            end_time=float(master["t"].iloc[end_idx]),
            duration_s=float(master["t"].iloc[end_idx] - master["t"].iloc[start_idx]),
            start_dist_m=start_dist,
            end_dist_m=end_dist,
        ))

    return laps


def _split_by_sn_wraparound(master: pd.DataFrame) -> list[Lap]:
    """Split using sn_idx wraparound (track position resets near start/finish)."""
    if "sn_idx" not in master.columns:
        return []

    sn = master["sn_idx"].values
    if np.isnan(sn).all():
        return []

    # Detect wraparound: sn_idx drops significantly (>50% of max)
    max_sn = np.nanmax(sn)
    if max_sn < 10:
        return []

    diff = np.diff(sn)
    # Wraparound = large negative jump
    threshold = -max_sn * 0.5
    wrap_points = np.where(diff < threshold)[0] + 1  # +1 for index after diff

    if len(wrap_points) == 0:
        return []

    # Build lap boundaries
    boundaries = [0] + list(wrap_points) + [len(master) - 1]
    laps = []
    for i in range(len(boundaries) - 1):
        start_idx = boundaries[i]
        end_idx = boundaries[i + 1] - 1 if i < len(boundaries) - 2 else boundaries[i + 1]

        laps.append(Lap(
            lap_number=i + 1,
            start_idx=int(start_idx),
            end_idx=int(end_idx),
            start_time=float(master["t"].iloc[start_idx]),
            end_time=float(master["t"].iloc[end_idx]),
            duration_s=float(master["t"].iloc[end_idx] - master["t"].iloc[start_idx]),
            start_dist_m=0.0,
            end_dist_m=0.0,
        ))

    return laps


def get_lap_data(master: pd.DataFrame, lap: Lap) -> pd.DataFrame:
    """Extract the master DataFrame slice for a single lap."""
    return master.iloc[lap.start_idx:lap.end_idx + 1].copy().reset_index(drop=True)
