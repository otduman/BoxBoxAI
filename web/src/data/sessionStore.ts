import { create } from "zustand";
import type { VizData, SessionSummary } from "./types";

interface SessionState {
  vizData: VizData | null;
  summary: SessionSummary | null;
  isLoading: boolean;
  error: string | null;
  loadFromFiles: (vizFile: File, summaryFile?: File) => Promise<void>;
  loadFromUrl: (vizUrl: string, summaryUrl?: string) => Promise<void>;
}

export const useSessionStore = create<SessionState>((set) => ({
  vizData: null,
  summary: null,
  isLoading: false,
  error: null,

  loadFromFiles: async (vizFile, summaryFile) => {
    set({ isLoading: true, error: null });
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
    set({ isLoading: true, error: null });
    try {
      const vizRes = await fetch(vizUrl);
      if (!vizRes.ok) throw new Error(`Failed to load viz data: ${vizRes.status}`);
      const vizData = (await vizRes.json()) as VizData;

      let summary: SessionSummary | null = null;
      if (summaryUrl) {
        const sumRes = await fetch(summaryUrl);
        if (sumRes.ok) {
          summary = (await sumRes.json()) as SessionSummary;
        }
      }

      set({ vizData, summary, isLoading: false });
    } catch (e) {
      set({ error: (e as Error).message, isLoading: false });
    }
  },
}));
