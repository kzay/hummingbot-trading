import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useShallow } from "zustand/react/shallow";

import { useDashboardStore } from "../store/useDashboardStore";
import type {
  BacktestJob,
  BacktestPreset,
  BacktestResultSummary,
} from "../types/backtest";
import {
  cancelJob,
  createJob,
  fetchJobHistory,
  fetchJobStatus,
  fetchPresets,
} from "../utils/backtestApi";

export function useBacktestData() {
  const { apiBase, apiToken } = useDashboardStore(
    useShallow((s) => ({ apiBase: s.settings.apiBase, apiToken: s.settings.apiToken })),
  );

  const [presets, setPresets] = useState<BacktestPreset[]>([]);
  const [selectedPreset, setSelectedPreset] = useState("");
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [currentJob, setCurrentJob] = useState<BacktestJob | null>(null);
  const [viewedResult, setViewedResult] = useState<BacktestResultSummary | null>(null);
  const [history, setHistory] = useState<BacktestJob[]>([]);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollFailRef = useRef(0);

  const isRunning = currentJob?.status === "running" || currentJob?.status === "pending";

  useEffect(() => {
    fetchPresets(apiBase, apiToken)
      .then((p) => {
        setPresets(p);
        if (p.length && !selectedPreset) setSelectedPreset(p[0].id);
      })
      .catch((e) => setError(e.message));
  }, [apiBase, apiToken]);

  const refreshHistory = useCallback(() => {
    fetchJobHistory(apiBase, apiToken)
      .then(setHistory)
      .catch(() => {});
  }, [apiBase, apiToken]);

  useEffect(() => { refreshHistory(); }, [refreshHistory]);

  const activePreset = useMemo(
    () => presets.find((p) => p.id === selectedPreset),
    [presets, selectedPreset],
  );
  useEffect(() => {
    if (!activePreset) return;
    queueMicrotask(() => {
      setOverrides({
        initial_equity: String(activePreset.initial_equity),
        start_date: activePreset.start_date,
        end_date: activePreset.end_date,
      });
    });
  }, [activePreset]);

  useEffect(() => {
    if (!currentJob || !isRunning) return;
    pollFailRef.current = 0;
    pollRef.current = setInterval(async () => {
      try {
        const status = await fetchJobStatus(apiBase, apiToken, currentJob.id);
        pollFailRef.current = 0;
        setCurrentJob(status);
        if (!["running", "pending"].includes(status.status)) {
          if (pollRef.current) clearInterval(pollRef.current);
          if (status.result_summary) setViewedResult(status.result_summary);
          if (status.status === "completed") {
            setError(null);
          } else if (["failed", "timed_out"].includes(status.status) && status.error) {
            setError(status.error);
          }
          refreshHistory();
        }
      } catch {
        pollFailRef.current += 1;
        if (pollFailRef.current >= 8) {
          setError("Cannot reach backtest API while polling job status — check connection and realtime-ui-api.");
        }
      }
    }, 1500);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [currentJob?.id, isRunning, apiBase, apiToken, refreshHistory]);

  const handleRun = useCallback(async () => {
    setError(null);
    setViewedResult(null);
    try {
      const parsed: Record<string, unknown> = {};
      if (overrides.initial_equity) parsed.initial_equity = parseFloat(overrides.initial_equity);
      if (overrides.start_date) parsed.start_date = overrides.start_date;
      if (overrides.end_date) parsed.end_date = overrides.end_date;
      const job = await createJob(apiBase, apiToken, selectedPreset, parsed);
      setCurrentJob(job);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [apiBase, apiToken, selectedPreset, overrides]);

  const handleCancel = useCallback(async () => {
    if (!currentJob?.id?.trim()) return;
    try {
      await cancelJob(apiBase, apiToken, currentJob.id);
      setCurrentJob((prev) => prev ? { ...prev, status: "cancelled" } : null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [apiBase, apiToken, currentJob?.id]);

  const handleHistorySelect = useCallback((job: BacktestJob) => {
    setCurrentJob(job);
    setViewedResult(job.result_summary ?? null);
  }, []);

  return {
    apiBase,
    apiToken,
    presets,
    selectedPreset,
    setSelectedPreset,
    overrides,
    setOverrides,
    currentJob,
    viewedResult,
    history,
    error,
    isRunning,
    handleRun,
    handleCancel,
    handleHistorySelect,
  };
}
