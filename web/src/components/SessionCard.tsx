import { motion } from "framer-motion";
import { Clock, Flag, Gauge } from "lucide-react";
import { useNavigate } from "react-router-dom";
import type { Session } from "@/data/mockData";

interface SessionCardProps {
  session: Session;
  index: number;
}

const SessionCard = ({ session, index }: SessionCardProps) => {
  const navigate = useNavigate();

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.08, duration: 0.4 }}
      whileHover={{ y: -2, borderColor: "hsl(var(--racing-red) / 0.3)" }}
      onClick={() => navigate(`/analysis/${session.id}`)}
      className="glass-panel p-5 cursor-pointer group transition-shadow hover:shadow-lg hover:shadow-racing-red/5"
    >
      <div className="space-y-3">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="text-base font-bold tracking-wide">{session.track}</h3>
            <p className="text-xs text-muted-foreground mt-0.5">{session.car}</p>
          </div>
          <span className="text-[10px] text-muted-foreground font-mono">{session.date}</span>
        </div>

        <div className="flex items-center gap-5 pt-1 border-t border-border">
          <div className="flex items-center gap-1.5 text-xs">
            <Clock className="w-3 h-3 text-sector-green" />
            <span className="font-mono font-semibold text-sector-green">{session.bestLap}</span>
          </div>
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Flag className="w-3 h-3" />
            <span className="font-mono">{session.laps} laps</span>
          </div>
        </div>
      </div>
    </motion.div>
  );
};

export default SessionCard;
