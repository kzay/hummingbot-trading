import { useEffect, useRef, useState } from "react";
import { Responsive, WidthProvider } from "react-grid-layout/legacy";
import type { Layout, ResponsiveLayouts } from "react-grid-layout/legacy";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";

import { AccountPnlPanel } from "./AccountPnlPanel";
import { Activity24hPanel } from "./Activity24hPanel";
import { BotGateBoardPanel } from "./BotGateBoardPanel";
import { DataInPanel } from "./DataInPanel";
import { DepthLadderPanel } from "./DepthLadderPanel";
import { EventFeedPanel } from "./EventFeedPanel";
import { FillsPanel } from "./FillsPanel";
import { InstancesPreviewStrip } from "./InstancesPreviewStrip";
import { MarketChartPanel } from "./MarketChartPanel";
import { PositionExposurePanel } from "./PositionExposurePanel";

const ResponsiveGridLayout = WidthProvider(Responsive);

export function RealtimeDashboard() {
  const renderCountRef = useRef(0);

  useEffect(() => {
    renderCountRef.current += 1;
  });

  useEffect(() => {
    const id = setInterval(() => {
      if (renderCountRef.current > 0) {
        console.debug(`[perf] Dashboard: ${renderCountRef.current} renders in 60s`);
        renderCountRef.current = 0;
      }
    }, 60_000);
    return () => clearInterval(id);
  }, []);

  const defaultLayouts = {
    lg: [
      { i: "instances", x: 0, y: 0, w: 12, h: 4, static: true },
      { i: "chart", x: 0, y: 4, w: 8, h: 14 },
      { i: "depth", x: 8, y: 4, w: 4, h: 7 },
      { i: "fills", x: 8, y: 11, w: 4, h: 7 },
      { i: "pnl", x: 0, y: 18, w: 5, h: 6 },
      { i: "exposure", x: 5, y: 18, w: 3, h: 6 },
      { i: "data", x: 8, y: 18, w: 4, h: 6 },
      { i: "activity", x: 0, y: 24, w: 4, h: 6 },
      { i: "gates", x: 4, y: 24, w: 4, h: 6 },
      { i: "feed", x: 8, y: 24, w: 4, h: 6 },
    ],
    md: [
      { i: "instances", x: 0, y: 0, w: 10, h: 4, static: true },
      { i: "chart", x: 0, y: 4, w: 6, h: 14 },
      { i: "depth", x: 6, y: 4, w: 4, h: 7 },
      { i: "fills", x: 6, y: 11, w: 4, h: 7 },
      { i: "pnl", x: 0, y: 18, w: 5, h: 6 },
      { i: "exposure", x: 5, y: 18, w: 5, h: 6 },
      { i: "activity", x: 0, y: 24, w: 5, h: 6 },
      { i: "gates", x: 5, y: 24, w: 5, h: 6 },
      { i: "data", x: 0, y: 30, w: 5, h: 6 },
      { i: "feed", x: 5, y: 30, w: 5, h: 6 },
    ],
    sm: [
      { i: "instances", x: 0, y: 0, w: 6, h: 4, static: true },
      { i: "chart", x: 0, y: 4, w: 6, h: 14 },
      { i: "depth", x: 0, y: 18, w: 3, h: 7 },
      { i: "fills", x: 3, y: 18, w: 3, h: 7 },
      { i: "pnl", x: 0, y: 25, w: 6, h: 6 },
      { i: "exposure", x: 0, y: 31, w: 6, h: 6 },
      { i: "activity", x: 0, y: 37, w: 6, h: 6 },
      { i: "gates", x: 0, y: 43, w: 6, h: 6 },
      { i: "data", x: 0, y: 49, w: 6, h: 6 },
      { i: "feed", x: 0, y: 55, w: 6, h: 6 },
    ],
    xs: [
      { i: "instances", x: 0, y: 0, w: 4, h: 4, static: true },
      { i: "chart", x: 0, y: 4, w: 4, h: 12 },
      { i: "depth", x: 0, y: 16, w: 4, h: 7 },
      { i: "fills", x: 0, y: 23, w: 4, h: 7 },
      { i: "pnl", x: 0, y: 30, w: 4, h: 6 },
      { i: "exposure", x: 0, y: 36, w: 4, h: 6 },
      { i: "activity", x: 0, y: 42, w: 4, h: 6 },
      { i: "gates", x: 0, y: 48, w: 4, h: 6 },
      { i: "data", x: 0, y: 54, w: 4, h: 6 },
      { i: "feed", x: 0, y: 60, w: 4, h: 6 },
    ],
    xxs: [
      { i: "instances", x: 0, y: 0, w: 2, h: 4, static: true },
      { i: "chart", x: 0, y: 4, w: 2, h: 12 },
      { i: "depth", x: 0, y: 16, w: 2, h: 7 },
      { i: "fills", x: 0, y: 23, w: 2, h: 7 },
      { i: "pnl", x: 0, y: 30, w: 2, h: 6 },
      { i: "exposure", x: 0, y: 36, w: 2, h: 6 },
      { i: "activity", x: 0, y: 42, w: 2, h: 6 },
      { i: "gates", x: 0, y: 48, w: 2, h: 6 },
      { i: "data", x: 0, y: 54, w: 2, h: 6 },
      { i: "feed", x: 0, y: 60, w: 2, h: 6 },
    ]
  };

  // State to hold current layout
  const [layouts, setLayouts] = useState(() => {
    const saved = localStorage.getItem("hbDashboardLayoutV3");
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        if (parsed && typeof parsed === 'object' && Object.keys(parsed).length > 0) {
          // Merge missing items from default layout to prevent broken UI
          const merged = { ...parsed };
          let needsUpdate = false;
          
          for (const bp of Object.keys(defaultLayouts)) {
            if (!merged[bp]) {
              merged[bp] = [...defaultLayouts[bp as keyof typeof defaultLayouts]];
              needsUpdate = true;
            } else {
              const defaultBpLayout = defaultLayouts[bp as keyof typeof defaultLayouts];
              if (defaultBpLayout) {
                for (const defaultItem of defaultBpLayout) {
                  if (!merged[bp].find((item: { i: string }) => item.i === defaultItem.i)) {
                    merged[bp].push({ ...defaultItem });
                    needsUpdate = true;
                  }
                }
              }
            }
          }
          
          if (needsUpdate) {
            localStorage.setItem("hbDashboardLayoutV3", JSON.stringify(merged));
          }
          
          return merged;
        }
      } catch (e) {
        return defaultLayouts;
      }
    }
    return defaultLayouts;
  });

  const onLayoutChange = (_layout: Layout, allLayouts: ResponsiveLayouts) => {
    setLayouts(allLayouts);
    localStorage.setItem("hbDashboardLayoutV3", JSON.stringify(allLayouts));
  };

  return (
    <div style={{ width: "100%" }}>
      <ResponsiveGridLayout
        className="layout"
        layouts={layouts}
        breakpoints={{ lg: 1200, md: 996, sm: 768, xs: 480, xxs: 0 }}
        cols={{ lg: 12, md: 10, sm: 6, xs: 4, xxs: 2 }}
        rowHeight={30}
        onLayoutChange={onLayoutChange}
        draggableHandle=".panel-head"
        margin={[12, 12]}
      >
        <div key="instances" data-grid={{ x: 0, y: 0, w: 12, h: 4, static: true }}>
          <InstancesPreviewStrip embedded />
        </div>
        <div key="chart" className="grid-panel-wrap" data-grid={{ x: 0, y: 4, w: 8, h: 14 }}>
          <MarketChartPanel />
        </div>
        <div key="pnl" className="grid-panel-wrap" data-grid={{ x: 0, y: 18, w: 5, h: 6 }}>
          <AccountPnlPanel />
        </div>
        <div key="exposure" className="grid-panel-wrap" data-grid={{ x: 5, y: 18, w: 3, h: 6 }}>
          <PositionExposurePanel />
        </div>
        <div key="depth" className="grid-panel-wrap" data-grid={{ x: 8, y: 4, w: 4, h: 7 }}>
          <DepthLadderPanel />
        </div>
        <div key="fills" className="grid-panel-wrap" data-grid={{ x: 8, y: 11, w: 4, h: 7 }}>
          <FillsPanel />
        </div>
        <div key="activity" className="grid-panel-wrap" data-grid={{ x: 0, y: 24, w: 4, h: 6 }}>
          <Activity24hPanel />
        </div>
        <div key="gates" className="grid-panel-wrap" data-grid={{ x: 4, y: 24, w: 4, h: 6 }}>
          <BotGateBoardPanel />
        </div>
        <div key="data" className="grid-panel-wrap" data-grid={{ x: 8, y: 18, w: 4, h: 6 }}>
          <DataInPanel />
        </div>
        <div key="feed" className="grid-panel-wrap" data-grid={{ x: 8, y: 24, w: 4, h: 6 }}>
          <EventFeedPanel />
        </div>
      </ResponsiveGridLayout>
    </div>
  );
}
