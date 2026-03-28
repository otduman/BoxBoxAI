export interface Session {
  id: string;
  track: string;
  car: string;
  bestLap: string;
  date: string;
  laps: number;
}

export interface Verdict {
  id: string;
  corner: string;
  issue: string;
  severity: "high" | "medium";
  timeLoss: string;
  sector: "purple" | "green" | "yellow";
  x: number;
  y: number;
}

export interface TelemetryPoint {
  distance: number;
  speedFast: number;
  speedCurrent: number;
  throttleFast: number;
  throttleCurrent: number;
  brakeFast: number;
  brakeCurrent: number;
}

export const sessions: Session[] = [
  { id: "1", track: "Spa-Francorchamps", car: "Ferrari 296 GT3", bestLap: "2:17.482", date: "2025-03-15", laps: 34 },
  { id: "2", track: "Monza", car: "Porsche 911 GT3 R", bestLap: "1:46.103", date: "2025-03-12", laps: 28 },
  { id: "3", track: "Silverstone", car: "McLaren 720S GT3", bestLap: "1:56.741", date: "2025-03-08", laps: 42 },
  { id: "4", track: "Barcelona", car: "AMG GT3 Evo", bestLap: "1:42.619", date: "2025-02-28", laps: 31 },
];

// More realistic Spa-Francorchamps outline with proper corners
// Coordinates in 0-1000 range for precision
export const spaTrackPath = `
  M 750,80
  C 780,80 800,85 810,100
  L 820,130
  C 825,145 820,160 810,170
  L 790,200
  C 775,218 760,240 755,260
  C 748,285 740,310 720,340
  C 700,370 670,400 640,420
  C 610,440 575,455 540,465
  C 500,478 460,485 420,490
  C 380,495 340,498 300,500
  C 260,502 230,510 200,525
  C 170,545 150,570 140,600
  C 128,635 125,670 130,700
  C 135,730 148,755 170,775
  C 195,798 225,810 260,815
  C 300,820 340,815 380,800
  C 420,785 455,765 490,740
  C 525,715 555,688 580,660
  C 605,632 625,605 645,580
  C 665,555 680,530 695,505
  C 710,480 725,452 740,425
  C 755,398 768,370 778,342
  C 790,310 798,280 805,250
  C 812,220 815,195 815,170
  C 815,145 810,125 800,110
  L 780,85
  C 770,78 758,78 750,80
  Z
`;

export const sectorSegments = [
  // Sector 1: Start/Finish → La Source → Eau Rouge (top right, going down)
  {
    id: "s1",
    d: "M 750,80 C 780,80 800,85 810,100 L 820,130 C 825,145 820,160 810,170 L 790,200 C 775,218 760,240 755,260 C 748,285 740,310 720,340",
    type: "purple" as const,
  },
  // Sector 2: Kemmel → Rivage → Pouhon (middle section going left and down)
  {
    id: "s2",
    d: "M 720,340 C 700,370 670,400 640,420 C 610,440 575,455 540,465 C 500,478 460,485 420,490 C 380,495 340,498 300,500 C 260,502 230,510 200,525 C 170,545 150,570 140,600",
    type: "green" as const,
  },
  // Sector 3: Fagnes → Stavelot → Bus Stop chicane (bottom, going right and up)
  {
    id: "s3",
    d: "M 140,600 C 128,635 125,670 130,700 C 135,730 148,755 170,775 C 195,798 225,810 260,815 C 300,820 340,815 380,800 C 420,785 455,765 490,740 C 525,715 555,688 580,660",
    type: "yellow" as const,
  },
  // Sector 4: Return to Start/Finish (right side going up)
  {
    id: "s4",
    d: "M 580,660 C 605,632 625,605 645,580 C 665,555 680,530 695,505 C 710,480 725,452 740,425 C 755,398 768,370 778,342 C 790,310 798,280 805,250 C 812,220 815,195 815,170 C 815,145 810,125 800,110 L 780,85 C 770,78 758,78 750,80",
    type: "green" as const,
  },
];

export const verdicts: Verdict[] = [
  {
    id: "v1",
    corner: "La Source",
    issue: "Late braking caused understeer on entry, missed apex by 1.2m",
    severity: "high",
    timeLoss: "-0.18s",
    sector: "yellow",
    x: 810, y: 170,
  },
  {
    id: "v2",
    corner: "Eau Rouge",
    issue: "Lifted throttle mid-corner, lost momentum through Raidillon",
    severity: "high",
    timeLoss: "-0.31s",
    sector: "yellow",
    x: 755, y: 260,
  },
  {
    id: "v3",
    corner: "Pouhon",
    issue: "Good entry speed but 2 seconds of wheelspin on exit",
    severity: "medium",
    timeLoss: "-0.10s",
    sector: "green",
    x: 200, y: 525,
  },
  {
    id: "v4",
    corner: "Bus Stop",
    issue: "Braked 8m too early, overly cautious entry",
    severity: "medium",
    timeLoss: "-0.14s",
    sector: "yellow",
    x: 750, y: 80,
  },
];

// Generate telemetry trace
export const telemetryData: TelemetryPoint[] = Array.from({ length: 50 }, (_, i) => {
  const d = i * 140;
  const base = 180 + Math.sin(i * 0.3) * 80 + Math.cos(i * 0.15) * 40;
  return {
    distance: d,
    speedFast: Math.max(60, Math.min(310, base + 10)),
    speedCurrent: Math.max(55, Math.min(305, base + Math.sin(i * 0.5) * 15 - 5)),
    throttleFast: Math.max(0, Math.min(100, 70 + Math.sin(i * 0.4) * 30)),
    throttleCurrent: Math.max(0, Math.min(100, 65 + Math.sin(i * 0.4) * 30 + Math.cos(i * 0.7) * 10)),
    brakeFast: Math.max(0, Math.min(100, Math.max(0, -Math.sin(i * 0.3) * 60))),
    brakeCurrent: Math.max(0, Math.min(100, Math.max(0, -Math.sin(i * 0.3) * 55 + 5))),
  };
});

export const trackPath = spaTrackPath;
