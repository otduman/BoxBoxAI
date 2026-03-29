import { useState, useRef, useEffect } from "react";
import { createPortal } from "react-dom";
import { motion, AnimatePresence } from "framer-motion";
import { HelpCircle } from "lucide-react";

/**
 * Racing terminology glossary for beginners.
 */
export const RACING_GLOSSARY: Record<string, { short: string; long?: string }> = {
  // Corner phases
  "trail-braking": {
    short: "Gradually releasing brakes while turning into a corner",
    long: "A technique where you continue braking past the turn-in point, progressively releasing pressure as you add steering. This keeps weight on the front tires for better grip.",
  },
  "trail-brake": {
    short: "Gradually releasing brakes while turning into a corner",
    long: "A technique where you continue braking past the turn-in point, progressively releasing pressure as you add steering. This keeps weight on the front tires for better grip.",
  },
  apex: {
    short: "The innermost point of your line through a corner",
    long: "The closest point to the inside of the corner. Hitting the apex correctly sets up a good exit. A 'late apex' is closer to corner exit and helps maximize straight-line speed.",
  },
  "entry speed": {
    short: "Your speed when starting to turn into a corner",
    long: "The speed at which you begin turning. Too fast = understeer and missed apex. Too slow = lost time. The optimal entry speed depends on corner type.",
  },
  "exit speed": {
    short: "Your speed when leaving a corner onto a straight",
    long: "The most important speed metric! Higher exit speed compounds down the following straight. Even 2 km/h more at exit = significant time gain.",
  },
  "apex speed": {
    short: "Minimum speed at the tightest part of the corner",
    long: "How fast you're going at the apex. Carrying more speed through the apex (without losing control) is a sign of good technique and car balance.",
  },

  // Braking
  "brake point": {
    short: "Where you start braking before a corner",
    long: "The distance marker or visual reference where you begin braking. Later braking = less time spent slowing down, but requires precise judgment.",
  },
  "braking intensity": {
    short: "How hard you're pressing the brake pedal (measured in G-force)",
    long: "Professional drivers brake at 1.5-2.5G in GT cars, up to 5-6G in F1. Harder initial braking lets you release sooner and carry speed.",
  },
  "brake release": {
    short: "How smoothly you lift off the brakes",
    long: "Abrupt release unsettles the car. Smooth, progressive release (overlapping with throttle application) maintains balance and grip.",
  },
  "coast time": {
    short: "Time spent neither braking nor accelerating",
    long: "Dead time where you're not using available grip. Good drivers minimize coasting by overlapping brake release with throttle application.",
  },

  // Dynamics
  "lateral G": {
    short: "Sideways force during cornering (measured in G-force)",
    long: "How hard the car is turning. Higher lateral G means you're closer to the grip limit. GT3 cars can achieve 2.0-2.5G on slicks.",
  },
  wheelspin: {
    short: "Rear tires losing traction under acceleration",
    long: "When you apply too much throttle too early, the rear tires spin faster than the car is moving. Brief wheelspin is normal; sustained spin loses time.",
  },
  understeer: {
    short: "Front tires losing grip, car pushes wide",
    long: "When the front tires can't grip enough, the car goes straighter than intended. Often caused by too much entry speed or turning too early.",
  },
  oversteer: {
    short: "Rear tires losing grip, car rotates too much",
    long: "When the rear loses traction and the car rotates more than intended. Can be caused by lifting off throttle mid-corner or too much power on exit.",
  },
  "traction control": {
    short: "Electronic system limiting wheelspin",
    long: "Cuts engine power when rear wheels spin. Helpful for beginners but can slow you down. Pro drivers use minimal TC.",
  },

  // Line & technique
  "racing line": {
    short: "The optimal path through a corner",
    long: "The fastest trajectory, typically: outside entry → apex → outside exit. The goal is to straighten the corner as much as possible while maintaining speed.",
  },
  "throttle point": {
    short: "Where you start accelerating after the apex",
    long: "Earlier throttle = more exit speed, but too early causes wheelspin or pushes you wide. Should be smooth and progressive.",
  },

  // Scoring
  optimal: {
    short: "Score above 85% - excellent execution",
  },
  good: {
    short: "Score 70-85% - solid but room to improve",
  },
  average: {
    short: "Score 50-70% - noticeable time being lost",
  },
  poor: {
    short: "Score below 50% - major improvement opportunity",
  },
};

interface TooltipProps {
  term: string;
  children?: React.ReactNode;
  showIcon?: boolean;
}

/**
 * Tooltip component that shows definition on hover.
 * Uses React Portal to render outside parent containers, avoiding overflow clipping.
 */
export const Tooltip = ({ term, children, showIcon = true }: TooltipProps) => {
  const [isOpen, setIsOpen] = useState(false);
  const [tooltipStyle, setTooltipStyle] = useState<React.CSSProperties>({});
  const triggerRef = useRef<HTMLSpanElement>(null);

  const termLower = term.toLowerCase();
  const definition = RACING_GLOSSARY[termLower];

  // If term not in glossary, just render children
  if (!definition) {
    return <>{children || term}</>;
  }

  const TOOLTIP_WIDTH = 280;
  const MARGIN = 12;

  // Calculate position when tooltip opens
  useEffect(() => {
    if (!isOpen || !triggerRef.current) return;

    const trigger = triggerRef.current.getBoundingClientRect();
    const estimatedHeight = definition.long ? 160 : 80;

    // Horizontal: center on trigger, but clamp to viewport
    let left = trigger.left + trigger.width / 2 - TOOLTIP_WIDTH / 2;
    left = Math.max(MARGIN, Math.min(left, window.innerWidth - TOOLTIP_WIDTH - MARGIN));

    // Vertical: prefer below trigger, fall back to above
    let top: number;
    const spaceBelow = window.innerHeight - trigger.bottom;
    const spaceAbove = trigger.top;

    if (spaceBelow >= estimatedHeight + MARGIN) {
      top = trigger.bottom + 8;
    } else if (spaceAbove >= estimatedHeight + MARGIN) {
      top = trigger.top - estimatedHeight - 8;
    } else {
      // Not enough space - position in center of screen
      top = (window.innerHeight - estimatedHeight) / 2;
    }

    setTooltipStyle({
      position: "fixed",
      top,
      left,
      width: TOOLTIP_WIDTH,
      zIndex: 99999,
    });
  }, [isOpen, definition.long]);

  const tooltipContent = (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.15 }}
          style={tooltipStyle}
          className="p-3 rounded-lg bg-zinc-900 border border-zinc-700 shadow-2xl text-left"
        >
          <p className="text-xs font-semibold text-zinc-100 mb-1.5">{term}</p>
          <p className="text-[11px] text-zinc-300 leading-relaxed">
            {definition.short}
          </p>
          {definition.long && (
            <p className="text-[10px] text-zinc-400 leading-relaxed mt-2 pt-2 border-t border-zinc-700">
              {definition.long}
            </p>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  );

  return (
    <>
      <span
        ref={triggerRef}
        className="inline-flex items-center gap-0.5 cursor-help"
        onMouseEnter={() => setIsOpen(true)}
        onMouseLeave={() => setIsOpen(false)}
      >
        <span className="border-b border-dotted border-current">
          {children || term}
        </span>
        {showIcon && (
          <HelpCircle className="w-3 h-3 text-muted-foreground/50 inline" />
        )}
      </span>
      {createPortal(tooltipContent, document.body)}
    </>
  );
};

/**
 * Auto-tooltip: Wraps text and automatically adds tooltips for known terms.
 */
export const AutoTooltip = ({ text }: { text: string }) => {
  const terms = Object.keys(RACING_GLOSSARY);

  // Create regex to match any glossary term (case-insensitive, whole words)
  const regex = new RegExp(
    `\\b(${terms.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})\\b`,
    'gi'
  );

  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match;
  let key = 0;

  while ((match = regex.exec(text)) !== null) {
    // Add text before match
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }

    // Add tooltip for the term
    parts.push(
      <Tooltip key={key++} term={match[0]} showIcon={false}>
        {match[0]}
      </Tooltip>
    );

    lastIndex = regex.lastIndex;
  }

  // Add remaining text
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return <>{parts}</>;
};

export default Tooltip;
