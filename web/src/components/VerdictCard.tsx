import { motion } from "framer-motion";
import {
  AlertTriangle,
  Octagon,
  ChevronDown,
  Timer,
  Crosshair,
} from "lucide-react";
import { useState } from "react";
import type { VizMarker } from "@/data/types";

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

interface VerdictCardProps {
  marker: VizMarker;
  index: number;
  isActive: boolean;
  onClick: () => void;
}

const VerdictCard = ({ marker, index, isActive, onClick }: VerdictCardProps) => {
  const [expanded, setExpanded] = useState(false);
  const isHigh = marker.severity === "high" || marker.severity === "critical";
  const categoryLabel = CATEGORY_LABELS[marker.category] || marker.category;

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: index * 0.08, duration: 0.3 }}
      layout
      className={`glass-panel overflow-hidden cursor-pointer transition-colors ${
        isActive ? "border-racing-red/50 glow-red" : "hover:border-foreground/10"
      }`}
      onClick={onClick}
    >
      <div className="p-3 space-y-2">
        {/* Header row */}
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2">
            {isHigh ? (
              <Octagon className="w-3.5 h-3.5 text-racing-red flex-shrink-0" />
            ) : (
              <AlertTriangle className="w-3.5 h-3.5 text-sector-yellow flex-shrink-0" />
            )}
            <span className="text-sm font-semibold tracking-wide">
              {marker.segment}
            </span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-foreground/5 text-muted-foreground uppercase tracking-wider">
              {categoryLabel}
            </span>
          </div>
          {marker.time_impact_s > 0 && (
            <span className="font-mono text-[11px] px-2 py-0.5 rounded bg-racing-red/15 text-racing-red font-semibold flex items-center gap-1">
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
            className={`text-[10px] uppercase tracking-[0.15em] font-semibold ${
              isHigh ? "text-racing-red" : "text-sector-yellow"
            }`}
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
