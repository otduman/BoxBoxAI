import { motion } from "framer-motion";
import {
  AlertTriangle,
  Octagon,
  ChevronDown,
  Timer,
  Crosshair,
  Activity,
} from "lucide-react";
import { useState } from "react";
import type { VizMarker } from "@/data/types";

/* Unified severity colors — matches Track3D.tsx markers exactly */
const SEV_COLORS: Record<string, { text: string; icon: string; border: string; bg: string }> = {
  critical: { text: "text-[#e10600]", icon: "text-[#e10600]", border: "border-[#e10600]/50", bg: "bg-[#e10600]/15" },
  high:     { text: "text-[#e10600]", icon: "text-[#e10600]", border: "border-[#e10600]/40", bg: "bg-[#e10600]/15" },
  medium:   { text: "text-[#f97316]", icon: "text-[#f97316]", border: "border-[#f97316]/40", bg: "bg-[#f97316]/15" },
  low:      { text: "text-[#eab308]", icon: "text-[#eab308]", border: "border-[#eab308]/30", bg: "bg-[#eab308]/15" },
};

const CATEGORY_LABELS: Record<string, string> = {
  trail_brake: "Trail Brake",
  brakes: "Braking",
  exit: "Corner Exit",
  dynamics: "Vehicle Dynamics",
  coast: "Coast Time",
  apex: "Apex",
  entry: "Entry",
  lockup: "Lockup",
  wheelspin: "Wheelspin",
  friction: "Grip Usage",
};

const UNIT_LABELS: Record<string, { suffix: string; decimals: number }> = {
  seconds: { suffix: "s", decimals: 3 },
  km_h: { suffix: " km/h", decimals: 1 },
  "km/h": { suffix: " km/h", decimals: 1 },
  percent: { suffix: "%", decimals: 1 },
  g: { suffix: " g", decimals: 2 },
  R_squared: { suffix: " R²", decimals: 2 },
  meters_past_apex: { suffix: " m", decimals: 1 },
  meters_early: { suffix: " m", decimals: 1 },
  meters_late_overshot: { suffix: " m", decimals: 1 },
  events: { suffix: " events", decimals: 0 },
  event_count: { suffix: " events", decimals: 0 },
};

const BOOLEAN_UNITS = new Set(["wheelspin_present", "trail_brake_present"]);
function isBooleanUnit(unit: string): boolean { return BOOLEAN_UNITS.has(unit); }

function formatMetric(value: number, unit: string): string {
  const fmt = UNIT_LABELS[unit];
  if (fmt) return value.toFixed(fmt.decimals) + fmt.suffix;
  // Boolean-like units
  if (unit === "trail_brake_present" || unit === "wheelspin_present")
    return value > 0 ? "Yes" : "No";
  return String(value);
}

interface VerdictCardProps {
  marker: VizMarker;
  index: number;
  isActive: boolean;
  onClick: () => void;
  showLapBadge?: boolean;
}

const VerdictCard = ({ marker, index, isActive, onClick, showLapBadge }: VerdictCardProps) => {
  const [expanded, setExpanded] = useState(false);
  const sev = SEV_COLORS[marker.severity] || SEV_COLORS.low;
  const categoryLabel = CATEGORY_LABELS[marker.category] || marker.category;

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: index * 0.08, duration: 0.3 }}
      layout
      className={`glass-panel overflow-hidden cursor-pointer transition-colors ${
        isActive ? `${sev.border} border` : "hover:border-foreground/10"
      }`}
      onClick={onClick}
    >
      <div className="p-3 space-y-2">
        {/* Header row */}
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2">
            {marker.severity === "critical" || marker.severity === "high" ? (
              <Octagon className={`w-3.5 h-3.5 ${sev.icon} flex-shrink-0`} />
            ) : (
              <AlertTriangle className={`w-3.5 h-3.5 ${sev.icon} flex-shrink-0`} />
            )}
            <span className="text-sm font-semibold tracking-wide">
              {marker.segment}
            </span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-foreground/5 text-muted-foreground uppercase tracking-wider">
              {categoryLabel}
            </span>
            {showLapBadge && marker.lap != null && (
              <span className="text-[9px] px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 font-mono uppercase tracking-wider">
                L{marker.lap + 1}
              </span>
            )}
          </div>
          {marker.time_impact_s > 0 && (
            <span className={`font-mono text-[11px] px-2 py-0.5 rounded ${sev.bg} ${sev.text} font-semibold flex items-center gap-1`}>
              <Timer className="w-3 h-3" />
              {marker.time_impact_s.toFixed(2)}s
            </span>
          )}
        </div>

        {/* Finding */}
        <p className="text-xs text-muted-foreground leading-relaxed pl-5">
          {marker.finding}
        </p>

        {/* Severity + expand toggle */}
        <div className="flex items-center justify-between pl-5">
          <span
            className={`text-[10px] uppercase tracking-[0.15em] font-semibold ${sev.text}`}
          >
            {marker.severity}
          </span>
          <button
            onClick={(e) => {
              e.stopPropagation();
              setExpanded(!expanded);
            }}
            className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors"
          >
            Details
            <motion.span animate={{ rotate: expanded ? 180 : 0 }} transition={{ duration: 0.2 }}>
              <ChevronDown className="w-3 h-3" />
            </motion.span>
          </button>
        </div>
      </div>

      {/* Expandable detail */}
      <motion.div
        initial={false}
        animate={{ height: expanded ? "auto" : 0, opacity: expanded ? 1 : 0 }}
        transition={{ duration: 0.3 }}
        className="overflow-hidden"
      >
        <div className="px-3 pb-3 pt-2 border-t border-border space-y-3">
          <div>
            <p className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground mb-1">
              Why this matters
            </p>
            <p className="text-xs text-foreground/80 leading-relaxed">
              {marker.reasoning}
            </p>
          </div>
          {/* Telemetry log */}
          {marker.measured != null && marker.unit && (
            <div className="bg-foreground/[0.03] border border-border rounded-md p-2.5">
              <div className="flex items-center gap-1.5 mb-2">
                <Activity className="w-3 h-3 text-muted-foreground" />
                <p className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground font-semibold">
                  Telemetry
                </p>
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-[11px]">
                <div className="flex flex-col">
                  <span className="text-[9px] uppercase tracking-wider text-muted-foreground/70 mb-0.5">Measured</span>
                  <span className={`font-bold ${sev.text}`}>
                    {isBooleanUnit(marker.unit)
                      ? (marker.measured > 0 ? "Detected" : "Not detected")
                      : formatMetric(marker.measured, marker.unit)}
                  </span>
                </div>
                {marker.target != null && (
                  <div className="flex flex-col">
                    <span className="text-[9px] uppercase tracking-wider text-muted-foreground/70 mb-0.5">Target</span>
                    <span className="font-bold text-sector-green">
                      {isBooleanUnit(marker.unit)
                        ? (marker.target > 0 ? "Expected" : "None")
                        : formatMetric(marker.target, marker.unit)}
                    </span>
                  </div>
                )}
              </div>
            </div>
          )}
          <div className="bg-sector-green/5 border border-sector-green/20 rounded-md p-2.5">
            <div className="flex items-center gap-1.5 mb-1">
              <Crosshair className="w-3 h-3 text-sector-green" />
              <p className="text-[10px] uppercase tracking-[0.15em] text-sector-green font-semibold">
                Action
              </p>
            </div>
            <p className="text-xs text-foreground/90 leading-relaxed">
              {marker.action}
            </p>
          </div>
        </div>
      </motion.div>
    </motion.div>
  );
};

export default VerdictCard;
