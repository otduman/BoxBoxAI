"""
High-speed MCAP reader: extracts ROS 2 telemetry into pandas DataFrames.
"""

import time
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from mcap.reader import make_reader
from mcap_ros2.decoder import DecoderFactory

from brain.config import TARGET_HZ
from brain.extract.topic_registry import (
    get_all_topics,
    get_primary_topics,
    get_topic_map,
    resolve_nested,
)

logger = logging.getLogger(__name__)


def read_mcap(
    mcap_path: str | Path,
    primary_only: bool = False,
) -> dict[str, pd.DataFrame]:
    """Read an MCAP file and return a dict of DataFrames keyed by topic key.

    Args:
        mcap_path: Path to the .mcap file.
        primary_only: If True, only extract essential topics (faster).

    Returns:
        Dictionary mapping topic key (e.g. "state_estimation") to a DataFrame
        with a float64 timestamp column 't' (seconds from epoch).
    """
    mcap_path = Path(mcap_path)
    if not mcap_path.exists():
        raise FileNotFoundError(f"MCAP file not found: {mcap_path}")

    specs = get_primary_topics() if primary_only else get_all_topics()
    topic_map = get_topic_map(specs)
    wanted_topics = set(topic_map.keys())

    # Accumulators: topic_key -> list of row dicts
    buffers: dict[str, list[dict]] = {spec.key: [] for spec in specs}

    t0 = time.perf_counter()
    decoder = DecoderFactory()

    with open(mcap_path, "rb") as f:
        try:
            #TODO: if make reader fails then make sure to stop, so it does not iterate the user
            reader = make_reader(f, decoder_factories=[decoder])
        except Exception as e:
            logger.error(f"Failed to open MCAP file: {mcap_path}")

        for schema, channel, message, decoded_msg in reader.iter_decoded_messages(
            topics=list(wanted_topics)
        ):
            topic = channel.topic
            spec = topic_map.get(topic)
            if spec is None:
                continue

            # Timestamp: nanoseconds -> seconds
            t_sec = message.log_time / 1e9

            row = {"t": t_sec}

            # Extract flat fields
            for field_name in spec.fields:
                val = getattr(decoded_msg, field_name, None)
                if val is not None:
                    row[field_name] = float(val) if not isinstance(val, (int, float, bool)) else val
                else:
                    row[field_name] = np.nan

            # Extract nested fields (e.g. sn_map_state.track_sn_state.sn_state.idx)
            for col_name, dotted_path in spec.nested_paths.items():
                val = resolve_nested(decoded_msg, dotted_path)
                if val is not None:
                    row[col_name] = float(val) if not isinstance(val, (int, float, bool)) else val
                else:
                    row[col_name] = np.nan

            buffers[spec.key].append(row)

    elapsed = time.perf_counter() - t0
    logger.info(f"MCAP read completed in {elapsed:.1f}s")

    # Convert buffers to DataFrames
    result = {}
    for spec in specs:
        rows = buffers[spec.key]
        if not rows:
            logger.warning(f"No messages found for topic '{spec.key}' ({spec.topic})")
            continue
        df = pd.DataFrame(rows)
        df.sort_values("t", inplace=True)
        df.reset_index(drop=True, inplace=True)
        result[spec.key] = df
        logger.info(
            f"  {spec.key}: {len(df)} messages, "
            f"{df['t'].iloc[-1] - df['t'].iloc[0]:.1f}s span"
        )

    return result


def build_master_dataframe(
    topic_dfs: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Align all topic DataFrames onto a single 50 Hz master timeline.

    StateEstimation is the backbone. Other topics are merged via
    merge_asof (nearest-neighbor in time with forward fill).

    Returns:
        Single DataFrame at TARGET_HZ with all columns.
    """
    if "state_estimation" not in topic_dfs:
        raise ValueError(
            "state_estimation topic is required but missing from MCAP data"
        )

    se = topic_dfs["state_estimation"].copy()

    # Decimate StateEstimation to TARGET_HZ
    # Calculate source frequency from the first few samples
    if len(se) > 1:
        dt = se["t"].iloc[1] - se["t"].iloc[0]
        source_hz = 1.0 / dt if dt > 0 else 100.0
    else:
        source_hz = 100.0

    step = max(1, round(source_hz / TARGET_HZ))
    master = se.iloc[::step].copy()
    master.reset_index(drop=True, inplace=True)

    # Merge each supplementary topic
    for key, df in topic_dfs.items():
        if key == "state_estimation":
            continue

        # Avoid column name collisions — prefix supplementary columns
        existing_cols = set(master.columns)
        rename_map = {}
        for col in df.columns:
            if col == "t":
                continue
            if col in existing_cols:
                rename_map[col] = f"{key}__{col}"

        df_renamed = df.rename(columns=rename_map)

        master = pd.merge_asof(
            master,
            df_renamed,
            on="t",
            direction="nearest",
            tolerance=0.1,  # 100ms tolerance — generous for low-rate topics
        )

    logger.info(
        f"Master DataFrame: {len(master)} rows, {len(master.columns)} columns, "
        f"{TARGET_HZ} Hz"
    )

    return master


def extract_session(
    mcap_path: str | Path,
    primary_only: bool = False,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Full extraction pipeline: MCAP -> master DataFrame + raw topic DataFrames.

    Returns:
        (master_df, raw_topic_dfs)
    """
    t0 = time.perf_counter()

    try:
        raw_dfs = read_mcap(mcap_path, primary_only=primary_only)
    except FileNotFoundError as exc:
        logger.error(f"Failed to read MCAP file: {mcap_path}")
        raise
    except Exception as exc:
        logger.error(f"Failed to extract session from MCAP file: {mcap_path}")
        raise

    master = build_master_dataframe(raw_dfs)

    elapsed = time.perf_counter() - t0
    logger.info(f"Total extraction: {elapsed:.1f}s")

    return master, raw_dfs
