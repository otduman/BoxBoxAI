import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, MessageSquare, Zap } from "lucide-react";
import { useState } from "react";
import type { SessionSummary } from "@/data/types";

interface CoachPanelProps {
  summary: SessionSummary;
}

export default function CoachPanel({ summary }: CoachPanelProps) {
  const [expanded, setExpanded] = useState(false);
  const coaching = summary.deterministic_coaching;
  const top3 = coaching.top_3_actions;

  return (
    <div className="glass-panel overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-3 py-2.5 flex items-center justify-between hover:bg-foreground/[0.02] transition-colors"
      >
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <MessageSquare className="w-3 h-3" />
          <span className="uppercase tracking-[0.15em] font-semibold">AI Coach Summary</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="font-mono text-[11px] font-semibold text-racing-red">
            {coaching.total_estimated_gain_s.toFixed(1)}s gain
          </span>
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
            <div className="px-3 pb-3 border-t border-border pt-2 space-y-3">
              <p className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
                Top 3 Priority Actions
              </p>

              {top3.map((action, i) => (
                <div key={i} className="flex gap-2.5">
                  <div className="flex-shrink-0 w-5 h-5 rounded-full bg-racing-red/15 flex items-center justify-center mt-0.5">
                    <span className="font-mono text-[10px] font-bold text-racing-red">{i + 1}</span>
                  </div>
                  <p className="text-xs text-foreground/85 leading-relaxed">{action}</p>
                </div>
              ))}

              <div className="flex items-center gap-1.5 pt-1 border-t border-border">
                <Zap className="w-3 h-3 text-sector-yellow" />
                <p className="text-[10px] text-muted-foreground">
                  {coaching.total_verdicts} issues found across session &middot; Est. total gain: {coaching.total_estimated_gain_s.toFixed(2)}s
                </p>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
