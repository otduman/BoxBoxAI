"""
Deterministic coaching rule engine.

Every coaching recommendation is backed by a concrete, computed verdict BEFORE
the LLM ever sees it. The LLM's job is to explain these verdicts in natural
language — not to generate analysis from raw numbers.

Architecture:
  Physics metrics (computed) -> Rule engine (deterministic verdicts) -> LLM (explains)

Each rule:
  1. Takes concrete metrics as input
  2. Applies a deterministic formula or threshold
  3. Outputs a Verdict with: what happened, why it matters, what to do, and
     the exact computed delta (time/distance/speed) backing it up.

The LLM cannot override or contradict these verdicts. It can only rephrase them.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum

from brain.config import (
    MPS_TO_KMH,
    BRAKE_ON_THRESHOLD_PA,
    get_active_profile,
)
from brain.physics.corner_analyzer import CornerAnalysis
from brain.physics.straight_analyzer import StraightAnalysis
from brain.physics.vehicle_dynamics import VehicleDynamicsAnalysis
from brain.track.segmentation import TrackSegment

logger = logging.getLogger(__name__)


class Severity(str, Enum):
    CRITICAL = "critical"   # Safety or massive time loss (>0.5s per corner)
    HIGH = "high"           # Significant time loss (0.1-0.5s per corner)
    MEDIUM = "medium"       # Moderate improvement opportunity
    LOW = "low"             # Minor refinement


class Category(str, Enum):
    BRAKING = "braking"
    TRAIL_BRAKE = "trail_brake"
    APEX = "apex"
    EXIT = "exit"
    STRAIGHT = "straight"
    DYNAMICS = "dynamics"
    TIRES = "tires"
    BRAKES = "brakes"
    CONSISTENCY = "consistency"


@dataclass
class Verdict:
    """A single, deterministic coaching verdict.

    Every field is computed — nothing here requires LLM interpretation.
    """
    category: Category
    severity: Severity
    segment_id: str                 # Which corner/straight (empty = lap-level)
    lap_number: int

    # The core verdict: what + why + action
    finding: str                    # What happened (factual, with numbers)
    reasoning: str                  # Why it costs time (physics explanation)
    action: str                     # What to do differently (specific, measurable)

    # The math backing it up
    computed_delta_s: float = 0.0   # Estimated time impact (seconds, positive = slower)
    computed_value: float = 0.0     # The measured value
    reference_value: float = 0.0    # The target/reference value
    unit: str = ""                  # Unit of computed_value

    # For comparison mode
    vs_reference: bool = False      # True if this verdict comes from lap comparison

    # For video snippet extraction
    timestamp_s: float = 0.0        # Time in session when the issue occurred (seconds)


@dataclass
class CoachingVerdicts:
    """All deterministic verdicts for a session, ranked by time impact."""
    verdicts: list[Verdict] = field(default_factory=list)
    total_estimated_gain_s: float = 0.0
    top_3_actions: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Rule functions: each returns a list of Verdicts
# ---------------------------------------------------------------------------

def rule_coast_time(corner: CornerAnalysis) -> list[Verdict]:
    """Coast time between brake release and throttle application = dead time.

    Physics: During coast, the car is neither decelerating (using brake grip)
    nor accelerating (using traction). It is just losing speed to drag.
    The time loss depends on the acceleration potential being wasted.
    """
    verdicts = []
    profile = get_active_profile()
    ct = corner.exit.coast_time_s
    if ct <= profile.coast_time_flag_s:
        return verdicts

    # Calculate time loss based on lost acceleration potential
    avg_speed_mps = corner.apex.min_speed_kmh / MPS_TO_KMH
    exit_speed_mps = corner.exit.exit_speed_kmh / MPS_TO_KMH

    if avg_speed_mps <= 0:
        avg_speed_mps = max(exit_speed_mps, 10.0)  # 10 m/s minimum fallback

    if exit_speed_mps > avg_speed_mps:
        # Should be accelerating during this time
        distance_traveled = ct * avg_speed_mps
        # Typical race car acceleration: 2.0 m/s² (conservative)
        potential_exit_speed = avg_speed_mps + (ct * 2.0)
        # Time to cover same distance if accelerating
        time_if_accel = distance_traveled / ((avg_speed_mps + min(potential_exit_speed, exit_speed_mps)) / 2)
        estimated_loss = max(0, ct - time_if_accel)
    else:
        # Already at or near target speed, less critical
        estimated_loss = ct * 0.3

    # Severity thresholds
    SEVERE_MULTIPLIER = 6
    MODERATE_MULTIPLIER = 3
    flag = profile.coast_time_flag_s
    if ct > flag * SEVERE_MULTIPLIER:
        sev = Severity.HIGH
    elif ct > flag * MODERATE_MULTIPLIER:
        sev = Severity.MEDIUM
    else:
        sev = Severity.LOW

    verdicts.append(Verdict(
        category=Category.EXIT,
        severity=sev,
        segment_id=corner.segment.segment_id,
        lap_number=corner.lap_number,
        finding=(
            f"{ct:.2f}s of coasting between brake release and throttle application."
        ),
        reasoning=(
            f"During {ct:.2f}s of coast, the car travels ~{ct * avg_speed_mps:.0f}m "
            f"with no acceleration. With typical race car acceleration (~2 m/s²), "
            f"you could have gained {ct * 2.0 * MPS_TO_KMH:.1f} km/h during this time."
        ),
        action=(
            f"Overlap brake release with throttle application. Target coast time < {profile.coast_time_flag_s:.2f}s. "
            f"As the left foot releases the brake, the right foot should already be "
            f"progressively applying throttle."
        ),
        computed_delta_s=estimated_loss,
        computed_value=ct,
        reference_value=profile.coast_time_flag_s,
        unit="seconds",
    ))
    return verdicts


def rule_trail_brake_missing(corner: CornerAnalysis) -> list[Verdict]:
    """No trail-braking detected = releasing brake fully before turning.

    Physics: Trail-braking transfers weight to the front axle during turn-in,
    increasing front grip. Without it, the car understeers at entry.
    The time cost is both reduced corner entry speed AND a later apex.
    """
    verdicts = []
    # Only flag if there was actual braking (not a flat-out corner)
    if corner.braking.peak_brake_pressure_pa < BRAKE_ON_THRESHOLD_PA:
        return verdicts
    if corner.trail_brake.brake_while_turning:
        return verdicts

    # Estimate time loss based on corner characteristics
    # Heavy braking corners benefit more from trail-braking
    corner_severity = corner.braking.deceleration_g / max(corner.apex.max_lateral_g, 0.5)

    if corner_severity > 1.5:  # Heavy braking corner (hairpin, tight chicane)
        estimated_loss = 0.20
        sev = Severity.HIGH
    elif corner_severity > 0.8:  # Medium corner
        estimated_loss = 0.10
        sev = Severity.HIGH
    else:  # Fast corner
        estimated_loss = 0.05
        sev = Severity.MEDIUM

    verdicts.append(Verdict(
        category=Category.TRAIL_BRAKE,
        severity=sev,
        segment_id=corner.segment.segment_id,
        lap_number=corner.lap_number,
        finding=(
            f"Brake released fully before steering input. No trail-braking detected."
        ),
        reasoning=(
            f"Releasing the brake before turning unloads the front axle at exactly the moment "
            f"you need front grip for turn-in. This forces a slower entry speed or causes "
            f"understeer. Trail-braking keeps weight forward, enabling higher entry speed "
            f"and a tighter line. For this corner (decel/lateral ratio: {corner_severity:.1f}), "
            f"trail-braking typically saves {estimated_loss:.2f}s."
        ),
        action=(
            f"Maintain light brake pressure (20-30% of peak) as you begin steering. "
            f"Progressively release the brake as steering angle increases. "
            f"Target: brake pressure should reach zero at or just past the apex."
        ),
        computed_delta_s=estimated_loss,
        computed_value=0.0,
        reference_value=1.0,
        unit="trail_brake_present",
    ))
    return verdicts


def rule_trail_brake_quality(corner: CornerAnalysis) -> list[Verdict]:
    """Trail-brake release was jerky (low R-squared = inconsistent pressure decay).

    Physics: A smooth, linear brake release maintains predictable weight transfer.
    A jerky release causes sudden load shifts, unsettling the car mid-corner.
    """
    verdicts = []
    tb = corner.trail_brake
    if not tb.brake_while_turning:
        return verdicts
    if tb.duration_s < 0.1:
        return verdicts

    r2 = tb.quality_r_squared
    if r2 >= 0.85:
        return verdicts

    sev = Severity.MEDIUM if r2 < 0.6 else Severity.LOW

    verdicts.append(Verdict(
        category=Category.TRAIL_BRAKE,
        severity=sev,
        segment_id=corner.segment.segment_id,
        lap_number=corner.lap_number,
        finding=(
            f"Trail-brake release quality: R²={r2:.2f} (target: >0.85). "
            f"Brake pressure decay is not smooth."
        ),
        reasoning=(
            f"An R² of {r2:.2f} means the brake release is inconsistent — "
            f"the pressure jumps or plateaus instead of declining linearly. "
            f"This causes abrupt weight transfer changes mid-corner, "
            f"reducing front grip predictability."
        ),
        action=(
            f"Focus on a smooth, progressive brake release through the corner entry. "
            f"Imagine slowly lifting your foot off a feather. "
            f"The brake trace should look like a clean downward ramp."
        ),
        computed_delta_s=0.05,
        computed_value=r2,
        reference_value=0.85,
        unit="R_squared",
    ))
    return verdicts


def rule_late_throttle(corner: CornerAnalysis) -> list[Verdict]:
    """Throttle applied too far past the apex = slow corner exit.

    Physics: Exit speed compounds down the following straight.
    Every 1 km/h lost at corner exit costs ~0.05-0.1s on a typical straight.
    """
    verdicts = []
    apex_dist = corner.apex.apex_dist_m
    throttle_dist = corner.exit.throttle_point_dist_m
    if apex_dist <= 0 or throttle_dist <= 0:
        return verdicts

    gap_m = throttle_dist - apex_dist
    if gap_m <= 10:
        return verdicts

    # Calculate time loss based on speed and lost acceleration
    avg_speed_mps = corner.apex.min_speed_kmh / MPS_TO_KMH
    if avg_speed_mps <= 0:
        # Fallback to exit speed if apex speed is invalid
        avg_speed_mps = max(corner.exit.exit_speed_kmh / MPS_TO_KMH, 10.0)

    # Time spent covering the gap distance
    time_to_cover = gap_m / avg_speed_mps
    # If accelerating, this time would have added speed
    # Typical race car: 2 m/s² acceleration
    lost_speed_gain_kmh = time_to_cover * 2.0 * MPS_TO_KMH
    # Speed loss compounds on next straight (100m reference)
    coast_equiv_s = time_to_cover * 0.5 + (lost_speed_gain_kmh * 0.05)

    sev = Severity.HIGH if gap_m > 30 else Severity.MEDIUM

    verdicts.append(Verdict(
        category=Category.EXIT,
        severity=sev,
        segment_id=corner.segment.segment_id,
        lap_number=corner.lap_number,
        finding=(
            f"Throttle applied {gap_m:.0f}m after the apex "
            f"(apex at {apex_dist:.0f}m, throttle at {throttle_dist:.0f}m)."
        ),
        reasoning=(
            f"The car covers {gap_m:.0f}m between the apex and first throttle application "
            f"without accelerating. This costs approximately {lost_speed_gain_kmh:.1f} km/h "
            f"of exit speed that compounds down the following straight."
        ),
        action=(
            f"Begin progressive throttle application at or slightly before the apex. "
            f"You do not need to wait until the car is fully straight. "
            f"Target: throttle > 10% within 5-10m of the apex."
        ),
        computed_delta_s=coast_equiv_s,
        computed_value=gap_m,
        reference_value=10.0,
        unit="meters_past_apex",
    ))
    return verdicts


def rule_wheelspin_on_exit(corner: CornerAnalysis) -> list[Verdict]:
    """Rear wheelspin on corner exit = too aggressive throttle application.

    Physics: Wheelspin means the rear tires exceeded their traction limit.
    The car accelerates slower (spinning tires have less grip than rolling tires)
    and risks snap oversteer.
    """
    verdicts = []
    if not corner.exit.rear_wheelspin:
        return verdicts

    verdicts.append(Verdict(
        category=Category.EXIT,
        severity=Severity.MEDIUM,
        segment_id=corner.segment.segment_id,
        lap_number=corner.lap_number,
        finding="Rear wheelspin detected on corner exit.",
        reasoning=(
            "The rear tires exceeded their traction limit during acceleration. "
            "Spinning tires generate less forward force than rolling tires, "
            "so the car actually accelerates slower despite more throttle input. "
            "It also risks snap oversteer."
        ),
        action=(
            "Apply throttle more progressively on exit. "
            "Wait until the steering is unwinding before increasing throttle past 50%. "
            "Think: 'unwind the wheel, then add throttle' — not both at once."
        ),
        computed_delta_s=0.1,
        computed_value=1.0,
        reference_value=0.0,
        unit="wheelspin_present",
    ))
    return verdicts


def rule_braking_comparison(
    user_corner: CornerAnalysis,
    ref_corner: CornerAnalysis,
) -> list[Verdict]:
    """Compare brake points between user lap and reference lap.

    Physics: Braking later (closer to the corner) means spending more time
    at high speed on the preceding straight. But braking TOO late means
    overshooting the corner.
    """
    verdicts = []
    user_bp = user_corner.braking.brake_point_dist_m
    ref_bp = ref_corner.braking.brake_point_dist_m
    if user_bp <= 0 or ref_bp <= 0:
        return verdicts

    # Only compare brake points if entry speeds are similar
    entry_speed_delta = abs(user_corner.entry_speed_kmh - ref_corner.entry_speed_kmh)
    if entry_speed_delta > 5:
        # Different entry speeds, can't directly compare brake points
        return verdicts

    delta_m = user_bp - ref_bp  # Positive = user braked earlier
    if abs(delta_m) < 5:
        return verdicts

    # Time estimate: distance / average approach speed
    approach_speed = max(user_corner.entry_speed_kmh, 50) / MPS_TO_KMH
    time_delta = abs(delta_m) / approach_speed

    if delta_m > 0:
        # User braked earlier than reference
        sev = Severity.HIGH if delta_m > 20 else Severity.MEDIUM
        verdicts.append(Verdict(
            category=Category.BRAKING,
            severity=sev,
            segment_id=user_corner.segment.segment_id,
            lap_number=user_corner.lap_number,
            finding=(
                f"Braked {delta_m:.0f}m earlier than the reference lap "
                f"(you: {user_bp:.0f}m, ref: {ref_bp:.0f}m)."
            ),
            reasoning=(
                f"Braking {delta_m:.0f}m earlier means spending {time_delta:.2f}s longer "
                f"at a lower speed on the approach. At {user_corner.entry_speed_kmh:.0f} km/h, "
                f"that is approximately {time_delta:.2f}s of lost time."
            ),
            action=(
                f"Move the brake point {delta_m:.0f}m closer to the corner. "
                f"Do this in increments of 5m per session. "
                f"Use a track-side reference marker to gauge distance."
            ),
            computed_delta_s=time_delta,
            computed_value=delta_m,
            reference_value=0.0,
            unit="meters_early",
            vs_reference=True,
        ))
    else:
        # User braked later — could be good or risky
        delta_m = abs(delta_m)
        # Check if they also had a worse apex speed (braked too late, overshot)
        apex_delta = user_corner.apex.min_speed_kmh - ref_corner.apex.min_speed_kmh
        if apex_delta < -3:
            verdicts.append(Verdict(
                category=Category.BRAKING,
                severity=Severity.MEDIUM,
                segment_id=user_corner.segment.segment_id,
                lap_number=user_corner.lap_number,
                finding=(
                    f"Braked {delta_m:.0f}m later than reference but apex speed "
                    f"was {abs(apex_delta):.1f} km/h slower — likely overshot the braking zone."
                ),
                reasoning=(
                    "Braking later should yield a higher apex speed. A lower apex speed "
                    "with a later brake point suggests the car could not slow down enough, "
                    "forcing a wider, slower line through the corner."
                ),
                action=(
                    f"Move the brake point back {delta_m // 2:.0f}m and focus on "
                    f"brake pressure modulation. Better to brake slightly earlier "
                    f"with a clean trail-brake than to lock up braking too late."
                ),
                computed_delta_s=0.1,
                computed_value=delta_m,
                reference_value=0.0,
                unit="meters_late_overshot",
                vs_reference=True,
            ))

    return verdicts


def rule_apex_speed_comparison(
    user_corner: CornerAnalysis,
    ref_corner: CornerAnalysis,
) -> list[Verdict]:
    """Compare apex speeds between user and reference."""
    verdicts = []
    user_v = user_corner.apex.min_speed_kmh
    ref_v = ref_corner.apex.min_speed_kmh
    if user_v <= 0 or ref_v <= 0:
        return verdicts

    delta = user_v - ref_v  # Negative = user was slower
    if delta >= -2:
        return verdicts

    # Time impact: Lower apex speed → lower exit speed → compounding loss on straight
    # Calculate exit speed delta
    user_exit = user_corner.exit.exit_speed_kmh
    ref_exit = ref_corner.exit.exit_speed_kmh
    exit_delta = user_exit - ref_exit

    # Estimate compounding effect on following straight (100m reference)
    STRAIGHT_REF_LENGTH = 100.0
    if exit_delta < 0:
        # Every 1 km/h exit speed deficit costs ~0.05s per 100m of straight
        time_loss = abs(exit_delta) * STRAIGHT_REF_LENGTH / 100 * 0.05
    else:
        # Apex speed lower but exit speed similar/better - just corner time loss
        corner_len = user_corner.segment.length_m
        if corner_len > 0:
            # Use average speed through corner, not just apex speed
            avg_user = (user_v + user_exit) / 2
            avg_ref = (ref_v + ref_exit) / 2
            if avg_user > 0:
                user_time = corner_len / (avg_user / MPS_TO_KMH)
                ref_time = corner_len / (avg_ref / MPS_TO_KMH)
                time_loss = max(0, user_time - ref_time)
            else:
                time_loss = 0.1
        else:
            time_loss = 0.1

    sev = Severity.HIGH if delta < -8 else Severity.MEDIUM

    verdicts.append(Verdict(
        category=Category.APEX,
        severity=sev,
        segment_id=user_corner.segment.segment_id,
        lap_number=user_corner.lap_number,
        finding=(
            f"Apex speed {abs(delta):.1f} km/h slower than reference "
            f"(you: {user_v:.1f} km/h, ref: {ref_v:.1f} km/h)."
        ),
        reasoning=(
            f"Carrying {abs(delta):.1f} km/h less through the apex results in "
            f"{abs(exit_delta):.1f} km/h exit speed deficit. This compounds down "
            f"the following straight, costing approximately {time_loss:.2f}s."
        ),
        action=(
            f"To increase apex speed by {abs(delta):.0f} km/h: "
            f"(1) Brake later but more precisely, (2) trail-brake deeper into the corner, "
            f"(3) tighten the entry line to carry more speed to the apex."
        ),
        computed_delta_s=time_loss,
        computed_value=user_v,
        reference_value=ref_v,
        unit="km/h",
        vs_reference=True,
    ))
    return verdicts


def rule_dynamics_balance(dynamics: VehicleDynamicsAnalysis) -> list[Verdict]:
    """Flag persistent oversteer or understeer tendency."""
    verdicts = []
    if dynamics.balance_tendency == "neutral":
        return verdicts

    if dynamics.balance_tendency == "oversteer":
        verdicts.append(Verdict(
            category=Category.DYNAMICS,
            severity=Severity.MEDIUM,
            segment_id="",
            lap_number=dynamics.lap_number,
            finding=(
                f"Oversteer tendency: {dynamics.oversteer_count} oversteer events "
                f"vs {dynamics.understeer_count} understeer events."
            ),
            reasoning=(
                "Persistent oversteer suggests the rear axle is losing grip before the front. "
                "This could be a driving style issue (too much throttle mid-corner, "
                "abrupt steering inputs) or a setup issue (rear too stiff, "
                "insufficient rear downforce/grip)."
            ),
            action=(
                "Driving: Smoother throttle application mid-corner. Unwind steering before adding throttle. "
                "Setup: Consider softening the rear anti-roll bar or adding rear downforce."
            ),
            computed_value=float(dynamics.oversteer_count),
            reference_value=float(dynamics.understeer_count),
            unit="event_count",
        ))
    else:
        verdicts.append(Verdict(
            category=Category.DYNAMICS,
            severity=Severity.MEDIUM,
            segment_id="",
            lap_number=dynamics.lap_number,
            finding=(
                f"Understeer tendency: {dynamics.understeer_count} understeer events "
                f"vs {dynamics.oversteer_count} oversteer events."
            ),
            reasoning=(
                "Persistent understeer means the front axle is saturating before the rear. "
                "The car pushes wide in corners. This limits corner entry speed and "
                "forces a later apex, losing time."
            ),
            action=(
                "Driving: More trail-braking to load the front axle. Slower initial steering rate. "
                "Setup: Consider softening the front anti-roll bar or increasing front downforce."
            ),
            computed_value=float(dynamics.understeer_count),
            reference_value=float(dynamics.oversteer_count),
            unit="event_count",
        ))

    return verdicts


# Seconds to skip at start of recording to avoid sensor-settling artifacts
_STARTUP_FILTER_S = 2.0


def rule_lockup(
    dynamics: VehicleDynamicsAnalysis,
    segments: list[TrackSegment],
    lap_start_time: float,
) -> list[Verdict]:
    """Wheel lockup = exceeding tire braking grip.

    Filters out startup artifacts and attributes each lockup event to the
    nearest corner segment via track_dist_m.
    """
    verdicts = []

    # Filter lockup events: remove those in the first N seconds (sensor settling)
    # Only apply filter if we have a valid lap start time
    lockup_events = [
        e for e in dynamics.events
        if e.event_type == "lockup"
        and (lap_start_time == 0.0 or (e.start_time - lap_start_time) >= _STARTUP_FILTER_S)
    ]

    if not lockup_events:
        return verdicts

    # Build segment lookup for attribution
    corner_segments = [s for s in segments if s.segment_type == "corner"]

    # Group lockup events by nearest corner segment
    segment_lockups: dict[str, list] = {}
    unattributed = []
    for event in lockup_events:
        best_seg = _find_nearest_segment(event.track_dist_m, corner_segments)
        if best_seg:
            segment_lockups.setdefault(best_seg.segment_id, []).append(event)
        else:
            unattributed.append(event)

    # Generate per-segment verdicts
    for seg_id, events in segment_lockups.items():
        n = len(events)
        sev = Severity.CRITICAL if n > 3 else Severity.HIGH
        estimated_loss = n * 0.15

        verdicts.append(Verdict(
            category=Category.BRAKES,
            severity=sev,
            segment_id=seg_id,
            lap_number=dynamics.lap_number,
            finding=f"{n} wheel lockup event(s) in braking zone.",
            reasoning=(
                "A locked wheel generates less braking force than a wheel at the slip limit "
                "(~10% slip). Each lockup extends the braking distance by 2-5 meters "
                "and flat-spots the tire, reducing grip for the rest of the session."
            ),
            action=(
                "Reduce initial brake pressure by 5-10% and apply the brake more progressively. "
                "The first 50ms of brake application should not be at maximum pressure. "
                "Squeeze the brake — do not stab it."
            ),
            computed_delta_s=estimated_loss,
            computed_value=float(n),
            reference_value=0.0,
            unit="events",
        ))

    # If there are unattributed events (on straights or transitions),
    # still report them as a single lap-level verdict
    if unattributed:
        n = len(unattributed)
        verdicts.append(Verdict(
            category=Category.BRAKES,
            severity=Severity.HIGH if n > 1 else Severity.MEDIUM,
            segment_id="",
            lap_number=dynamics.lap_number,
            finding=f"{n} wheel lockup event(s) outside corner braking zones.",
            reasoning=(
                "Lockups outside of braking zones may indicate ABS issues, "
                "debris on track, or mid-corner instability."
            ),
            action=(
                "Review brake application technique on entry to straights. "
                "If ABS is not intervening, check brake bias."
            ),
            computed_delta_s=n * 0.1,
            computed_value=float(n),
            reference_value=0.0,
            unit="events",
        ))

    return verdicts


def _find_nearest_segment(
    dist_m: float,
    segments: list[TrackSegment],
    lookback_m: float = 150.0,
) -> TrackSegment | None:
    """Find the corner segment that a track distance falls within/near.

    Includes a lookback to catch lockups in the braking zone before the corner.
    """
    for seg in segments:
        extended_start = seg.start_dist_m - lookback_m
        if extended_start <= dist_m <= seg.end_dist_m:
            return seg
    return None


def rule_friction_utilization(dynamics: VehicleDynamicsAnalysis) -> list[Verdict]:
    """Low friction circle utilization = not using the car's full grip potential.

    Note: 60% is qualifying-pace target. Race pace is typically 55-65%.
    """
    verdicts = []
    util = dynamics.gg_metrics.friction_circle_utilization_pct
    peak_g = dynamics.gg_metrics.peak_combined_g

    # New metric: % of active-grip time spent within 80% of own peak g.
    # A well-driven lap should have 25-40% of corner time near the limit.
    # Below 15% means most corners are well below the car's capability.
    TARGET = 25.0
    if util >= TARGET:
        return verdicts
    if util <= 0 or peak_g <= 0:
        return verdicts

    sev = Severity.MEDIUM if util >= 10 else Severity.HIGH

    # Time impact: proportional to grip deficit fraction, capped at 2% of lap
    grip_deficit_fraction = 1.0 - (util / TARGET) ** 0.5
    estimated_loss = min(
        dynamics.lap_duration_s * 0.12 * grip_deficit_fraction,
        dynamics.lap_duration_s * 0.02,
    )

    verdicts.append(Verdict(
        category=Category.DYNAMICS,
        severity=sev,
        segment_id="",
        lap_number=dynamics.lap_number,
        finding=(
            f"Only {util:.1f}% of cornering time near grip limit "
            f"(peak: {peak_g:.2f}g, target: >{TARGET:.0f}% of corners at ≥80% peak g)."
        ),
        reasoning=(
            f"During corners and braking, the car reaches {peak_g:.2f}g peak, but spends only "
            f"{util:.1f}% of that time above 80% of its own peak. "
            f"This means most corners are being driven well below the car's capability — "
            f"either entry speed is too low, apex is taken too cautiously, or exits are lifted early."
        ),
        action=(
            "Trust the car's grip — it has more than you're using. "
            "Carry more entry speed into corners, hold throttle longer on exit, "
            "and brake later/harder to spend more time near the grip limit."
        ),
        computed_delta_s=estimated_loss,
        computed_value=util,
        reference_value=TARGET,
        unit="percent",
    ))
    return verdicts


def rule_insufficient_acceleration(straight: StraightAnalysis) -> list[Verdict]:
    """Detect when the car is not accelerating properly on straights.

    Skips straights shorter than 150m. Accounts for:
    - Braking zone at end of straight (driver must lift before corner → cap throttle expectation)
    - Aero drag limiting acceleration at high speed (lower g expectation above 150 km/h)
    - Realistic time-loss estimation using v = v0 + a*t physics
    """
    verdicts = []

    if straight.segment.length_m < 150.0 or straight.time_on_straight_s < 1.5:
        return verdicts

    # ── Throttle check ──
    # Cap at 90%: the last ~10% of a straight is typically lift-and-brake zone
    length_factor = min(straight.segment.length_m / 400.0, 1.0)
    expected_throttle = min(60.0 + length_factor * 30.0, 90.0)

    throttle_deficit = expected_throttle - straight.time_at_full_throttle_pct
    # Require at least 3% gap — filters measurement noise and marginal cases
    if throttle_deficit >= 3.0:
        # Physics: partial throttle means less acceleration over time
        # lost_accel ≈ deficit_fraction × typical_accel_potential (0.4g ≈ 3.9 m/s²)
        # avg_speed_deficit = lost_accel × time / 2  (linear build-up)
        # time_loss ≈ distance × avg_speed_deficit / avg_speed²
        avg_speed_mps = (straight.entry_speed_kmh + straight.top_speed_kmh) / 2.0 / 3.6
        lost_accel = (throttle_deficit / 100.0) * 3.9  # m/s²
        avg_v_deficit = lost_accel * straight.time_on_straight_s / 2.0
        estimated_loss = straight.segment.length_m * avg_v_deficit / max(avg_speed_mps ** 2, 100)

        sev = Severity.MEDIUM if throttle_deficit > 15 else Severity.LOW

        verdicts.append(Verdict(
            category=Category.STRAIGHT,
            severity=sev,
            segment_id=straight.segment.segment_id,
            lap_number=straight.lap_number,
            finding=(
                f"Only {straight.time_at_full_throttle_pct:.0f}% of straight at full throttle "
                f"(expected >{expected_throttle:.0f}% for {straight.segment.length_m:.0f}m straight)."
            ),
            reasoning=(
                f"On a {straight.segment.length_m:.0f}m straight entered at "
                f"{straight.entry_speed_kmh:.0f} km/h, the car spent "
                f"{100 - straight.time_at_full_throttle_pct:.0f}% of the distance with partial "
                f"throttle, losing potential acceleration time."
            ),
            action=(
                "Get on full throttle earlier after corner exit and hold it longer "
                "before the braking zone. Only lift for gear changes or traction issues."
            ),
            computed_delta_s=estimated_loss,
            computed_value=straight.time_at_full_throttle_pct,
            reference_value=expected_throttle,
            unit="percent",
        ))

    # ── Peak acceleration check ──
    # At high speed aero drag fights hard: expect less g above 150 km/h
    avg_speed = (straight.entry_speed_kmh + straight.top_speed_kmh) / 2.0
    if avg_speed > 150:
        drag_penalty = (avg_speed - 150) / 200.0  # up to ~0.25g reduction at 200 km/h
    else:
        drag_penalty = 0.0
    expected_accel = max(0.3 - drag_penalty, 0.15)

    if straight.max_acceleration_g < expected_accel:
        accel_deficit = expected_accel - straight.max_acceleration_g
        # Same physics: lost_accel = deficit_g * 9.81, then distance * Δv_avg / v²
        avg_speed_mps2 = (straight.entry_speed_kmh + straight.top_speed_kmh) / 2.0 / 3.6
        lost_a = accel_deficit * 9.81
        avg_v_def = lost_a * straight.time_on_straight_s / 2.0
        estimated_loss = straight.segment.length_m * avg_v_def / max(avg_speed_mps2 ** 2, 100)

        sev = Severity.MEDIUM if accel_deficit > 0.1 else Severity.LOW

        verdicts.append(Verdict(
            category=Category.STRAIGHT,
            severity=sev,
            segment_id=straight.segment.segment_id,
            lap_number=straight.lap_number,
            finding=(
                f"Peak acceleration {straight.max_acceleration_g:.2f}g on "
                f"{straight.segment.length_m:.0f}m straight "
                f"(expected >{expected_accel:.2f}g at avg {avg_speed:.0f} km/h)."
            ),
            reasoning=(
                f"At an average speed of {avg_speed:.0f} km/h, the car should still achieve "
                f"at least {expected_accel:.2f}g peak longitudinal acceleration. "
                f"The measured {straight.max_acceleration_g:.2f}g suggests traction limits or "
                f"conservative throttle application."
            ),
            action=(
                "Apply throttle more aggressively at corner exit. If rear wheelspin is the "
                "limiting factor, consider adjusting traction control or throttle mapping."
            ),
            computed_delta_s=estimated_loss,
            computed_value=straight.max_acceleration_g,
            reference_value=expected_accel,
            unit="g",
        ))

    return verdicts


# ---------------------------------------------------------------------------
# Master orchestrator
# ---------------------------------------------------------------------------

def compute_all_verdicts(
    corner_analyses: dict[int, list[CornerAnalysis]],
    straight_analyses: dict[int, list[StraightAnalysis]],
    dynamics_analyses: dict[int, VehicleDynamicsAnalysis],
    segments: list[TrackSegment] | None = None,
    lap_start_times: dict[int, float] | None = None,
    ref_corners: list[CornerAnalysis] | None = None,
) -> CoachingVerdicts:
    """Run all deterministic rules and produce ranked verdicts.

    Args:
        ref_corners: If provided, corner analyses from the reference (faster) lap
                     for comparison verdicts.
    """
    all_verdicts: list[Verdict] = []

    # Build reference corner lookup
    ref_map = {}
    if ref_corners:
        ref_map = {c.segment.segment_id: c for c in ref_corners}

    # Build segment-to-timestamp map for verdict timestamping
    # Key: (lap_number, segment_id) -> start_time_s
    segment_timestamps: dict[tuple[int, str], float] = {}
    for lap_num, corners in corner_analyses.items():
        for ca in corners:
            segment_timestamps[(lap_num, ca.segment.segment_id)] = ca.start_time_s
    for lap_num, straights in straight_analyses.items():
        for sa in straights:
            segment_timestamps[(lap_num, sa.segment.segment_id)] = sa.start_time_s

    def _add_verdicts_with_timestamp(verdicts: list[Verdict], timestamp: float):
        """Add verdicts with timestamp assigned."""
        for v in verdicts:
            v.timestamp_s = timestamp
        all_verdicts.extend(verdicts)

    # Per-corner rules
    for lap_num, corners in corner_analyses.items():
        for ca in corners:
            ts = ca.start_time_s
            _add_verdicts_with_timestamp(rule_coast_time(ca), ts)
            _add_verdicts_with_timestamp(rule_trail_brake_missing(ca), ts)
            _add_verdicts_with_timestamp(rule_trail_brake_quality(ca), ts)
            _add_verdicts_with_timestamp(rule_late_throttle(ca), ts)
            _add_verdicts_with_timestamp(rule_wheelspin_on_exit(ca), ts)

            # Comparison rules
            ref = ref_map.get(ca.segment.segment_id)
            if ref:
                _add_verdicts_with_timestamp(rule_braking_comparison(ca, ref), ts)
                _add_verdicts_with_timestamp(rule_apex_speed_comparison(ca, ref), ts)

    # Per-straight rules
    for lap_num, straights in straight_analyses.items():
        for sa in straights:
            ts = sa.start_time_s
            _add_verdicts_with_timestamp(rule_insufficient_acceleration(sa), ts)

    # Per-lap dynamics rules (use lap start time as timestamp)
    segs = segments or []
    start_times = lap_start_times or {}
    for lap_num, da in dynamics_analyses.items():
        ts = start_times.get(lap_num, 0.0)
        _add_verdicts_with_timestamp(rule_dynamics_balance(da), ts)
        _add_verdicts_with_timestamp(rule_lockup(da, segs, ts), ts)
        _add_verdicts_with_timestamp(rule_friction_utilization(da), ts)

    # Sort by estimated time impact (biggest gains first), then severity
    all_verdicts.sort(key=lambda v: (-v.computed_delta_s, v.severity.value))

    # Compute totals
    total_gain = sum(v.computed_delta_s for v in all_verdicts)

    # Top 3 actions: prioritize high-impact verdicts, include segment ID for specificity
    # Don't deduplicate - if Turn 1 and Turn 3 both have critical braking issues, show both
    top_3 = []
    for v in all_verdicts:
        if v.computed_delta_s > 0.05 or v.severity in (Severity.CRITICAL, Severity.HIGH):
            action_with_context = v.action
            if v.segment_id:
                action_with_context = f"[{v.segment_id}] {v.action}"
            top_3.append(action_with_context)
            if len(top_3) == 3:
                break

    # Limit to max_verdicts from profile (autonomous=20, human=5)
    profile = get_active_profile()
    capped_verdicts = all_verdicts[:profile.max_verdicts]

    result = CoachingVerdicts(
        verdicts=capped_verdicts,
        total_estimated_gain_s=total_gain,
        top_3_actions=top_3,
    )

    logger.info(
        f"Coaching verdicts: {len(all_verdicts)} total, "
        f"estimated gain: {total_gain:.2f}s, "
        f"top categories: {[v.category.value for v in all_verdicts[:5]]}"
    )

    return result


def verdicts_to_dict(cv: CoachingVerdicts) -> dict:
    """Serialize verdicts for JSON output."""
    return {
        "total_verdicts": len(cv.verdicts),
        "total_estimated_gain_s": round(cv.total_estimated_gain_s, 2),
        "top_3_actions": cv.top_3_actions,
        "verdicts": [
            {
                "category": v.category.value,
                "severity": v.severity.value,
                "segment": v.segment_id,
                "lap": v.lap_number,
                "finding": v.finding,
                "reasoning": v.reasoning,
                "action": v.action,
                "time_impact_s": round(v.computed_delta_s, 3),
                "measured": round(v.computed_value, 3),
                "target": round(v.reference_value, 3),
                "unit": v.unit,
                "vs_reference": v.vs_reference,
                "timestamp_s": round(v.timestamp_s, 2),
            }
            for v in cv.verdicts
        ],
    }
