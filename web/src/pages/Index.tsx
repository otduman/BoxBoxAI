import { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  Upload,
  Gauge,
  FileJson,
  Loader2,
  ArrowRight,
  HardDrive,
  Zap,
  BarChart3,
  MessageSquare,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useSessionStore } from "@/data/sessionStore";

interface DemoMeta { lapTime: string; issues: number; gain: string }

const Index = () => {
  const navigate = useNavigate();
  const { loadFromFiles, loadFromUrl, loadFromMcap, isLoading, pipelineProgress } =
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
  const vizInputRef = useRef<HTMLInputElement>(null);
  const sumInputRef = useRef<HTMLInputElement>(null);
  const mcapInputRef = useRef<HTMLInputElement>(null);
  const [vizFile, setVizFile] = useState<File | null>(null);
  const [sumFile, setSumFile] = useState<File | null>(null);
  const [mcapFile, setMcapFile] = useState<File | null>(null);
  const [uploadMode, setUploadMode] = useState<"mcap" | "json">("mcap");

  const handleLoadFiles = useCallback(async () => {
    if (!vizFile) return;
    await loadFromFiles(vizFile, sumFile ?? undefined);
    navigate("/analysis/live");
  }, [vizFile, sumFile, loadFromFiles, navigate]);

  const handleLoadMcap = useCallback(async () => {
    if (!mcapFile) return;
    await loadFromMcap(mcapFile);
    navigate("/analysis/live");
  }, [mcapFile, loadFromMcap, navigate]);

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
          setUploadMode("mcap");
        } else if (f.name.includes("viz")) setVizFile(f);
        else if (f.name.includes("summary")) setSumFile(f);
        else if (f.name.endsWith(".json") && !vizFile) setVizFile(f);
      }
    },
    [vizFile]
  );

  return (
    <div className="min-h-screen">
      {/* Header */}
      <header className="border-b border-border px-6 py-4 flex items-center gap-3">
        <div className="w-8 h-8 rounded bg-racing-red flex items-center justify-center">
          <Gauge className="w-4 h-4 text-primary-foreground" />
        </div>
        <div>
          <h1 className="text-lg font-bold tracking-wide leading-none">
            Pocket Race Engineer
          </h1>
          <p className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
            AI-Powered Telemetry Analysis
          </p>
        </div>
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

        {/* Upload mode toggle */}
        <div className="flex items-center justify-center gap-2">
          <div className="flex bg-accent p-0.5 rounded-md border border-border">
            <button
              onClick={() => setUploadMode("mcap")}
              className={`px-3 py-1.5 text-[10px] font-mono tracking-wider uppercase rounded-sm transition-all duration-200 ${
                uploadMode === "mcap"
                  ? "bg-background text-foreground shadow-sm font-bold"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              MCAP Telemetry
            </button>
            <button
              onClick={() => setUploadMode("json")}
              className={`px-3 py-1.5 text-[10px] font-mono tracking-wider uppercase rounded-sm transition-all duration-200 ${
                uploadMode === "json"
                  ? "bg-background text-foreground shadow-sm font-bold"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              Pre-processed JSON
            </button>
          </div>
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
            {uploadMode === "mcap" ? (
              <HardDrive className="w-5 h-5 text-muted-foreground" />
            ) : (
              <Upload className="w-5 h-5 text-muted-foreground" />
            )}
          </div>

          {uploadMode === "mcap" ? (
            <>
              <div className="text-center">
                <p className="text-sm font-semibold">Upload MCAP Telemetry</p>
                <p className="text-xs text-muted-foreground mt-1">
                  Drop your .mcap file here — analysis runs server-side in ~15s
                </p>
              </div>

              <div className="flex gap-3 mt-2">
                <input
                  ref={mcapInputRef}
                  type="file"
                  accept=".mcap"
                  className="hidden"
                  onChange={(e) => setMcapFile(e.target.files?.[0] ?? null)}
                />
                <button
                  onClick={() => mcapInputRef.current?.click()}
                  className={`flex items-center gap-2 px-3 py-1.5 text-xs rounded border transition-colors ${
                    mcapFile
                      ? "border-sector-green/50 bg-sector-green/10 text-sector-green"
                      : "border-border hover:bg-accent"
                  }`}
                >
                  <HardDrive className="w-3 h-3" />
                  {mcapFile ? mcapFile.name : "Select .mcap file"}
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
            </>
          ) : (
            <>
              <div className="text-center">
                <p className="text-sm font-semibold">Upload Pre-processed Data</p>
                <p className="text-xs text-muted-foreground mt-1">
                  Drop viz_data.json + session_summary.json here
                </p>
              </div>

              <div className="flex gap-3 mt-2">
                <input
                  ref={vizInputRef}
                  type="file"
                  accept=".json"
                  className="hidden"
                  onChange={(e) => setVizFile(e.target.files?.[0] ?? null)}
                />
                <button
                  onClick={() => vizInputRef.current?.click()}
                  className="flex items-center gap-2 px-3 py-1.5 text-xs rounded border border-border hover:bg-accent transition-colors"
                >
                  <FileJson className="w-3 h-3" />
                  {vizFile ? vizFile.name : "viz_data.json"}
                </button>

                <input
                  ref={sumInputRef}
                  type="file"
                  accept=".json"
                  className="hidden"
                  onChange={(e) => setSumFile(e.target.files?.[0] ?? null)}
                />
                <button
                  onClick={() => sumInputRef.current?.click()}
                  className="flex items-center gap-2 px-3 py-1.5 text-xs rounded border border-border hover:bg-accent transition-colors"
                >
                  <FileJson className="w-3 h-3" />
                  {sumFile ? sumFile.name : "session_summary.json"}
                </button>
              </div>

              {vizFile && (
                <motion.button
                  initial={{ opacity: 0, y: 5 }}
                  animate={{ opacity: 1, y: 0 }}
                  onClick={handleLoadFiles}
                  disabled={isLoading}
                  className="flex items-center gap-2 px-5 py-2 rounded-md bg-racing-red text-primary-foreground text-sm font-semibold hover:bg-racing-red/90 transition-colors disabled:opacity-50"
                >
                  {isLoading ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <ArrowRight className="w-4 h-4" />
                  )}
                  Analyze Session
                </motion.button>
              )}
            </>
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
