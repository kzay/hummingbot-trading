import { useEffect } from "react";

import type { ActiveView } from "./useReviewData";
import { useDashboardStore } from "../store/useDashboardStore";

const VIEW_ORDER: ActiveView[] = ["realtime", "history", "service", "daily", "weekly", "journal"];
const TIMEFRAMES = [15, 30, 60, 300];

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  const tagName = target.tagName.toLowerCase();
  return tagName === "input" || tagName === "select" || tagName === "textarea" || target.isContentEditable;
}

export function useKeyboardShortcuts(activeView: ActiveView, onActiveViewChange: (view: ActiveView) => void): void {
  const instanceNames = useDashboardStore((state) => state.instanceNames);
  const instanceName = useDashboardStore((state) => state.settings.instanceName);
  const timeframeS = useDashboardStore((state) => state.settings.timeframeS);
  const updateSettings = useDashboardStore((state) => state.updateSettings);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || isEditableTarget(event.target) || event.metaKey || event.ctrlKey || event.altKey) {
        return;
      }

      if (/^[1-6]$/.test(event.key)) {
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

      if (event.key === "Escape") {
        document.querySelectorAll("details[open]").forEach((entry) => {
          (entry as HTMLDetailsElement).open = false;
        });
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [activeView, instanceName, instanceNames, onActiveViewChange, timeframeS, updateSettings]);
}
