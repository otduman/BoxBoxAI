import { motion, AnimatePresence } from "framer-motion";
import { RotateCcw, AlertTriangle, Octagon } from "lucide-react";
import { sectorSegments, verdicts as allVerdicts } from "@/data/mockData";
import type { Verdict } from "@/data/mockData";

interface TrackMapProps {
  activeVerdict: Verdict | null;
  onReset: () => void;
}

const TrackMap = ({ activeVerdict, onReset }: TrackMapProps) => {
  const isZoomed = !!activeVerdict;

  // Full track view vs zoomed-in on a specific corner
  const getViewBox = () => {
    if (!activeVerdict) return "50 0 850 900";
    const cx = activeVerdict.x;
    const cy = activeVerdict.y;
    const size = 200;
    return `${cx - size / 2} ${cy - size / 2} ${size} ${size}`;
  };

  return (
    <div className="relative w-full h-full flex items-center justify-center overflow-hidden rounded bg-background/50">
      {/* Grid background */}
      <div
        className="absolute inset-0 opacity-[0.03]"
        style={{
          backgroundImage: `
            linear-gradient(hsl(var(--foreground) / 0.3) 1px, transparent 1px),
            linear-gradient(90deg, hsl(var(--foreground) / 0.3) 1px, transparent 1px)
          `,
          backgroundSize: "40px 40px",
        }}
      />

      <motion.svg
        viewBox={getViewBox()}
        className="w-full h-full max-h-full"
        style={{ filter: "drop-shadow(0 0 12px hsl(var(--sector-green) / 0.1))" }}
        animate={{ viewBox: getViewBox() }}
        transition={{ duration: 1.4, ease: [0.25, 0.46, 0.45, 0.94] }}
      >
        {/* Track outline shadow for depth */}
        {sectorSegments.map((seg) => (
          <path
            key={`shadow-${seg.id}`}
            d={seg.d}
            fill="none"
            stroke="hsl(0 0% 0% / 0.5)"
            strokeWidth={isZoomed ? 12 : 14}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ))}

        {/* Track asphalt (dark gray base) */}
        {sectorSegments.map((seg) => (
          <path
            key={`asphalt-${seg.id}`}
            d={seg.d}
            fill="none"
            stroke="hsl(var(--muted))"
            strokeWidth={isZoomed ? 8 : 10}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ))}

        {/* Track colored racing line (thin, on top) */}
        {sectorSegments.map((seg) => (
          <motion.path
            key={seg.id}
            d={seg.d}
            fill="none"
            strokeWidth={isZoomed ? 3 : 3.5}
            strokeLinecap="round"
            strokeLinejoin="round"
            className={
              seg.type === "purple"
                ? "track-segment-best"
                : seg.type === "green"
                ? "track-segment-good"
                : "track-segment-slow"
            }
            initial={false}
            animate={{ opacity: 1 }}
          />
        ))}

        {/* All verdict markers (always visible) */}
        {allVerdicts.map((v) => {
          const isActive = activeVerdict?.id === v.id;
          const markerSize = isZoomed ? 8 : 16;
          const iconColor = v.severity === "high" ? "hsl(var(--racing-red))" : "hsl(var(--sector-yellow))";

          return (
            <g key={v.id}>
              {/* Outer glow ring */}
              <circle
                cx={v.x}
                cy={v.y}
                r={markerSize * 1.2}
                fill={`${iconColor.replace(")", " / 0.15)")}`}
                stroke="none"
              />
              {/* Background circle */}
              <circle
                cx={v.x}
                cy={v.y}
                r={markerSize * 0.8}
                fill="hsl(var(--background))"
                stroke={iconColor}
                strokeWidth={isZoomed ? 1.5 : 2}
                style={{ filter: `drop-shadow(0 0 ${isZoomed ? 4 : 8}px ${iconColor.replace(")", " / 0.6)")})` }}
              />
              {/* Severity icon - triangle or octagon shape */}
              {v.severity === "high" ? (
                // Red octagon/stop shape
                <polygon
                  points={(() => {
                    const cx = v.x, cy = v.y, s = markerSize * 0.45;
                    return [0, 45, 90, 135, 180, 225, 270, 315]
                      .map(a => {
                        const r = a * Math.PI / 180;
                        return `${cx + s * Math.cos(r)},${cy + s * Math.sin(r)}`;
                      })
                      .join(" ");
                  })()}
                  fill={iconColor}
                />
              ) : (
                // Yellow warning triangle
                <polygon
                  points={`${v.x},${v.y - markerSize * 0.45} ${v.x - markerSize * 0.4},${v.y + markerSize * 0.3} ${v.x + markerSize * 0.4},${v.y + markerSize * 0.3}`}
                  fill={iconColor}
                />
              )}
              {/* Exclamation mark */}
              <text
                x={v.x}
                y={v.y + (v.severity === "high" ? 1 : -1)}
                textAnchor="middle"
                dominantBaseline="central"
                fill="hsl(var(--background))"
                fontSize={markerSize * 0.5}
                fontWeight="bold"
                fontFamily="sans-serif"
              >
                !
              </text>

              {/* Pulsing ring when active */}
              {isActive && (
                <motion.circle
                  cx={v.x}
                  cy={v.y}
                  r={markerSize * 1.5}
                  fill="none"
                  stroke={iconColor}
                  strokeWidth={1.5}
                  animate={{
                    r: [markerSize * 1.2, markerSize * 2.5, markerSize * 1.2],
                    opacity: [0.8, 0, 0.8],
                  }}
                  transition={{ duration: 2, repeat: Infinity }}
                />
              )}

              {/* Corner label */}
              {(isActive || !isZoomed) && (
                <text
                  x={v.x}
                  y={v.y - markerSize * 1.6}
                  textAnchor="middle"
                  fill="hsl(var(--foreground))"
                  fontSize={isZoomed ? 10 : 14}
                  fontFamily="'Titillium Web', sans-serif"
                  fontWeight="600"
                  style={{ filter: "drop-shadow(0 1px 2px hsl(0 0% 0% / 0.8))" }}
                >
                  {v.corner}
                </text>
              )}
            </g>
          );
        })}
      </motion.svg>

      {/* Track name label */}
      <div className="absolute top-4 left-4 font-sans text-xs tracking-[0.2em] uppercase text-muted-foreground">
        Spa-Francorchamps
      </div>

      {/* Sector legend */}
      <div className="absolute bottom-4 left-4 flex gap-4 text-xs font-mono text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-sector-purple" /> Overall Best
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-sector-green" /> Personal Best
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-sector-yellow" /> Sub-optimal
        </span>
      </div>

      {/* Reset button */}
      <AnimatePresence>
        {isZoomed && (
          <motion.button
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 10 }}
            onClick={onReset}
            className="absolute top-4 right-4 glass-panel px-3 py-2 flex items-center gap-2 text-xs font-sans tracking-wider uppercase text-foreground hover:bg-accent transition-colors cursor-pointer"
          >
            <RotateCcw className="w-3 h-3" />
            Reset View
          </motion.button>
        )}
      </AnimatePresence>
    </div>
  );
};

export default TrackMap;
