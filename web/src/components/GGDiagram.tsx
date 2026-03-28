import { useMemo } from "react";
import type { LapAnalysis } from "@/data/types";

interface GGDiagramProps {
  lap: LapAnalysis;
}

export default function GGDiagram({ lap }: GGDiagramProps) {
  const gg = lap.dynamics.gg_diagram;
  const maxG = Math.max(gg.max_lateral_g, gg.max_braking_g, gg.max_accel_g, 2);
  const utilization = gg.friction_utilization_pct;

  // SVG dimensions
  const size = 200;
  const cx = size / 2;
  const cy = size / 2;
  const radius = size / 2 - 20;

  const toX = (lateralG: number) => cx + (lateralG / maxG) * radius;
  const toY = (longG: number) => cy - (longG / maxG) * radius;

  // Grid circles
  const gridSteps = [0.5, 1.0, 1.5, 2.0].filter((g) => g <= maxG);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
          Friction Circle
        </p>
        <span
          className={`font-mono text-xs font-semibold ${
            utilization > 80 ? "text-sector-green" : utilization > 60 ? "text-sector-yellow" : "text-racing-red"
          }`}
        >
          {utilization.toFixed(1)}% utilized
        </span>
      </div>

      <svg width="100%" viewBox={`0 0 ${size} ${size}`} className="mx-auto">
        {/* Background */}
        <rect width={size} height={size} fill="transparent" />

        {/* Grid circles */}
        {gridSteps.map((g) => (
          <circle
            key={g}
            cx={cx}
            cy={cy}
            r={(g / maxG) * radius}
            fill="none"
            stroke="hsl(var(--foreground) / 0.08)"
            strokeWidth={0.5}
          />
        ))}

        {/* Axes */}
        <line x1={cx} y1={10} x2={cx} y2={size - 10} stroke="hsl(var(--foreground) / 0.15)" strokeWidth={0.5} />
        <line x1={10} y1={cy} x2={size - 10} y2={cy} stroke="hsl(var(--foreground) / 0.15)" strokeWidth={0.5} />

        {/* Max envelope circle */}
        <circle
          cx={cx}
          cy={cy}
          r={radius}
          fill="none"
          stroke="hsl(var(--sector-green) / 0.3)"
          strokeWidth={1}
          strokeDasharray="4 2"
        />

        {/* Peak markers */}
        {/* Max braking (top) */}
        <circle cx={cx} cy={toY(gg.max_braking_g)} r={3} fill="hsl(var(--racing-red))" />
        {/* Max accel (bottom) */}
        <circle cx={cx} cy={toY(-gg.max_accel_g)} r={3} fill="hsl(var(--sector-green))" />
        {/* Max lateral left */}
        <circle cx={toX(-gg.max_lateral_g)} cy={cy} r={3} fill="hsl(var(--sector-yellow))" />
        {/* Max lateral right */}
        <circle cx={toX(gg.max_lateral_g)} cy={cy} r={3} fill="hsl(var(--sector-yellow))" />

        {/* Utilization fill */}
        <circle
          cx={cx}
          cy={cy}
          r={(utilization / 100) * radius}
          fill="hsl(var(--sector-green) / 0.06)"
          stroke="hsl(var(--sector-green) / 0.2)"
          strokeWidth={1}
        />

        {/* Labels */}
        <text x={cx} y={14} textAnchor="middle" fill="hsl(var(--foreground) / 0.4)" fontSize={8} fontFamily="'JetBrains Mono', monospace">
          BRAKE {gg.max_braking_g.toFixed(1)}g
        </text>
        <text x={cx} y={size - 6} textAnchor="middle" fill="hsl(var(--foreground) / 0.4)" fontSize={8} fontFamily="'JetBrains Mono', monospace">
          ACCEL {gg.max_accel_g.toFixed(1)}g
        </text>
        <text x={size - 8} y={cy - 4} textAnchor="end" fill="hsl(var(--foreground) / 0.4)" fontSize={8} fontFamily="'JetBrains Mono', monospace">
          {gg.max_lateral_g.toFixed(1)}g
        </text>
      </svg>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-2 text-center">
        <div>
          <p className="font-mono text-sm font-bold text-racing-red">{gg.max_braking_g.toFixed(2)}g</p>
          <p className="text-[9px] text-muted-foreground uppercase tracking-wider">Braking</p>
        </div>
        <div>
          <p className="font-mono text-sm font-bold text-sector-yellow">{gg.max_lateral_g.toFixed(2)}g</p>
          <p className="text-[9px] text-muted-foreground uppercase tracking-wider">Lateral</p>
        </div>
        <div>
          <p className="font-mono text-sm font-bold text-sector-green">{gg.max_accel_g.toFixed(2)}g</p>
          <p className="text-[9px] text-muted-foreground uppercase tracking-wider">Accel</p>
        </div>
      </div>
    </div>
  );
}
