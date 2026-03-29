import { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  FileJson,
  Loader2,
  HardDrive,
  Zap,
  BarChart3,
  MessageSquare,
  Upload,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useSessionStore } from "@/data/sessionStore";

interface DemoMeta { lapTime: string; issues: number; gain: string }

const Index = () => {
  const navigate = useNavigate();
  const { loadFromUrl, loadFromMcap, isLoading, pipelineProgress } =
    useSessionStore();
  const [demoMeta, setDemoMeta] = useState<Record<"fast" | "good", DemoMeta>>({
    fast: { lapTime: "—:——.———", issues: 0, gain: "—" },
    good: { lapTime: "—:——.———", issues: 0, gain: "—" },
  });

  useEffect(() => {
    (["fast", "good"] as const).forEach(async (variant) => {
      try {
        const res = await fetch(`/session_summary_${variant}.json`);
        if (!res.ok) return;
        const d = await res.json();
        const dur = d?.session?.laps?.[0]?.duration_s as number | undefined;
        const gain = d?.deterministic_coaching?.total_estimated_gain_s as number | undefined;
        const issues = d?.deterministic_coaching?.total_verdicts as number | undefined;
        if (dur == null) return;
        const mins = Math.floor(dur / 60);
        const secs = dur % 60;
        const whole = Math.floor(secs);
        const ms = Math.round((secs - whole) * 1000);
        const lapTime = `${mins}:${String(whole).padStart(2, "0")}.${String(ms).padStart(3, "0")}`;
        setDemoMeta((prev) => ({
          ...prev,
          [variant]: {
            lapTime,
            issues: issues ?? 0,
            gain: gain != null ? `-${gain.toFixed(2)}s` : "—",
          },
        }));
      } catch { /* ignore if files not present */ }
    });
  }, []);

  const mcapInputRef = useRef<HTMLInputElement>(null);
  const boundaryInputRef = useRef<HTMLInputElement>(null);
  const [mcapFile, setMcapFile] = useState<File | null>(null);
  const [boundaryFile, setBoundaryFile] = useState<File | null>(null);

  const handleLoadMcap = useCallback(async () => {
    if (!mcapFile) return;
    await loadFromMcap(mcapFile, boundaryFile ?? undefined);
    navigate("/analysis/live");
  }, [mcapFile, boundaryFile, loadFromMcap, navigate]);

  const handleLoadDemo = useCallback(
    async (variant: "fast" | "good") => {
      await loadFromUrl(`/viz_data_${variant}.json`, `/session_summary_${variant}.json`);
      navigate("/analysis/demo");
    },
    [loadFromUrl, navigate]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const files = Array.from(e.dataTransfer.files);
      for (const f of files) {
        if (f.name.endsWith(".mcap")) {
          setMcapFile(f);
        } else if (f.name.includes("bnd") || f.name.includes("boundary")) {
          setBoundaryFile(f);
        }
      }
    },
    []
  );

  return (
    <div className="min-h-screen">
      {/* Header */}
      <header className="border-b border-border px-6 py-4 flex items-center">
        <img
          src="/logo.png"
          alt="BoxBox AI"
          className="h-10 object-contain"
        />
      </header>

      <main className="max-w-3xl mx-auto px-6 py-10 space-y-10">
        {/* Hero */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="text-center space-y-3"
        >
          <h2 className="text-2xl sm:text-3xl font-bold tracking-tight">
            Your AI Race Engineer, in Your Pocket
          </h2>
          <p className="text-sm text-muted-foreground max-w-lg mx-auto leading-relaxed">
            Upload your telemetry, get corner-by-corner coaching backed by physics.
            Every insight is measured, every recommendation is actionable.
          </p>
        </motion.div>

        {/* How it works */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {[
            {
              icon: <Upload className="w-4 h-4" />,
              title: "Upload",
              desc: "Drop your MCAP telemetry file",
            },
            {
              icon: <BarChart3 className="w-4 h-4" />,
              title: "Analyze",
              desc: "Physics engine processes every corner",
            },
            {
              icon: <MessageSquare className="w-4 h-4" />,
              title: "Coach",
              desc: "Get actionable, data-backed advice",
            },
          ].map((step, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 15 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 + i * 0.1, duration: 0.4 }}
              className="glass-panel p-4 text-center space-y-2"
            >
              <div className="w-8 h-8 rounded-full bg-racing-red/10 flex items-center justify-center mx-auto text-racing-red">
                {step.icon}
              </div>
              <p className="text-xs font-semibold uppercase tracking-wider">{step.title}</p>
              <p className="text-[11px] text-muted-foreground">{step.desc}</p>
            </motion.div>
          ))}
        </div>

        {/* Upload dropzone */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.5, delay: 0.2 }}
          onDragOver={(e) => e.preventDefault()}
          onDrop={handleDrop}
          className="glass-panel border-dashed border-2 border-border hover:border-muted-foreground/30 transition-colors p-8 flex flex-col items-center gap-4 cursor-pointer group"
        >
          <div className="w-12 h-12 rounded-full bg-secondary flex items-center justify-center group-hover:bg-accent transition-colors">
            <HardDrive className="w-5 h-5 text-muted-foreground" />
          </div>

          <div className="text-center">
            <p className="text-sm font-semibold">Upload MCAP Telemetry</p>
            <p className="text-xs text-muted-foreground mt-1">
              Drop your .mcap file here — analysis runs server-side in ~15s
            </p>
          </div>

          <div className="flex flex-col gap-3 mt-4 w-full max-w-sm">
            <input
              ref={mcapInputRef}
              type="file"
              accept=".mcap"
              className="hidden"
              onChange={(e) => setMcapFile(e.target.files?.[0] ?? null)}
            />
            <button
              onClick={() => mcapInputRef.current?.click()}
              className={`w-full flex items-center justify-center gap-3 px-6 py-4 text-sm font-medium rounded-lg border-2 transition-all ${
                mcapFile
                  ? "border-sector-green bg-sector-green/10 text-sector-green"
                  : "border-dashed border-muted-foreground/30 hover:border-racing-red/50 hover:bg-racing-red/5"
              }`}
            >
              <HardDrive className="w-5 h-5" />
              <span className="truncate">{mcapFile ? mcapFile.name : "Select MCAP telemetry file"}</span>
            </button>

            <input
              ref={boundaryInputRef}
              type="file"
              accept=".json"
              className="hidden"
              onChange={(e) => setBoundaryFile(e.target.files?.[0] ?? null)}
            />
            <button
              onClick={() => boundaryInputRef.current?.click()}
              className={`w-full flex items-center justify-center gap-3 px-6 py-3 text-sm rounded-lg border transition-all ${
                boundaryFile
                  ? "border-sector-green bg-sector-green/10 text-sector-green"
                  : "border-border text-muted-foreground hover:border-muted-foreground/50 hover:bg-accent"
              }`}
            >
              <FileJson className="w-4 h-4" />
              <span className="truncate">{boundaryFile ? boundaryFile.name : "Track boundary (optional)"}</span>
            </button>
          </div>

          {mcapFile && (
            <motion.button
              initial={{ opacity: 0, y: 5 }}
              animate={{ opacity: 1, y: 0 }}
              onClick={handleLoadMcap}
              disabled={isLoading}
              className="flex items-center gap-2 px-5 py-2 rounded-md bg-racing-red text-primary-foreground text-sm font-semibold hover:bg-racing-red/90 transition-colors disabled:opacity-50"
            >
              {isLoading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span className="text-xs">
                    {pipelineProgress ?? "Processing..."}
                  </span>
                </>
              ) : (
                <>
                  <Zap className="w-4 h-4" />
                  Analyze Session
                </>
              )}
            </motion.button>
          )}
        </motion.div>

        {/* Demo sessions */}
        <div>
          <h2 className="text-xs uppercase tracking-[0.2em] text-muted-foreground mb-4">
            Try It Now
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3, duration: 0.4 }}
              whileHover={{ y: -2, borderColor: "hsl(var(--racing-red) / 0.3)" }}
              onClick={() => handleLoadDemo("fast")}
              className="glass-panel p-5 cursor-pointer group transition-shadow hover:shadow-lg hover:shadow-racing-red/5"
            >
              <div className="space-y-3">
                <div className="flex items-start justify-between">
                  <div>
                    <h3 className="text-sm font-bold tracking-wide">Fast Lap</h3>
                    <p className="text-[11px] text-muted-foreground mt-0.5">
                      Aggressive push — Yas Marina
                    </p>
                  </div>
                  <span className="text-[10px] px-2 py-0.5 rounded bg-foreground/8 text-muted-foreground font-mono">
                    {demoMeta.fast.lapTime}
                  </span>
                </div>
                <div className="flex items-center gap-4 pt-1 border-t border-border text-[11px] text-muted-foreground">
                  <span className="font-mono">{demoMeta.fast.issues} issues</span>
                  <span className="font-mono text-sector-green">{demoMeta.fast.gain} gain</span>
                </div>
              </div>
            </motion.div>

            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.4, duration: 0.4 }}
              whileHover={{ y: -2, borderColor: "hsl(var(--sector-green) / 0.3)" }}
              onClick={() => handleLoadDemo("good")}
              className="glass-panel p-5 cursor-pointer group transition-shadow hover:shadow-lg hover:shadow-sector-green/5"
            >
              <div className="space-y-3">
                <div className="flex items-start justify-between">
                  <div>
                    <h3 className="text-sm font-bold tracking-wide">Good Lap</h3>
                    <p className="text-[11px] text-muted-foreground mt-0.5">
                      Consistent drive — Yas Marina
                    </p>
                  </div>
                  <span className="text-[10px] px-2 py-0.5 rounded bg-foreground/8 text-muted-foreground font-mono">
                    {demoMeta.good.lapTime}
                  </span>
                </div>
                <div className="flex items-center gap-4 pt-1 border-t border-border text-[11px] text-muted-foreground">
                  <span className="font-mono">{demoMeta.good.issues} issues</span>
                  <span className="font-mono text-sector-green">{demoMeta.good.gain} gain</span>
                </div>
              </div>
            </motion.div>
          </div>
        </div>
      </main>
    </div>
  );
};

export default Index;
