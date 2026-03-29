import { create } from "zustand";
import type { VizData, SessionSummary, VizMarker } from "./types";

/** Context for asking AI about a specific verdict */
export interface AskAIContext {
  marker: VizMarker;
  question: string;
}

interface SessionState {
  vizData: VizData | null;
  summary: SessionSummary | null;
  isLoading: boolean;
  error: string | null;
  pipelineProgress: string | null;
  uploadProgress: number | null; // 0-100 during upload, null otherwise
  // Chat context for "Ask AI" feature
  askAIContext: AskAIContext | null;
  chatOpen: boolean;
  loadFromUrl: (vizUrl: string, summaryUrl?: string) => Promise<void>;
  loadFromMcap: (mcapFile: File, boundaryFile?: File) => Promise<void>;
  // Ask AI about a specific verdict
  askAI: (marker: VizMarker) => void;
  // Ask AI about a segment score
  askAIAboutScore: (
    segmentId: string,
    segmentType: "corner" | "straight",
    score: number,
    mainIssue: string,
    components: Record<string, number>,
    features: Record<string, number | boolean>
  ) => void;
  // Clear the ask context (after it's been used)
  clearAskContext: () => void;
  // Toggle chat panel
  setChatOpen: (open: boolean) => void;
}

async function tryLoadGenerativeInsights(
  summaryUrl: string,
  summary: SessionSummary
): Promise<SessionSummary> {
  try {
    const genUrl = summaryUrl
      .replace("session_summary_fast.json", "generative_insights.json")
      .replace("session_summary_good.json", "generative_insights.json")
      .replace("session_summary.json", "generative_insights.json");
    const genRes = await fetch(genUrl);
    if (genRes.ok) {
      summary.generative_coaching = await genRes.json();
    }
  } catch {
    // generative insights are optional
  }
  return summary;
}

export const useSessionStore = create<SessionState>((set) => ({
  vizData: null,
  summary: null,
  isLoading: false,
  error: null,
  pipelineProgress: null,
  uploadProgress: null,
  askAIContext: null,
  chatOpen: false,

  loadFromUrl: async (vizUrl, summaryUrl) => {
    set({ isLoading: true, error: null, pipelineProgress: null });
    try {
      const vizRes = await fetch(vizUrl);
      if (!vizRes.ok) throw new Error(`Failed to load viz data: ${vizRes.status}`);
      const vizData = (await vizRes.json()) as VizData;

      let summary: SessionSummary | null = null;
      if (summaryUrl) {
        const sumRes = await fetch(summaryUrl);
        if (sumRes.ok) {
          summary = await tryLoadGenerativeInsights(
            summaryUrl,
            (await sumRes.json()) as SessionSummary
          );
        }
      }

      set({ vizData, summary, isLoading: false });
    } catch (e) {
      set({ error: (e as Error).message, isLoading: false });
    }
  },

  loadFromMcap: async (mcapFile, boundaryFile) => {
    set({ isLoading: true, error: null, pipelineProgress: "Uploading telemetry...", uploadProgress: 0 });
    try {
      const form = new FormData();
      form.append("mcap", mcapFile);
      if (boundaryFile) {
        form.append("boundaries", boundaryFile);
      }

      // Use XHR to track upload progress (fetch API doesn't support it)
      const data = await new Promise<{ viz_data: VizData; session_summary: SessionSummary }>(
        (resolve, reject) => {
          const xhr = new XMLHttpRequest();
          xhr.open("POST", "/api/analyze");

          xhr.upload.onprogress = (e) => {
            if (e.lengthComputable) {
              const pct = Math.round((e.loaded / e.total) * 100);
              set({
                uploadProgress: pct,
                pipelineProgress: pct < 100
                  ? `Uploading... ${pct}%`
                  : "Analyzing telemetry (~15s)...",
              });
            }
          };

          xhr.onload = () => {
            if (xhr.status >= 200 && xhr.status < 300) {
              try { resolve(JSON.parse(xhr.responseText)); }
              catch { reject(new Error("Invalid response from server")); }
            } else {
              reject(new Error(`Pipeline failed (${xhr.status}): ${xhr.responseText}`));
            }
          };

          xhr.onerror = () => reject(new Error("Network error during upload"));
          xhr.send(form);
        }
      );

      set({ vizData: data.viz_data, summary: data.session_summary, isLoading: false, pipelineProgress: null, uploadProgress: null });
    } catch (e) {
      set({ error: (e as Error).message, isLoading: false, pipelineProgress: null, uploadProgress: null });
    }
  },

  askAI: (marker) => {
    const question = `Explain this issue in ${marker.segment}: "${marker.finding}" - What exactly went wrong and how can I fix it?`;
    set({
      askAIContext: { marker, question },
      chatOpen: true,
    });
  },

  askAIAboutScore: (segmentId, segmentType, score, mainIssue, components, features) => {
    // Build a detailed question with score breakdown and telemetry
    const scorePercent = (score * 100).toFixed(0);

    // Format component scores (what contributed to the score)
    const allComponents = Object.entries(components)
      .sort(([, a], [, b]) => a - b)
      .map(([name, val]) => `${name.replace(/_/g, " ")}: ${(val * 100).toFixed(0)}%`)
      .join(", ");

    // Format telemetry features (actual measured values)
    const telemetryLines: string[] = [];
    if (segmentType === "corner") {
      if (features.entry_speed_kmh) telemetryLines.push(`Entry speed: ${(features.entry_speed_kmh as number).toFixed(0)} km/h`);
      if (features.apex_speed_kmh) telemetryLines.push(`Apex speed: ${(features.apex_speed_kmh as number).toFixed(0)} km/h`);
      if (features.exit_speed_kmh) telemetryLines.push(`Exit speed: ${(features.exit_speed_kmh as number).toFixed(0)} km/h`);
      if (features.max_lateral_g) telemetryLines.push(`Max lateral G: ${(features.max_lateral_g as number).toFixed(2)}G`);
      if (features.braking_g) telemetryLines.push(`Braking G: ${(features.braking_g as number).toFixed(2)}G`);
      if (features.trail_brake_quality !== undefined) telemetryLines.push(`Trail brake quality: ${((features.trail_brake_quality as number) * 100).toFixed(0)}%`);
      if (features.coast_time_s) telemetryLines.push(`Coast time: ${(features.coast_time_s as number).toFixed(2)}s`);
    } else {
      if (features.entry_speed_kmh) telemetryLines.push(`Entry speed: ${(features.entry_speed_kmh as number).toFixed(0)} km/h`);
      if (features.top_speed_kmh) telemetryLines.push(`Top speed: ${(features.top_speed_kmh as number).toFixed(0)} km/h`);
      if (features.exit_speed_kmh) telemetryLines.push(`Exit speed: ${(features.exit_speed_kmh as number).toFixed(0)} km/h`);
      if (features.throttle_pct) telemetryLines.push(`Full throttle: ${(features.throttle_pct as number).toFixed(0)}%`);
      if (features.max_accel_g) telemetryLines.push(`Max acceleration: ${(features.max_accel_g as number).toFixed(2)}G`);
    }
    const telemetry = telemetryLines.join(", ");

    const question = `Analyze my ${segmentType} performance at ${segmentId}:

**Overall Score:** ${scorePercent}/100
**Main Issue:** ${mainIssue}
**Component Scores:** ${allComponents}
**Telemetry Data:** ${telemetry}

Based on these exact numbers, explain:
1. What specifically caused each low component score?
2. What technique changes would improve my weakest areas?
3. What should my target values be for entry/apex/exit speed?`;

    // Create a minimal marker for the context
    const marker = {
      x: 0,
      y: 0,
      segment: segmentId,
      category: "scoring",
      severity: "medium" as const,
      finding: `Score: ${scorePercent}/100, Main issue: ${mainIssue}`,
      reasoning: "",
      action: "",
      time_impact_s: 0,
    };

    set({
      askAIContext: { marker, question },
      chatOpen: true,
    });
  },

  clearAskContext: () => {
    set({ askAIContext: null });
  },

  setChatOpen: (open) => {
    set({ chatOpen: open });
  },
}));
