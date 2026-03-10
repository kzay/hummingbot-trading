import { useEffect, useMemo, useRef } from "react";

import { useDashboardStore } from "../store/useDashboardStore";
import { Panel } from "./Panel";

export function EventFeedPanel() {
  const eventFilter = useDashboardStore((state) => state.settings.eventFilter);
  const autoScrollFeed = useDashboardStore((state) => state.settings.autoScrollFeed);
  const feedPaused = useDashboardStore((state) => state.settings.feedPaused);
  const eventLines = useDashboardStore((state) => state.eventLines);
  const updateSettings = useDashboardStore((state) => state.updateSettings);
  const clearEventFeed = useDashboardStore((state) => state.clearEventFeed);
  const feedRef = useRef<HTMLPreElement | null>(null);
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
    <Panel title="Live Feed" subtitle="Searchable connection and runtime event tape." className="panel-span-6">
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
        <button type="button" className="secondary" onClick={() => updateSettings({ feedPaused: !feedPaused })}>
          {feedPaused ? "Resume" : "Pause"}
        </button>
        <button type="button" className="secondary" onClick={() => updateSettings({ autoScrollFeed: !autoScrollFeed })}>
          {autoScrollFeed ? "Auto-scroll on" : "Auto-scroll off"}
        </button>
        <button type="button" className="secondary" onClick={clearEventFeed}>
          Clear
        </button>
      </div>
      <div className="panel-meta-row">
        <span className="meta-pill">Shown {filteredLines.length}</span>
        <span className="meta-pill">Total {eventLines.length}</span>
        <span className="meta-pill">{feedPaused ? "Paused" : "Live"}</span>
        <span className="meta-pill">Pause and auto-scroll reset on reload</span>
      </div>
      <pre ref={feedRef} className="event-feed">
        {filteredLines.join("\n")}
      </pre>
    </Panel>
  );
}
