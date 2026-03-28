import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { ArrowLeft, Gauge, Loader2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import Track3D from "@/components/Track3D";
import VerdictCard from "@/components/VerdictCard";
import DynamicsPanel from "@/components/DynamicsPanel";
import CoachPanel from "@/components/CoachPanel";
import { useSessionStore } from "@/data/sessionStore";

const Analysis = () => {
  const navigate = useNavigate();
  const { vizData, summary, isLoading, error, loadFromUrl } = useSessionStore();
  const [activeIdx, setActiveIdx] = useState<number | null>(null);

  // Auto-load data from public folder on mount
  useEffect(() => {
    if (!vizData && !isLoading) {
      loadFromUrl("/viz_data.json", "/session_summary.json");
    }
  }, []);

  const handleMarkerClick = (idx: number) => {
    if (idx < 0 || activeIdx === idx) {
      setActiveIdx(null); // Reset to top-down
    } else {
      setActiveIdx(idx);
    }
  };

  // Get first lap analysis
  const firstLap = summary?.lap_analyses?.["0"] ?? null;
  const trackName = summary?.session?.track ?? "Circuit";
  const lapTime = firstLap ? formatTime(firstLap.duration_s) : "--:--.---";
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
      <header className="border-b border-border px-4 py-3 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate("/")}
            className="p-1.5 rounded hover:bg-accent transition-colors"
          >
            <ArrowLeft className="w-4 h-4 text-muted-foreground" />
          </button>
          <div className="flex items-center gap-3">
            <div className="w-6 h-6 rounded bg-racing-red flex items-center justify-center">
              <Gauge className="w-3 h-3 text-primary-foreground" />
            </div>
            <div className="flex items-center gap-6">
              <div>
                <p className="text-xs text-muted-foreground leading-none">Track</p>
                <p className="text-sm font-semibold tracking-wide">{trackName}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground leading-none">Laps</p>
                <p className="text-sm font-semibold tracking-wide">
                  {summary?.session?.total_laps ?? "-"}
                </p>
              </div>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <div className="text-right">
            <p className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground">Lap Time</p>
            <p className="font-mono text-xl font-bold tracking-tight text-sector-green">{lapTime}</p>
          </div>
          {totalGain > 0 && (
            <div className="text-right">
              <p className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
                Potential Gain
              </p>
              <p className="font-mono text-sm font-semibold text-racing-red">
                +{totalGain.toFixed(2)}s
              </p>
            </div>
          )}
        </div>
      </header>

      {/* Main content */}
      <div className="flex-1 flex overflow-hidden">
        {/* 3D Map area */}
        <div className="flex-1 relative">
          <Track3D
            data={vizData}
            activeMarkerIdx={activeIdx}
            onMarkerClick={handleMarkerClick}
          />
        </div>

        {/* Sidebar */}
        <motion.aside
          initial={{ x: 30, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          transition={{ duration: 0.4, delay: 0.2 }}
          className="w-[340px] flex-shrink-0 border-l border-border flex flex-col overflow-hidden"
        >
          <div className="px-4 py-3 border-b border-border flex-shrink-0">
            <div className="flex items-center justify-between">
              <h2 className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
                Race Coach
              </h2>
              <span className="font-mono text-[10px] px-2 py-0.5 rounded bg-racing-red/10 text-racing-red">
                {vizData.markers.length} issues
              </span>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            {/* AI Coach summary */}
            {summary && <CoachPanel summary={summary} />}

            {/* Dynamics panels */}
            {firstLap && <DynamicsPanel lap={firstLap} />}

            {/* Verdict cards */}
            <div className="pt-1">
              <p className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground mb-2 px-1">
                Detailed Findings
              </p>
              {vizData.markers.map((m, i) => (
                <div key={i} className="mb-2">
                  <VerdictCard
                    marker={m}
                    index={i}
                    isActive={activeIdx === i}
                    onClick={() => handleMarkerClick(i)}
                  />
                </div>
              ))}
            </div>
          </div>
        </motion.aside>
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
