![BoxBox.AI](web/public/logo.png)
# BoxBox.AI -Pocket Race Engineer 
### AI Race Coaching from Raw Telemetry
**Constructor GenAI Hackathon 2026**

---

## The Problem We're Solving

If you've ever driven on a track and felt like you *should* be faster but had no idea where you were losing time — that's the gap we're closing.

Drivers generate enormous amounts of telemetry data. The problem is that telemetry tools were built for engineers, not drivers. You can open a graph showing your brake pressure over time, but unless you already know what good brake pressure looks like, the graph tells you nothing. Meanwhile, a real race engineer sitting beside you could look at that same data and immediately say: *"You're braking 15 meters too late into Turn 4 — the car's unstable on entry and you're bleeding two tenths every lap."*

That kind of coaching doesn't scale. Most drivers — even competitive amateurs — don't have access to it. **BoxBox.AI is our answer to that.**

---

## What It Does

Upload a `.mcap` telemetry file. Get back a full coaching session: what you're doing well, where you're losing time, and exactly what to change. Then ask follow-up questions.

> "Why am I slow in Turn 3?"  
> "What is trail braking and am I doing it?"  
> "Which corner should I focus on first?"

The AI responds like a coach who's actually looked at your data — because it has.

---

## How It Actually Works

We didn't want to build a chatbot that hallucinates driving advice. So before Gemini ever says a word, a deterministic physics pipeline has already done all the real analysis. The AI's job is to *explain* findings, not *invent* them.

Here's how we process a lap from raw data to coaching:

### Step 1 — Understand the Track

We reconstruct the track geometry from boundary data and use curvature analysis to automatically detect corners versus straights. No hardcoded track knowledge. The system figures out the layout on its own, which means it generalizes to any circuit.

### Step 2 — Break Each Corner Into Phases

Racing isn't just "go fast." Each corner has a structure, and mistakes happen in specific phases:

1. **Braking** — when and how hard you hit the brakes
2. **Trail Braking** — whether you smoothly release brake pressure while turning in
3. **Apex** — how much speed you carry through the tightest point
4. **Exit** — how early and cleanly you get back on throttle

By segmenting corners this way, we can pinpoint *where* in a corner a driver is losing time and *why*.

### Step 3 — Measure Physics, Not Vibes

We compute real signals from the telemetry:

- Grip usage via the friction circle
- Tire slip ratios (detecting wheelspin and lockups)
- Brake pressure modulation quality
- Steering input vs. lateral force balance

This tells us how well the car is actually being driven, using physics — not gut feel.

### Step 4 — Run the Coaching Rule Engine

A rule engine converts all of that physics data into structured insights. Things like:

- *"Braking too late → unstable entry"*
- *"Low apex speed → missed grip potential"*
- *"Early throttle + high slip → wheelspin killing exit speed"*

Each verdict comes with a severity rating, an estimated time loss, and the raw telemetry that backs it up. This is the deterministic layer — trustworthy, repeatable, not made up.

### Step 5 — Let Gemini Explain It Like a Human

Finally, we pass those structured insights to Gemini. The AI generates natural language explanations tailored to the driver's level (beginner / intermediate / advanced) and powers the interactive chat. This is where understanding actually happens — the physics tells us what's wrong, Gemini helps the driver genuinely get it.

---

## Key Features

**AI Race Engineer Chat**  
Ask anything about your session in plain language. Gemini keeps responses grounded in your actual telemetry data, not generic driving theory.

**Interactive Verdict Cards with Video Snippets**  
When you click on a mistake in the analysis view, you get a video frame from that exact moment in the lap overlaid with AI-generated coaching. The system extracts the precise frame from the MCAP video at the moment the error occurred and provides context-specific advice like "What happened" and "What to do."

**Pro Lap Comparison**  
See exactly where you're losing time relative to a fast reference lap, broken down corner by corner with braking and throttle overlays.

**Physics-Based Insights**  
Friction circle utilization, slip ratios, brake modulation quality, understeer/oversteer detection — all computed from first principles, not heuristics.

**Interactive Track Map (React + TypeScript)**  
Visual front-end with track maps, insight markers (clickable for video clips), lap selection, comparison overlays, and an integrated AI chat panel.

**Zero Setup Input**  
Drop in one `.mcap` file and you're off. Custom track boundary JSON is optional — it defaults to Yas Marina.

---

### Verdict Categories

The system automatically detects and flags these categories of mistakes:

| Category | What It Measures |
|----------|------------------|
| **Braking** | Brake point (too early/late), brake pressure modulation |
| **Trail Brake** | Smoothness of brake release while turning in |
| **Apex** | Speed at the tightest point of the corner |
| **Exit** | Throttle application timing and smoothness after apex |
| **Straight** | Acceleration efficiency, wheelspin, top speed on straights |
| **Dynamics** | G-force balance, friction circle utilization, oversteer/understeer |
| **Tires** | Temperature gradients, slip ratios, degradation trends |
| **Consistency** | Lap-to-lap variation for the same corner |

Each verdict includes:
- **Finding**: Factual statement of what happened (with numbers)
- **Reasoning**: Why it costs time (physics explanation)
- **Action**: Specific, measurable thing to do differently
- **Time Impact**: Estimated seconds gained if corrected
- **Measured Value**: The actual telemetry reading
- **Target Value**: What good looks like (from reference lap or physics threshold)

---

## 🎬 The Verdict Card & Video Snippet System

When analyzing a lap, each mistake is displayed as an interactive **Verdict Card** in the sidebar. Click on any mistake to:

1. **See the video frame** — Extracts and displays the exact moment the error occurred from the MCAP video (if available)
2. **Get moment-specific coaching** — AI generates "What happened" and "What to do" advice specific to that instant
3. **View the telemetry** — Shows the measured values that triggered the verdict (brake pressure, speed, slip ratio, etc.)
4. **Understand the time cost** — See exactly how many tenths this mistake is costing you per lap

This makes mistakes tangible — instead of just reading "apex speed too low," you see yourself on track, at that exact corner, with the frame overlaid showing what the data meant.

---

## 🏗️ System Architecture

```
MCAP telemetry file
        ↓
Signal extraction & alignment  (brain/extract)
        ↓
Track geometry reconstruction + curvature segmentation
        ↓
Lap detection & boundary splitting
        ↓
Physics analysis — corners, straights, vehicle dynamics
        ↓
Rule-based coaching verdicts
        ↓
Gemini AI explanation + interactive chat  (generative)
        ↓
React frontend visualization
```

---

## Technical Architecture

### Backend — Python

**Extract Layer**
- `extract/mcap_reader.py` — Parses MCAP telemetry, extracts StateEstimation and CAN messages
- `extract/topic_registry.py` — Defines available telemetry topics and fields

**Track Layer**
- `track/boundaries.py` — Loads track geometry, computes centerline and curvature
- `track/segmentation.py` — Automatically detects turns vs. straights via curvature thresholds

**Physics Analysis Layer**
- `physics/lap_splitter.py` — Detects lap boundaries from telemetry
- `physics/corner_analyzer.py` — 4-phase analysis: braking → trail-braking → apex → exit
- `physics/straight_analyzer.py` — Acceleration, top speed, gear shift analysis
- `physics/vehicle_dynamics.py` — G-forces, oversteer/understeer, friction circle utilization
- `physics/tire_analyzer.py` — Tire temperatures, slip ratios, degradation trends
- `physics/brake_analyzer.py` — Brake bias, modulation quality, lock-up detection
- `physics/consistency.py` — Lap-to-lap variation analysis
- `physics/scoring.py` — Segment and lap scoring (0–1 scale)
- `physics/coaching_rules.py` — Rule engine: physics data → actionable verdicts
- `physics/reference_builder.py` — Pro lap analysis and comparison

**Output Layer**
- `output/json_builder.py` — Assembles `session_summary.json`
- `output/track_viz.py` — Generates interactive visualization data (`viz_data.json`)
- `output/llm_prompt.py` — Formats structured insights for Gemini

**Chat Layer**
- `chat_service.py` — Streaming chat interface with **Gemini** (Google)
- Controlled system prompt keeping AI focused on racing topics only
- Full conversation history support

**API Server**
- `server.py` — FastAPI REST API with CORS support
- `main.py` — Main CLI orchestrator for the full pipeline

### Frontend — React + TypeScript
- `pages/Analysis.tsx` — Main analysis interface with panels and 3D track
- `components/Track3D.tsx` — 3D track visualization with markers
- `components/VerdictCard.tsx` — Interactive verdict cards with expandable details
- `components/VideoSnippet.tsx` — Video frame extraction and moment coaching
- `components/CoachPanel.tsx` — Physics verdict summary
- `components/DynamicsPanel.tsx` — G-g diagram and force visualization
- `components/ScoringPanel.tsx` — Segment scoring breakdown
- `components/ChatPanel.tsx` — AI coach chat interface

---

## Setup & Running Locally

### Prerequisites

- **Python 3.14+**
- **Node.js 18+**
- **Google Gemini API key** (free at https://aistudio.google.com/apikey)

### Driver Profiles

The system adapts to different driving contexts via configurable driver profiles (set in `brain/config.py`):

- **autonomous** — lower sensitivity thresholds, suited for autonomous racing vehicles
- **human** — higher sensitivity thresholds, adapted for human drivers

Profiles control lockup detection thresholds, wheelspin detection, minimum anomaly event duration, and coast detection behavior.

---

### Backend Setup

```bash
# Navigate to brain directory
cd brain

# Install dependencies
pip install -r requirements.txt
```

Set your Gemini API key. Create a `.env` file in the project root:

```env
GEMINI_API_KEY=your_api_key_here
```

Or export it in your terminal:

```bash
# macOS/Linux
export GEMINI_API_KEY="your_api_key_here"

# Windows PowerShell
$env:GEMINI_API_KEY="your_api_key_here"
```

Start the backend server:

```bash
cd ..
uvicorn brain.server:app --reload --port 8000
```

API available at `http://localhost:8000`

---

### Frontend Setup

```bash
cd web
npm install
npm run dev
```

Frontend available at `http://localhost:8080`

---

## Performance

- Selective topic parsing skips non-driving data for speed
- Streaming responses on the chat endpoint for snappy UX
- Time-series alignment via Pandas & NumPy

---

## ⚠️ Important Notes & Limitations

### Video Snippet Feature
The **video snippet feature** requires that your MCAP file contains encoded video data (camera topics like `sensor_fusion/camera_front`). If your MCAP file only contains telemetry (CAN bus, GPS, IMU), the video frame endpoints will return an error. This is expected — the rest of the analysis (verdicts, comparison, physics) will work perfectly.

### Gemini API Prerequisites
- **Gemini** (Google) is used exclusively for the AI coach
- Chat features require `GEMINI_API_KEY` environment variable
- The AI is constrained to racing/coaching topics via system prompt
- If API key is not set, `/api/chat` returns a 503 (unavailable) response  

### Performance Considerations
- Subsequent requests use cached JSON data (much faster)
- Video frame extraction is real-time but depends on MCAP encoding quality
- Streaming chat responses arrive in chunks for better UX

---

## Why We Built It This Way

A lot of AI tools in motorsport try to do everything with a large language model. We made a deliberate choice not to do that.

The physics analysis is entirely deterministic. The rule engine runs on hard thresholds grounded in vehicle dynamics theory, not vibes or training data. We use Gemini for exactly one thing: turning trustworthy, structured findings into language a driver can actually understand and act on.

That hybrid design is the core of BoxBox.AI. It's why the coaching is specific rather than generic, why it won't hallucinate that you're understeering when you're oversteering, and why every insight can be traced back to real telemetry evidence.

The goal was never to replace race engineers. It was to make that quality of feedback available to every driver who's ever wanted to know: *what exactly am I doing wrong, and what do I fix first?*

---

## Vision

> "A race engineer in your pocket — for every driver, at every level."

From club racers who can't afford a data engineer, to sim drivers trying to learn real technique, to competitive amateurs who generate data but don't know what to do with it — BoxBox.AI makes professional-grade feedback accessible, scalable, and actually understandable.

We're not just showing you data. We're turning it into improvement.
