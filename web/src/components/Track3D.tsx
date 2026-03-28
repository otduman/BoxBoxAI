import { useRef, useMemo, useEffect, useCallback, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { RotateCcw } from "lucide-react";
import type { VizData } from "@/data/types";

const SEV_COLORS: Record<string, string> = {
  critical: "#dc2626",
  high: "#ef4444",
  medium: "#eab308",
  low: "#6b7280",
};

// ── Build a narrow track ribbon from centerline (±halfWidth) ──
function buildTrackRibbon(
  centerline: [number, number][],
  halfWidth: number
): { left: [number, number][]; right: [number, number][] } {
  const n = centerline.length;
  const left: [number, number][] = [];
  const right: [number, number][] = [];

  for (let i = 0; i < n; i++) {
    // Compute normal at this point
    const prev = i > 0 ? i - 1 : n - 1;
    const next = i < n - 1 ? i + 1 : 0;
    const dx = centerline[next][0] - centerline[prev][0];
    const dy = centerline[next][1] - centerline[prev][1];
    const len = Math.sqrt(dx * dx + dy * dy) || 1;
    const nx = -dy / len; // normal perpendicular to direction
    const ny = dx / len;

    left.push([
      centerline[i][0] + nx * halfWidth,
      centerline[i][1] + ny * halfWidth,
    ]);
    right.push([
      centerline[i][0] - nx * halfWidth,
      centerline[i][1] - ny * halfWidth,
    ]);
  }
  return { left, right };
}

// ── Smooth interpolation helper ──
interface ViewState {
  cx: number;
  cy: number;
  viewSize: number;
}

function lerpView(a: ViewState, b: ViewState, t: number): ViewState {
  return {
    cx: a.cx + (b.cx - a.cx) * t,
    cy: a.cy + (b.cy - a.cy) * t,
    viewSize: a.viewSize + (b.viewSize - a.viewSize) * t,
  };
}

// Ease in-out cubic
function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

interface Track3DProps {
  data: VizData;
  activeMarkerIdx: number | null;
  onMarkerClick: (idx: number) => void;
}

export default function Track3D({ data, activeMarkerIdx, onMarkerClick }: Track3DProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [hoveredIdx, setHoveredIdx] = useState(-1);

  // Animation state
  const animRef = useRef<number>(0);
  const currentView = useRef<ViewState | null>(null);
  const targetView = useRef<ViewState | null>(null);
  const animStartTime = useRef(0);
  const animDuration = 1.2; // seconds

  const isZoomed = activeMarkerIdx !== null;

  // Use car trajectory as the "real road" reference, fallback to centerline
  const roadLine = useMemo(
    () => data.car_trajectory ?? data.track.centerline,
    [data]
  );

  // Compute bounds from the road line + markers
  const bounds = useMemo(() => {
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    const allPts = [
      ...roadLine,
      ...data.markers.map((m): [number, number] => [m.x, m.y]),
    ];
    for (const [x, y] of allPts) {
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    }
    const size = Math.max(maxX - minX, maxY - minY) * 1.15;
    return { cx: (minX + maxX) / 2, cy: (minY + maxY) / 2, size };
  }, [roadLine, data.markers]);

  // Build track ribbon from the road line (±7m ≈ realistic track half-width)
  const trackRibbon = useMemo(
    () => buildTrackRibbon(roadLine, 7),
    [roadLine]
  );

  // Canvas size tracking (only resize when container changes, not every frame)
  const canvasSizeRef = useRef({ w: 0, h: 0 });

  // Default (overview) view
  const overviewView: ViewState = useMemo(
    () => ({ cx: bounds.cx, cy: bounds.cy, viewSize: bounds.size }),
    [bounds]
  );

  // Target view based on active marker
  const zoomedView: ViewState | null = useMemo(() => {
    if (activeMarkerIdx === null) return null;
    const m = data.markers[activeMarkerIdx];
    if (!m) return null;
    return { cx: m.x, cy: m.y, viewSize: bounds.size * 0.25 };
  }, [activeMarkerIdx, data.markers, bounds]);

  // Trigger animation when target changes
  useEffect(() => {
    const newTarget = zoomedView ?? overviewView;
    if (!currentView.current) {
      currentView.current = { ...overviewView };
    }
    targetView.current = newTarget;
    animStartTime.current = performance.now();
  }, [zoomedView, overviewView]);

  // Coordinate transform from a view state
  const getTransform = useCallback(
    (canvasW: number, canvasH: number, view: ViewState) => {
      const pad = 40;
      const scale = Math.min(
        (canvasW - pad * 2) / view.viewSize,
        (canvasH - pad * 2) / view.viewSize
      );
      const offX = canvasW / 2 - view.cx * scale;
      const offY = canvasH / 2 - view.cy * scale;

      return {
        toScreen: (x: number, y: number): [number, number] => [
          x * scale + offX,
          y * scale + offY,
        ],
        scale,
      };
    },
    []
  );

  // Main draw + animate loop
  useEffect(() => {
    let running = true;

    const loop = () => {
      if (!running) return;
      const canvas = canvasRef.current;
      const wrap = wrapRef.current;
      if (!canvas || !wrap) {
        animRef.current = requestAnimationFrame(loop);
        return;
      }

      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      const dpr = window.devicePixelRatio || 1;
      const w = wrap.clientWidth;
      const h = wrap.clientHeight;

      // Only resize canvas buffer when container size actually changes
      if (canvasSizeRef.current.w !== w || canvasSizeRef.current.h !== h) {
        canvas.width = w * dpr;
        canvas.height = h * dpr;
        canvas.style.width = w + "px";
        canvas.style.height = h + "px";
        canvasSizeRef.current = { w, h };
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      // Animate view interpolation
      if (currentView.current && targetView.current) {
        const elapsed = (performance.now() - animStartTime.current) / 1000;
        const t = Math.min(elapsed / animDuration, 1);
        const eased = easeInOutCubic(t);
        const view = lerpView(currentView.current, targetView.current, eased);

        if (t >= 1) {
          currentView.current = { ...targetView.current };
        }

        drawScene(ctx, w, h, view);
      }

      animRef.current = requestAnimationFrame(loop);
    };

    const drawScene = (
      ctx: CanvasRenderingContext2D,
      w: number,
      h: number,
      view: ViewState
    ) => {
      const { toScreen } = getTransform(w, h, view);

      // Clear
      ctx.fillStyle = "#0a0a0f";
      ctx.fillRect(0, 0, w, h);

      // Subtle grid
      ctx.strokeStyle = "rgba(255,255,255,0.02)";
      ctx.lineWidth = 1;
      for (let x = 0; x < w; x += 50) {
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
      }
      for (let y = 0; y < h; y += 50) {
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
      }

      // Helper: draw polyline
      const drawLine = (pts: [number, number][], color: string, width: number) => {
        if (pts.length < 2) return;
        ctx.beginPath();
        const [sx, sy] = toScreen(pts[0][0], pts[0][1]);
        ctx.moveTo(sx, sy);
        for (let i = 1; i < pts.length; i++) {
          const [px, py] = toScreen(pts[i][0], pts[i][1]);
          ctx.lineTo(px, py);
        }
        ctx.strokeStyle = color;
        ctx.lineWidth = width;
        ctx.stroke();
      };

      // Helper: draw filled polygon between two polylines
      const drawRibbon = (
        leftPts: [number, number][],
        rightPts: [number, number][],
        fillColor: string
      ) => {
        const n = Math.min(leftPts.length, rightPts.length);
        if (n < 2) return;
        ctx.beginPath();
        let [sx, sy] = toScreen(leftPts[0][0], leftPts[0][1]);
        ctx.moveTo(sx, sy);
        for (let i = 1; i < n; i++) {
          [sx, sy] = toScreen(leftPts[i][0], leftPts[i][1]);
          ctx.lineTo(sx, sy);
        }
        for (let i = n - 1; i >= 0; i--) {
          [sx, sy] = toScreen(rightPts[i][0], rightPts[i][1]);
          ctx.lineTo(sx, sy);
        }
        ctx.closePath();
        ctx.fillStyle = fillColor;
        ctx.fill();
      };

      // Track surface ribbon (built from the actual driving line)
      drawRibbon(trackRibbon.left, trackRibbon.right, "#141420");

      // Track edge lines (curb markers)
      drawLine(trackRibbon.left, "#2a2a40", 1.2);
      drawLine(trackRibbon.right, "#2a2a40", 1.2);

      // Racing line (center of the ribbon — the hero line)
      drawLine(roadLine, "rgba(59,130,246,0.12)", 5);
      drawLine(roadLine, "rgba(59,130,246,0.35)", 2.5);
      drawLine(roadLine, "#3b82f6", 1.2);

      // Corner labels
      ctx.textAlign = "center";
      for (const seg of data.segments) {
        if (seg.type === "corner") {
          const [sx, sy] = toScreen(seg.apex[0], seg.apex[1]);
          ctx.font = "600 10px 'Titillium Web', sans-serif";
          ctx.fillStyle = "#50506a";
          ctx.fillText(seg.id.replace("_", " "), sx, sy - 18);
        }
      }

      // Verdict markers
      for (let i = 0; i < data.markers.length; i++) {
        const m = data.markers[i];
        const [sx, sy] = toScreen(m.x, m.y);
        const color = SEV_COLORS[m.severity] || "#6b7280";
        const isActive = i === activeMarkerIdx;
        const isHov = i === hoveredIdx;
        const r = isActive ? 13 : isHov ? 10 : 7;

        // Glow
        if (isActive || isHov) {
          ctx.beginPath();
          ctx.arc(sx, sy, r + 8, 0, Math.PI * 2);
          ctx.fillStyle = color + "25";
          ctx.fill();
        }

        // Pulsing ring
        if (isActive) {
          const pulse = 0.5 + Math.sin(performance.now() / 300) * 0.5;
          ctx.beginPath();
          ctx.arc(sx, sy, r + 12 + pulse * 10, 0, Math.PI * 2);
          ctx.strokeStyle = color;
          ctx.globalAlpha = 0.6 - pulse * 0.5;
          ctx.lineWidth = 1.5;
          ctx.stroke();
          ctx.globalAlpha = 1;
        }

        // Circle
        ctx.beginPath();
        ctx.arc(sx, sy, r, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = isActive ? 2.5 : 1.5;
        ctx.stroke();

        // Number
        ctx.font = `bold ${isActive ? 12 : 10}px 'Titillium Web', sans-serif`;
        ctx.fillStyle = "#fff";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(String(i + 1), sx, sy);
        ctx.textBaseline = "alphabetic";
      }
    };

    loop();
    return () => {
      running = false;
      cancelAnimationFrame(animRef.current);
    };
  }, [data, roadLine, trackRibbon, getTransform, activeMarkerIdx, hoveredIdx]);

  // Get current animated view for hit testing
  const getCurrentView = useCallback((): ViewState => {
    return currentView.current ?? overviewView;
  }, [overviewView]);

  // Mouse interaction
  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      const canvas = canvasRef.current;
      const wrap = wrapRef.current;
      if (!canvas || !wrap) return;
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const view = getCurrentView();
      const { toScreen } = getTransform(wrap.clientWidth, wrap.clientHeight, view);

      let found = -1;
      for (let i = 0; i < data.markers.length; i++) {
        const m = data.markers[i];
        const [sx, sy] = toScreen(m.x, m.y);
        const dx = mx - sx, dy = my - sy;
        if (dx * dx + dy * dy < 225) {
          found = i;
          break;
        }
      }
      setHoveredIdx(found);
      canvas.style.cursor = found >= 0 ? "pointer" : isZoomed ? "pointer" : "default";
    },
    [data.markers, getTransform, getCurrentView, isZoomed]
  );

  const handleClick = useCallback(() => {
    if (hoveredIdx >= 0) {
      onMarkerClick(hoveredIdx);
    } else if (isZoomed) {
      onMarkerClick(-1);
    }
  }, [hoveredIdx, onMarkerClick, isZoomed]);

  return (
    <div ref={wrapRef} className="w-full h-full relative">
      <canvas
        ref={canvasRef}
        className="w-full h-full block"
        onMouseMove={handleMouseMove}
        onClick={handleClick}
        onMouseLeave={() => setHoveredIdx(-1)}
      />

      {/* Track info */}
      <div className="absolute top-4 left-4 font-sans text-xs tracking-[0.2em] uppercase text-muted-foreground pointer-events-none">
        {Math.round(data.track.total_length_m)}m &middot;{" "}
        {data.segments.filter((s) => s.type === "corner").length} corners
      </div>

      {/* Reset button */}
      <AnimatePresence>
        {isZoomed && (
          <motion.button
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 10 }}
            onClick={() => onMarkerClick(-1)}
            className="absolute top-4 right-4 glass-panel px-3 py-2 flex items-center gap-2 text-xs font-sans tracking-wider uppercase text-foreground hover:bg-accent transition-colors cursor-pointer"
          >
            <RotateCcw className="w-3 h-3" />
            Reset View
          </motion.button>
        )}
      </AnimatePresence>

      {/* Hover tooltip */}
      {hoveredIdx >= 0 && (
        <div
          className="absolute pointer-events-none bg-card/95 border border-border rounded-md px-3 py-2 text-xs max-w-[240px] z-50 shadow-xl"
          style={{ left: "50%", bottom: 16, transform: "translateX(-50%)" }}
        >
          <div className="font-semibold text-foreground">
            {data.markers[hoveredIdx].segment} — {data.markers[hoveredIdx].category}
          </div>
          <div className="text-muted-foreground mt-1 leading-relaxed">
            {data.markers[hoveredIdx].finding}
          </div>
        </div>
      )}
    </div>
  );
}
