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
  // Chat context for "Ask AI" feature
  askAIContext: AskAIContext | null;
  chatOpen: boolean;
  loadFromFiles: (vizFile: File, summaryFile?: File) => Promise<void>;
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
  askAIContext: null,
  chatOpen: false,

  loadFromFiles: async (vizFile, summaryFile) => {
    set({ isLoading: true, error: null, pipelineProgress: null });
    try {
      const vizText = await vizFile.text();
      const vizData = JSON.parse(vizText) as VizData;

      let summary: SessionSummary | null = null;
      if (summaryFile) {
        const sumText = await summaryFile.text();
        summary = JSON.parse(sumText) as SessionSummary;
      }

      set({ vizData, summary, isLoading: false });
    } catch (e) {
      set({ error: (e as Error).message, isLoading: false });
    }
  },

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
    set({ isLoading: true, error: null, pipelineProgress: "Uploading telemetry..." });
    try {
      const form = new FormData();
      form.append("mcap", mcapFile);
      if (boundaryFile) {
        form.append("boundaries", boundaryFile);
      }

      set({ pipelineProgress: "Analyzing telemetry (this may take ~15s)..." });

      const res = await fetch("/api/analyze", { method: "POST", body: form });
      if (!res.ok) {
        const body = await res.text();
        throw new Error(`Pipeline failed (${res.status}): ${body}`);
      }

      const data = await res.json();
      const vizData = data.viz_data as VizData;
      const summary = data.session_summary as SessionSummary;

      set({ vizData, summary, isLoading: false, pipelineProgress: null });
    } catch (e) {
      set({ error: (e as Error).message, isLoading: false, pipelineProgress: null });
    }
  },

  askAI: (marker) => {
    const question = `Explain this issue in ${marker.segment}: "${marker.finding}" - What exactly went wrong and how can I fix it?`;
    set({
      askAIContext: { marker, question },
      chatOpen: true,
    });
  },

  askAIAboutScore: (segmentId, score, mainIssue, components) => {
    // Build a detailed question with score breakdown
    const scorePercent = (score * 100).toFixed(0);
    const weakestComponents = Object.entries(components)
      .sort(([, a], [, b]) => a - b)
      .slice(0, 3)
      .map(([name, val]) => `${name}: ${(val * 100).toFixed(0)}%`)
      .join(", ");

    const question = `My performance score for ${segmentId} is ${scorePercent}/100. The main issue is "${mainIssue}". My weakest areas are: ${weakestComponents}. Why did I score low in these areas and what specific techniques should I focus on to improve?`;

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
