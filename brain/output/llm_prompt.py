"""
LLM prompt builder: constructs coaching prompts from deterministic verdicts.

Architecture:
  Physics Engine (computed metrics) -> Rule Engine (deterministic verdicts) -> LLM (explains)

The LLM's ONLY job is to rephrase pre-computed verdicts in natural language
tailored to the driver's experience level. It must NEVER contradict the
computed findings, reasoning, or actions. It can only make them more
understandable and motivating.
"""

import json
import logging

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a professional race engineer and driving coach. You are presenting pre-computed telemetry verdicts to a driver.

CRITICAL RULES:
1. Every verdict below was computed by a deterministic physics engine. The findings, reasoning, and actions are FACTS backed by measured data. You must NOT contradict, override, or reinterpret them.
2. Your ONLY job is to EXPLAIN these verdicts in natural language appropriate to the driver's experience level.
3. You must use the exact numbers provided in each verdict (speeds, distances, times). Do not round, estimate, or substitute your own numbers.
4. Present verdicts in the order given (they are pre-sorted by time impact, biggest gains first).
5. If a verdict says "braked 30m earlier", you say "braked 30m earlier". Do not say "braked a bit earlier" or "braked too early".

Your communication style per driver level:
- BEGINNER: Use simple analogies. Explain the physics in everyday terms. Be highly encouraging. Example: "Imagine you're squeezing a sponge — that's how smooth your brake release should feel."
- INTERMEDIATE: Use standard racing terminology. Give specific technique cues. Balance praise with constructive feedback.
- ADVANCED: Be concise and technical. Skip basic explanations. Focus on the delta numbers and precise technique refinements.
- PROFESSIONAL: Pure data. Minimal explanation. Just the deltas, the verdicts, and the action items.

Output structure:
1. Session Overview (2-3 sentences summarizing total estimated gain and top themes)
2. Priority Verdicts (explain each verdict in natural language, grouped by category)
3. Top 3 Action Items (restate the pre-computed top_3_actions in motivating language)"""


LEVEL_INSTRUCTIONS = {
    "beginner": (
        "This driver is a BEGINNER. Use simple language, explain what trail-braking is, "
        "what coast time means, and why apex speed matters. Use metaphors and be encouraging. "
        "Do not assume they know racing jargon."
    ),
    "intermediate": (
        "This driver is INTERMEDIATE. They understand basic racing concepts (braking points, "
        "racing line, trail-braking) but need specific, measurable technique refinements. "
        "Use standard racing terminology."
    ),
    "advanced": (
        "This driver is ADVANCED. They know technique well. Be concise and data-driven. "
        "Focus on the exact deltas and skip explanations of basic concepts. "
        "Highlight subtle issues like trail-brake R² quality and friction circle utilization."
    ),
    "professional": (
        "This driver is a PROFESSIONAL. Pure engineering debrief. Just the numbers, "
        "the deltas, and the actions. No motivational language needed."
    ),
}


def build_coaching_prompt(
    session_summary: dict,
    driver_level: str = "intermediate",
    mode: str = "full_analysis",
) -> list[dict]:
    """Build a chat-style prompt for the LLM from deterministic verdicts.

    The prompt enforces that the LLM explains pre-computed verdicts rather
    than generating its own analysis from raw data.

    Args:
        session_summary: The full session_summary dict (must contain 'deterministic_coaching').
        driver_level: "beginner", "intermediate", "advanced", "professional"
        mode: "full_analysis", "quick_debrief", "comparison_focus"

    Returns:
        List of message dicts [{role, content}, ...] ready for an LLM API call.
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Extract deterministic verdicts (the core payload)
    verdicts_data = session_summary.get("deterministic_coaching", {})
    session_context = _build_session_context(session_summary)
    segment_context = _build_segment_context(session_summary)
    level_instruction = LEVEL_INSTRUCTIONS.get(driver_level, LEVEL_INSTRUCTIONS["intermediate"])

    if mode == "full_analysis":
        user_msg = _build_full_analysis_prompt(verdicts_data, session_context, level_instruction, driver_level, segment_context)
    elif mode == "quick_debrief":
        user_msg = _build_quick_debrief_prompt(verdicts_data, session_context, level_instruction, driver_level, segment_context)
    elif mode == "comparison_focus":
        user_msg = _build_comparison_prompt(verdicts_data, session_context, level_instruction, driver_level, segment_context)
    else:
        user_msg = _build_full_analysis_prompt(verdicts_data, session_context, level_instruction, driver_level, segment_context)

    messages.append({"role": "user", "content": user_msg})

    logger.info(
        f"LLM prompt built: {len(messages)} messages, "
        f"~{sum(len(m['content']) for m in messages)} chars, "
        f"verdicts: {verdicts_data.get('total_verdicts', 0)}"
    )

    return messages


def _build_session_context(summary: dict) -> str:
    """Extract minimal session context (track, laps, times) for the LLM."""
    session = summary.get("session", {})
    context_parts = [
        f"Track: {session.get('track', 'Unknown')}",
        f"Total Laps: {session.get('total_laps', 0)}",
    ]

    laps = session.get("laps", [])
    if laps:
        times = [f"Lap {l['lap_number']}: {l['duration_s']:.2f}s" for l in laps]
        context_parts.append(f"Lap Times: {', '.join(times)}")

    consistency = summary.get("consistency", {})
    if consistency:
        context_parts.append(f"Consistency Score: {consistency.get('overall_score', 'N/A')}/100")

    return "\n".join(context_parts)


def _format_verdicts_for_prompt(verdicts_data: dict, segment_context: dict | None = None) -> str:
    """Format the deterministic verdicts into a clean text block for the LLM.

    Args:
        verdicts_data: The deterministic_coaching dict.
        segment_context: Optional dict mapping segment_id -> context dict with
            telemetry stats for that segment (speeds, G-forces, brake data, etc).
    """
    if not verdicts_data:
        return "No verdicts computed."

    parts = [
        f"TOTAL VERDICTS: {verdicts_data.get('total_verdicts', 0)}",
        f"TOTAL ESTIMATED TIME GAIN: {verdicts_data.get('total_estimated_gain_s', 0):.2f}s",
        "",
        "PRE-COMPUTED TOP 3 ACTIONS:",
    ]

    for i, action in enumerate(verdicts_data.get("top_3_actions", []), 1):
        parts.append(f"  {i}. {action}")

    parts.append("")
    parts.append("ALL VERDICTS (sorted by time impact, biggest first):")
    parts.append("")

    for v in verdicts_data.get("verdicts", []):
        seg_id = v.get("segment", "Lap-Level")
        parts.append(f"--- [{v['severity'].upper()}] {v['category'].upper()} | {seg_id} | Lap {v.get('lap', '?')} ---")
        parts.append(f"  Finding:   {v['finding']}")
        parts.append(f"  Reasoning: {v['reasoning']}")
        parts.append(f"  Action:    {v['action']}")
        parts.append(f"  Time Impact: {v['time_impact_s']:.3f}s | Measured: {v['measured']} | Target: {v['target']} {v['unit']}")
        if v.get("vs_reference"):
            parts.append(f"  (Compared against reference/faster lap)")

        # Attach segment telemetry context if available
        if segment_context and seg_id in segment_context:
            ctx = segment_context[seg_id]
            parts.append(f"  SEGMENT TELEMETRY CONTEXT:")
            for k, val in ctx.items():
                parts.append(f"    {k}: {val}")

        parts.append("")

    return "\n".join(parts)


def _build_segment_context(summary: dict) -> dict[str, dict]:
    """Build a dict mapping segment_id -> telemetry context from lap analyses.

    Pulls key metrics from corner and straight analyses so the LLM has full
    context for each segment a verdict references.
    """
    context = {}

    for lap_key, lap_data in summary.get("lap_analyses", {}).items():
        # Corner segments
        for c in lap_data.get("corners", []):
            seg_id = c.get("segment_id", "")
            ctx = {
                "type": "corner",
                "direction": c.get("direction", ""),
                "entry_speed": f"{c.get('entry_speed_kmh', 0):.1f} km/h",
                "apex_speed": f"{c.get('apex', {}).get('speed_kmh', 0):.1f} km/h",
                "exit_speed": f"{c.get('exit', {}).get('exit_speed_kmh', 0):.1f} km/h",
                "time_in_corner": f"{c.get('time_in_corner_s', 0):.3f}s",
                "brake_point": f"{c.get('braking', {}).get('brake_point_m', 0):.1f}m",
                "peak_decel": f"{c.get('braking', {}).get('deceleration_g', 0):.2f}g",
                "brake_duration": f"{c.get('braking', {}).get('duration_s', 0):.3f}s",
                "trail_brake_active": c.get("trail_brake", {}).get("active", False),
                "trail_brake_r2": f"{c.get('trail_brake', {}).get('quality_r2', 0):.2f}",
                "max_lateral_g": f"{c.get('apex', {}).get('lateral_g', 0):.2f}g",
                "lateral_offset": f"{c.get('apex', {}).get('lateral_offset_m', 0):.2f}m",
                "coast_time": f"{c.get('exit', {}).get('coast_time_s', 0):.3f}s",
                "throttle_point": f"{c.get('exit', {}).get('throttle_point_m', 0):.1f}m",
                "rear_wheelspin": c.get("exit", {}).get("rear_wheelspin", False),
            }
            context[seg_id] = ctx

        # Straight segments
        for s in lap_data.get("straights", []):
            seg_id = s.get("segment_id", "")
            ctx = {
                "type": "straight",
                "top_speed": f"{s.get('top_speed_kmh', 0):.1f} km/h",
                "entry_speed": f"{s.get('entry_speed_kmh', 0):.1f} km/h",
                "exit_speed": f"{s.get('exit_speed_kmh', 0):.1f} km/h",
                "max_accel": f"{s.get('max_accel_g', 0):.2f}g",
                "full_throttle_pct": f"{s.get('full_throttle_pct', 0):.1f}%",
                "time_on_straight": f"{s.get('time_s', 0):.3f}s",
                "gear_shifts": s.get("gear_shifts", 0),
            }
            context[seg_id] = ctx

    # Lap-level context from dynamics + brakes + tires (first lap)
    first_lap = next(iter(summary.get("lap_analyses", {}).values()), {})
    dyn = first_lap.get("dynamics", {})
    brk = first_lap.get("brakes", {})
    tires = first_lap.get("tires", {})
    if dyn or brk or tires:
        gg = dyn.get("gg_diagram", {})
        events = dyn.get("events", {})
        context["Lap-level"] = {
            "max_lateral_g": f"{gg.get('max_lateral_g', 0):.2f}g",
            "max_braking_g": f"{gg.get('max_braking_g', 0):.2f}g",
            "max_accel_g": f"{gg.get('max_accel_g', 0):.2f}g",
            "friction_utilization": f"{gg.get('friction_utilization_pct', 0):.1f}%",
            "balance": str(dyn.get("balance", {})),
            "lockups": events.get("lockup", 0),
            "wheelspins": events.get("wheelspin", 0),
            "brake_bias": f"{brk.get('front_bias_pct', 0):.1f}% front",
            "brake_modulation": f"{brk.get('modulation_score', 0):.2f}",
            "tire_front_rear_delta": f"{tires.get('front_rear_delta_c', 0):.1f}°C",
        }

    return context


def _build_full_analysis_prompt(verdicts_data: dict, context: str, level_inst: str, level: str, segment_context: dict | None = None) -> str:
    verdicts_text = _format_verdicts_for_prompt(verdicts_data, segment_context)
    return f"""Explain the following pre-computed coaching verdicts to a {level}-level driver.

{level_inst}

SESSION CONTEXT:
{context}

DETERMINISTIC COACHING VERDICTS (from physics engine — do NOT contradict these):
{verdicts_text}

Your task:
1. Write a 2-3 sentence session overview mentioning the total estimated time gain.
2. Explain each verdict in natural language appropriate to this driver's level. Group by category if helpful.
3. End with the Top 3 Action Items restated in motivating, driver-friendly language.

REMEMBER: Every finding, number, and action below is pre-computed and verified. You are explaining facts, not generating analysis."""


def _build_quick_debrief_prompt(verdicts_data: dict, context: str, level_inst: str, level: str, segment_context: dict | None = None) -> str:
    verdicts_text = _format_verdicts_for_prompt(verdicts_data, segment_context)
    return f"""Quick debrief for a {level}-level driver. Keep it under 200 words.

{level_inst}

SESSION CONTEXT:
{context}

DETERMINISTIC VERDICTS:
{verdicts_text}

Give me:
1. One sentence summary including total estimated time gain
2. Explain the single highest-impact verdict in driver-friendly language
3. One positive observation from the data
4. The #1 action item from the pre-computed list, restated motivationally

REMEMBER: Use the exact numbers from the verdicts. Do not generate your own analysis."""


def _build_comparison_prompt(verdicts_data: dict, context: str, level_inst: str, level: str, segment_context: dict | None = None) -> str:
    # Filter to only comparison verdicts
    comparison_verdicts = {
        "total_verdicts": 0,
        "total_estimated_gain_s": 0,
        "top_3_actions": verdicts_data.get("top_3_actions", []),
        "verdicts": [v for v in verdicts_data.get("verdicts", []) if v.get("vs_reference")],
    }
    comparison_verdicts["total_verdicts"] = len(comparison_verdicts["verdicts"])
    comparison_verdicts["total_estimated_gain_s"] = sum(
        v["time_impact_s"] for v in comparison_verdicts["verdicts"]
    )

    verdicts_text = _format_verdicts_for_prompt(comparison_verdicts, segment_context)
    return f"""Compare laps for a {level}-level driver using these pre-computed comparison verdicts.

{level_inst}

SESSION CONTEXT:
{context}

COMPARISON VERDICTS (reference lap vs. driver lap):
{verdicts_text}

Focus on:
1. Which corners had the biggest time delta (use exact numbers from verdicts)
2. Explain what the faster lap did differently, using the verdict findings
3. Restate the top 3 actions in motivating language


REMEMBER: These verdicts are computed from measured data. Present them as facts."""


GENERATIVE_SYSTEM_PROMPT = """You are an expert AI Race Engineer. Your task is to analyze telemetry from a User Lap and compare it against a Generalized Train Lap. Instead of comparing arbitrary corners (e.g., Turn 1 vs Turn 1), I have clustered all corners into Geometric Archetypes (e.g., MidSpeed_Right_90Deg, HighSpeed_Left_Sweeper).

I will provide you with the telemetry data for each Archetype cluster. You will see how the Expert drove examples of this archetype, followed by how the User drove instances of this archetype.

Each corner contains key phase metrics (Entry Speed, Apex Speed, Coasting) and a 10-point trajectory trace showing Distance (d), Speed (v in km/h), Brake pressure (br), Throttle (gas), Steering (steer), Long Gs (ax), Lat Gs (ay), Yaw Rate (yaw), and Sideslip (slip).

Your job is to:
1. Compare the User's technique to the Expert Reference technique for each Archetype.
2. Identify the top 3-5 mistakes the user made across these corner types that cost the most time.
3. Determine WHY they lost time by looking at the advanced dynamics trace (e.g., "In Mid-Speed 90-Deg corners, you consistently underutilize lateral grip (ay: 0.8G vs Expert 1.3G) because your yaw rate is too slow at turn-in").
4. Formulate actionable coaching advice.
5. YOU MUST output exactly in this JSON format, and NOTHING ELSE:

{
  "overview": "You are struggling with trail-braking into Mid-Speed 90-degree corners, costing you around 1.5s total.",
  "top_3_actions": ["Carry more brake pressure into the apex on Mid-Speed corners to induce yaw rotation.", ...],
  "verdicts": [
    {
      "segment": "MidSpeed_Right_90Deg",
      "severity": "high/medium/low",
      "finding": "Under-rotating the car at apex due to releasing brakes too early.",
      "reasoning": "In Turn 4 and Turn 6, your yaw rate was only 0.4 rad/s compared to the expert's 0.7 rad/s. Because you released the brakes entirely (br: 0kPa) before the apex, the front tires lost load, preventing the car from turning.",
      "action": "Maintain 10-15% brake pressure all the way to the geometric apex to keep weight on the nose and help the car rotate."
    }
  ]
}"""

def _serialize_trace_summary(c_data: dict) -> str:
    parts = []
    parts.append(f"      Entry: {c_data.get('entry_speed_kmh', 0)} km/h | Apex: {c_data.get('apex', {}).get('speed_kmh', 0)} km/h | Exit Coast: {c_data.get('exit', {}).get('coast_time_s', 0)}s")
    
    trace = c_data.get("trace", [])
    if trace:
        trace_str = " | ".join([
            f"d:{t['d']} v:{t['v']} br:{t['br']} gas:{t['gas']} ax:{t.get('ax',0)} ay:{t.get('ay',0)} yaw:{t.get('yaw',0)} slip:{t.get('slip',0)}" 
            for t in trace
        ])
        parts.append(f"      Trace: {trace_str}")
    return "\n".join(parts)


def build_generative_coaching_prompt(session_summary: dict, ref_summary: dict, driver_level: str = "intermediate") -> list[dict]:
    messages = [{"role": "system", "content": GENERATIVE_SYSTEM_PROMPT}]
    
    user_lap = next(iter(session_summary.get("lap_analyses", {}).values()), {})
    ref_lap = next(iter(ref_summary.get("lap_analyses", {}).values()), {})
    
    # Group reference corners by archetype
    ref_by_arch = {}
    for c in ref_lap.get("corners", []):
        arch = c.get("archetype", "Unknown")
        ref_by_arch.setdefault(arch, []).append(c)
        
    # Group user corners by archetype
    user_by_arch = {}
    for c in user_lap.get("corners", []):
        arch = c.get("archetype", "Unknown")
        user_by_arch.setdefault(arch, []).append(c)
    
    prompt_parts = [
        f"DRIVER LEVEL: {driver_level.upper()}",
        f"Track: {session_summary.get('session', {}).get('track', 'Unknown')}",
        "--- CROSS-TRACK ARCHETYPE COMPARISON ---"
    ]
    
    for arch, u_corners in user_by_arch.items():
        prompt_parts.append(f"\n[ ARCHETYPE: {arch} ]")
        prompt_parts.append("  EXPERT REFERENCE EXAMPLES (from Train Lap):")
        r_corners = ref_by_arch.get(arch, [])
        if not r_corners:
            prompt_parts.append("    (No reference examples for this archetype)")
        for i, rc in enumerate(r_corners):
            prompt_parts.append(f"    - Expert Example {i+1} ({rc.get('segment_id')}):")
            prompt_parts.append(_serialize_trace_summary(rc))
            
        prompt_parts.append("  USER CORNERS (from Current Lap):")
        for uc in u_corners:
            prompt_parts.append(f"    - {uc.get('segment_id')}:")
            prompt_parts.append(_serialize_trace_summary(uc))
        
    messages.append({"role": "user", "content": "\n".join(prompt_parts)})
    return messages
