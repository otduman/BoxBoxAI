import { LineChart, Line, XAxis, YAxis, ResponsiveContainer, Area, AreaChart } from "recharts";
import { telemetryData } from "@/data/mockData";

const TelemetryMini = () => {
  const data = telemetryData.slice(0, 25);

  return (
    <div className="pt-3 space-y-2">
      {/* Speed trace */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <span className="text-[9px] uppercase tracking-[0.15em] text-muted-foreground">Speed (km/h)</span>
          <div className="flex gap-3 text-[9px] text-muted-foreground">
            <span className="flex items-center gap-1"><span className="w-3 h-[1px] bg-sector-green inline-block" /> Fast</span>
            <span className="flex items-center gap-1"><span className="w-3 h-[1px] bg-sector-yellow inline-block" /> Current</span>
          </div>
        </div>
        <ResponsiveContainer width="100%" height={60}>
          <AreaChart data={data}>
            <defs>
              <linearGradient id="speedGreen" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="hsl(145, 70%, 50%)" stopOpacity={0.2} />
                <stop offset="100%" stopColor="hsl(145, 70%, 50%)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <Area type="monotone" dataKey="speedFast" stroke="hsl(145, 70%, 50%)" strokeWidth={1.5} fill="url(#speedGreen)" dot={false} />
            <Area type="monotone" dataKey="speedCurrent" stroke="hsl(45, 95%, 55%)" strokeWidth={1} fill="none" dot={false} strokeDasharray="3 2" />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Throttle/Brake */}
      <div>
        <span className="text-[9px] uppercase tracking-[0.15em] text-muted-foreground">Throttle / Brake</span>
        <ResponsiveContainer width="100%" height={40}>
          <LineChart data={data}>
            <Line type="monotone" dataKey="throttleFast" stroke="hsl(145, 70%, 50%)" strokeWidth={1} dot={false} />
            <Line type="monotone" dataKey="brakeFast" stroke="hsl(0, 95%, 44%)" strokeWidth={1} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

export default TelemetryMini;
