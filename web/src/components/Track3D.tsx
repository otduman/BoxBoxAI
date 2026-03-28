import { useRef, useMemo, useEffect, useCallback, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { RotateCcw } from "lucide-react";
import type { VizData } from "@/data/types";

/* Unified severity palette — used for BOTH marker dots AND segment coloring */
const SEV_COLORS: Record<string, string> = {
  critical: "#dc2626",
  high: "#e10600",
  medium: "#f97316",
  low: "#eab308",
};
const ANIM_DUR = 1.0;
const ORBIT_SPEED = 0.015;
const INERTIA_FRICTION = 0.92;
const MIN_ZOOM = 0.4;
const MAX_ZOOM = 16;
const ZOOM_STEP = 1.03;
const DRAG_THRESHOLD_PX = 4;

/* ────────── geometry helpers ────────── */
function buildTrackRibbon(
  centerline: [number, number][],
  halfWidth: number
): { left: [number, number][]; right: [number, number][] } {
  const n = centerline.length;
  const left: [number, number][] = [];
  const right: [number, number][] = [];
  for (let i = 0; i < n; i++) {
    const prev = i > 0 ? i - 1 : n - 1;
    const next = i < n - 1 ? i + 1 : 0;
    const dx = centerline[next][0] - centerline[prev][0];
    const dy = centerline[next][1] - centerline[prev][1];
    const len = Math.sqrt(dx * dx + dy * dy) || 1;
    const nx = -dy / len;
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

/* ────────── camera ────────── */
interface Cam {
  cx: number;
  cy: number;
  zoom: number;
  rotation: number; // radians — world rotates around (cx, cy)
}

function lerpCam(a: Cam, b: Cam, t: number): Cam {
  return {
    cx: a.cx + (b.cx - a.cx) * t,
    cy: a.cy + (b.cy - a.cy) * t,
    zoom: a.zoom + (b.zoom - a.zoom) * t,
    rotation: a.rotation + (b.rotation - a.rotation) * t,
  };
}

function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

/* ────────── canvas draw helpers ────────── */
type ToScreen = (wx: number, wy: number) => [number, number];

function drawPolyline(
  ctx: CanvasRenderingContext2D,
  pts: [number, number][],
  color: string,
  width: number,
  toScreen: ToScreen
) {
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
}

function drawRibbon(
  ctx: CanvasRenderingContext2D,
  left: [number, number][],
  right: [number, number][],
  fill: string,
  toScreen: ToScreen
) {
  const n = Math.min(left.length, right.length);
  if (n < 2) return;
  ctx.beginPath();
  let [sx, sy] = toScreen(left[0][0], left[0][1]);
  ctx.moveTo(sx, sy);
  for (let i = 1; i < n; i++) {
    [sx, sy] = toScreen(left[i][0], left[i][1]);
    ctx.lineTo(sx, sy);
  }
  for (let i = n - 1; i >= 0; i--) {
    [sx, sy] = toScreen(right[i][0], right[i][1]);
    ctx.lineTo(sx, sy);
  }
  ctx.closePath();
  ctx.fillStyle = fill;
  ctx.fill();
}

function drawDirectionArrows(
  ctx: CanvasRenderingContext2D,
  pts: [number, number][],
  color: string,
  toScreen: (worldX: number, worldY: number) => [number, number]
) {
  if (pts.length < 10) return;
  const ARROW_SPACING_PTS = 150; 
  ctx.fillStyle = color;
  for (let i = ARROW_SPACING_PTS; i < pts.length; i += ARROW_SPACING_PTS) {
    const p1 = pts[i - 2];
    const p2 = pts[i];
    if (!p1 || !p2) continue;
    const dx = p2[0] - p1[0];
    const dy = p2[1] - p1[1];
    const len = Math.sqrt(dx * dx + dy * dy) || 1;
    const dirX = dx / len;
    const dirY = dy / len;
    
    // Perpendicular vector
    const px = -dirY;
    const py = dirX;
    
    // Size in world meters
    const length = 4.5;
    const width = 2.5;
    
    const [tipX, tipY] = toScreen(p2[0], p2[1]);
    const [blX, blY] = toScreen(p2[0] - dirX * length + px * width, p2[1] - dirY * length + py * width);
    const [brX, brY] = toScreen(p2[0] - dirX * length - px * width, p2[1] - dirY * length - py * width);
    const [backX, backY] = toScreen(p2[0] - dirX * length * 0.5, p2[1] - dirY * length * 0.5);
    
    ctx.beginPath();
    ctx.moveTo(tipX, tipY);
    ctx.lineTo(blX, blY);
    ctx.lineTo(backX, backY);
    ctx.lineTo(brX, brY);
    ctx.closePath();
    ctx.fill();
  }
}

/* ────────── component ────────── */
/* ────────── F1 sector colors ────────── */
const SEG_COLORS = {
  green:  "#00d455",   // clean segment
  yellow: "#eab308",   // low severity issues
  orange: "#f97316",   // medium severity issues
  red:    "#e10600",   // high / critical severity issues
} as const;

// Severity rank for draw order: higher = drawn later (on top)
const SEG_RANK: Record<string, number> = {
  [SEG_COLORS.green]: 0,
  [SEG_COLORS.yellow]: 1,
  [SEG_COLORS.orange]: 2,
  [SEG_COLORS.red]: 3,
};

interface Props {
  data: VizData;
  activeMarkerIdx: number | null;
  onMarkerClick: (idx: number) => void;
}

export default function Track3D({
  data,
  activeMarkerIdx,
  onMarkerClick,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [hoveredIdx, setHoveredIdx] = useState(-1);
  const hoveredRef = useRef(-1);
  const activeRef = useRef<number | null>(null);
  activeRef.current = activeMarkerIdx;

  const isZoomed = activeMarkerIdx !== null;

  // Road reference: car trajectory when available, else centerline
  const roadLine = useMemo(
    () => data.car_trajectory ?? data.track.centerline,
    [data]
  );

  // Bounding box of all geometry
  const bounds = useMemo(() => {
    let minX = Infinity,
      maxX = -Infinity,
      minY = Infinity,
      maxY = -Infinity;
    for (const [x, y] of roadLine) {
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    }
    for (const m of data.markers) {
      if (m.x < minX) minX = m.x;
      if (m.x > maxX) maxX = m.x;
      if (m.y < minY) minY = m.y;
      if (m.y > maxY) maxY = m.y;
    }
    const size = Math.max(maxX - minX, maxY - minY) * 1.15;
    return { cx: (minX + maxX) / 2, cy: (minY + maxY) / 2, size };
  }, [roadLine, data.markers]);

  const trackRibbon = useMemo(
    () => buildTrackRibbon(roadLine, 7),
    [roadLine]
  );

  // F1-style segment health: map each segment → color based on worst verdict severity
  const segmentHealth = useMemo(() => {
    const health: Record<string, string> = {};
    // Default: all segments green
    for (const seg of data.segments) health[seg.id] = SEG_COLORS.green;
    // Override based on marker severity
    for (const m of data.markers) {
      if (m.segment === "Lap-level") continue;
      const current = health[m.segment];
      const currentRank = SEG_RANK[current] ?? 0;
      if (m.severity === "critical" || m.severity === "high") {
        if (currentRank < SEG_RANK[SEG_COLORS.red]) health[m.segment] = SEG_COLORS.red;
      } else if (m.severity === "medium") {
        if (currentRank < SEG_RANK[SEG_COLORS.orange]) health[m.segment] = SEG_COLORS.orange;
      } else if (m.severity === "low") {
        if (currentRank < SEG_RANK[SEG_COLORS.yellow]) health[m.segment] = SEG_COLORS.yellow;
      }
    }
    return health;
  }, [data.segments, data.markers]);

  // For each segment, find the roadLine indices that fall within it
  const segmentSlices = useMemo(() => {
    const slices: { id: string; start: number; end: number }[] = [];
    for (const seg of data.segments) {
      // Find closest roadLine index to segment start and end
      let bestStart = 0, bestEnd = 0;
      let dStart = Infinity, dEnd = Infinity;
      for (let j = 0; j < roadLine.length; j++) {
        const ds = (roadLine[j][0] - seg.start[0]) ** 2 + (roadLine[j][1] - seg.start[1]) ** 2;
        const de = (roadLine[j][0] - seg.end[0]) ** 2 + (roadLine[j][1] - seg.end[1]) ** 2;
        if (ds < dStart) { dStart = ds; bestStart = j; }
        if (de < dEnd) { dEnd = de; bestEnd = j; }
      }
      // Handle circular track: if start > end, the segment wraps around
      if (bestStart > bestEnd) {
        slices.push({ id: seg.id, start: bestStart, end: roadLine.length - 1 });
        slices.push({ id: seg.id, start: 0, end: Math.max(bestEnd, 1) });
      } else {
        slices.push({ id: seg.id, start: bestStart, end: bestEnd });
      }
    }
    return slices;
  }, [data.segments, roadLine]);

  /* ── camera + animation refs ── */
  const cam = useRef<Cam>({
    cx: bounds.cx,
    cy: bounds.cy,
    zoom: 1,
    rotation: 0,
  });
  const animFrom = useRef<Cam | null>(null);
  const animTo = useRef<Cam | null>(null);
  const animStart = useRef(0);
  const orbitActive = useRef(false);

  /* ── inertia ── */
  const vel = useRef({ vx: 0, vy: 0 }); // world-space velocity (m/s)

  /* ── drag ── */
  const drag = useRef({
    active: false,
    startX: 0,
    startY: 0,
    lastX: 0,
    lastY: 0,
    lastT: 0,
    moved: false,
    pixVx: 0,
    pixVy: 0,
  });

  /* ── touch / pinch ── */
  const pinch = useRef({
    active: false,
    dist: 0,
    midX: 0,
    midY: 0,
  });

  /* ── misc ── */
  const canvasSize = useRef({ w: 0, h: 0 });
  const lastFrame = useRef(0);
  const frameId = useRef(0);

  /* ── transforms ── */
  const getBaseScale = useCallback(
    (w: number, h: number) => {
      const pad = 60;
      return Math.min(
        (w - pad * 2) / bounds.size,
        (h - pad * 2) / bounds.size
      );
    },
    [bounds.size]
  );

  const makeTransform = useCallback(
    (w: number, h: number, c: Cam) => {
      const scale = getBaseScale(w, h) * c.zoom;
      const cosR = Math.cos(c.rotation);
      const sinR = Math.sin(c.rotation);
      return {
        toScreen: (wx: number, wy: number): [number, number] => {
          const dx = wx - c.cx;
          const dy = wy - c.cy;
          return [
            w / 2 + (dx * cosR - dy * sinR) * scale,
            h / 2 + (dx * sinR + dy * cosR) * scale,
          ];
        },
        toWorld: (sx: number, sy: number): [number, number] => {
          const rx = (sx - w / 2) / scale;
          const ry = (sy - h / 2) / scale;
          return [
            c.cx + rx * cosR + ry * sinR,
            c.cy - rx * sinR + ry * cosR,
          ];
        },
        scale,
      };
    },
    [getBaseScale]
  );

  /* ── animation control ── */
  const startAnim = useCallback((target: Cam) => {
    animFrom.current = { ...cam.current };
    animTo.current = target;
    animStart.current = performance.now();
    orbitActive.current = false;
    vel.current = { vx: 0, vy: 0 };
  }, []);

  const cancelAnim = useCallback(() => {
    if (animFrom.current && animTo.current) {
      const t = Math.min(
        (performance.now() - animStart.current) / 1000 / ANIM_DUR,
        1
      );
      cam.current = lerpCam(
        animFrom.current,
        animTo.current,
        easeInOutCubic(t)
      );
    }
    animFrom.current = null;
    animTo.current = null;
    orbitActive.current = false;
  }, []);

  /* ── react to marker selection ── */
  const isLapLevel = activeMarkerIdx !== null && data.markers[activeMarkerIdx]?.segment === "Lap-level";

  useEffect(() => {
    if (activeMarkerIdx !== null) {
      const m = data.markers[activeMarkerIdx];
      if (!m) return;
      if (m.segment === "Lap-level") {
        // Lap-level: animate back to overview with a slow spin
        startAnim({ cx: bounds.cx, cy: bounds.cy, zoom: 1, rotation: 0 });
      } else {
        startAnim({ cx: m.x, cy: m.y, zoom: 4, rotation: 0 });
      }
    } else {
      startAnim({ cx: bounds.cx, cy: bounds.cy, zoom: 1, rotation: 0 });
    }
  }, [activeMarkerIdx, data.markers, bounds, startAnim]);

  /* ── pixel → world delta ── */
  const pixelToWorld = useCallback(
    (dxPx: number, dyPx: number, c: Cam, w: number, h: number) => {
      const scale = getBaseScale(w, h) * c.zoom;
      const cosR = Math.cos(c.rotation);
      const sinR = Math.sin(c.rotation);
      return {
        dwx: (dxPx * cosR + dyPx * sinR) / scale,
        dwy: (-dxPx * sinR + dyPx * cosR) / scale,
      };
    },
    [getBaseScale]
  );

  /* ── mouse handlers ── */
  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      cancelAnim();
      drag.current = {
        active: true,
        startX: e.clientX,
        startY: e.clientY,
        lastX: e.clientX,
        lastY: e.clientY,
        lastT: performance.now(),
        moved: false,
        pixVx: 0,
        pixVy: 0,
      };
      vel.current = { vx: 0, vy: 0 };
    },
    [cancelAnim]
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      const canvas = canvasRef.current;
      const wrap = wrapRef.current;
      if (!canvas || !wrap) return;
      const w = wrap.clientWidth;
      const h = wrap.clientHeight;

      if (drag.current.active) {
        const dxPx = e.clientX - drag.current.lastX;
        const dyPx = e.clientY - drag.current.lastY;
        const dt = Math.max(
          (performance.now() - drag.current.lastT) / 1000,
          0.001
        );

        // Check if moved enough to count as drag
        const tx = e.clientX - drag.current.startX;
        const ty = e.clientY - drag.current.startY;
        if (tx * tx + ty * ty > DRAG_THRESHOLD_PX * DRAG_THRESHOLD_PX) {
          drag.current.moved = true;
        }

        const { dwx, dwy } = pixelToWorld(dxPx, dyPx, cam.current, w, h);
        cam.current = {
          ...cam.current,
          cx: cam.current.cx - dwx,
          cy: cam.current.cy - dwy,
        };

        drag.current.pixVx = dxPx / dt;
        drag.current.pixVy = dyPx / dt;
        drag.current.lastX = e.clientX;
        drag.current.lastY = e.clientY;
        drag.current.lastT = performance.now();
        canvas.style.cursor = "grabbing";
        return;
      }

      // Hit-test markers
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const { toScreen } = makeTransform(w, h, cam.current);

      let found = -1;
      for (let i = 0; i < data.markers.length; i++) {
        const m = data.markers[i];
        const [sx, sy] = toScreen(m.x, m.y);
        if ((mx - sx) ** 2 + (my - sy) ** 2 < 225) {
          found = i;
          break;
        }
      }
      if (found !== hoveredRef.current) {
        hoveredRef.current = found;
        setHoveredIdx(found);
      }
      canvas.style.cursor = found >= 0 ? "pointer" : "grab";
    },
    [data.markers, makeTransform, pixelToWorld]
  );

  const handleMouseUp = useCallback(() => {
    if (!drag.current.active) return;
    drag.current.active = false;

    // If mouse was stationary at release, no inertia
    if (
      performance.now() - drag.current.lastT > 100 ||
      !drag.current.moved
    ) {
      vel.current = { vx: 0, vy: 0 };
      return;
    }

    // Convert pixel velocity → world velocity
    const wrap = wrapRef.current;
    if (!wrap) return;
    const w = wrap.clientWidth;
    const h = wrap.clientHeight;
    const { dwx, dwy } = pixelToWorld(
      drag.current.pixVx,
      drag.current.pixVy,
      cam.current,
      w,
      h
    );
    vel.current = { vx: dwx, vy: dwy };
  }, [pixelToWorld]);

  const handleClick = useCallback(() => {
    if (drag.current.moved) return;
    if (hoveredRef.current >= 0) {
      onMarkerClick(hoveredRef.current);
    } else if (activeRef.current !== null) {
      onMarkerClick(-1);
    }
  }, [onMarkerClick]);

  const handleMouseLeave = useCallback(() => {
    drag.current.active = false;
    if (hoveredRef.current !== -1) {
      hoveredRef.current = -1;
      setHoveredIdx(-1);
    }
  }, []);

  /* ── wheel zoom (toward cursor) ── */
  const handleWheel = useCallback(
    (e: WheelEvent) => {
      e.preventDefault();
      cancelAnim();
      const wrap = wrapRef.current;
      if (!wrap) return;

      const c = cam.current;
      const w = wrap.clientWidth;
      const h = wrap.clientHeight;
      const rect = wrap.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;

      // World point under cursor (before zoom)
      const { toWorld } = makeTransform(w, h, c);
      const [wx, wy] = toWorld(mx, my);

      // Apply zoom
      const factor = e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP;
      const newZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, c.zoom * factor));

      // Adjust camera center so (wx, wy) stays under cursor
      const newScale = getBaseScale(w, h) * newZoom;
      const cosR = Math.cos(c.rotation);
      const sinR = Math.sin(c.rotation);
      const a =
        ((mx - w / 2) * cosR + (my - h / 2) * sinR) / newScale;
      const b =
        (-(mx - w / 2) * sinR + (my - h / 2) * cosR) / newScale;

      cam.current = { ...c, zoom: newZoom, cx: wx - a, cy: wy - b };
    },
    [cancelAnim, makeTransform, getBaseScale]
  );

  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    wrap.addEventListener("wheel", handleWheel, { passive: false });
    return () => wrap.removeEventListener("wheel", handleWheel);
  }, [handleWheel]);

  /* ── touch handlers (mobile: pan + pinch) ── */
  const handleTouchStart = useCallback(
    (e: TouchEvent) => {
      e.preventDefault();
      if (e.touches.length === 1) {
        cancelAnim();
        const t = e.touches[0];
        drag.current = {
          active: true,
          startX: t.clientX,
          startY: t.clientY,
          lastX: t.clientX,
          lastY: t.clientY,
          lastT: performance.now(),
          moved: false,
          pixVx: 0,
          pixVy: 0,
        };
        vel.current = { vx: 0, vy: 0 };
      } else if (e.touches.length === 2) {
        cancelAnim();
        drag.current.active = false;
        const t0 = e.touches[0];
        const t1 = e.touches[1];
        const dx = t1.clientX - t0.clientX;
        const dy = t1.clientY - t0.clientY;
        pinch.current = {
          active: true,
          dist: Math.sqrt(dx * dx + dy * dy),
          midX: (t0.clientX + t1.clientX) / 2,
          midY: (t0.clientY + t1.clientY) / 2,
        };
      }
    },
    [cancelAnim]
  );

  const handleTouchMove = useCallback(
    (e: TouchEvent) => {
      e.preventDefault();
      const wrap = wrapRef.current;
      if (!wrap) return;
      const w = wrap.clientWidth;
      const h = wrap.clientHeight;

      if (pinch.current.active && e.touches.length === 2) {
        const t0 = e.touches[0];
        const t1 = e.touches[1];
        const dx = t1.clientX - t0.clientX;
        const dy = t1.clientY - t0.clientY;
        const newDist = Math.sqrt(dx * dx + dy * dy);
        const newMidX = (t0.clientX + t1.clientX) / 2;
        const newMidY = (t0.clientY + t1.clientY) / 2;

        // Zoom by ratio of distances
        const factor = newDist / (pinch.current.dist || 1);
        const c = cam.current;
        const newZoom = Math.max(
          MIN_ZOOM,
          Math.min(MAX_ZOOM, c.zoom * factor)
        );

        // Pan by midpoint delta
        const dxPx = newMidX - pinch.current.midX;
        const dyPx = newMidY - pinch.current.midY;
        const { dwx, dwy } = pixelToWorld(dxPx, dyPx, c, w, h);

        // Zoom toward pinch center
        const rect = wrap.getBoundingClientRect();
        const mx = newMidX - rect.left;
        const my = newMidY - rect.top;
        const { toWorld } = makeTransform(w, h, c);
        const [wx, wy] = toWorld(mx, my);
        const newScale = getBaseScale(w, h) * newZoom;
        const cosR = Math.cos(c.rotation);
        const sinR = Math.sin(c.rotation);
        const a =
          ((mx - w / 2) * cosR + (my - h / 2) * sinR) / newScale;
        const b =
          (-(mx - w / 2) * sinR + (my - h / 2) * cosR) / newScale;

        cam.current = {
          ...c,
          zoom: newZoom,
          cx: wx - a - dwx * 0.3,
          cy: wy - b - dwy * 0.3,
        };

        pinch.current = {
          active: true,
          dist: newDist,
          midX: newMidX,
          midY: newMidY,
        };
        drag.current.moved = true;
        return;
      }

      if (drag.current.active && e.touches.length === 1) {
        const t = e.touches[0];
        const dxPx = t.clientX - drag.current.lastX;
        const dyPx = t.clientY - drag.current.lastY;
        const dt = Math.max(
          (performance.now() - drag.current.lastT) / 1000,
          0.001
        );

        const tx = t.clientX - drag.current.startX;
        const ty = t.clientY - drag.current.startY;
        if (tx * tx + ty * ty > DRAG_THRESHOLD_PX * DRAG_THRESHOLD_PX) {
          drag.current.moved = true;
        }

        const { dwx, dwy } = pixelToWorld(dxPx, dyPx, cam.current, w, h);
        cam.current = {
          ...cam.current,
          cx: cam.current.cx - dwx,
          cy: cam.current.cy - dwy,
        };

        drag.current.pixVx = dxPx / dt;
        drag.current.pixVy = dyPx / dt;
        drag.current.lastX = t.clientX;
        drag.current.lastY = t.clientY;
        drag.current.lastT = performance.now();
      }
    },
    [pixelToWorld, makeTransform, getBaseScale]
  );

  const handleTouchEnd = useCallback(
    (e: TouchEvent) => {
      if (e.touches.length === 0) {
        pinch.current.active = false;
        if (drag.current.active) {
          drag.current.active = false;
          if (
            drag.current.moved &&
            performance.now() - drag.current.lastT < 100
          ) {
            const wrap = wrapRef.current;
            if (wrap) {
              const { dwx, dwy } = pixelToWorld(
                drag.current.pixVx,
                drag.current.pixVy,
                cam.current,
                wrap.clientWidth,
                wrap.clientHeight
              );
              vel.current = { vx: dwx, vy: dwy };
            }
          }
        }

        // Handle tap (touch click)
        if (!drag.current.moved && e.changedTouches.length > 0) {
          const t = e.changedTouches[0];
          const wrap = wrapRef.current;
          if (wrap) {
            const rect = wrap.getBoundingClientRect();
            const mx = t.clientX - rect.left;
            const my = t.clientY - rect.top;
            const { toScreen } = makeTransform(
              wrap.clientWidth,
              wrap.clientHeight,
              cam.current
            );
            let found = -1;
            for (let i = 0; i < data.markers.length; i++) {
              const m = data.markers[i];
              const [sx, sy] = toScreen(m.x, m.y);
              if ((mx - sx) ** 2 + (my - sy) ** 2 < 400) {
                found = i;
                break;
              }
            }
            if (found >= 0) {
              onMarkerClick(found);
            } else if (activeRef.current !== null) {
              onMarkerClick(-1);
            }
          }
        }
      } else if (e.touches.length === 1) {
        // Went from 2 → 1 fingers: transition from pinch to pan
        pinch.current.active = false;
        const t = e.touches[0];
        drag.current = {
          active: true,
          startX: t.clientX,
          startY: t.clientY,
          lastX: t.clientX,
          lastY: t.clientY,
          lastT: performance.now(),
          moved: true,
          pixVx: 0,
          pixVy: 0,
        };
      }
    },
    [data.markers, makeTransform, onMarkerClick, pixelToWorld]
  );

  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    wrap.addEventListener("touchstart", handleTouchStart, { passive: false });
    wrap.addEventListener("touchmove", handleTouchMove, { passive: false });
    wrap.addEventListener("touchend", handleTouchEnd, { passive: false });
    return () => {
      wrap.removeEventListener("touchstart", handleTouchStart);
      wrap.removeEventListener("touchmove", handleTouchMove);
      wrap.removeEventListener("touchend", handleTouchEnd);
    };
  }, [handleTouchStart, handleTouchMove, handleTouchEnd]);

  /* ── render loop ── */
  useEffect(() => {
    let running = true;
    lastFrame.current = performance.now();

    const tick = () => {
      if (!running) return;
      const now = performance.now();
      const dt = Math.min((now - lastFrame.current) / 1000, 0.05);
      lastFrame.current = now;

      const canvas = canvasRef.current;
      const wrap = wrapRef.current;
      if (!canvas || !wrap) {
        frameId.current = requestAnimationFrame(tick);
        return;
      }
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        frameId.current = requestAnimationFrame(tick);
        return;
      }

      const dpr = window.devicePixelRatio || 1;
      const w = wrap.clientWidth;
      const h = wrap.clientHeight;

      if (canvasSize.current.w !== w || canvasSize.current.h !== h) {
        canvas.width = w * dpr;
        canvas.height = h * dpr;
        canvas.style.width = w + "px";
        canvas.style.height = h + "px";
        canvasSize.current = { w, h };
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      /* ── update camera ── */
      if (animFrom.current && animTo.current) {
        // Animated transition
        const elapsed = (now - animStart.current) / 1000;
        const t = Math.min(elapsed / ANIM_DUR, 1);
        cam.current = lerpCam(
          animFrom.current,
          animTo.current,
          easeInOutCubic(t)
        );
        if (t >= 1) {
          animFrom.current = null;
          animTo.current = null;
          if (activeRef.current !== null) {
            orbitActive.current = true;
          }
        }
      } else if (orbitActive.current && !drag.current.active) {
        // Slow auto-orbit around the focused marker
        const speed =
          ORBIT_SPEED + Math.sin(now * 0.001) * 0.015;
        cam.current = {
          ...cam.current,
          rotation: cam.current.rotation + speed * dt,
        };
        if (cam.current.rotation > Math.PI * 2) {
          cam.current.rotation -= Math.PI * 2;
        }
      } else if (!drag.current.active && !pinch.current.active) {
        // Inertia coast
        const v = vel.current;
        if (Math.abs(v.vx) > 0.001 || Math.abs(v.vy) > 0.001) {
          cam.current = {
            ...cam.current,
            cx: cam.current.cx - v.vx * dt,
            cy: cam.current.cy - v.vy * dt,
          };
          const decay = Math.pow(INERTIA_FRICTION, dt * 60);
          vel.current = { vx: v.vx * decay, vy: v.vy * decay };
        }
      }

      /* ── draw ── */
      const c = cam.current;
      const { toScreen } = makeTransform(w, h, c);

      // Background
      ctx.fillStyle = "#0a0a0f";
      ctx.fillRect(0, 0, w, h);

      // Vignette
      const vig = ctx.createRadialGradient(
        w / 2,
        h / 2,
        Math.min(w, h) * 0.2,
        w / 2,
        h / 2,
        Math.max(w, h) * 0.75
      );
      vig.addColorStop(0, "rgba(10,10,20,0)");
      vig.addColorStop(1, "rgba(0,0,0,0.5)");
      ctx.fillStyle = vig;
      ctx.fillRect(0, 0, w, h);

      // Track surface
      drawRibbon(ctx, trackRibbon.left, trackRibbon.right, "#141420", toScreen);

      // Track edges
      drawPolyline(ctx, trackRibbon.left, "#2a2a40", 1.2, toScreen);
      drawPolyline(ctx, trackRibbon.right, "#2a2a40", 1.2, toScreen);

      // F1-style segment coloring — sorted by severity so red draws on top
      const sortedSlices = [...segmentSlices].sort((a, b) => {
        const ra = SEG_RANK[segmentHealth[a.id] || SEG_COLORS.green] ?? 0;
        const rb = SEG_RANK[segmentHealth[b.id] || SEG_COLORS.green] ?? 0;
        return ra - rb;
      });
      for (const slice of sortedSlices) {
        const color = segmentHealth[slice.id] || SEG_COLORS.green;
        const pts = roadLine.slice(slice.start, slice.end + 1);
        if (pts.length < 2) continue;
        // Glow layer
        ctx.globalAlpha = 0.15;
        drawPolyline(ctx, pts, color, 10, toScreen);
        ctx.globalAlpha = 0.5;
        drawPolyline(ctx, pts, color, 4, toScreen);
        // Main colored line (full opacity)
        ctx.globalAlpha = 1;
        drawPolyline(ctx, pts, color, 1.8, toScreen);
      }

      // Direction arrows
      drawDirectionArrows(ctx, roadLine, "rgba(255, 255, 255, 0.4)", toScreen);

      // Lap-level pulse: when a lap-level verdict is active, pulse the whole track
      if (isLapLevel) {
        const pulse = 0.3 + Math.sin(now / 400) * 0.3;
        for (const slice of sortedSlices) {
          const color = segmentHealth[slice.id] || SEG_COLORS.green;
          const pts = roadLine.slice(slice.start, slice.end + 1);
          if (pts.length < 2) continue;
          ctx.globalAlpha = pulse;
          drawPolyline(ctx, pts, color, 6, toScreen);
          ctx.globalAlpha = 1;
        }
      }

      // Corner labels — offset perpendicular to the track in world-space
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      for (const seg of data.segments) {
        if (seg.type === "corner") {
          const ax = seg.apex[0];
          const ay = seg.apex[1];
          // Find the closest point on roadLine to compute tangent direction
          let bestDist = Infinity;
          let bestIdx = 0;
          for (let j = 0; j < roadLine.length; j++) {
            const d = (roadLine[j][0] - ax) ** 2 + (roadLine[j][1] - ay) ** 2;
            if (d < bestDist) { bestDist = d; bestIdx = j; }
          }
          // Compute tangent from neighbors
          const prev = Math.max(0, bestIdx - 3);
          const next = Math.min(roadLine.length - 1, bestIdx + 3);
          const tdx = roadLine[next][0] - roadLine[prev][0];
          const tdy = roadLine[next][1] - roadLine[prev][1];
          const tlen = Math.sqrt(tdx * tdx + tdy * tdy) || 1;
          const perpX = -tdy / tlen;
          const perpY = tdx / tlen;
          // Pick the outward side (away from bounds center)
          const outward = ((ax + perpX * 30 - bounds.cx) ** 2 + (ay + perpY * 30 - bounds.cy) ** 2) >=
            ((ax - perpX * 30 - bounds.cx) ** 2 + (ay - perpY * 30 - bounds.cy) ** 2) ? 1 : -1;
          const lx = ax + perpX * 30 * outward;
          const ly = ay + perpY * 30 * outward;
          const [sx, sy] = toScreen(lx, ly);
          const fontSize = Math.max(9, Math.min(13, 10 * Math.sqrt(c.zoom)));
          ctx.font = `600 ${fontSize}px 'Titillium Web', sans-serif`;
          ctx.fillStyle = "#50506a";
          ctx.fillText(seg.id.replace("_", " "), sx, sy);
        }
      }

      // Verdict markers (skip lap-level — they have no meaningful track position)
      const hov = hoveredRef.current;
      for (let i = 0; i < data.markers.length; i++) {
        const m = data.markers[i];
        if (m.segment === "Lap-level") continue;
        const [sx, sy] = toScreen(m.x, m.y);
        const color = SEV_COLORS[m.severity] || "#6b7280";
        const isActive = i === activeRef.current;
        const isHov = i === hov;
        const r = isActive ? 13 : isHov ? 10 : 7;

        // Glow
        if (isActive || isHov) {
          ctx.beginPath();
          ctx.arc(sx, sy, r + 8, 0, Math.PI * 2);
          ctx.fillStyle = color + "25";
          ctx.fill();
        }

        // Pulse ring
        if (isActive) {
          const pulse = 0.5 + Math.sin(now / 300) * 0.5;
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
        ctx.strokeStyle = "#fff";
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

      frameId.current = requestAnimationFrame(tick);
    };

    tick();
    return () => {
      running = false;
      cancelAnimationFrame(frameId.current);
    };
  }, [data, roadLine, trackRibbon, makeTransform, segmentSlices, segmentHealth, isLapLevel, bounds]);

  return (
    <div ref={wrapRef} className="w-full h-full relative touch-none">
      <canvas
        ref={canvasRef}
        className="w-full h-full block"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseLeave}
        onClick={handleClick}
      />

      {/* Track info overlay */}
      <div className="absolute top-4 left-4 font-sans text-xs tracking-[0.2em] uppercase text-muted-foreground pointer-events-none">
        {Math.round(data.track.total_length_m)}m &middot;{" "}
        {data.segments.filter((s) => s.type === "corner").length} corners
      </div>

      {/* Reset view button */}
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
            {data.markers[hoveredIdx].segment} —{" "}
            {data.markers[hoveredIdx].category}
          </div>
          <div className="text-muted-foreground mt-1 leading-relaxed">
            {data.markers[hoveredIdx].finding}
          </div>
        </div>
      )}
    </div>
  );
}
