import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Camera, Loader2, AlertCircle, Lightbulb, X } from "lucide-react";

interface VideoSnippetProps {
  timestamp_s: number;
  segment: string;
  finding: string;
  onClose?: () => void;
}

interface FrameData {
  data_url: string;
  camera: string;
  actual_timestamp_ns: number;
}

interface MomentCoaching {
  what_happened: string;
  what_to_do: string;
  loading: boolean;
  error?: string;
}

/**
 * VideoSnippet displays a frame from the MCAP video at the moment
 * a mistake occurred, along with AI-generated moment-specific coaching.
 */
const VideoSnippet = ({ timestamp_s, segment, finding, onClose }: VideoSnippetProps) => {
  const [frame, setFrame] = useState<FrameData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [coaching, setCoaching] = useState<MomentCoaching>({
    what_happened: "",
    what_to_do: "",
    loading: true,
  });

  // Fetch frame from backend
  useEffect(() => {
    const fetchFrame = async () => {
      try {
        setLoading(true);
        setError(null);
        const res = await fetch(`/api/frame?timestamp=${timestamp_s}`);
        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || "Failed to fetch frame");
        }
        const data = await res.json();
        setFrame(data);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Unknown error");
      } finally {
        setLoading(false);
      }
    };

    fetchFrame();
  }, [timestamp_s]);

  // Fetch AI coaching for this specific moment
  useEffect(() => {
    const fetchCoaching = async () => {
      try {
        setCoaching((prev) => ({ ...prev, loading: true, error: undefined }));
        const res = await fetch("/api/moment-coaching", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            timestamp_s,
            segment,
            finding,
          }),
        });
        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || "Failed to get coaching");
        }
        const data = await res.json();
        setCoaching({
          what_happened: data.what_happened,
          what_to_do: data.what_to_do,
          loading: false,
        });
      } catch (e) {
        setCoaching({
          what_happened: "",
          what_to_do: "",
          loading: false,
          error: e instanceof Error ? e.message : "Unknown error",
        });
      }
    };

    fetchCoaching();
  }, [timestamp_s, segment, finding]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 10 }}
      className="relative bg-zinc-900/95 border border-zinc-700 rounded-lg overflow-hidden"
    >
      {/* Close button */}
      {onClose && (
        <button
          onClick={onClose}
          className="absolute top-2 right-2 z-10 p-1 rounded-full bg-zinc-800/80 hover:bg-zinc-700 transition-colors"
        >
          <X className="w-4 h-4 text-zinc-400" />
        </button>
      )}

      {/* Frame display */}
      <div className="relative aspect-video bg-zinc-950">
        {loading ? (
          <div className="absolute inset-0 flex items-center justify-center">
            <Loader2 className="w-8 h-8 text-zinc-500 animate-spin" />
          </div>
        ) : error ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-zinc-500 p-4">
            <AlertCircle className="w-8 h-8 mb-2" />
            <p className="text-xs text-center">{error}</p>
          </div>
        ) : frame ? (
          <>
            <img
              src={frame.data_url}
              alt={`Frame at ${timestamp_s.toFixed(2)}s`}
              className="w-full h-full object-cover"
            />
            {/* Timestamp overlay */}
            <div className="absolute bottom-2 left-2 bg-black/70 px-2 py-1 rounded text-xs font-mono text-white">
              {timestamp_s.toFixed(2)}s • {frame.camera}
            </div>
          </>
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-zinc-500">
            <Camera className="w-8 h-8" />
          </div>
        )}
      </div>

      {/* AI Coaching section */}
      <div className="p-3 space-y-2 border-t border-zinc-700">
        <div className="flex items-center gap-2">
          <Lightbulb className="w-4 h-4 text-amber-400" />
          <span className="text-xs font-semibold uppercase tracking-wider text-amber-400">
            AI Coach
          </span>
        </div>

        <AnimatePresence mode="wait">
          {coaching.loading ? (
            <motion.div
              key="loading"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex items-center gap-2 text-xs text-zinc-500"
            >
              <Loader2 className="w-3 h-3 animate-spin" />
              Analyzing this moment...
            </motion.div>
          ) : coaching.error ? (
            <motion.p
              key="error"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="text-xs text-red-400"
            >
              {coaching.error}
            </motion.p>
          ) : (
            <motion.div
              key="content"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="space-y-2"
            >
              {coaching.what_happened && (
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-zinc-500 mb-0.5">
                    What happened
                  </p>
                  <p className="text-xs text-zinc-300 leading-relaxed">
                    {coaching.what_happened}
                  </p>
                </div>
              )}
              {coaching.what_to_do && (
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-amber-500/70 mb-0.5">
                    What to do
                  </p>
                  <p className="text-xs text-zinc-200 leading-relaxed font-medium">
                    {coaching.what_to_do}
                  </p>
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
};

export default VideoSnippet;
