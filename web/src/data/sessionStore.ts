import { create } from "zustand";
import type { VizData, SessionSummary } from "./types";

interface SessionState {
  vizData: VizData | null;
  summary: SessionSummary | null;
  isLoading: boolean;
  error: string | null;
  pipelineProgress: string | null;
  loadFromFiles: (vizFile: File, summaryFile?: File) => Promise<void>;
  loadFromUrl: (vizUrl: string, summaryUrl?: string) => Promise<void>;
  loadFromMcap: (mcapFile: File, boundaryFile?: File) => Promise<void>;
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
}));
