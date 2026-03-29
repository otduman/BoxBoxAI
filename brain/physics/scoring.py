"""
ML-like segment scoring system.

Computes a multi-factor driving score per segment using normalized features
and weighted aggregation. Behaves like a learned regression model but:
- No training required
- Fully deterministic
- Explainable

Each segment (corner/straight) produces:
- A score (0-1)
- Component scores for each factor
- The weakest factor identified
- A quality label (optimal/good/average/poor)
"""

from dataclasses import dataclass, field
from typing import Literal

from brain.physics.corner_analyzer import CornerAnalysis
from brain.physics.straight_analyzer import StraightAnalysis


# ---------------------------------------------------------------------------
# Vehicle class configurations - industry-standard G-force targets
# ---------------------------------------------------------------------------

VEHICLE_CLASS_DEFAULTS = {
    "gt3": {
        "braking_g": 2.2,  # GT3 race cars on slicks: 2.0-2.5G
        "lateral_g": 2.0,  # With aero and slicks
        "acceleration_g": 0.5,
    },
    "gt4": {
        "braking_g": 1.8,  # GT4 cars: slightly less grip
        "lateral_g": 1.6,
        "acceleration_g": 0.45,
    },
    "touring": {
        "braking_g": 1.5,  # Touring cars / track day cars
        "lateral_g": 1.3,
        "acceleration_g": 0.4,
    },
    "formula": {
        "braking_g": 4.0,  # Open-wheel with aero
        "lateral_g": 3.5,
        "acceleration_g": 1.5,
    },
    "road_car": {
        "braking_g": 1.0,  # Street cars
        "lateral_g": 1.0,
        "acceleration_g": 0.35,
    },
}

# Default vehicle class (can be overridden per session)
DEFAULT_VEHICLE_CLASS = "gt3"


# ---------------------------------------------------------------------------
# Configurable weights - can be tuned per driver or car
# ---------------------------------------------------------------------------

CORNER_WEIGHTS = {
    # Speed factors (40% total)
    "entry_speed": 0.10,
    "apex_speed": 0.10,
    "exit_speed": 0.20,  # Most important - compounds on straight
    # Braking factors (20% total)
    "brake_point": 0.10,
    "braking_intensity": 0.05,  # NEW: deceleration G
    "brake_release": 0.05,  # NEW: coast time penalty
    # Technique factors (25% total)
    "trail_brake": 0.10,
    "throttle_point": 0.10,
    "traction_control": 0.05,  # NEW: wheelspin penalty
    # Precision factors (15% total)
    "line": 0.08,
    "lateral_g_utilization": 0.07,  # NEW: how hard pushing grip
}

STRAIGHT_WEIGHTS = {
    "entry_speed": 0.20,
    "exit_speed": 0.15,  # NEW: setup for next corner
    "top_speed": 0.25,
    "throttle_pct": 0.20,
    "acceleration": 0.20,
}


# ---------------------------------------------------------------------------
# Score normalization functions (feature -> 0-1 score)
# ---------------------------------------------------------------------------

def _entry_speed_score(actual: float, optimal: float) -> float:
    """Score based on entry speed difference.

    Penalizes being slower (strongly) and being faster (lightly).
    Excessive entry speed often leads to compromised apex/exit.
    """
    if optimal <= 0:
        return 1.0
    diff = actual - optimal  # Positive = user was FASTER
    if diff > 0:
        # Faster than reference - slight penalty (may be overdriving)
        # 30 km/h faster = 0.7 score (not catastrophic but suspicious)
        return max(0.7, 1.0 - diff / 100.0)
    else:
        # Slower than reference - stronger penalty
        # 20 km/h slower = 0 score
        return max(0.0, 1.0 + diff / 20.0)


def _exit_speed_score(actual: float, optimal: float) -> float:
    """Exit speed is VERY important - compounds on following straight.

    Penalizes being slower (strongly). Being faster is rewarded up to a point,
    but excessive speed might indicate missed apex or run-off.
    """
    if optimal <= 0:
        return 1.0
    diff = actual - optimal  # Positive = user was FASTER
    if diff > 0:
        # Faster exit is generally good, but cap the bonus
        # and penalize extreme overspeed (might be cutting/running wide)
        if diff > 15:
            return max(0.8, 1.0 - (diff - 15) / 50.0)
        return 1.0  # Faster exit = perfect
    else:
        # Slower than reference - strong penalty
        # 15 km/h slower = 0 score (stricter than entry)
        return max(0.0, 1.0 + diff / 15.0)


def _brake_point_score(actual_m: float, optimal_m: float) -> float:
    """Brake point distance. Later is generally better (closer to corner)."""
    if optimal_m <= 0:
        return 1.0
    diff = abs(actual_m - optimal_m)
    # 10m off = 0 score
    return max(0.0, 1.0 - diff / 10.0)


def _trail_brake_score(
    r_squared: float,
    has_trail_brake: bool,
    corner_requires_braking: bool = True,
) -> float:
    """Trail-brake quality score.

    Args:
        r_squared: Quality of brake-steering correlation (0-1)
        has_trail_brake: Whether driver applied trail braking
        corner_requires_braking: Whether this corner needs braking at all

    Returns:
        Score 0-1 where:
        - 1.0 = perfect trail braking or N/A (flat-out corner)
        - 0.3 = braked but didn't trail-brake (suboptimal but not catastrophic)
        - 0.0 = poor trail braking quality
    """
    if not corner_requires_braking:
        # Fast corner - no braking needed, trail-brake N/A
        return 1.0

    if not has_trail_brake:
        # Braked but didn't trail-brake - suboptimal technique
        # Not catastrophic (0.0) because some corners don't benefit from it
        return 0.3

    # R² of 0.85+ = perfect, below 0.5 = poor
    return min(1.0, max(0.0, (r_squared - 0.5) / 0.35))


def _line_score(deviation_m: float) -> float:
    """Lateral deviation from optimal line. 0 = perfect, 2m+ = 0 score."""
    return max(0.0, 1.0 - abs(deviation_m) / 2.0)


def _throttle_point_score(actual_gap_m: float, reference_gap_m: float | None = None) -> float:
    """Distance from apex to throttle application.

    Args:
        actual_gap_m: Driver's throttle point relative to apex (negative = before apex)
        reference_gap_m: Reference lap's throttle point (if available)

    The optimal throttle point depends on corner type:
    - Hairpin: Throttle AT or just past apex
    - Fast sweeper: May start throttle before apex
    - Entry-speed corner: Late throttle is acceptable

    When reference is available, compare against it. Otherwise use absolute scoring.
    """
    if reference_gap_m is not None:
        # Compare to reference lap
        diff = abs(actual_gap_m - reference_gap_m)
        # 15m difference from reference = 0 score
        return max(0.0, 1.0 - diff / 15.0)

    # No reference - use absolute scoring with reasonable defaults
    # Throttle slightly before to slightly after apex is ideal (±5m)
    if -5.0 <= actual_gap_m <= 5.0:
        return 1.0
    elif actual_gap_m < -5.0:
        # Very early throttle - may compromise apex
        return max(0.5, 1.0 - abs(actual_gap_m + 5.0) / 20.0)
    else:
        # Late throttle - penalize more strongly
        # 20m past apex = 0.25 score
        return max(0.25, 1.0 - (actual_gap_m - 5.0) / 20.0)


def _throttle_pct_score(actual: float, expected: float = 85.0) -> float:
    """Time at full throttle on straights."""
    if expected <= 0:
        return 1.0
    # Score based on how close to expected
    ratio = actual / expected
    return min(1.0, max(0.0, ratio))


def _acceleration_score(actual_g: float, expected_g: float = 0.35) -> float:
    """Peak acceleration on straights."""
    if expected_g <= 0:
        return 1.0
    ratio = actual_g / expected_g
    return min(1.0, max(0.0, ratio))


def _top_speed_score(actual: float, optimal: float) -> float:
    """Top speed achieved on straight."""
    if optimal <= 0:
        return 1.0
    diff = optimal - actual
    # 10 km/h slower = 0 score
    return max(0.0, 1.0 - diff / 10.0)


def _apex_speed_score(actual: float, optimal: float) -> float:
    """Minimum speed at apex. Higher is better (carrying speed)."""
    if optimal <= 0:
        return 1.0
    diff = optimal - actual  # Positive = user was slower
    # 15 km/h slower = 0 score
    return max(0.0, 1.0 - diff / 15.0)


def _braking_intensity_score(
    actual_g: float,
    optimal_g: float | None = None,
    vehicle_class: str = DEFAULT_VEHICLE_CLASS,
) -> float:
    """Braking deceleration G. Higher = more efficient braking.

    Industry-standard braking G by vehicle class:
    - GT3 race cars (slicks): 2.0-2.5G
    - GT4 cars: 1.6-2.0G
    - Touring/track day: 1.3-1.6G
    - Formula/open-wheel: 4.0-6.0G
    - Road cars: 0.8-1.2G

    Args:
        actual_g: Driver's peak braking deceleration
        optimal_g: Reference lap's braking G (if available)
        vehicle_class: Vehicle class for default thresholds
    """
    if optimal_g is None or optimal_g <= 0:
        # Use vehicle class default
        vehicle_config = VEHICLE_CLASS_DEFAULTS.get(
            vehicle_class, VEHICLE_CLASS_DEFAULTS[DEFAULT_VEHICLE_CLASS]
        )
        optimal_g = vehicle_config["braking_g"]

    if optimal_g <= 0:
        return 1.0

    ratio = actual_g / optimal_g
    return min(1.0, max(0.0, ratio))


def _brake_release_score(coast_time_s: float) -> float:
    """Coast time penalty. 0s = perfect overlap, >0.3s = poor.

    Good drivers overlap brake release with throttle application.
    """
    if coast_time_s <= 0:
        return 1.0  # Perfect - throttle before brake fully released
    # 0.3s coast = 0 score
    return max(0.0, 1.0 - coast_time_s / 0.3)


def _traction_control_score(
    has_wheelspin: bool,
    wheelspin_severity: float = 0.5,
) -> float:
    """Wheelspin/traction penalty with severity grading.

    Args:
        has_wheelspin: Whether wheelspin was detected
        wheelspin_severity: Severity factor 0-1 (0=brief, 1=sustained/severe)
            Can be computed from duration, slip ratio, or event count.

    Returns:
        Score 0-1 where:
        - 1.0 = No wheelspin (perfect traction)
        - 0.85 = Brief wheelspin (acceptable, ~0.05s)
        - 0.6 = Noticeable wheelspin (~0.15s)
        - 0.3 = Excessive wheelspin (>0.3s or severe)

    Note: Brief wheelspin on corner exit is normal in high-power cars.
    Only sustained or repeated wheelspin is penalized heavily.
    """
    if not has_wheelspin:
        return 1.0

    # Severity 0 = brief/negligible, 1 = sustained/severe
    # Map severity to score: 0.85 (brief) down to 0.3 (severe)
    return max(0.3, 0.85 - wheelspin_severity * 0.55)


def _lateral_g_score(actual_g: float, optimal_g: float) -> float:
    """Lateral G utilization. How close to grip limit.

    If reference achieved 1.8G and user only 1.2G, they're not pushing.
    """
    if optimal_g <= 0:
        return 1.0
    ratio = actual_g / optimal_g
    return min(1.0, max(0.0, ratio))


# ---------------------------------------------------------------------------
# Data classes for scoring results
# ---------------------------------------------------------------------------

QualityLabel = Literal["optimal", "good", "average", "poor"]


@dataclass
class ComponentScores:
    """Individual component scores for a segment."""
    scores: dict[str, float] = field(default_factory=dict)

    def weakest(self) -> tuple[str, float]:
        """Return the component with the lowest score."""
        if not self.scores:
            return ("unknown", 0.0)
        worst_key = min(self.scores, key=self.scores.get)
        return (worst_key, self.scores[worst_key])

    def strongest(self) -> tuple[str, float]:
        """Return the component with the highest score."""
        if not self.scores:
            return ("unknown", 1.0)
        best_key = max(self.scores, key=self.scores.get)
        return (best_key, self.scores[best_key])


@dataclass
class SegmentScore:
    """Complete scoring result for a segment."""
    segment_id: str
    segment_type: str  # "corner" or "straight"
    lap_number: int

    # Overall score
    score: float  # 0-1
    quality: QualityLabel

    # Component breakdown
    components: ComponentScores = field(default_factory=ComponentScores)

    # Diagnostic info
    main_issue: str = ""
    main_issue_score: float = 0.0

    # Feature values used (for debugging)
    features: dict[str, float] = field(default_factory=dict)


def _score_to_quality(score: float) -> QualityLabel:
    """Convert numeric score to quality label."""
    if score > 0.85:
        return "optimal"
    elif score > 0.70:
        return "good"
    elif score > 0.50:
        return "average"
    else:
        return "poor"


# ---------------------------------------------------------------------------
# Main scoring functions
# ---------------------------------------------------------------------------

def score_corner(
    corner: CornerAnalysis,
    reference: CornerAnalysis | None = None,
    weights: dict[str, float] | None = None,
    vehicle_class: str = DEFAULT_VEHICLE_CLASS,
) -> SegmentScore:
    """
    Score a corner pass against an optimal reference.

    If no reference provided, uses absolute thresholds based on vehicle class.

    Args:
        corner: The corner analysis to score
        reference: Optional reference (fast lap) corner for comparison
        weights: Optional custom weights (defaults to CORNER_WEIGHTS)
        vehicle_class: Vehicle class for default G-force thresholds

    Returns:
        SegmentScore with overall score, components, and diagnostics
    """
    w = weights or CORNER_WEIGHTS
    vehicle_config = VEHICLE_CLASS_DEFAULTS.get(
        vehicle_class, VEHICLE_CLASS_DEFAULTS[DEFAULT_VEHICLE_CLASS]
    )

    # Determine if this corner requires braking
    # (flat-out corners have no brake application)
    corner_requires_braking = (
        corner.braking.brake_point_dist_m > 0 or
        corner.braking.deceleration_g > 0.3  # Threshold for meaningful braking
    )

    # Extract optimal values from reference or use vehicle-class defaults
    if reference:
        opt_entry = reference.entry_speed_kmh
        opt_exit = reference.exit.exit_speed_kmh
        opt_brake = reference.braking.brake_point_dist_m
        opt_apex_speed = reference.apex.min_speed_kmh
        opt_decel_g = reference.braking.deceleration_g
        opt_lateral_g = reference.apex.max_lateral_g
        ref_throttle_gap = reference.exit.throttle_point_dist_m - reference.apex.apex_dist_m
    else:
        # No reference - use absolute scoring with vehicle-class defaults
        opt_entry = corner.entry_speed_kmh
        opt_exit = corner.exit.exit_speed_kmh
        opt_brake = corner.braking.brake_point_dist_m
        opt_apex_speed = corner.apex.min_speed_kmh
        opt_decel_g = None  # Will use vehicle class default
        opt_lateral_g = vehicle_config["lateral_g"]
        ref_throttle_gap = None  # Will use absolute scoring

    # Compute component scores
    components = ComponentScores()

    # Speed factors
    components.scores["entry_speed"] = _entry_speed_score(
        corner.entry_speed_kmh, opt_entry
    )

    components.scores["apex_speed"] = _apex_speed_score(
        corner.apex.min_speed_kmh, opt_apex_speed
    )

    components.scores["exit_speed"] = _exit_speed_score(
        corner.exit.exit_speed_kmh, opt_exit
    )

    # Braking factors
    components.scores["brake_point"] = _brake_point_score(
        corner.braking.brake_point_dist_m, opt_brake
    )

    components.scores["braking_intensity"] = _braking_intensity_score(
        corner.braking.deceleration_g,
        optimal_g=opt_decel_g,
        vehicle_class=vehicle_class,
    )

    components.scores["brake_release"] = _brake_release_score(
        corner.exit.coast_time_s
    )

    # Technique factors
    components.scores["trail_brake"] = _trail_brake_score(
        corner.trail_brake.quality_r_squared,
        corner.trail_brake.brake_while_turning,
        corner_requires_braking=corner_requires_braking,
    )

    throttle_gap = corner.exit.throttle_point_dist_m - corner.apex.apex_dist_m
    components.scores["throttle_point"] = _throttle_point_score(
        throttle_gap,
        reference_gap_m=ref_throttle_gap,
    )

    # Wheelspin scoring - use medium severity as default when detected
    # (without duration data, assume moderate severity)
    components.scores["traction_control"] = _traction_control_score(
        corner.exit.rear_wheelspin,
        wheelspin_severity=0.5,  # Default to medium severity
    )

    # Precision factors
    components.scores["line"] = _line_score(corner.apex.lateral_offset_m)

    components.scores["lateral_g_utilization"] = _lateral_g_score(
        corner.apex.max_lateral_g, opt_lateral_g
    )

    # Store features for debugging
    features = {
        "entry_speed_kmh": corner.entry_speed_kmh,
        "apex_speed_kmh": corner.apex.min_speed_kmh,
        "exit_speed_kmh": corner.exit.exit_speed_kmh,
        "brake_point_m": corner.braking.brake_point_dist_m,
        "deceleration_g": corner.braking.deceleration_g,
        "coast_time_s": corner.exit.coast_time_s,
        "trail_brake_r2": corner.trail_brake.quality_r_squared,
        "throttle_gap_m": throttle_gap,
        "rear_wheelspin": corner.exit.rear_wheelspin,
        "lateral_offset_m": corner.apex.lateral_offset_m,
        "max_lateral_g": corner.apex.max_lateral_g,
        "time_in_corner_s": corner.time_in_corner_s,
        "requires_braking": corner_requires_braking,
        "vehicle_class": vehicle_class,
    }

    # Weighted sum
    total_score = sum(
        w.get(k, 0) * v for k, v in components.scores.items()
    )

    # Normalize by total weight (in case weights don't sum to 1)
    total_weight = sum(w.get(k, 0) for k in components.scores)
    if total_weight > 0:
        total_score /= total_weight

    # Find weakest component
    main_issue, main_issue_score = components.weakest()

    return SegmentScore(
        segment_id=corner.segment.segment_id,
        segment_type="corner",
        lap_number=corner.lap_number,
        score=round(total_score, 3),
        quality=_score_to_quality(total_score),
        components=components,
        main_issue=main_issue,
        main_issue_score=round(main_issue_score, 3),
        features=features,
    )


def score_straight(
    straight: StraightAnalysis,
    reference: StraightAnalysis | None = None,
    weights: dict[str, float] | None = None,
) -> SegmentScore:
    """
    Score a straight pass against an optimal reference.

    Args:
        straight: The straight analysis to score
        reference: Optional reference (fast lap) straight for comparison
        weights: Optional custom weights (defaults to STRAIGHT_WEIGHTS)

    Returns:
        SegmentScore with overall score, components, and diagnostics
    """
    w = weights or STRAIGHT_WEIGHTS

    # Extract optimal values
    if reference:
        opt_entry = reference.entry_speed_kmh
        opt_exit = reference.exit_speed_kmh
        opt_top = reference.top_speed_kmh
    else:
        opt_entry = straight.entry_speed_kmh
        opt_exit = straight.exit_speed_kmh
        opt_top = straight.top_speed_kmh

    # Expected throttle percentage based on straight length
    length_factor = min(straight.segment.length_m / 400.0, 1.0)
    expected_throttle = min(60.0 + length_factor * 30.0, 90.0)

    # Expected acceleration (adjusted for speed)
    avg_speed = (straight.entry_speed_kmh + straight.top_speed_kmh) / 2.0
    if avg_speed > 150:
        drag_penalty = (avg_speed - 150) / 200.0
    else:
        drag_penalty = 0.0
    expected_accel = max(0.35 - drag_penalty, 0.15)

    # Compute component scores
    components = ComponentScores()

    components.scores["entry_speed"] = _entry_speed_score(
        straight.entry_speed_kmh, opt_entry
    )

    components.scores["exit_speed"] = _exit_speed_score(
        straight.exit_speed_kmh, opt_exit
    )

    components.scores["top_speed"] = _top_speed_score(
        straight.top_speed_kmh, opt_top
    )

    components.scores["throttle_pct"] = _throttle_pct_score(
        straight.time_at_full_throttle_pct, expected_throttle
    )

    components.scores["acceleration"] = _acceleration_score(
        straight.max_acceleration_g, expected_accel
    )

    # Store features
    features = {
        "entry_speed_kmh": straight.entry_speed_kmh,
        "exit_speed_kmh": straight.exit_speed_kmh,
        "top_speed_kmh": straight.top_speed_kmh,
        "throttle_pct": straight.time_at_full_throttle_pct,
        "max_accel_g": straight.max_acceleration_g,
        "length_m": straight.segment.length_m,
        "gear_shifts": straight.gear_shifts,
    }

    # Weighted sum
    total_score = sum(
        w.get(k, 0) * v for k, v in components.scores.items()
    )

    total_weight = sum(w.get(k, 0) for k in components.scores)
    if total_weight > 0:
        total_score /= total_weight

    main_issue, main_issue_score = components.weakest()

    return SegmentScore(
        segment_id=straight.segment.segment_id,
        segment_type="straight",
        lap_number=straight.lap_number,
        score=round(total_score, 3),
        quality=_score_to_quality(total_score),
        components=components,
        main_issue=main_issue,
        main_issue_score=round(main_issue_score, 3),
        features=features,
    )


def score_lap(
    corners: list[CornerAnalysis],
    straights: list[StraightAnalysis],
    ref_corners: list[CornerAnalysis] | None = None,
    ref_straights: list[StraightAnalysis] | None = None,
    vehicle_class: str = DEFAULT_VEHICLE_CLASS,
) -> tuple[float, list[SegmentScore]]:
    """
    Score an entire lap.

    Args:
        corners: List of corner analyses for this lap
        straights: List of straight analyses for this lap
        ref_corners: Optional reference corners (from fast lap)
        ref_straights: Optional reference straights (from fast lap)
        vehicle_class: Vehicle class for G-force thresholds

    Returns:
        Tuple of (overall_lap_score, list_of_segment_scores)
    """
    # Build reference lookup
    ref_corner_map = {}
    ref_straight_map = {}

    if ref_corners:
        ref_corner_map = {c.segment.segment_id: c for c in ref_corners}
    if ref_straights:
        ref_straight_map = {s.segment.segment_id: s for s in ref_straights}

    segment_scores: list[SegmentScore] = []

    # Score corners
    for corner in corners:
        ref = ref_corner_map.get(corner.segment.segment_id)
        segment_scores.append(score_corner(corner, ref, vehicle_class=vehicle_class))

    # Score straights
    for straight in straights:
        ref = ref_straight_map.get(straight.segment.segment_id)
        segment_scores.append(score_straight(straight, ref))

    # Overall lap score: weighted by segment importance
    # Corners weighted more than straights (where technique matters more)
    if not segment_scores:
        return (0.0, [])

    corner_scores = [s.score for s in segment_scores if s.segment_type == "corner"]
    straight_scores = [s.score for s in segment_scores if s.segment_type == "straight"]

    corner_avg = sum(corner_scores) / len(corner_scores) if corner_scores else 0.0
    straight_avg = sum(straight_scores) / len(straight_scores) if straight_scores else 0.0

    # 70% corners, 30% straights
    if corner_scores and straight_scores:
        lap_score = 0.7 * corner_avg + 0.3 * straight_avg
    elif corner_scores:
        lap_score = corner_avg
    else:
        lap_score = straight_avg

    return (round(lap_score, 3), segment_scores)


def segment_score_to_dict(score: SegmentScore) -> dict:
    """Serialize a SegmentScore to JSON-compatible dict."""
    return {
        "segment_id": score.segment_id,
        "segment_type": score.segment_type,
        "lap_number": score.lap_number,
        "score": score.score,
        "quality": score.quality,
        "main_issue": score.main_issue,
        "main_issue_score": score.main_issue_score,
        "components": {k: round(v, 3) for k, v in score.components.scores.items()},
        "features": {k: round(v, 3) if isinstance(v, float) else v
                     for k, v in score.features.items()},
    }
