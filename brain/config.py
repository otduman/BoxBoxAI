"""
Brain configuration: physics-based thresholds, topic maps, and tunable parameters.

All thresholds are derived from vehicle dynamics, not track-specific tuning.
This file is the single source of truth for magic numbers.
"""

# ---------------------------------------------------------------------------
# Sampling & Smoothing
# ---------------------------------------------------------------------------
TARGET_HZ = 50                          # Downsample everything to 50 Hz
SMOOTHING_WINDOW = 5                    # Savitzky-Golay window (samples at TARGET_HZ)
SMOOTHING_ORDER = 2                     # Savitzky-Golay polynomial order
MEDIAN_FILTER_WINDOW = 5               # Median filter for CAN noise removal

# ---------------------------------------------------------------------------
# Braking Detection (physics-based, vehicle-agnostic)
# ---------------------------------------------------------------------------
BRAKE_ON_THRESHOLD_PA = 500_000         # ~5 bar — noise floor for intentional braking
BRAKE_OFF_THRESHOLD_PA = 100_000        # ~1 bar — fully off brake
BRAKE_TRAIL_FRACTION = 0.50             # Trail-brake starts when pressure < 50% of peak

# ---------------------------------------------------------------------------
# Steering
# ---------------------------------------------------------------------------
STEERING_DEADBAND_RAD = 0.017           # ~1 degree — below = straight steering

# ---------------------------------------------------------------------------
# Throttle
# ---------------------------------------------------------------------------
THROTTLE_ON_THRESHOLD = 0.10            # 10% throttle = intentional acceleration
THROTTLE_FULL = 0.95                    # >95% = full throttle

# ---------------------------------------------------------------------------
# Corner Detection (from track geometry curvature)
# ---------------------------------------------------------------------------
CURVATURE_CORNER_THRESHOLD = 0.005      # rad/m — ~200m radius and tighter = corner
MIN_CORNER_LENGTH_M = 30.0              # Ignore wiggles shorter than this
MIN_STRAIGHT_LENGTH_M = 50.0            # Minimum to count as a straight
CHICANE_MERGE_GAP_M = 20.0             # Merge corner segments separated by < this

# ---------------------------------------------------------------------------
# Vehicle Dynamics
# ---------------------------------------------------------------------------
OVERSTEER_BETA_THRESHOLD_RAD = 0.05     # |beta| > ~2.9 deg = notable sideslip
LOCKUP_LAMBDA_THRESHOLD = -3.0          # Slip ratio < -3 = wheel lockup (raw units, not 0-1)
WHEELSPIN_LAMBDA_THRESHOLD = 5.0        # Slip ratio > +5 = wheelspin (raw units, not 0-1)
SLIP_ANGLE_WARNING_RAD = 0.12           # ~7 deg tire slip angle = grip limit
MAX_LATERAL_G_ESTIMATE = 15.0           # m/s² — approx lateral limit for slick-tire racer

# ---------------------------------------------------------------------------
# Tire Temperature
# ---------------------------------------------------------------------------
TIRE_TEMP_IMBALANCE_THRESHOLD_C = 8.0   # Inner-outer gradient warning threshold

# ---------------------------------------------------------------------------
# Lap Validation
# ---------------------------------------------------------------------------
MIN_LAP_DURATION_S = 30.0               # Reject fragments shorter than this

# ---------------------------------------------------------------------------
# Corner Analysis — extension before geometric corner to catch braking zone
# ---------------------------------------------------------------------------
BRAKE_ZONE_LOOKBACK_M = 150.0           # Search this far back for brake point

# ---------------------------------------------------------------------------
# Apex Detection
# ---------------------------------------------------------------------------
APEX_SPEED_TOLERANCE = 0.02             # Within 2% of min speed = apex zone

# ---------------------------------------------------------------------------
# ROS 2 Topic Paths (standard A2RL convention — constructor0 prefix)
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
G_ACCEL = 9.81  # m/s²
HPA_TO_BAR = 0.001  # TPMS pressure: raw values are in hPa, convert to bar
