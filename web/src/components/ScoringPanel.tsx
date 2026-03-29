import { motion } from "framer-motion";
import { ChevronDown, ChevronUp, Target, TrendingUp, AlertTriangle } from "lucide-react";
import { useState } from "react";
import { Tooltip } from "./Tooltip";

interface SegmentScore {
  segment_id: string;
  segment_type: "corner" | "straight";
  score: number;
  quality: "optimal" | "good" | "average" | "poor";
  main_issue: string;
  main_issue_score: number;
  components: Record<string, number>;
  features: Record<string, number | boolean>;
}

interface LapScoreData {
  lap_score: number;
  segment_scores: SegmentScore[];
}

interface ScoringData {
  lap_scores: Record<string, LapScoreData>;
  track_reference?: {
    theoretical_best_s: number;
    best_lap_time_s: number;
  };
}

interface ScoringPanelProps {
  scoring: ScoringData;
  selectedLap?: number | "all";
}

const qualityColors: Record<string, string> = {
  optimal: "text-sector-green",
  good: "text-[#22c55e]",
  average: "text-[#eab308]",
  poor: "text-racing-red",
};

const qualityBgColors: Record<string, string> = {
  optimal: "bg-sector-green/20",
  good: "bg-[#22c55e]/20",
  average: "bg-[#eab308]/20",
  poor: "bg-racing-red/20",
};

// Human-readable labels for component scores (maps to glossary terms)
const componentLabels: Record<string, { label: string; term: string }> = {
  entry_speed: { label: "Entry Speed", term: "entry speed" },
  apex_speed: { label: "Apex Speed", term: "apex speed" },
  exit_speed: { label: "Exit Speed", term: "exit speed" },
  brake_point: { label: "Brake Point", term: "brake point" },
  braking_intensity: { label: "Braking G", term: "braking intensity" },
  brake_release: { label: "Brake Release", term: "brake release" },
  trail_brake: { label: "Trail Brake", term: "trail-braking" },
  throttle_point: { label: "Throttle Point", term: "throttle point" },
  traction_control: { label: "Traction", term: "traction control" },
  line: { label: "Racing Line", term: "racing line" },
  lateral_g_utilization: { label: "Lateral G", term: "lateral G" },
  top_speed: { label: "Top Speed", term: "top speed" },
  throttle_pct: { label: "Throttle %", term: "throttle" },
  acceleration: { label: "Acceleration", term: "acceleration" },
};

const ScoringPanel = ({ scoring, selectedLap = "all" }: ScoringPanelProps) => {
  const [expandedSegment, setExpandedSegment] = useState<string | null>(null);

  // Get the lap data to display
  const lapKey = selectedLap === "all" ? Object.keys(scoring.lap_scores)[0] : String(selectedLap);
  const lapData = scoring.lap_scores[lapKey];

  if (!lapData) return null;

  const { lap_score, segment_scores } = lapData;

  // Separate corners and straights
  const corners = segment_scores.filter((s) => s.segment_type === "corner");
  const straights = segment_scores.filter((s) => s.segment_type === "straight");

  // Find weakest segments
  const weakestCorner = corners.reduce((a, b) => (a.score < b.score ? a : b), corners[0]);
  const weakestStraight = straights.reduce((a, b) => (a.score < b.score ? a : b), straights[0]);

  const getScoreColor = (score: number) => {
    if (score >= 0.85) return "text-sector-green";
    if (score >= 0.70) return "text-[#22c55e]";
    if (score >= 0.50) return "text-[#eab308]";
    return "text-racing-red";
  };

  const getScoreBarColor = (score: number) => {
    if (score >= 0.85) return "bg-sector-green";
    if (score >= 0.70) return "bg-[#22c55e]";
    if (score >= 0.50) return "bg-[#eab308]";
    return "bg-racing-red";
  };

  return (
    <div className="glass-panel p-3 space-y-3">
      {/* Header with overall score */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Target className="w-4 h-4 text-muted-foreground" />
          <p className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
            Performance Score
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`font-mono text-2xl font-bold ${getScoreColor(lap_score)}`}>
            {(lap_score * 100).toFixed(0)}
          </span>
          <span className="text-xs text-muted-foreground">/100</span>
        </div>
      </div>

      {/* Score breakdown bar */}
      <div className="space-y-1.5">
        <div className="flex justify-between text-[10px] text-muted-foreground">
          <span>Corners ({corners.length})</span>
          <span>Straights ({straights.length})</span>
        </div>
        <div className="h-2 bg-foreground/10 rounded-full overflow-hidden flex">
          {segment_scores.map((seg, i) => (
            <motion.div
              key={seg.segment_id}
              className={`h-full ${getScoreBarColor(seg.score)} opacity-80`}
              initial={{ width: 0 }}
              animate={{ width: `${100 / segment_scores.length}%` }}
              transition={{ duration: 0.4, delay: i * 0.03 }}
              title={`${seg.segment_id}: ${(seg.score * 100).toFixed(0)}%`}
            />
          ))}
        </div>
      </div>

      {/* Quick insights */}
      <div className="grid grid-cols-2 gap-2 pt-1">
        {weakestCorner && (
          <div className="bg-foreground/5 rounded-lg p-2">
            <div className="flex items-center gap-1.5 mb-1">
              <AlertTriangle className="w-3 h-3 text-[#eab308]" />
              <span className="text-[9px] uppercase tracking-wider text-muted-foreground">
                Focus Corner
              </span>
            </div>
            <p className="text-xs font-medium truncate">{weakestCorner.segment_id}</p>
            <p className="text-[10px] text-muted-foreground">
              Issue: <Tooltip term={componentLabels[weakestCorner.main_issue]?.term || weakestCorner.main_issue}>
                {componentLabels[weakestCorner.main_issue]?.label || weakestCorner.main_issue}
              </Tooltip>
            </p>
          </div>
        )}
        {weakestStraight && (
          <div className="bg-foreground/5 rounded-lg p-2">
            <div className="flex items-center gap-1.5 mb-1">
              <TrendingUp className="w-3 h-3 text-[#eab308]" />
              <span className="text-[9px] uppercase tracking-wider text-muted-foreground">
                Focus Straight
              </span>
            </div>
            <p className="text-xs font-medium truncate">{weakestStraight.segment_id}</p>
            <p className="text-[10px] text-muted-foreground">
              Issue: <Tooltip term={componentLabels[weakestStraight.main_issue]?.term || weakestStraight.main_issue}>
                {componentLabels[weakestStraight.main_issue]?.label || weakestStraight.main_issue}
              </Tooltip>
            </p>
          </div>
        )}
      </div>

      {/* Segment details */}
      <div className="space-y-1.5 pt-2 border-t border-border">
        <p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-2">
          Segment Breakdown
        </p>
        {segment_scores.map((seg) => {
          const isExpanded = expandedSegment === seg.segment_id;
          return (
            <div key={seg.segment_id} className="space-y-1">
              <button
                onClick={() => setExpandedSegment(isExpanded ? null : seg.segment_id)}
                className="w-full flex items-center gap-2 hover:bg-foreground/5 rounded-md px-1.5 py-1 transition-colors"
              >
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    seg.segment_type === "corner" ? "bg-racing-red" : "bg-sector-green"
                  }`}
                />
                <span className="text-xs flex-1 text-left truncate">{seg.segment_id}</span>
                <span
                  className={`text-[10px] px-1.5 py-0.5 rounded ${qualityBgColors[seg.quality]} ${qualityColors[seg.quality]}`}
                >
                  {seg.quality}
                </span>
                <span className={`font-mono text-xs font-semibold ${getScoreColor(seg.score)}`}>
                  {(seg.score * 100).toFixed(0)}
                </span>
                {isExpanded ? (
                  <ChevronUp className="w-3 h-3 text-muted-foreground" />
                ) : (
                  <ChevronDown className="w-3 h-3 text-muted-foreground" />
                )}
              </button>

              {/* Expanded component details */}
              {isExpanded && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  className="ml-4 pl-2 border-l border-border space-y-1 pb-2"
                >
                  {Object.entries(seg.components).map(([key, value]) => (
                    <div key={key} className="flex items-center gap-2">
                      <span className="text-[10px] text-muted-foreground w-24 truncate">
                        <Tooltip term={componentLabels[key]?.term || key} showIcon={false}>
                          {componentLabels[key]?.label || key}
                        </Tooltip>
                      </span>
                      <div className="flex-1 h-1 bg-foreground/10 rounded-full overflow-hidden">
                        <motion.div
                          className={`h-full rounded-full ${getScoreBarColor(value)}`}
                          initial={{ width: 0 }}
                          animate={{ width: `${value * 100}%` }}
                          transition={{ duration: 0.3 }}
                        />
                      </div>
                      <span
                        className={`font-mono text-[10px] w-8 text-right ${getScoreColor(value)}`}
                      >
                        {(value * 100).toFixed(0)}
                      </span>
                    </div>
                  ))}

                  {/* Key features */}
                  <div className="pt-1.5 mt-1.5 border-t border-border/50">
                    <p className="text-[9px] uppercase tracking-wider text-muted-foreground mb-1">
                      Key Metrics
                    </p>
                    <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[10px]">
                      {seg.segment_type === "corner" ? (
                        <>
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Entry</span>
                            <span className="font-mono">
                              {(seg.features.entry_speed_kmh as number)?.toFixed(0)} km/h
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Apex</span>
                            <span className="font-mono">
                              {(seg.features.apex_speed_kmh as number)?.toFixed(0)} km/h
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Exit</span>
                            <span className="font-mono">
                              {(seg.features.exit_speed_kmh as number)?.toFixed(0)} km/h
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Lateral G</span>
                            <span className="font-mono">
                              {(seg.features.max_lateral_g as number)?.toFixed(2)}G
                            </span>
                          </div>
                        </>
                      ) : (
                        <>
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Entry</span>
                            <span className="font-mono">
                              {(seg.features.entry_speed_kmh as number)?.toFixed(0)} km/h
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Top Speed</span>
                            <span className="font-mono">
                              {(seg.features.top_speed_kmh as number)?.toFixed(0)} km/h
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Throttle</span>
                            <span className="font-mono">
                              {(seg.features.throttle_pct as number)?.toFixed(0)}%
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Length</span>
                            <span className="font-mono">
                              {(seg.features.length_m as number)?.toFixed(0)}m
                            </span>
                          </div>
                        </>
                      )}
                    </div>
                  </div>
                </motion.div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default ScoringPanel;
