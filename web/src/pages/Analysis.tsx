import { useState, useEffect, useRef, useMemo } from "react";
import { motion } from "framer-motion";
import { ArrowLeft, Gauge, Loader2, ChevronDown } from "lucide-react";
import { useNavigate } from "react-router-dom";
import Track3D from "@/components/Track3D";
import VerdictCard from "@/components/VerdictCard";
import DynamicsPanel from "@/components/DynamicsPanel";
import CoachPanel from "@/components/CoachPanel";
import ChatPanel from "@/components/ChatPanel";
import ScoringPanel from "@/components/ScoringPanel";
import { useSessionStore } from "@/data/sessionStore";

const Analysis = () => {
  const navigate = useNavigate();
  const { vizData, summary, isLoading, error, loadFromUrl } = useSessionStore();
  const [activeIdx, setActiveIdx] = useState<number | null>(null);
  const [selectedLap, setSelectedLap] = useState<number | "all">("all");
  const verdictListRef = useRef<HTMLDivElement>(null);

  // Load demo data if nothing is in the store yet (direct URL navigation)
  useEffect(() => {
    if (!vizData && !isLoading) {
      loadFromUrl("/viz_data_fast.json", "/session_summary_fast.json");
    }
  }, [vizData, isLoading, loadFromUrl]);

  // Available lap numbers
  const lapNumbers = useMemo(() => {
    if (!summary?.lap_analyses) return [];
    return Object.keys(summary.lap_analyses).map(Number).sort((a, b) => a - b);
  }, [summary]);

  const isMultiLap = lapNumbers.length > 1;

  // Get selected lap analysis
  const activeLapData = useMemo(() => {
    if (!summary?.lap_analyses) return null;
    if (selectedLap === "all") {
      return Object.values(summary.lap_analyses)[0] ?? null;
    }
    return summary.lap_analyses[String(selectedLap)] ?? null;
  }, [summary, selectedLap]);

  // Filter markers by selected lap
  const filteredMarkerIndices = useMemo(() => {
    if (!vizData) return [];
    if (selectedLap === "all") return vizData.markers.map((_, i) => i);
    return vizData.markers
      .map((m, i) => ({ m, i }))
      .filter(({ m }) => m.lap === selectedLap || m.segment === "Lap-level")
      .map(({ i }) => i);
  }, [vizData, selectedLap]);

  const handleMarkerClick = (idx: number) => {
    if (idx < 0 || activeIdx === idx) {
      setActiveIdx(null);
    } else {
      setActiveIdx(idx);
    }
  };

  // Auto-scroll sidebar to the active verdict card
  useEffect(() => {
    if (activeIdx === null) return;
    const container = verdictListRef.current;
    if (!container) return;
    const el = container.querySelector(`[data-verdict-idx="${activeIdx}"]`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [activeIdx]);

  const trackName = summary?.session?.track ?? "Circuit";
  const lapTime = activeLapData ? formatTime(activeLapData.duration_s) : "--:--.---";
  const totalGain = summary?.deterministic_coaching?.total_estimated_gain_s ?? 0;

  if (isLoading) {
    return (
      <div className="h-screen flex items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="w-8 h-8 text-racing-red animate-spin" />
          <p className="text-sm text-muted-foreground font-mono tracking-wider">
            Loading telemetry data...
          </p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-screen flex items-center justify-center bg-background">
        <div className="text-center space-y-2">
          <p className="text-racing-red font-semibold">Failed to load data</p>
          <p className="text-xs text-muted-foreground">{error}</p>
          <button onClick={() => navigate("/")} className="text-xs text-sector-green underline">
            Go back
          </button>
        </div>
      </div>
    );
  }

  if (!vizData) {
    return (
      <div className="h-screen flex items-center justify-center bg-background">
        <p className="text-muted-foreground">No session data loaded.</p>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      {/* Header */}
      <header className="border-b border-border px-3 sm:px-4 py-2 sm:py-3 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-2 sm:gap-4">
          <button
            onClick={() => navigate("/")}
            className="p-1.5 rounded hover:bg-accent transition-colors"
          >
            <ArrowLeft className="w-4 h-4 text-muted-foreground" />
          </button>
          <div className="flex items-center gap-2 sm:gap-3">
            <div className="w-6 h-6 rounded bg-racing-red flex items-center justify-center">
              <Gauge className="w-3 h-3 text-primary-foreground" />
            </div>
            <div className="flex items-center gap-3 sm:gap-6">
              <div>
                <p className="text-[10px] text-muted-foreground leading-none">Track</p>
                <p className="text-xs sm:text-sm font-semibold tracking-wide">{trackName}</p>
              </div>
              <div className="hidden sm:block">
                <p className="text-[10px] text-muted-foreground leading-none">Laps</p>
                <p className="text-sm font-semibold tracking-wide">
                  {summary?.session?.total_laps ?? "-"}
                </p>
              </div>

{/* Lap selector (only for multi-lap sessions) */}
              {isMultiLap && (
                <div className="relative">
                  <select
                    value={selectedLap}
                    onChange={(e) => {
                      const v = e.target.value;
                      setSelectedLap(v === "all" ? "all" : Number(v));
                      setActiveIdx(null);
                    }}
                    className="appearance-none bg-accent border border-border rounded-md px-3 pr-7 py-1 sm:py-1.5 text-[10px] font-mono tracking-wider uppercase cursor-pointer hover:bg-accent/80 transition-colors"
                  >
                    <option value="all">All Laps</option>
                    {lapNumbers.map((ln) => (
                      <option key={ln} value={ln}>
                        Lap {ln + 1}
                      </option>
                    ))}
                  </select>
                  <ChevronDown className="w-3 h-3 absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none text-muted-foreground" />
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3 sm:gap-5">
          <div className="text-right">
            <p className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground">Lap Time</p>
            <p className="font-mono text-base sm:text-xl font-bold tracking-tight text-sector-green">
              {lapTime}
            </p>
          </div>
        </div>
      </header>

      {/* Main content */}
      <div className="flex-1 flex flex-col overflow-hidden relative">
        <div className="h-[45vh] flex-shrink-0 md:absolute md:inset-0 md:h-auto">
          <Track3D data={vizData} activeMarkerIdx={activeIdx} onMarkerClick={handleMarkerClick} />
        </div>

        <motion.aside
          initial={{ x: 30, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          transition={{ duration: 0.4, delay: 0.2 }}
          className="flex-1 flex flex-col overflow-hidden border-t border-border bg-background md:absolute md:top-0 md:right-0 md:bottom-0 md:w-[420px] md:border-t-0 md:border-l md:border-border/50 md:bg-background/92 md:backdrop-blur-xl"
        >
          <div className="px-3 sm:px-4 py-2 sm:py-3 border-b border-border flex-shrink-0">
            <div className="flex items-center justify-between">
              <h2 className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
                Race Coach
              </h2>
              <span className="font-mono text-[10px] px-2 py-0.5 rounded bg-racing-red/10 text-racing-red">
                {filteredMarkerIndices.length} issues
              </span>
            </div>
          </div>

          <div ref={verdictListRef} className="flex-1 overflow-y-auto p-3 space-y-2">
            {/* Potential gain summary */}
            {totalGain > 0 && activeLapData && (() => {
              const lapDuration = activeLapData.duration_s;
              const improvedTime = lapDuration - totalGain;
              const verdicts = summary?.deterministic_coaching?.verdicts ?? [];
              return (
                <div className="glass-panel p-3 space-y-2.5">
                  {/* Header: big gain number + lap time comparison */}
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground">Potential Gain</p>
                      <p className="font-mono text-2xl font-bold text-sector-green leading-none mt-0.5">
                        -{totalGain.toFixed(2)}s
                      </p>
                    </div>
                    <div className="flex items-center gap-3 text-right">
                      <div>
                        <p className="text-[9px] uppercase tracking-wider text-muted-foreground/70">Current</p>
                        <p className="font-mono text-sm font-semibold text-muted-foreground">{formatTime(lapDuration)}</p>
                      </div>
                      <div className="text-muted-foreground/30 text-lg">→</div>
                      <div>
                        <p className="text-[9px] uppercase tracking-wider text-muted-foreground/70">Target</p>
                        <p className="font-mono text-sm font-bold text-sector-green">{formatTime(improvedTime)}</p>
                      </div>
                    </div>
                  </div>
                  {/* Per-verdict breakdown */}
                  {verdicts.filter(v => v.time_impact_s > 0).length > 0 && (
                    <div className="space-y-1.5 pt-2 border-t border-border">
                      {verdicts.filter(v => v.time_impact_s > 0).map((v, i) => {
                        const barW = Math.min((v.time_impact_s / totalGain) * 100, 100);
                        const sevColor = v.severity === "high" || v.severity === "critical"
                          ? "bg-[#e10600]" : v.severity === "medium" ? "bg-[#f97316]" : "bg-[#eab308]";
                        return (
                          <div key={i} className="flex items-center gap-2">
                            <span className="text-[10px] text-muted-foreground w-[88px] truncate shrink-0">
                              {v.segment || "Lap-level"}
                            </span>
                            <div className="flex-1 h-1.5 bg-foreground/10 rounded-full overflow-hidden">
                              <motion.div
                                className={`h-full rounded-full ${sevColor} opacity-80`}
                                initial={{ width: 0 }}
                                animate={{ width: `${barW}%` }}
                                transition={{ duration: 0.6, delay: i * 0.06, ease: "easeOut" }}
                              />
                            </div>
                            <span className="font-mono text-[10px] text-muted-foreground w-10 text-right shrink-0">
                              -{v.time_impact_s.toFixed(2)}s
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })()}

            {summary && <CoachPanel summary={summary} />}

            {/* ML-like Performance Scoring */}
            {summary?.scoring && (
              <ScoringPanel
                scoring={summary.scoring}
                selectedLap={selectedLap}
              />
            )}

            {activeLapData && <DynamicsPanel lap={activeLapData} />}

            {/* Consistency summary (multi-lap) */}
            {isMultiLap && (summary as any)?.consistency && (
              <div className="glass-panel p-3 space-y-2">
                <p className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
                  Lap Consistency
                </p>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-foreground/80">Overall Score</span>
                  <span className="font-mono text-sm font-bold text-sector-green">
                    {(summary as any).consistency.overall_score}/100
                  </span>
                </div>
                {(summary as any).consistency.weakest_segment && (
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-foreground/80">Weakest Segment</span>
                    <span className="font-mono text-xs text-racing-red">
                      {(summary as any).consistency.weakest_segment}
                    </span>
                  </div>
                )}
              </div>
            )}

            {/* Verdict cards */}
            <div className="pt-1">
              <p className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground mb-2 px-1">
                Detailed Findings
              </p>
              {filteredMarkerIndices.map((origIdx) => {
                const m = vizData.markers[origIdx];
                return (
                  <div key={origIdx} className="mb-2" data-verdict-idx={origIdx}>
                    <VerdictCard
                      marker={m}
                      index={origIdx}
                      isActive={activeIdx === origIdx}
                      onClick={() => handleMarkerClick(origIdx)}
                      showLapBadge={isMultiLap}
                    />
                  </div>
                );
              })}
            </div>
          </div>
        </motion.aside>

        {/* Chat Panel - floating button + chat window */}
        <ChatPanel />
      </div>
    </div>
  );
};

function formatTime(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  const whole = Math.floor(secs);
  const ms = Math.round((secs - whole) * 1000);
  return `${mins}:${String(whole).padStart(2, "0")}.${String(ms).padStart(3, "0")}`;
}

export default Analysis;
