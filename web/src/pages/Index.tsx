import { useCallback, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Upload, Gauge, FileJson, Loader2, ArrowRight } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useSessionStore } from "@/data/sessionStore";

const Index = () => {
  const navigate = useNavigate();
  const { loadFromFiles, loadFromUrl, isLoading, vizData } = useSessionStore();
  const vizInputRef = useRef<HTMLInputElement>(null);
  const sumInputRef = useRef<HTMLInputElement>(null);
  const [vizFile, setVizFile] = useState<File | null>(null);
  const [sumFile, setSumFile] = useState<File | null>(null);

  const handleLoadFiles = useCallback(async () => {
    if (!vizFile) return;
    await loadFromFiles(vizFile, sumFile ?? undefined);
    navigate("/analysis/live");
  }, [vizFile, sumFile, loadFromFiles, navigate]);

  const handleLoadDemo = useCallback(async () => {
    await loadFromUrl("/viz_data.json", "/session_summary.json");
    navigate("/analysis/demo");
  }, [loadFromUrl, navigate]);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const files = Array.from(e.dataTransfer.files);
      for (const f of files) {
        if (f.name.includes("viz")) setVizFile(f);
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
          <h1 className="text-lg font-bold tracking-wide leading-none">Pocket Race Engineer</h1>
          <p className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
            AI-Powered Telemetry Analysis
          </p>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-10 space-y-8">
        {/* Upload dropzone */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.5 }}
          onDragOver={(e) => e.preventDefault()}
          onDrop={handleDrop}
          className="glass-panel border-dashed border-2 border-border hover:border-muted-foreground/30 transition-colors p-8 flex flex-col items-center gap-4 cursor-pointer group"
        >
          <div className="w-12 h-12 rounded-full bg-secondary flex items-center justify-center group-hover:bg-accent transition-colors">
            <Upload className="w-5 h-5 text-muted-foreground" />
          </div>
          <div className="text-center">
            <p className="text-sm font-semibold">Upload Session Data</p>
            <p className="text-xs text-muted-foreground mt-1">
              Drop viz_data.json + session_summary.json here, or select files below
            </p>
          </div>

          {/* File selectors */}
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

          {/* Load button */}
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
        </motion.div>

        {/* Demo session */}
        <div>
          <h2 className="text-xs uppercase tracking-[0.2em] text-muted-foreground mb-4">
            Quick Start
          </h2>
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1, duration: 0.4 }}
            whileHover={{ y: -2, borderColor: "hsl(var(--racing-red) / 0.3)" }}
            onClick={handleLoadDemo}
            className="glass-panel p-5 cursor-pointer group transition-shadow hover:shadow-lg hover:shadow-racing-red/5"
          >
            <div className="space-y-3">
              <div className="flex items-start justify-between">
                <div>
                  <h3 className="text-base font-bold tracking-wide">A2RL Yas Marina</h3>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Autonomous Racing League — Dallara AV-24
                  </p>
                </div>
                <span className="text-[10px] px-2 py-0.5 rounded bg-sector-green/10 text-sector-green font-mono">
                  DEMO
                </span>
              </div>
              <div className="flex items-center gap-5 pt-1 border-t border-border text-xs text-muted-foreground">
                <span className="font-mono">2600.8m track</span>
                <span className="font-mono">7 corners</span>
                <span className="font-mono">7 issues found</span>
              </div>
            </div>
          </motion.div>
        </div>
      </main>
    </div>
  );
};

export default Index;
