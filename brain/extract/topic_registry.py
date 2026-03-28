"""
Topic registry: maps ROS 2 topic names to their message fields for extraction.

Each TopicSpec defines what fields to pull from a given topic, enabling the
mcap_reader to decode only what we need without touching the full message schema.
"""

from dataclasses import dataclass, field
from brain.config import TOPICS, TARGET_HZ


@dataclass
class TopicSpec:
    """Specification for a single topic to extract from an MCAP file."""
    key: str                        # Short internal name (e.g. "state_estimation")
    topic: str                      # Full ROS 2 topic path
    fields: list[str]               # Flat field names to extract from the message
    rate_hz: int = 100              # Expected publish rate
    nested_paths: dict[str, str] = field(default_factory=dict)
    # nested_paths maps output_column_name -> dotted attribute path
    # e.g. {"sn_idx": "sn_map_state.track_sn_state.sn_state.idx"}


def _se_nested() -> dict[str, str]:
    """Nested field paths for StateEstimation -> SnMapState -> SnLaneState -> SnState."""
    base = "sn_map_state.track_sn_state.sn_state"
    return {
        "sn_idx":    f"{base}.idx",
        "sn_ds":     f"{base}.ds",
        "sn_d_idx":  f"{base}.d_idx",
        "sn_n":      f"{base}.n",
        "sn_epsi":   f"{base}.epsi",
        "sn_status": f"{base}.status",
    }


# ---------------------------------------------------------------------------
# Primary topics — always extracted (essential for all analysis)
# ---------------------------------------------------------------------------
PRIMARY_TOPICS: list[TopicSpec] = [
    TopicSpec(
        key="state_estimation",
        topic=TOPICS["state_estimation"],
        fields=[
            # Position & orientation
            "x_m", "y_m", "z_m",
            "roll_rad", "pitch_rad", "yaw_rad",
            # Velocity
            "vx_mps", "vy_mps", "vz_mps", "v_mps",
            # Acceleration
            "ax_mps2", "ay_mps2", "az_mps2",
            # Angular rates
            "wz_radps",
            # Wheel speeds
            "omega_w_fl", "omega_w_fr", "omega_w_rl", "omega_w_rr",
            # Slip ratios & angles
            "lambda_fl_perc", "lambda_fr_perc", "lambda_rl_perc", "lambda_rr_perc",
            "alpha_fl_rad", "alpha_fr_rad", "alpha_rl_rad", "alpha_rr_rad",
            # Sideslip & curvature
            "beta_rad", "kappa_radpm",
            # Driver inputs
            "gas", "brake", "clutch", "gear", "rpm",
            "delta_wheel_rad",
            # Brake pressures
            "front_brake_pressure", "rear_brake_pressure",
            "cba_actual_pressure_fl_pa", "cba_actual_pressure_fr_pa",
            "cba_actual_pressure_rl_pa", "cba_actual_pressure_rr_pa",
            # Safety
            "is_safe",
        ],
        rate_hz=100,
        nested_paths=_se_nested(),
    ),
    TopicSpec(
        key="badenia_misc",
        topic=TOPICS["badenia_misc"],
        fields=["lap_time", "lap_distance", "lap_number", "battery_voltage"],
        rate_hz=50,
    ),
]

# ---------------------------------------------------------------------------
# Supplementary topics — extracted for deeper analysis
# ---------------------------------------------------------------------------
SUPPLEMENTARY_TOPICS: list[TopicSpec] = [
    TopicSpec(
        key="ice_status_01",
        topic=TOPICS["ice_status_01"],
        fields=["ice_actual_gear", "ice_actual_throttle", "ice_available_fuel_l"],
        rate_hz=100,
    ),
    TopicSpec(
        key="ice_status_02",
        topic=TOPICS["ice_status_02"],
        fields=[
            "ice_engine_speed_rpm", "ice_oil_temp_deg_c",
            "ice_water_temp_deg_c", "ice_oil_press_k_pa",
        ],
        rate_hz=100,
    ),
    TopicSpec(
        key="kistler_acc",
        topic=TOPICS["kistler_acc"],
        fields=["acc_x_body", "acc_y_body", "acc_z_body"],
        rate_hz=250,
    ),
    TopicSpec(
        key="kistler_correvit",
        topic=TOPICS["kistler_correvit"],
        fields=["vel_x_cor", "vel_y_cor", "vel_cor", "angle_cor"],
        rate_hz=250,
    ),
    TopicSpec(
        key="wheel_load",
        topic=TOPICS["wheel_load"],
        fields=["load_wheel_fl", "load_wheel_fr", "load_wheel_rr", "load_wheel_rl"],
        rate_hz=100,
    ),
    TopicSpec(
        key="tpms_front",
        topic=TOPICS["tpms_front"],
        fields=["tpr4_temp_fl", "tpr4_temp_fr", "tpr4_abs_press_fl", "tpr4_abs_press_fr"],
        rate_hz=50,
    ),
    TopicSpec(
        key="tpms_rear",
        topic=TOPICS["tpms_rear"],
        fields=["tpr4_temp_rl", "tpr4_temp_rr", "tpr4_abs_press_rl", "tpr4_abs_press_rr"],
        rate_hz=50,
    ),
    TopicSpec(
        key="tyre_temp_front",
        topic=TOPICS["tyre_temp_front"],
        fields=["outer_fl", "center_fl", "inner_fl", "outer_fr", "center_fr", "inner_fr"],
        rate_hz=20,
    ),
    TopicSpec(
        key="tyre_temp_rear",
        topic=TOPICS["tyre_temp_rear"],
        fields=["outer_rl", "center_rl", "inner_rl", "outer_rr", "center_rr", "inner_rr"],
        rate_hz=20,
    ),
    TopicSpec(
        key="brake_disk_temp",
        topic=TOPICS["brake_disk_temp"],
        fields=["brake_disk_temp_fl", "brake_disk_temp_fr", "brake_disk_temp_rr", "brake_disk_temp_rl"],
        rate_hz=20,
    ),
    TopicSpec(
        key="ride_front",
        topic=TOPICS["ride_front"],
        fields=["ride_height_front", "damper_stroke_fl", "damper_stroke_fr"],
        rate_hz=100,
    ),
    TopicSpec(
        key="ride_rear",
        topic=TOPICS["ride_rear"],
        fields=["ride_height_rear", "damper_stroke_rl", "damper_stroke_rr"],
        rate_hz=100,
    ),
]


def get_primary_topics() -> list[TopicSpec]:
    """Return the essential topics needed for basic analysis."""
    return PRIMARY_TOPICS


def get_all_topics() -> list[TopicSpec]:
    """Return all topics including supplementary data."""
    return PRIMARY_TOPICS + SUPPLEMENTARY_TOPICS


def get_topic_map(specs: list[TopicSpec]) -> dict[str, TopicSpec]:
    """Build a lookup from ROS 2 topic path -> TopicSpec."""
    return {spec.topic: spec for spec in specs}


def resolve_nested(msg, dotted_path: str):
    """Walk a dotted attribute path on a ROS 2 message object.

    Example: resolve_nested(msg, "sn_map_state.track_sn_state.sn_state.idx")
    """
    obj = msg
    for attr in dotted_path.split("."):
        obj = getattr(obj, attr, None)
        if obj is None:
            return None
    return obj
