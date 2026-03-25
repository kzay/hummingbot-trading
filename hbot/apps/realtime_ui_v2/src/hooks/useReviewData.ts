import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useDashboardStore } from "../store/useDashboardStore";
import type { DailyReviewPayload, JournalReviewPayload, JournalTrade, WeeklyReviewPayload } from "../types/realtime";
import { readLocalStorage, writeLocalStorage } from "../utils/browserStorage";
import { parseDailyReviewResponse, parseJournalReviewResponse, parseWeeklyReviewResponse } from "../utils/realtimeParsers";

export type ActiveView = "realtime" | "history" | "service" | "daily" | "weekly" | "journal" | "backtest" | "research" | "ml";

interface ReviewState<TPayload> {
  source: string;
  review: TPayload | null;
  error: string;
  loading: boolean;
}

export interface UseReviewDataResult {
  activeView: ActiveView;
  setActiveView: (view: ActiveView) => void;
  dailyDay: string;
  setDailyDay: (day: string) => void;
  journalStartDay: string;
  setJournalStartDay: (day: string) => void;
  journalEndDay: string;
  setJournalEndDay: (day: string) => void;
  daily: ReviewState<DailyReviewPayload>;
  weekly: ReviewState<WeeklyReviewPayload>;
  journal: ReviewState<JournalReviewPayload>;
  selectedTradeId: string;
  setSelectedTradeId: (tradeId: string) => void;
  selectedTrade: JournalTrade | null;
  refreshDaily: () => Promise<void>;
  refreshWeekly: () => Promise<void>;
  refreshJournal: () => Promise<void>;
}

function todayUtc(): string {
  return new Date().toISOString().slice(0, 10);
}

function buildHeaders(token: string): HeadersInit {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token.trim()) {
    headers.Authorization = `Bearer ${token.trim()}`;
  }
  return headers;
}

export function useReviewData(): UseReviewDataResult {
  const apiBase = useDashboardStore((state) => state.settings.apiBase);
  const apiToken = useDashboardStore((state) => state.settings.apiToken);
  const instanceName = useDashboardStore((state) => state.settings.instanceName);

  const [activeView, setActiveViewState] = useState<ActiveView>(() => {
    const raw = readLocalStorage("hbV2ActiveView", "realtime");
    return ["realtime", "history", "service", "daily", "weekly", "journal", "backtest", "research", "ml"].includes(raw) ? (raw as ActiveView) : "realtime";
  });
  const [dailyDay, setDailyDayState] = useState<string>(() => readLocalStorage("hbV2DailyDay", todayUtc()));
  const [journalStartDay, setJournalStartDayState] = useState<string>(() => readLocalStorage("hbV2JournalStartDay", ""));
  const [journalEndDay, setJournalEndDayState] = useState<string>(() => readLocalStorage("hbV2JournalEndDay", ""));

  const [daily, setDaily] = useState<ReviewState<DailyReviewPayload>>({
    source: "",
    review: null,
    error: "",
    loading: false,
  });
  const [weekly, setWeekly] = useState<ReviewState<WeeklyReviewPayload>>({
    source: "",
    review: null,
    error: "",
    loading: false,
  });
  const [journal, setJournal] = useState<ReviewState<JournalReviewPayload>>({
    source: "",
    review: null,
    error: "",
    loading: false,
  });
  const [selectedTradeId, setSelectedTradeIdState] = useState<string>("");
  const selectedTradeIdRef = useRef(selectedTradeId);

  const dailyRequestRef = useRef(0);
  const weeklyRequestRef = useRef(0);
  const journalRequestRef = useRef(0);
  const dailyAbortRef = useRef<AbortController | null>(null);
  const weeklyAbortRef = useRef<AbortController | null>(null);
  const journalAbortRef = useRef<AbortController | null>(null);

  const setActiveView = useCallback((view: ActiveView) => {
    setActiveViewState(view);
    writeLocalStorage("hbV2ActiveView", view);
  }, []);

  const setDailyDay = useCallback((day: string) => {
    setDailyDayState(day);
    writeLocalStorage("hbV2DailyDay", day);
  }, []);

  const setJournalStartDay = useCallback((day: string) => {
    setJournalStartDayState(day);
    writeLocalStorage("hbV2JournalStartDay", day);
  }, []);

  const setJournalEndDay = useCallback((day: string) => {
    setJournalEndDayState(day);
    writeLocalStorage("hbV2JournalEndDay", day);
  }, []);

  const setSelectedTradeId = useCallback((tradeId: string) => {
    setSelectedTradeIdState(tradeId);
    selectedTradeIdRef.current = tradeId;
  }, []);

  const refreshDaily = useCallback(async () => {
    if (!instanceName.trim()) {
      return;
    }
    dailyAbortRef.current?.abort();
    const controller = new AbortController();
    dailyAbortRef.current = controller;
    const requestId = dailyRequestRef.current + 1;
    dailyRequestRef.current = requestId;
    setDaily((state) => ({ ...state, loading: true, error: "" }));
    const params = new URLSearchParams();
    params.set("instance_name", instanceName.trim());
    if (dailyDay) {
      params.set("day", dailyDay);
    }
    try {
      const response = await fetch(`${apiBase}/api/v1/review/daily?${params.toString()}`, {
        headers: buildHeaders(apiToken),
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new Error(`daily HTTP ${response.status}`);
      }
      const payload = parseDailyReviewResponse(await response.json());
      if (controller.signal.aborted || requestId !== dailyRequestRef.current) {
        return;
      }
      setDaily({
        source: String(payload.source || ""),
        review: payload.review || null,
        error: "",
        loading: false,
      });
      if (payload.review?.day) {
        setDailyDay(String(payload.review.day));
      }
    } catch (error) {
      if (controller.signal.aborted || requestId !== dailyRequestRef.current) {
        return;
      }
      const message = error instanceof Error ? error.message : String(error);
      setDaily({
        source: "",
        review: null,
        error: `Daily review unavailable: ${message}`,
        loading: false,
      });
    }
  }, [apiBase, apiToken, dailyDay, instanceName, setDailyDay]);

  const refreshWeekly = useCallback(async () => {
    if (!instanceName.trim()) {
      return;
    }
    weeklyAbortRef.current?.abort();
    const controller = new AbortController();
    weeklyAbortRef.current = controller;
    const requestId = weeklyRequestRef.current + 1;
    weeklyRequestRef.current = requestId;
    setWeekly((state) => ({ ...state, loading: true, error: "" }));
    const params = new URLSearchParams();
    params.set("instance_name", instanceName.trim());
    try {
      const response = await fetch(`${apiBase}/api/v1/review/weekly?${params.toString()}`, {
        headers: buildHeaders(apiToken),
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new Error(`weekly HTTP ${response.status}`);
      }
      const payload = parseWeeklyReviewResponse(await response.json());
      if (controller.signal.aborted || requestId !== weeklyRequestRef.current) {
        return;
      }
      setWeekly({
        source: String(payload.source || ""),
        review: payload.review || null,
        error: "",
        loading: false,
      });
    } catch (error) {
      if (controller.signal.aborted || requestId !== weeklyRequestRef.current) {
        return;
      }
      const message = error instanceof Error ? error.message : String(error);
      setWeekly({
        source: "",
        review: null,
        error: `Weekly review unavailable: ${message}`,
        loading: false,
      });
    }
  }, [apiBase, apiToken, instanceName]);

  const refreshJournal = useCallback(async () => {
    if (!instanceName.trim()) {
      return;
    }
    journalAbortRef.current?.abort();
    const controller = new AbortController();
    journalAbortRef.current = controller;
    const requestId = journalRequestRef.current + 1;
    journalRequestRef.current = requestId;
    setJournal((state) => ({ ...state, loading: true, error: "" }));
    const params = new URLSearchParams();
    params.set("instance_name", instanceName.trim());
    if (journalStartDay) {
      params.set("start_day", journalStartDay);
    }
    if (journalEndDay) {
      params.set("end_day", journalEndDay);
    }
    try {
      const response = await fetch(`${apiBase}/api/v1/review/journal?${params.toString()}`, {
        headers: buildHeaders(apiToken),
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new Error(`journal HTTP ${response.status}`);
      }
      const payload = parseJournalReviewResponse(await response.json());
      if (controller.signal.aborted || requestId !== journalRequestRef.current) {
        return;
      }
      const review = payload.review || null;
      const trades = Array.isArray(review?.trades) ? review.trades : [];
      const currentTradeId = selectedTradeIdRef.current;
      const hasSelected = trades.some((trade) => String(trade.trade_id || "") === currentTradeId);
      const nextTradeId = hasSelected ? currentTradeId : String(trades.at(-1)?.trade_id || "");
      setSelectedTradeIdState(nextTradeId);
      selectedTradeIdRef.current = nextTradeId;
      setJournal({
        source: String(payload.source || ""),
        review,
        error: "",
        loading: false,
      });
    } catch (error) {
      if (controller.signal.aborted || requestId !== journalRequestRef.current) {
        return;
      }
      const message = error instanceof Error ? error.message : String(error);
      setSelectedTradeIdState("");
      selectedTradeIdRef.current = "";
      setJournal({
        source: "",
        review: null,
        error: `Journal unavailable: ${message}`,
        loading: false,
      });
    }
  }, [
    journalEndDay,
    journalStartDay,
    apiBase,
    apiToken,
    instanceName,
  ]);

  useEffect(() => {
    dailyAbortRef.current?.abort();
    weeklyAbortRef.current?.abort();
    journalAbortRef.current?.abort();
    setDaily({ source: "", review: null, error: "", loading: false });
    setWeekly({ source: "", review: null, error: "", loading: false });
    setJournal({ source: "", review: null, error: "", loading: false });
    setSelectedTradeIdState("");
    selectedTradeIdRef.current = "";
  }, [instanceName]);

  useEffect(() => {
    return () => {
      dailyAbortRef.current?.abort();
      weeklyAbortRef.current?.abort();
      journalAbortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (activeView === "daily") {
      void refreshDaily();
    }
    if (activeView === "weekly") {
      void refreshWeekly();
    }
    if (activeView === "journal") {
      void refreshJournal();
    }
  }, [activeView, refreshDaily, refreshJournal, refreshWeekly]);

  const selectedTrade = useMemo(() => {
    const trades = Array.isArray(journal.review?.trades) ? journal.review?.trades : [];
    if (trades.length === 0) {
      return null;
    }
    return trades.find((trade) => String(trade.trade_id || "") === selectedTradeId) || trades[trades.length - 1] || null;
  }, [journal.review?.trades, selectedTradeId]);

  return {
    activeView,
    setActiveView,
    dailyDay,
    setDailyDay,
    journalStartDay,
    setJournalStartDay,
    journalEndDay,
    setJournalEndDay,
    daily,
    weekly,
    journal,
    selectedTradeId,
    setSelectedTradeId,
    selectedTrade,
    refreshDaily,
    refreshWeekly,
    refreshJournal,
  };
}
