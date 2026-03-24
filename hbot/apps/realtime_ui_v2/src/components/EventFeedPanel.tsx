import { memo, useEffect, useMemo, useRef } from "react";

import { useDashboardStore } from "../store/useDashboardStore";
import { Panel } from "./Panel";

function lineClass(line: string): string {
  const lower = line.toLowerCase();
  if (lower.includes("error") || lower.includes("exception") || lower.includes("fail"))
    return "feed-line-error";
  if (lower.includes("bot_fill") || lower.includes("order_fill"))
    return lower.includes("sell") ? "feed-line-sell" : "feed-line-buy";
  if (lower.includes("market_quote") || lower.includes("market_depth"))
    return "feed-line-dim";
  if (lower.includes("warn"))
    return "feed-line-warn";
  return "";
}

export const EventFeedPanel = memo(function EventFeedPanel() {
  const eventFilter = useDashboardStore((state) => state.settings.eventFilter);
  const autoScrollFeed = useDashboardStore((state) => state.settings.autoScrollFeed);
  const feedPaused = useDashboardStore((state) => state.settings.feedPaused);
  const eventLines = useDashboardStore((state) => state.eventLines);
  const updateSettings = useDashboardStore((state) => state.updateSettings);
  const clearEventFeed = useDashboardStore((state) => state.clearEventFeed);
  const feedRef = useRef<HTMLDivElement | null>(null);
  const filteredLines = useMemo(() => {
    const query = eventFilter.trim().toLowerCase();
    if (!query) {
      return eventLines;
    }
    return eventLines.filter((line) => line.toLowerCase().includes(query));
  }, [eventFilter, eventLines]);

  useEffect(() => {
    if (!autoScrollFeed || feedPaused) {
      return;
    }
    if (feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [filteredLines, autoScrollFeed, feedPaused]);

  return (
    <Panel
      title={<>Feed<span className="panel-count">({eventLines.length})</span></>}
      className="panel-span-6"
    >
      <div className="panel-toolbar">
        <label>
          Search
          <input
            type="text"
            placeholder="event type / stream / error"
            value={eventFilter}
            onChange={(event) => updateSettings({ eventFilter: event.target.value })}
          />
        </label>
        <button
          type="button"
          className="secondary"
          onClick={() => updateSettings({ feedPaused: !feedPaused })}
          aria-label={feedPaused ? "Resume event feed" : "Pause event feed"}
        >
          {feedPaused ? "▶" : "⏸"}
        </button>
        <button type="button" className="secondary" onClick={clearEventFeed}>
          Clear
        </button>
      </div>
      <div ref={feedRef} className="event-feed">
        {filteredLines.map((line, i) => (
          <div key={i} className={`feed-line ${lineClass(line)}`}>{line}</div>
        ))}
      </div>
    </Panel>
  );
});
