import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, AlertTriangle, Target, Gauge } from "lucide-react";
import { useState } from "react";
import type { LapAnalysis } from "@/data/types";
import GGDiagram from "./GGDiagram";

interface DynamicsPanelProps {
  lap: LapAnalysis;
}

export default function DynamicsPanel({ lap }: DynamicsPanelProps) {
  const [showGG, setShowGG] = useState(false);
  const [showEvents, setShowEvents] = useState(false);
  const [showBrakes, setShowBrakes] = useState(false);

  const events = lap.dynamics.events;
  const brakes = lap.brakes;
  const totalEvents = events.oversteer + events.understeer + events.lockup + events.wheelspin;

  return (
    <div className="space-y-1.5">
      {/* Friction Circle (expandable) */}
      <ExpandableSection
        label="Friction Circle"
        icon={<Target className="w-3 h-3" />}
        badge={`${lap.dynamics.gg_diagram.friction_utilization_pct.toFixed(0)}%`}
        badgeColor={
          lap.dynamics.gg_diagram.friction_utilization_pct > 80
            ? "text-sector-green"
            : "text-sector-yellow"
        }
        expanded={showGG}
        onToggle={() => setShowGG(!showGG)}
      >
        <GGDiagram lap={lap} />
      </ExpandableSection>

      {/* Events summary (expandable) */}
      <ExpandableSection
        label="Dynamic Events"
        icon={<AlertTriangle className="w-3 h-3" />}
        badge={`${totalEvents}`}
        badgeColor={totalEvents > 10 ? "text-racing-red" : "text-sector-yellow"}
        expanded={showEvents}
        onToggle={() => setShowEvents(!showEvents)}
      >
        <div className="grid grid-cols-2 gap-2">
          <EventStat label="Lockup" value={events.lockup} warn={events.lockup > 0} />
          <EventStat label="Wheelspin" value={events.wheelspin} warn={events.wheelspin > 5} />
          <EventStat label="Oversteer" value={events.oversteer} warn={events.oversteer > 3} />
          <EventStat label="Understeer" value={events.understeer} warn={events.understeer > 3} />
        </div>
      </ExpandableSection>

      {/* Brake analysis (expandable) */}
      <ExpandableSection
        label="Brake Analysis"
        icon={<Gauge className="w-3 h-3" />}
        badge={`${brakes.front_bias_pct.toFixed(0)}% front`}
        badgeColor="text-muted-foreground"
        expanded={showBrakes}
        onToggle={() => setShowBrakes(!showBrakes)}
      >
        <div className="space-y-2">
          <StatBar label="Front Bias" value={brakes.front_bias_pct} unit="%" max={100} />
          <StatBar label="L/R Imbalance" value={brakes.lr_imbalance_pct} unit="%" max={20} />
          <StatBar label="Modulation" value={brakes.modulation_score * 100} unit="" max={100} />
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>Brake zones: {brakes.zone_count}</span>
            <span>Brake time: {brakes.brake_time_pct.toFixed(0)}%</span>
          </div>
        </div>
      </ExpandableSection>
    </div>
  );
}

// ── Reusable expandable section ──
function ExpandableSection({
  label,
  icon,
  badge,
  badgeColor,
  expanded,
  onToggle,
  children,
}: {
  label: string;
  icon: React.ReactNode;
  badge: string;
  badgeColor: string;
  expanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="glass-panel overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full px-3 py-2.5 flex items-center justify-between hover:bg-foreground/[0.02] transition-colors"
      >
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {icon}
          <span className="uppercase tracking-[0.15em] font-semibold">{label}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className={`font-mono text-[11px] font-semibold ${badgeColor}`}>{badge}</span>
          <motion.span animate={{ rotate: expanded ? 180 : 0 }} transition={{ duration: 0.2 }}>
            <ChevronDown className="w-3 h-3 text-muted-foreground" />
          </motion.span>
        </div>
      </button>
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3 }}
            className="overflow-hidden"
          >
            <div className="px-3 pb-3 border-t border-border pt-2">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function EventStat({ label, value, warn }: { label: string; value: number; warn: boolean }) {
  return (
    <div className="bg-background/50 rounded px-2.5 py-2 text-center">
      <p className={`font-mono text-lg font-bold ${warn ? "text-racing-red" : "text-foreground"}`}>
        {value}
      </p>
      <p className="text-[9px] uppercase tracking-wider text-muted-foreground">{label}</p>
    </div>
  );
}

function StatBar({ label, value, unit, max }: { label: string; value: number; unit: string; max: number }) {
  const pct = Math.min((value / max) * 100, 100);
  return (
    <div>
      <div className="flex justify-between text-[10px] text-muted-foreground mb-0.5">
        <span>{label}</span>
        <span className="font-mono">
          {value.toFixed(1)}{unit}
        </span>
      </div>
      <div className="h-1 bg-foreground/5 rounded-full overflow-hidden">
        <div
          className="h-full bg-sector-green/60 rounded-full transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
