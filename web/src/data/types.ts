// ── Types matching our Python backend output ──

// viz_data.json
export interface VizData {
  track: {
    centerline: [number, number][];
    left_border: [number, number][];
    right_border: [number, number][];
    total_length_m: number;
  };
  segments: VizSegment[];
  markers: VizMarker[];
  car_trajectory?: [number, number][];
  mcap_file?: string;  // Original MCAP filename for video extraction
}

export interface VizSegment {
  id: string;
  type: "corner" | "straight";
  direction: "left" | "right" | "straight";
  start: [number, number];
  end: [number, number];
  apex: [number, number];
  start_m: number;
  end_m: number;
  length_m: number;
}

export interface VizMarker {
  x: number;
  y: number;
  segment: string;
  lap?: number;
  category: string;
  severity: "high" | "medium" | "low" | "critical";
  finding: string;
  reasoning: string;
  action: string;
  time_impact_s: number;
  measured?: number;
  target?: number;
  unit?: string;
  timestamp_s?: number;  // Time in session when the issue occurred (seconds)
}

// session_summary.json
export interface SessionSummary {
  session: {
    track: string;
    source_file: string;
    total_laps: number;
    laps: number[];
  };
  track_layout: {
    total_corners: number;
    total_straights: number;
    segments: Array<{
      id: string;
      type: string;
      direction: string;
      length_m: number;
    }>;
  };
  lap_analyses: Record<string, LapAnalysis>;
  coaching_highlights: CoachingHighlight[];
  deterministic_coaching: {
    total_verdicts: number;
    total_estimated_gain_s: number;
    top_3_actions: string[];
    verdicts: Verdict[];
  };
  generative_coaching?: {
    overview: string;
    top_3_actions: string[];
    verdicts: Verdict[];
  };
}

export interface LapAnalysis {
  lap_number: number;
  duration_s: number;
  corners: CornerAnalysis[];
  straights: StraightAnalysis[];
  dynamics: {
    gg_diagram: {
      max_lateral_g: number;
      max_braking_g: number;
      max_accel_g: number;
      friction_utilization_pct: number;
    };
    balance: Record<string, unknown>;
    events: {
      oversteer: number;
      understeer: number;
      lockup: number;
      wheelspin: number;
    };
  };
  tires: {
    wheels: Record<string, unknown>;
    front_rear_delta_c: number;
    left_right_delta_c: number;
    warnings: string[];
  };
  brakes: {
    front_bias_pct: number;
    lr_imbalance_pct: number;
    zone_count: number;
    modulation_score: number;
    brake_time_pct: number;
  };
}

export interface CornerAnalysis {
  segment_id: string;
  direction: string;
  entry_speed_kmh: number;
  time_in_corner_s: number;
  braking: {
    brake_point_m: number;
    peak_pressure_pa: number;
    deceleration_g: number;
    duration_s: number;
  };
  trail_brake: {
    active: boolean;
    quality_r2: number;
    duration_s: number;
  };
  apex: {
    speed_kmh: number;
    lateral_g: number;
    lateral_offset_m: number;
    sideslip_rad: number;
    distance_m: number;
  };
  exit: {
    throttle_point_m: number;
    exit_speed_kmh: number;
    coast_time_s: number;
    rear_wheelspin: boolean;
  };
}

export interface StraightAnalysis {
  segment_id: string;
  top_speed_kmh: number;
  entry_speed_kmh: number;
  exit_speed_kmh: number;
  max_accel_g: number;
  full_throttle_pct: number;
  gear_shifts: number;
  time_s: number;
}

export interface CoachingHighlight {
  type: string;
  priority: string;
  lap?: number;
  segment?: string;
  message: string;
}

export interface Verdict {
  category: string;
  severity: "high" | "medium" | "low" | "critical";
  segment: string;
  lap: number;
  finding: string;
  reasoning: string;
  action: string;
  time_impact_s: number;
  measured: number | string | null;
  target: number | string | null;
  unit: string | null;
  vs_reference: string | null;
}
