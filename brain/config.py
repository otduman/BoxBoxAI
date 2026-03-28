"""
Brain configuration: physics-based thresholds, topic maps, and tunable parameters.

All thresholds are derived from vehicle dynamics, not track-specific tuning.
This file is the single source of truth for magic numbers.

Two driver profiles are provided:
  - "autonomous": For analyzing autonomous racing controllers (ms-level reactions)
  - "human": For analyzing human drivers (100-300ms reaction time, coarser inputs)

The active profile is selected at runtime. All modules import thresholds from
get_active_profile() rather than using flat globals.
"""

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Driver Profile dataclass
# ---------------------------------------------------------------------------
@dataclass
class DriverProfile:
    """Complete set of detection thresholds for a driver type."""
    name: str

    # Slip ratio thresholds (raw units from StateEstimation, not 0-1)
    lockup_lambda_threshold: float       # Slip ratio below this = lockup
    wheelspin_lambda_threshold: float     # Slip ratio above this = wheelspin
    min_event_duration_s: float          # Ignore events shorter than this

    # Sideslip / balance
    oversteer_beta_threshold_rad: float  # |beta| above this = oversteer event
    slip_angle_warning_rad: float        # Front tire slip angle = understeer

    # Coast time
    coast_time_flag_s: float             # Only flag coast time above this

    # Trail-brake
    trail_brake_fraction: float          # Trail-brake starts at this fraction of peak

    # Coaching output
    max_verdicts: int                    # Max verdicts to present to the driver


# ---------------------------------------------------------------------------
# Autonomous profile: tight thresholds, ms-level precision
# Calibrated from A2RL data where slip ratios range -6 to +10 raw units.
# Peak braking force occurs at ~-8% to -12% slip (Pacejka tire model).
# Peak traction force occurs at ~+5% to +10% slip.
# Autonomous controllers react in <20ms so even brief events are intentional.
# ---------------------------------------------------------------------------
PROFILE_AUTONOMOUS = DriverProfile(
    name="autonomous",
    lockup_lambda_threshold=-3.0,      # Raw units; ~3% beyond normal operating range
    wheelspin_lambda_threshold=5.0,    # Raw units; beyond peak traction slip
    min_event_duration_s=0.02,         # 20ms — controller reacts this fast
    oversteer_beta_threshold_rad=0.05, # ~2.9 deg — subtle but intentional for a controller
    slip_angle_warning_rad=0.12,       # ~7 deg — approaching grip limit
    coast_time_flag_s=0.05,            # 50ms — any coast is notable for a controller
    trail_brake_fraction=0.50,         # Trail-brake detection at 50% of peak
    max_verdicts=20,                   # Controller can digest many verdicts
)

# ---------------------------------------------------------------------------
# Human profile: relaxed thresholds, accounts for reaction time + input noise
#
# Sources:
#   - Pacejka "Tire and Vehicle Dynamics": peak longitudinal force at 8-15% slip
#   - MoTeC i2 Pro default lockup threshold: -10% to -15% slip ratio
#   - AiM Race Studio: event filter default 100ms minimum
#   - SAE J2489: tire force vs. slip characterization
#   - Professional race engineers (MoTeC forums, data-driven motorsport):
#     coast time < 0.2s is human reaction time, not a coaching issue
#   - Typical ABS activation: -10% to -15% slip ratio
#   - Typical TC activation: +3% to +8% slip ratio (setting dependent)
#   - Human brake-to-throttle transition: 100-300ms physically unavoidable
# ---------------------------------------------------------------------------
PROFILE_HUMAN = DriverProfile(
    name="human",
    lockup_lambda_threshold=-8.0,      # Industry standard: ABS at -10 to -15%, flag at -8
    wheelspin_lambda_threshold=8.0,    # Beyond peak traction; TC kicks in at 3-8%
    min_event_duration_s=0.10,         # 100ms min — humans can't feel <100ms events
    oversteer_beta_threshold_rad=0.08, # ~4.6 deg — normal rotation below this
    slip_angle_warning_rad=0.12,       # ~7 deg — same for both (tire physics)
    coast_time_flag_s=0.30,            # 300ms — below this is just human reaction time
    trail_brake_fraction=0.50,         # Same for both
    max_verdicts=5,                    # Humans can process 3-5 actions per session
)

# ---------------------------------------------------------------------------
# Active profile management
# ---------------------------------------------------------------------------
_active_profile: DriverProfile = PROFILE_AUTONOMOUS


def set_driver_profile(profile_name: str) -> None:
    """Set the active driver profile by name."""
    global _active_profile
    profiles = {"autonomous": PROFILE_AUTONOMOUS, "human": PROFILE_HUMAN}
    if profile_name not in profiles:
        raise ValueError(f"Unknown profile '{profile_name}'. Options: {list(profiles.keys())}")
    _active_profile = profiles[profile_name]


def get_active_profile() -> DriverProfile:
    """Get the currently active driver profile."""
    return _active_profile


# ---------------------------------------------------------------------------
# Fixed thresholds (not profile-dependent — these are physics/hardware constants)
# ---------------------------------------------------------------------------

# Sampling & Smoothing
TARGET_HZ = 50
SMOOTHING_WINDOW = 5
SMOOTHING_ORDER = 2
MEDIAN_FILTER_WINDOW = 5

# Braking Detection
BRAKE_ON_THRESHOLD_PA = 500_000
BRAKE_OFF_THRESHOLD_PA = 100_000
BRAKE_TRAIL_FRACTION = 0.50

# Steering
STEERING_DEADBAND_RAD = 0.017

# Throttle
THROTTLE_ON_THRESHOLD = 0.10
THROTTLE_FULL = 0.95

# Corner Detection (from track geometry curvature)
CURVATURE_CORNER_THRESHOLD = 0.005
MIN_CORNER_LENGTH_M = 30.0
MIN_STRAIGHT_LENGTH_M = 50.0
CHICANE_MERGE_GAP_M = 20.0

# Vehicle Dynamics (kept as module-level for backward compat, but prefer profile)
OVERSTEER_BETA_THRESHOLD_RAD = 0.05
LOCKUP_LAMBDA_THRESHOLD = -3.0
WHEELSPIN_LAMBDA_THRESHOLD = 5.0
SLIP_ANGLE_WARNING_RAD = 0.12
MAX_LATERAL_G_ESTIMATE = 15.0

# Tire Temperature
TIRE_TEMP_IMBALANCE_THRESHOLD_C = 8.0

# Lap Validation
MIN_LAP_DURATION_S = 30.0

# Corner Analysis
BRAKE_ZONE_LOOKBACK_M = 150.0

# Apex Detection
APEX_SPEED_TOLERANCE = 0.02

# ---------------------------------------------------------------------------
# ROS 2 Topic Paths
# ---------------------------------------------------------------------------
TOPIC_PREFIX = "/constructor0"

TOPICS = {
    "state_estimation":     f"{TOPIC_PREFIX}/state_estimation",
    "badenia_misc":         f"{TOPIC_PREFIX}/can/badenia_560_badenia_misc",
    "cba_fl":               f"{TOPIC_PREFIX}/can/cba_status_fl",
    "cba_fr":               f"{TOPIC_PREFIX}/can/cba_status_fr",
    "cba_rl":               f"{TOPIC_PREFIX}/can/cba_status_rl",
    "cba_rr":               f"{TOPIC_PREFIX}/can/cba_status_rr",
    "ice_status_01":        f"{TOPIC_PREFIX}/can/ice_status_01",
    "ice_status_02":        f"{TOPIC_PREFIX}/can/ice_status_02",
    "psa_status_01":        f"{TOPIC_PREFIX}/can/psa_status_01",
    "wheels_speed":         f"{TOPIC_PREFIX}/can/wheels_speed_01",
    "kistler_acc":          f"{TOPIC_PREFIX}/can/kistler_acc_body",
    "kistler_correvit":     f"{TOPIC_PREFIX}/can/kistler_correvit",
    "wheel_load":           f"{TOPIC_PREFIX}/can/badenia_560_wheel_load",
    "tpms_front":           f"{TOPIC_PREFIX}/can/badenia_560_tpms_front",
    "tpms_rear":            f"{TOPIC_PREFIX}/can/badenia_560_tpms_rear",
    "tyre_temp_front":      f"{TOPIC_PREFIX}/can/badenia_560_tyre_surface_temp_front",
    "tyre_temp_rear":       f"{TOPIC_PREFIX}/can/badenia_560_tyre_surface_temp_rear",
    "brake_disk_temp":      f"{TOPIC_PREFIX}/can/badenia_560_brake_disk_temp",
    "ride_front":           f"{TOPIC_PREFIX}/can/badenia_560_ride_front",
    "ride_rear":            f"{TOPIC_PREFIX}/can/badenia_560_ride_rear",
}

# ---------------------------------------------------------------------------
# Unit Conversions
# ---------------------------------------------------------------------------
MPS_TO_KMH = 3.6
RAD_TO_DEG = 57.2957795131
G_ACCEL = 9.81
HPA_TO_BAR = 0.001
