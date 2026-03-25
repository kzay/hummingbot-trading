import { useCallback, useEffect, useState } from "react";
import { useShallow } from "zustand/react/shallow";

import { useDashboardStore } from "../store/useDashboardStore";
import type {
  CandidateDetail,
  ExplorationSession,
  ResearchCandidate,
} from "../types/research";
import type { LaunchExplorationRequest } from "../types/research";
import {
  fetchCandidateDetail,
  fetchCandidates,
  fetchExplorations,
} from "../utils/researchApi";

export type ResearchSubView = "scoreboard" | "candidate-detail" | "exploration-detail";

export function useResearchData() {
  const { apiBase, apiToken } = useDashboardStore(
    useShallow((s) => ({ apiBase: s.settings.apiBase, apiToken: s.settings.apiToken })),
  );

  const [subView, setSubView] = useState<ResearchSubView>("scoreboard");
  const [candidates, setCandidates] = useState<ResearchCandidate[]>([]);
  const [explorations, setExplorations] = useState<ExplorationSession[]>([]);
  const [selectedDetail, setSelectedDetail] = useState<CandidateDetail | null>(null);
  const [selectedExplorationId, setSelectedExplorationId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showLaunchModal, setShowLaunchModal] = useState(false);
  const [rerunConfig, setRerunConfig] = useState<Partial<LaunchExplorationRequest> | undefined>(undefined);

  const refreshAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cands, expls] = await Promise.all([
        fetchCandidates(apiBase, apiToken),
        fetchExplorations(apiBase, apiToken),
      ]);
      setCandidates(cands);
      setExplorations(expls);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [apiBase, apiToken]);

  useEffect(() => { void refreshAll(); }, [refreshAll]);

  const handleCandidateSelect = useCallback(async (name: string) => {
    setError(null);
    try {
      const detail = await fetchCandidateDetail(apiBase, apiToken, name);
      setSelectedDetail(detail);
      setSubView("candidate-detail");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [apiBase, apiToken]);

  const handleExplorationSelect = useCallback((sessionId: string) => {
    setSelectedExplorationId(sessionId);
    setSubView("exploration-detail");
  }, []);

  const handleBack = useCallback(() => {
    setSubView("scoreboard");
    setSelectedDetail(null);
    setSelectedExplorationId(null);
  }, []);

  const handleRerun = useCallback((params: Partial<LaunchExplorationRequest>) => {
    setRerunConfig(params);
    setShowLaunchModal(true);
  }, []);

  const handleLaunched = useCallback((sessionId: string) => {
    setShowLaunchModal(false);
    setRerunConfig(undefined);
    setSelectedExplorationId(sessionId);
    setSubView("exploration-detail");
    void refreshAll();
  }, [refreshAll]);

  const openLaunchModal = useCallback(() => {
    setShowLaunchModal(true);
  }, []);

  const closeLaunchModal = useCallback(() => {
    setShowLaunchModal(false);
    setRerunConfig(undefined);
  }, []);

  return {
    apiBase,
    apiToken,
    subView,
    candidates,
    explorations,
    selectedDetail,
    selectedExplorationId,
    error,
    loading,
    showLaunchModal,
    rerunConfig,
    refreshAll,
    handleCandidateSelect,
    handleExplorationSelect,
    handleBack,
    handleRerun,
    handleLaunched,
    openLaunchModal,
    closeLaunchModal,
  };
}
