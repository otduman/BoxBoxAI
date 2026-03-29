"""
Brain CLI: the main orchestrator that runs the full pipeline.

Usage:
    python -m brain.main <mcap_file> --boundaries <boundary_json> [options]
"""

import argparse
import logging
import time
from pathlib import Path

from brain.extract.mcap_reader import extract_session
from brain.track.boundaries import load_track_boundaries, project_to_centerline
from brain.track.segmentation import detect_segments
from brain.physics.lap_splitter import split_laps, get_lap_data
from brain.physics.corner_analyzer import analyze_all_corners
from brain.physics.straight_analyzer import analyze_all_straights
from brain.physics.vehicle_dynamics import analyze_vehicle_dynamics
from brain.physics.tire_analyzer import analyze_tires, analyze_tire_degradation
from brain.physics.brake_analyzer import analyze_brakes
from brain.physics.consistency import analyze_consistency, compare_laps
from brain.physics.coaching_rules import compute_all_verdicts, verdicts_to_dict
from brain.output.json_builder import build_session_summary, save_session_summary
from brain.output.llm_prompt import build_coaching_prompt
from brain.output.track_viz import export_viz_json

import numpy as np

logger = logging.getLogger("brain")


def run_pipeline(
    mcap_path: str,
    boundary_path: str,
    output_path: str = "session_summary.json",
    primary_only: bool = False,
    driver_level: str = "intermediate",
    driver_profile: str = "autonomous",
    reference_path: str | None = None,
) -> dict:
    """Run the full Brain pipeline: MCAP -> analysis -> JSON.

    Args:
        mcap_path: Path to .mcap telemetry file.
        boundary_path: Path to track boundary JSON.
        output_path: Where to save session_summary.json.
        primary_only: If True, skip supplementary topics (faster).
        driver_level: For LLM prompt generation.
        driver_profile: "autonomous" or "human" — controls detection thresholds.

    Returns:
        The session summary dict.
    """
    t_start = time.perf_counter()

    # --- Step 0: Set driver profile ---
    from brain.config import set_driver_profile, get_active_profile
    set_driver_profile(driver_profile)
    profile = get_active_profile()
    logger.info(f"Driver profile: {profile.name} (lockup={profile.lockup_lambda_threshold}, "
                f"wheelspin={profile.wheelspin_lambda_threshold}, min_event={profile.min_event_duration_s}s, "
                f"coast_flag={profile.coast_time_flag_s}s)")

    # --- Step 1: Extract telemetry ---
    logger.info("Step 1/6: Extracting telemetry from MCAP...")
    master, raw_dfs = extract_session(mcap_path, primary_only=primary_only)
    t_extract = time.perf_counter()
    logger.info(f"  Extraction: {t_extract - t_start:.1f}s")

    # --- Step 2: Load track geometry ---
    logger.info("Step 2/6: Loading track geometry...")
    track = load_track_boundaries(boundary_path)
    segments = detect_segments(track)
    t_track = time.perf_counter()
    logger.info(f"  Track geometry: {t_track - t_extract:.1f}s")

    # --- Step 3: Project car positions onto centerline ---
    logger.info("Step 3/6: Projecting positions onto track...")
    if "x_m" in master.columns and "y_m" in master.columns:
        xy = master[["x_m", "y_m"]].values
        track_dist, lateral_offset = project_to_centerline(track, xy)
        master["track_dist_m"] = track_dist
        master["lateral_offset_m"] = lateral_offset

        # Remap segment boundaries to match unwrapped track distance.
        # The car may start mid-track (e.g., at 1896m on a 2601m track),
        # so after the start/finish line crossing, distances continue
        # past total_length (e.g., 2601 + 200 = 2801 for a segment
        # originally at 200m). We shift segments that the car reaches
        # AFTER wrapping so their boundaries match the unwrapped values.
        car_start_dist = track_dist[0]
        L = track.total_length
        for seg in segments:
            if seg.start_dist_m < car_start_dist:
                seg.start_dist_m += L
                seg.end_dist_m += L
                seg.apex_dist_m += L
    else:
        logger.warning("No x_m/y_m in data, using sn_idx for track distance")
        if "sn_idx" in master.columns and "sn_ds" in master.columns:
            master["track_dist_m"] = master["sn_idx"].fillna(0) + master["sn_ds"].fillna(0)
        else:
            master["track_dist_m"] = np.arange(len(master), dtype=float)
    t_project = time.perf_counter()
    logger.info(f"  Projection: {t_project - t_track:.1f}s")

    # --- Step 4: Split into laps ---
    logger.info("Step 4/6: Splitting laps...")
    laps = split_laps(master, raw_dfs)
    t_laps = time.perf_counter()
    logger.info(f"  Lap splitting: {t_laps - t_project:.1f}s")

    # --- Step 5: Per-lap analysis ---
    logger.info("Step 5/6: Running physics analysis...")
    corner_analyses = {}
    straight_analyses = {}
    dynamics_analyses = {}
    tire_analyses = {}
    brake_analyses = {}

    for lap in laps:
        ln = lap.lap_number
        lap_df = get_lap_data(master, lap)
        logger.info(f"  Analyzing Lap {ln} ({lap.duration_s:.2f}s, {len(lap_df)} samples)...")

        corner_analyses[ln] = analyze_all_corners(lap_df, segments, ln)
        straight_analyses[ln] = analyze_all_straights(lap_df, segments, ln)
        dynamics_analyses[ln] = analyze_vehicle_dynamics(lap_df, ln)
        tire_analyses[ln] = analyze_tires(lap_df, ln)
        brake_analyses[ln] = analyze_brakes(lap_df, ln)

    # Tire degradation trend
    if len(tire_analyses) > 1:
        degradation = analyze_tire_degradation(list(tire_analyses.values()))
        logger.info(f"  Tire degradation trend: {degradation}")

    # Consistency analysis (needs 2+ laps)
    consistency = None
    if len(laps) >= 2:
        consistency = analyze_consistency(corner_analyses, straight_analyses)
        logger.info(f"  Consistency score: {consistency.overall_consistency_score:.1f}/100")

    # Lap comparison (compare fastest vs slowest)
    comparison_deltas = None
    if len(laps) >= 2:
        fastest = min(laps, key=lambda l: l.duration_s)
        slowest = max(laps, key=lambda l: l.duration_s)
        if fastest.lap_number != slowest.lap_number:
            comparison_deltas = compare_laps(
                corners_a=corner_analyses[fastest.lap_number],
                corners_b=corner_analyses[slowest.lap_number],
                straights_a=straight_analyses[fastest.lap_number],
                straights_b=straight_analyses[slowest.lap_number],
            )
    t_analysis = time.perf_counter()
    logger.info(f"  Physics analysis: {t_analysis - t_laps:.1f}s")

    # --- Step 5b: Deterministic coaching verdicts ---
    logger.info("Step 5b/7: Computing deterministic coaching verdicts...")
    # For comparison: use fastest lap corners as reference if 2+ laps
    ref_corners = None
    if len(laps) >= 2:
        fastest = min(laps, key=lambda l: l.duration_s)
        ref_corners = corner_analyses.get(fastest.lap_number)

    # Build lap start times for startup artifact filtering
    lap_start_times = {lap.lap_number: lap.start_time for lap in laps}

    coaching_verdicts = compute_all_verdicts(
        corner_analyses=corner_analyses,
        straight_analyses=straight_analyses,
        dynamics_analyses=dynamics_analyses,
        segments=segments,
        lap_start_times=lap_start_times,
        ref_corners=ref_corners,
    )
    logger.info(
        f"  {len(coaching_verdicts.verdicts)} verdicts, "
        f"estimated total gain: {coaching_verdicts.total_estimated_gain_s:.2f}s"
    )
    t_verdicts = time.perf_counter()

    # --- Step 6: Build output ---
    logger.info("Step 6/7: Building session summary...")
    track_name = Path(boundary_path).stem.replace("_bnd", "").replace("_", " ").title()
    summary = build_session_summary(
        laps=laps,
        segments=segments,
        corner_analyses=corner_analyses,
        straight_analyses=straight_analyses,
        dynamics_analyses=dynamics_analyses,
        tire_analyses=tire_analyses,
        brake_analyses=brake_analyses,
        consistency=consistency,
        comparison_deltas=comparison_deltas,
        track_name=track_name,
        mcap_file=Path(mcap_path).name,
    )

    # Inject deterministic verdicts into the summary
    summary["deterministic_coaching"] = verdicts_to_dict(coaching_verdicts)

    save_session_summary(summary, output_path, master_df=master)

    # --- Step 7: Build LLM prompt (explains verdicts, does not generate them) ---
    logger.info("Step 7/7: Building LLM prompt...")
    prompt = build_coaching_prompt(summary, driver_level=driver_level)
    prompt_path = Path(output_path).with_suffix(".prompt.json")
    import json
    with open(prompt_path, "w") as f:
        json.dump(prompt, f, indent=2)
    logger.info(f"LLM prompt saved to {prompt_path}")

    # --- Step 7b: Build Generative AI LLM prompt ---
    if reference_path:
        logger.info(f"Step 7b: Building Generative AI prompt using reference {reference_path}...")
        try:
            with open(reference_path, "r") as f:
                ref_summary = json.load(f)
            from brain.output.llm_prompt import build_generative_coaching_prompt
            gen_prompt = build_generative_coaching_prompt(summary, ref_summary, driver_level=driver_level)
            gen_prompt_path = Path(output_path).with_name("generative_coaching.prompt.json")
            with open(gen_prompt_path, "w") as f:
                json.dump(gen_prompt, f, indent=2)
            logger.info(f"Generative LLM prompt saved to {gen_prompt_path}")
            
            # Trigger Live LLM analysis if API key is present
            from brain.llm_client import generate_insights
            insights_path = Path(output_path).with_name("generative_insights.json")
            generate_insights(gen_prompt_path, insights_path)
            
        except Exception as e:
            logger.error(f"Failed to build generative prompt: {e}")

    # --- Step 8: Export track visualization data ---
    logger.info("Step 8: Exporting track visualization data...")
    # Derive viz filename from output: session_summary_fast.json → viz_data_fast.json
    out_stem = Path(output_path).stem  # e.g. "session_summary_fast"
    viz_suffix = out_stem.replace("session_summary", "viz_data") if "session_summary" in out_stem else "viz_data"
    viz_path = Path(output_path).with_name(f"{viz_suffix}.json")
    car_xy = master[["x_m", "y_m"]].values if "x_m" in master.columns else None
    export_viz_json(track, segments, coaching_verdicts, str(viz_path), car_xy=car_xy)

    t_total = time.perf_counter() - t_start
    logger.info(f"Pipeline complete in {t_total:.1f}s")

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Brain: Pocket Race Engineer telemetry analyzer"
    )
    parser.add_argument(
        "mcap_file",
        help="Path to the .mcap telemetry file",
    )
    parser.add_argument(
        "--boundaries", "-b",
        required=True,
        help="Path to track boundary JSON file",
    )
    parser.add_argument(
        "--output", "-o",
        default="session_summary.json",
        help="Output path for session_summary.json (default: session_summary.json)",
    )
    parser.add_argument(
        "--primary-only",
        action="store_true",
        help="Only extract primary topics (faster, less detail)",
    )
    parser.add_argument(
        "--driver-level",
        default="intermediate",
        choices=["beginner", "intermediate", "advanced", "professional"],
        help="Driver experience level for coaching feedback",
    )
    parser.add_argument(
        "--profile", "-p",
        default="autonomous",
        choices=["autonomous", "human"],
        help="Driver profile: 'autonomous' for tight thresholds, 'human' for relaxed (default: autonomous)",
    )
    parser.add_argument(
        "--reference", "-r",
        default=None,
        help="Path to a pre-computed session_summary.json to use as a 'Good Lap' reference for Generative AI coaching",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    run_pipeline(
        mcap_path=args.mcap_file,
        boundary_path=args.boundaries,
        output_path=args.output,
        primary_only=args.primary_only,
        driver_level=args.driver_level,
        driver_profile=args.profile,
        reference_path=args.reference,
    )


if __name__ == "__main__":
    main()
