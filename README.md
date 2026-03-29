# Pocket Race Engineer
### AI-Powered Telemetry Coaching — Constructor GenAI Hackathon 2026

Upload a `.mcap` telemetry file from any racing car on any circuit. Get corner-by-corner coaching backed by physics in under 60 seconds.

---

## Completed Tasks

1. ~~Look into what parameters out of all topics (e.g. speed, position, angular position, track dim., etc) we support are necessary in standard segment for context to LLM.~~
2. ~~Divide insights into deterministic (optional) and fully genai insights for better UX.~~
3. ~~Make a unified solution to accept .mcap data file and output visualized insights (currently: we have to parse and then upload to visualizer)~~
4. ~~Use Pandas Dataframe for intermediate data storage instead of separate Json file~~
5. ~~Look into multiple laps visualization and insights support~~
6. ~~Cover the business usecase in UI~~

---

## How It Works

### Architecture Overview

```
MCAP telemetry file
      │
      ▼
brain/main.py  ←── CLI or FastAPI server (brain/server.py)
      │
      ├── extract/mcap_reader.py        Read selected topics → dict of DataFrames
      ├── extract/topic_registry.py     Topic + field definitions (StateEstimation primary)
      │
      ├── track/boundaries.py           Load boundary JSON → compute centerline + curvature
      ├── track/segmentation.py         Curvature threshold → Turn_1/Straight_1/... segments
      │
      ├── physics/lap_splitter.py       Detect lap boundaries from lap_number or sn_idx wraparound
      ├── physics/corner_analyzer.py    4-phase corner decomposition per corner per lap
      ├── physics/straight_analyzer.py  Top speed, acceleration profile, gear shifts
      ├── physics/vehicle_dynamics.py   Oversteer/understeer, g-g diagram, friction utilization
      ├── physics/tire_analyzer.py      Surface temp gradients, degradation trends
      ├── physics/brake_analyzer.py     Front/rear bias, modulation quality
      ├── physics/consistency.py        Lap-to-lap segment variation
      ├── physics/coaching_rules.py     Rule engine: physics findings → actionable verdicts
      │
      ├── output/json_builder.py        Assemble session_summary.json + viz_data.json
      └── output/llm_prompt.py          Build Claude prompt for generative coaching insights
                                                 │
                                                 ▼
                                        Claude API (claude-sonnet-4-6)
                                        → generative_coaching in session_summary
```

### Data Flow

1. **MCAP Read** — The reader loads only ~15 of 40+ topics (skipping cameras/TF/GPS). `StateEstimation` at 100 Hz is the primary source: it contains fused position `(x_m, y_m)`, velocity `v_mps`, accelerations `(ax, ay)`, steering `psa_actual_pos_rad`, throttle `gas`, brake pressures per wheel, slip ratios, slip angles, sideslip `beta_rad`, gear, RPM, and track projection `(sn_idx, sn_n)`. All channels are downsampled and aligned to a 50 Hz master DataFrame via `merge_asof`.

2. **Track Geometry** — The boundary JSON `{boundaries: {left_border: [[x,y],...], right_border: [[x,y],...]}}`  is loaded, both borders are re-parameterized to the same arc-length grid, and their midpoint is the centerline. Curvature is computed via a Savitzky-Golay smoothed discrete formula and thresholded to detect corners vs. straights. Segments are auto-numbered: `Turn_1`, `Straight_1`, etc. No hardcoded track knowledge — this works on any circuit.

3. **Lap Splitting** — Laps are detected from the `lap_number` field in `BadeniaMisc`. Fallback: `sn_idx` wraparound (track distance resets to 0 at start/finish).

4. **Corner Analysis (4 phases per corner)**
   - **Phase A — Braking**: sum of per-wheel brake pressures > 500 kPa; ends when throttle rises or brake drops below 50% of peak
   - **Phase B — Trail-brake**: brake still declining while steering is increasing; quality scored as R² of linear pressure decay
   - **Phase C — Apex**: minimum speed within the corner segment + closest lateral offset to inside edge
   - **Phase D — Exit**: from apex, throttle > 10% while steering returns toward 0; checks for rear wheelspin (`lambda_rl/rr > 8%` sustained for ≥ 60 ms)

5. **Physics Verdicts** — `coaching_rules.py` converts physics findings into verdicts with severity (low/medium/high/critical), estimated time impact in seconds, and telemetry-backed evidence. Thresholds are physics-based (g-forces, slip ratios, pressures), not track-specific. Key calibrations based on actual AV-24 telemetry distributions:
   - Wheelspin threshold: 8.0% slip ratio (p99 of normal operation = 7.79%)
   - Lockup threshold: −5.0% slip ratio (braking easily reaches −4.8% without locking)
   - Minimum event duration: 60 ms (3 samples at 50 Hz filters transient noise)

6. **Friction Circle Utilization** — Measures driver skill, not track geometry. Only samples where combined g-force ≥ 30% of lap peak are considered "active grip" phases. The metric is the fraction of those active samples that reach ≥ 80% of the lap peak g. A skilled driver maximizes grip usage in every corner; a novice leaves the friction circle half-empty.

7. **Generative Coaching** — The session summary JSON is injected into a structured prompt sent to Claude. The LLM acts as a race engineer and produces: an overview paragraph, top 3 actionable recommendations, and deeper insights that go beyond what rule-based analysis can capture (e.g. driving style patterns, setup implications).

8. **Visualization** — `viz_data.json` contains the car's trajectory as a polyline plus a list of verdict markers (each with track position, severity, telemetry values). The React frontend renders an interactive canvas map using principal component analysis (PCA) to auto-rotate the track for optimal screen fit. Verdict markers are snapped to the nearest point on the actual car trajectory.

### API Upload Mode

```bash
# Start the server
cd brain && uvicorn server:app --reload --port 8000

# The frontend dev proxy forwards /api → localhost:8000
# Drop an MCAP file in the UI → POST /api/analyze → full pipeline runs server-side → JSON response
```

The pipeline completes in ~25 seconds on a 1 GB MCAP file (cameras and TF topics are skipped entirely — they make up the bulk of file size but contain no driving data).

### Multi-Lap Sessions

When the MCAP contains multiple laps, the UI shows a lap selector in the header. Each lap has its own `lap_analyses` entry in the summary. The track map shows all laps' verdict markers by default; selecting a specific lap filters markers to that lap and updates the coaching panels.

### Track-Agnostic Design

Nothing in the Brain is specific to Yas Marina or the AV-24 car. To analyze a new track:
- Provide a boundary JSON in the standard format
- Provide MCAP telemetry recorded on that track
- Zero code changes required

Car-class presets (GT3, Formula, Karting) are planned for future threshold tuning, but the algorithms are identical across all classes.

---

## Running Locally

```bash
# Backend
cd brain
pip install -r requirements.txt
python -m brain.main driving-data/hackathon_good_lap.mcap --boundaries driving-data/yas_marina_bnd.json

# Frontend
cd web
npm install
npm run dev
```

Set `ANTHROPIC_API_KEY` in `.env` to enable generative coaching. Without it, the AI Coach panel is hidden and only physics analysis is shown.

---

## Roadmap

- **Wheel-to-wheel comparison** — Overlay two drivers' telemetry aligned by track distance. Requires two MCAP files (or two cars' data streams in one file). Shows per-corner brake point delta, apex speed delta, and time delta.
- **Video overlay** — Sync onboard camera with telemetry markers for visual reference
- **Mobile app** — PWA wrapper around the existing React frontend
- **Setup recommendations** — Use tire temperature gradients and understeer/oversteer balance to recommend suspension changes
