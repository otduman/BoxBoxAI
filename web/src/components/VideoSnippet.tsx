import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Camera, Loader2, AlertCircle, Lightbulb, X, ChevronLeft, ChevronRight, Play, Pause } from "lucide-react";

interface VideoSnippetProps {
  timestamp_s: number;
  segment: string;
  finding: string;
  mcapFile?: string;
  onClose?: () => void;
}

interface FrameData {
  data_url: string;
  camera: string;
  timestamp_ns: number;
}

interface FramesResponse {
  center_timestamp_s: number;
  num_frames: number;
  span_s: number;
  frames: FrameData[];
}

interface MomentCoaching {
  what_happened: string;
  what_to_do: string;
  loading: boolean;
  error?: string;
}

/**
 * VideoSnippet displays multiple frames from the MCAP video around the moment
 * a mistake occurred, with a carousel/auto-play feature and AI coaching.
 */
const VideoSnippet = ({ timestamp_s, segment, finding, mcapFile, onClose }: VideoSnippetProps) => {
  const [frames, setFrames] = useState<FrameData[]>([]);
  const [currentIdx, setCurrentIdx] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isPlaying, setIsPlaying] = useState(true);
  const [coaching, setCoaching] = useState<MomentCoaching>({
    what_happened: "",
    what_to_do: "",
    loading: true,
  });

  // Fetch multiple frames from backend
  useEffect(() => {
    const fetchFrames = async () => {
      try {
        setLoading(true);
        setError(null);
        let url = `/api/frames?timestamp=${timestamp_s}&num_frames=5&span_s=2.0`;
        if (mcapFile) {
          url += `&mcap_file=${encodeURIComponent(mcapFile)}`;
        }
        const res = await fetch(url);
        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || "Failed to fetch frames");
        }
        const data: FramesResponse = await res.json();
        setFrames(data.frames);
        // Start at the middle frame (the actual moment)
        setCurrentIdx(Math.floor(data.frames.length / 2));
      } catch (e) {
        setError(e instanceof Error ? e.message : "Unknown error");
      } finally {
        setLoading(false);
      }
    };

    fetchFrames();
  }, [timestamp_s, mcapFile]);

  // Auto-play carousel
  useEffect(() => {
    if (!isPlaying || frames.length <= 1) return;

    const interval = setInterval(() => {
      setCurrentIdx((prev) => (prev + 1) % frames.length);
    }, 400); // 400ms per frame = ~2.5 fps for smooth viewing

    return () => clearInterval(interval);
  }, [isPlaying, frames.length]);

  // Navigation handlers
  const goToPrev = useCallback(() => {
    setIsPlaying(false);
    setCurrentIdx((prev) => (prev - 1 + frames.length) % frames.length);
  }, [frames.length]);

  const goToNext = useCallback(() => {
    setIsPlaying(false);
    setCurrentIdx((prev) => (prev + 1) % frames.length);
  }, [frames.length]);

  const togglePlay = useCallback(() => {
    setIsPlaying((prev) => !prev);
  }, []);

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

  const currentFrame = frames[currentIdx];

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
        ) : currentFrame ? (
          <>
            <img
              src={currentFrame.data_url}
              alt={`Frame ${currentIdx + 1} of ${frames.length}`}
              className="w-full h-full object-cover"
            />

            {/* Frame navigation controls */}
            {frames.length > 1 && (
              <>
                {/* Prev/Next buttons */}
                <button
                  onClick={goToPrev}
                  className="absolute left-2 top-1/2 -translate-y-1/2 p-1.5 rounded-full bg-black/60 hover:bg-black/80 transition-colors"
                >
                  <ChevronLeft className="w-4 h-4 text-white" />
                </button>
                <button
                  onClick={goToNext}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 rounded-full bg-black/60 hover:bg-black/80 transition-colors"
                >
                  <ChevronRight className="w-4 h-4 text-white" />
                </button>

                {/* Play/Pause button */}
                <button
                  onClick={togglePlay}
                  className="absolute top-2 left-2 p-1.5 rounded-full bg-black/60 hover:bg-black/80 transition-colors"
                >
                  {isPlaying ? (
                    <Pause className="w-4 h-4 text-white" />
                  ) : (
                    <Play className="w-4 h-4 text-white" />
                  )}
                </button>

                {/* Frame indicator dots */}
                <div className="absolute bottom-2 left-1/2 -translate-x-1/2 flex gap-1.5">
                  {frames.map((_, idx) => (
                    <button
                      key={idx}
                      onClick={() => {
                        setIsPlaying(false);
                        setCurrentIdx(idx);
                      }}
                      className={`w-2 h-2 rounded-full transition-all ${
                        idx === currentIdx
                          ? "bg-white scale-125"
                          : "bg-white/40 hover:bg-white/60"
                      }`}
                    />
                  ))}
                </div>
              </>
            )}

            {/* Timestamp overlay */}
            <div className="absolute bottom-2 right-2 bg-black/70 px-2 py-1 rounded text-xs font-mono text-white">
              {currentFrame.camera} • {currentIdx + 1}/{frames.length}
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
