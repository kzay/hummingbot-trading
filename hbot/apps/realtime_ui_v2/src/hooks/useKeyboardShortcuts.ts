import { useCallback, useEffect, useState } from "react";

import type { ActiveView } from "./useReviewData";
import { useDashboardStore } from "../store/useDashboardStore";

const VIEW_ORDER: ActiveView[] = ["realtime", "history", "service", "daily", "weekly", "journal", "backtest", "research", "ml"];
const TIMEFRAMES = [15, 30, 60, 300];

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  const tagName = target.tagName.toLowerCase();
  return tagName === "input" || tagName === "select" || tagName === "textarea" || target.isContentEditable;
}

interface KeyboardShortcutState {
  helpOpen: boolean;
  toggleHelp: () => void;
}

export function useKeyboardShortcuts(
  activeView: ActiveView,
  onActiveViewChange: (view: ActiveView) => void,
): KeyboardShortcutState {
  const instanceNames = useDashboardStore((state) => state.instanceNames);
  const instanceName = useDashboardStore((state) => state.settings.instanceName);
  const timeframeS = useDashboardStore((state) => state.settings.timeframeS);
  const feedPaused = useDashboardStore((state) => state.settings.feedPaused);
  const updateSettings = useDashboardStore((state) => state.updateSettings);
  const [helpOpen, setHelpOpen] = useState(false);
  const toggleHelp = useCallback(() => setHelpOpen((prev) => !prev), []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) {
        return;
      }

      if (event.key === "Escape") {
        if (helpOpen) {
          event.preventDefault();
          setHelpOpen(false);
          return;
        }
        document.querySelectorAll("details[open]").forEach((entry) => {
          (entry as HTMLDetailsElement).open = false;
        });
        return;
      }

      if (event.key === "?") {
        event.preventDefault();
        setHelpOpen((prev) => !prev);
        return;
      }

      if (isEditableTarget(event.target)) {
        return;
      }

      if (/^[1-9]$/.test(event.key)) {
        const nextView = VIEW_ORDER[Number(event.key) - 1];
        if (nextView) {
          event.preventDefault();
          onActiveViewChange(nextView);
        }
        return;
      }

      if (event.key.toLowerCase() === "t") {
        event.preventDefault();
        const currentIndex = TIMEFRAMES.indexOf(Number(timeframeS || 60));
        const nextTimeframe = TIMEFRAMES[(currentIndex + 1 + TIMEFRAMES.length) % TIMEFRAMES.length];
        updateSettings({ timeframeS: nextTimeframe });
        return;
      }

      if ((event.key === "[" || event.key === "]") && instanceNames.length > 0) {
        event.preventDefault();
        const currentIndex = Math.max(0, instanceNames.indexOf(instanceName));
        const delta = event.key === "]" ? 1 : -1;
        const nextIndex = (currentIndex + delta + instanceNames.length) % instanceNames.length;
        updateSettings({ instanceName: instanceNames[nextIndex] });
        return;
      }

      if (event.key === "/") {
        event.preventDefault();
        const input = document.querySelector<HTMLInputElement>(
          ".panel-toolbar input[type='text']",
        );
        if (input) input.focus();
        return;
      }

      if (event.key === " ") {
        event.preventDefault();
        updateSettings({ feedPaused: !feedPaused });
        return;
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [activeView, feedPaused, helpOpen, instanceName, instanceNames, onActiveViewChange, timeframeS, updateSettings]);

  return { helpOpen, toggleHelp };
}
