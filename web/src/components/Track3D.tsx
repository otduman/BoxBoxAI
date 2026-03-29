import { useRef, useMemo, useEffect, useCallback, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { RotateCcw, ChevronLeft, ChevronRight } from "lucide-react";
import type { VizData } from "@/data/types";

/* Unified severity palette — used for BOTH marker dots AND segment coloring */
const SEV_COLORS: Record<string, string> = {
  critical: "#e10600",
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
const SIDEBAR_WIDTH_PX = 420;  // must match Analysis.tsx md:w-[420px]
const TRACK_PADDING_PX = 35;
const MD_BREAKPOINT = 768;

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
    const length = 7;
    const width = 4;
    
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

function drawWorldGrid(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  toScreen: ToScreen,
  toWorld: (sx: number, sy: number) => [number, number],
  scale: number
) {
  // Adaptive spacing based on zoom
  const pxPerMeter = scale;
  let spacing = 200;
  if (pxPerMeter > 1.5) spacing = 100;
  if (pxPerMeter > 4) spacing = 50;
  if (pxPerMeter > 10) spacing = 20;

  // Visible world bounds (all 4 screen corners → world)
  const c0 = toWorld(0, 0);
  const c1 = toWorld(w, 0);
  const c2 = toWorld(w, h);
  const c3 = toWorld(0, h);
  const wMinX = Math.min(c0[0], c1[0], c2[0], c3[0]);
  const wMaxX = Math.max(c0[0], c1[0], c2[0], c3[0]);
  const wMinY = Math.min(c0[1], c1[1], c2[1], c3[1]);
  const wMaxY = Math.max(c0[1], c1[1], c2[1], c3[1]);

  // Draw dot grid at intersections
  const dotR = Math.max(0.5, Math.min(1.5, pxPerMeter * 0.3));
  ctx.fillStyle = "rgba(255,255,255,0.04)";
  const startX = Math.floor(wMinX / spacing) * spacing;
  const startY = Math.floor(wMinY / spacing) * spacing;
  for (let wx = startX; wx <= wMaxX; wx += spacing) {
    for (let wy = startY; wy <= wMaxY; wy += spacing) {
      const [sx, sy] = toScreen(wx, wy);
      if (sx < -10 || sx > w + 10 || sy < -10 || sy > h + 10) continue;
      ctx.beginPath();
      ctx.arc(sx, sy, dotR, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}

/* ────────── auto-rotation via PCA ────────── */
function computeOptimalRotation(points: [number, number][]): number {
  const n = points.length;
  if (n < 10) return 0;
  let cx = 0, cy = 0;
  for (const [x, y] of points) { cx += x; cy += y; }
  cx /= n; cy /= n;
  let cxx = 0, cxy = 0, cyy = 0;
  for (const [x, y] of points) {
    const dx = x - cx, dy = y - cy;
    cxx += dx * dx; cxy += dx * dy; cyy += dy * dy;
  }
  // Principal axis angle
  const angle = Math.atan2(2 * cxy, cxx - cyy) / 2;

  // Pick between angle and angle+90° — whichever makes bbox wider than tall
  const testAr = (a: number) => {
    const c = Math.cos(a), s = Math.sin(a);
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const [x, y] of points) {
      const dx = x - cx, dy = y - cy;
      const rx = dx * c - dy * s, ry = dx * s + dy * c;
      if (rx < minX) minX = rx; if (rx > maxX) maxX = rx;
      if (ry < minY) minY = ry; if (ry > maxY) maxY = ry;
    }
    return (maxX - minX) / ((maxY - minY) || 1);
  };
  const ar1 = testAr(angle);
  const ar2 = testAr(angle + Math.PI / 2);
  // Prefer the orientation whose aspect ratio is wider (landscape-friendly)
  return ar1 >= ar2 ? angle : angle + Math.PI / 2;
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

  // PCA-based optimal rotation for best screen fit
  const optimalRotation = useMemo(
    () => computeOptimalRotation(roadLine),
    [roadLine]
  );

  // Bounding box of all geometry — computed in rotated frame around centroid
  const bounds = useMemo(() => {
    // World-space centroid as camera pivot
    let sumX = 0, sumY = 0;
    for (const [x, y] of roadLine) { sumX += x; sumY += y; }
    const cx = sumX / roadLine.length;
    const cy = sumY / roadLine.length;

    // Compute extents in the rotated frame around centroid
    const cosR = Math.cos(optimalRotation);
    const sinR = Math.sin(optimalRotation);
    let minRX = Infinity, maxRX = -Infinity, minRY = Infinity, maxRY = -Infinity;
    const project = (wx: number, wy: number) => {
      const dx = wx - cx, dy = wy - cy;
      const rx = dx * cosR - dy * sinR;
      const ry = dx * sinR + dy * cosR;
      if (rx < minRX) minRX = rx; if (rx > maxRX) maxRX = rx;
      if (ry < minRY) minRY = ry; if (ry > maxRY) maxRY = ry;
    };
    for (const [x, y] of roadLine) project(x, y);
    for (const m of data.markers) project(m.x, m.y);

    // If the rotated bbox is off-center relative to centroid, adjust
    // so camera targets the true visual center
    const offsetRX = (minRX + maxRX) / 2;
    const offsetRY = (minRY + maxRY) / 2;
    // Inverse-rotate offset back to world space and shift centroid
    const adjCx = cx + offsetRX * cosR + offsetRY * sinR;
    const adjCy = cy - offsetRX * sinR + offsetRY * cosR;

    const width = (maxRX - minRX) * 1.18;
    const height = (maxRY - minRY) * 1.18;
    return { cx: adjCx, cy: adjCy, width, height };
  }, [roadLine, data.markers, optimalRotation]);

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
  // Initial position includes sidebar offset to avoid first-frame flash
  const cam = useRef<Cam>((() => {
    const wrap = wrapRef.current;
    const w = wrap?.clientWidth ?? 800;
    const h = wrap?.clientHeight ?? 600;
    const baseScale = Math.min((w - TRACK_PADDING_PX * 2) / bounds.width, (h - TRACK_PADDING_PX * 2) / bounds.height);
    const cosR = Math.cos(optimalRotation);
    const sinR = Math.sin(optimalRotation);
    const offset = w >= MD_BREAKPOINT ? SIDEBAR_WIDTH_PX / (2 * baseScale) : 0;
    return {
      cx: bounds.cx + offset * cosR,
      cy: bounds.cy - offset * sinR,
      zoom: 1,
      rotation: optimalRotation,
    };
  })());
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
      return Math.min(
        (w - TRACK_PADDING_PX * 2) / bounds.width,
        (h - TRACK_PADDING_PX * 2) / bounds.height
      );
    },
    [bounds.width, bounds.height]
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
    const from = { ...cam.current };
    // Normalize rotation for shortest-path interpolation
    let dr = target.rotation - from.rotation;
    while (dr > Math.PI) dr -= Math.PI * 2;
    while (dr < -Math.PI) dr += Math.PI * 2;
    target = { ...target, rotation: from.rotation + dr };
    animFrom.current = from;
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
  const isLapLevelRef = useRef(false);
  isLapLevelRef.current = isLapLevel;

  // Sidebar compensation helper: shift camera right (in rotated frame)
  // so the visible area (left of sidebar) is centered on the target
  const sidebarShift = useCallback(
    (targetX: number, targetY: number, zoom: number): { cx: number; cy: number } => {
      const wrap = wrapRef.current;
      const w = wrap?.clientWidth ?? 1;
      if (w < MD_BREAKPOINT) return { cx: targetX, cy: targetY }; // mobile: no sidebar
      const scale = getBaseScale(w, wrap?.clientHeight ?? 1) * zoom;
      const cosR = Math.cos(optimalRotation);
      const sinR = Math.sin(optimalRotation);
      const offset = SIDEBAR_WIDTH_PX / (2 * scale);
      return {
        cx: targetX + offset * cosR,
        cy: targetY - offset * sinR,
      };
    },
    [getBaseScale, optimalRotation]
  );

  useEffect(() => {
    const { cx: oCx, cy: oCy } = sidebarShift(bounds.cx, bounds.cy, 1);
    const overview: Cam = { cx: oCx, cy: oCy, zoom: 1, rotation: optimalRotation };
    if (activeMarkerIdx !== null) {
      const m = data.markers[activeMarkerIdx];
      if (!m) return;
      if (m.segment === "Lap-level") {
        startAnim(overview);
      } else {
        const { cx, cy } = sidebarShift(m.x, m.y, 4);
        startAnim({ cx, cy, zoom: 4, rotation: optimalRotation });
      }
    } else {
      startAnim(overview);
    }
  }, [activeMarkerIdx, data.markers, bounds, startAnim, optimalRotation, sidebarShift]);

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
          // Only orbit for non-lap-level markers (lap-level stays at overview)
          if (activeRef.current !== null && !isLapLevelRef.current) {
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

      // World-space dot grid (moves with pan/zoom for depth reference)
      const { toWorld, scale: camScale } = makeTransform(w, h, c);
      drawWorldGrid(ctx, w, h, toScreen, toWorld, camScale);

      // Track surface
      drawRibbon(ctx, trackRibbon.left, trackRibbon.right, "#141420", toScreen);

      // Track edges
      drawPolyline(ctx, trackRibbon.left, "#2a2a40", 1.2, toScreen);
      drawPolyline(ctx, trackRibbon.right, "#2a2a40", 1.2, toScreen);

      // Base green layer: entire track colored green so no gaps
      ctx.globalAlpha = 0.15;
      drawPolyline(ctx, roadLine, SEG_COLORS.green, 10, toScreen);
      ctx.globalAlpha = 0.5;
      drawPolyline(ctx, roadLine, SEG_COLORS.green, 4, toScreen);
      ctx.globalAlpha = 1;
      drawPolyline(ctx, roadLine, SEG_COLORS.green, 1.8, toScreen);

      // F1-style segment coloring — only non-green segments drawn on top
      const sortedSlices = [...segmentSlices].sort((a, b) => {
        const ra = SEG_RANK[segmentHealth[a.id] || SEG_COLORS.green] ?? 0;
        const rb = SEG_RANK[segmentHealth[b.id] || SEG_COLORS.green] ?? 0;
        return ra - rb;
      });
      for (const slice of sortedSlices) {
        const color = segmentHealth[slice.id] || SEG_COLORS.green;
        if (color === SEG_COLORS.green) continue; // base layer already green
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
      drawDirectionArrows(ctx, roadLine, "rgba(255, 255, 255, 0.65)", toScreen);

      // START/FINISH marker — white line across track + label
      {
        const sp = roadLine[0];
        const np = roadLine[Math.min(5, roadLine.length - 1)];
        const sdx = np[0] - sp[0], sdy = np[1] - sp[1];
        const slen = Math.sqrt(sdx * sdx + sdy * sdy) || 1;
        const spx = -sdy / slen, spy = sdx / slen;
        const sOut = ((sp[0] + spx * 40 - bounds.cx) ** 2 + (sp[1] + spy * 40 - bounds.cy) ** 2) >=
          ((sp[0] - spx * 40 - bounds.cx) ** 2 + (sp[1] - spy * 40 - bounds.cy) ** 2) ? 1 : -1;
        const [x1, y1] = toScreen(sp[0] + spx * 14, sp[1] + spy * 14);
        const [x2, y2] = toScreen(sp[0] - spx * 14, sp[1] - spy * 14);
        const [lx, ly] = toScreen(sp[0] + spx * 28 * sOut, sp[1] + spy * 28 * sOut);
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.strokeStyle = "rgba(255,255,255,0.9)";
        ctx.lineWidth = 2.5;
        ctx.setLineDash([]);
        ctx.stroke();
        const sFontSize = Math.max(8, Math.min(11, 9 * Math.sqrt(c.zoom)));
        ctx.font = `600 ${sFontSize}px 'Titillium Web', sans-serif`;
        ctx.strokeStyle = "rgba(0,0,0,0.6)";
        ctx.lineWidth = 3;
        ctx.fillStyle = "rgba(255,255,255,0.75)";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.strokeText("S/F", lx, ly);
        ctx.fillText("S/F", lx, ly);
        ctx.textBaseline = "alphabetic";
      }

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
          // Compute tangent + curvature direction for outside-of-corner placement
          const spread = 20;
          const pIdx = Math.max(0, bestIdx - spread);
          const nIdx = Math.min(roadLine.length - 1, bestIdx + spread);
          const tdx = roadLine[nIdx][0] - roadLine[pIdx][0];
          const tdy = roadLine[nIdx][1] - roadLine[pIdx][1];
          const tlen = Math.sqrt(tdx * tdx + tdy * tdy) || 1;
          const perpX = -tdy / tlen;
          const perpY = tdx / tlen;
          // Use curvature direction: cross product of two tangent segments
          const mIdx = bestIdx;
          const p0 = roadLine[Math.max(0, mIdx - spread)];
          const p1 = roadLine[mIdx];
          const p2 = roadLine[Math.min(roadLine.length - 1, mIdx + spread)];
          const d1x = p1[0] - p0[0], d1y = p1[1] - p0[1];
          const d2x = p2[0] - p1[0], d2y = p2[1] - p1[1];
          const cross = d1x * d2y - d1y * d2x;
          // Label goes on the OUTSIDE of the corner (opposite to center of curvature)
          // Fallback: if cross is near zero (straight-ish), push away from track centroid
          const outward = Math.abs(cross) < 0.01
            ? (((ax + perpX - bounds.cx) ** 2 + (ay + perpY - bounds.cy) ** 2) >=
               ((ax - perpX - bounds.cx) ** 2 + (ay - perpY - bounds.cy) ** 2) ? 1 : -1)
            : (cross > 0 ? -1 : 1);
          const labelOffset = 45;
          const lx = ax + perpX * labelOffset * outward;
          const ly = ay + perpY * labelOffset * outward;
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
        const r = isActive ? 16 : isHov ? 13 : 10;

        // Glow — use white/neutral so it doesn't clash with segment coloring
        if (isActive || isHov) {
          ctx.beginPath();
          ctx.arc(sx, sy, r + 10, 0, Math.PI * 2);
          ctx.fillStyle = "rgba(255,255,255,0.08)";
          ctx.fill();
        }

        // Pulse ring — neutral white to avoid clashing with segment colors
        if (isActive) {
          const pulse = 0.5 + Math.sin(now / 300) * 0.5;
          ctx.beginPath();
          ctx.arc(sx, sy, r + 14 + pulse * 10, 0, Math.PI * 2);
          ctx.strokeStyle = "rgba(255,255,255,0.7)";
          ctx.globalAlpha = 0.5 - pulse * 0.4;
          ctx.lineWidth = 2;
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
            className="absolute top-12 left-4 glass-panel px-3 py-2 flex items-center gap-2 text-xs font-sans tracking-wider uppercase text-foreground hover:bg-accent transition-colors cursor-pointer z-10"
          >
            <RotateCcw className="w-3 h-3" />
            Reset View
          </motion.button>
        )}
      </AnimatePresence>

      {/* Prev / Next marker navigation */}
      <AnimatePresence>
        {isZoomed && !isLapLevel && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 10 }}
            className="absolute bottom-4 left-1/2 -translate-x-1/2 md:left-[calc(50%-210px)] flex items-center gap-1 glass-panel px-2 py-1.5 z-40"
          >
            <button
              onClick={() => {
                let idx = activeMarkerIdx!;
                for (let k = 0; k < data.markers.length; k++) {
                  idx = idx > 0 ? idx - 1 : data.markers.length - 1;
                  if (data.markers[idx].segment !== "Lap-level") break;
                }
                onMarkerClick(idx);
              }}
              className="p-1.5 rounded hover:bg-accent transition-colors"
            >
              <ChevronLeft className="w-4 h-4 text-foreground" />
            </button>
            <span className="text-xs font-mono tracking-wider text-muted-foreground min-w-[48px] text-center">
              {activeMarkerIdx! + 1} / {data.markers.length}
            </span>
            <button
              onClick={() => {
                let idx = activeMarkerIdx!;
                for (let k = 0; k < data.markers.length; k++) {
                  idx = idx < data.markers.length - 1 ? idx + 1 : 0;
                  if (data.markers[idx].segment !== "Lap-level") break;
                }
                onMarkerClick(idx);
              }}
              className="p-1.5 rounded hover:bg-accent transition-colors"
            >
              <ChevronRight className="w-4 h-4 text-foreground" />
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Hover tooltip — hidden when zoomed to avoid overlapping prev/next */}
      {hoveredIdx >= 0 && !isZoomed && (
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
