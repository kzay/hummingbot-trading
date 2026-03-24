import { useEffect, useRef, useState } from "react";
import { Responsive, WidthProvider } from "react-grid-layout/legacy";
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

  // Define default layouts for different breakpoints
  const defaultLayouts = {
    lg: [
      { i: "instances", x: 0, y: 0, w: 12, h: 4, static: true },
      { i: "chart", x: 0, y: 4, w: 8, h: 14 },
      { i: "depth", x: 8, y: 4, w: 4, h: 7 },
      { i: "fills", x: 8, y: 11, w: 4, h: 7 },
      { i: "pnl", x: 0, y: 18, w: 5, h: 6 },
      { i: "exposure", x: 5, y: 18, w: 3, h: 6 },
      { i: "activity", x: 0, y: 24, w: 4, h: 6 },
      { i: "gates", x: 4, y: 24, w: 4, h: 6 },
      { i: "data", x: 8, y: 18, w: 4, h: 6 },
      { i: "feed", x: 8, y: 24, w: 4, h: 6 },
    ]
  };

  // State to hold current layout
  const [layouts, setLayouts] = useState(() => {
    const saved = localStorage.getItem("hbDashboardLayoutV3");
    if (saved) {
      try {
        return JSON.parse(saved);
      } catch (e) {
        return defaultLayouts;
      }
    }
    return defaultLayouts;
  });

  const onLayoutChange = (_layout: any, allLayouts: any) => {
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
        <div key="instances">
          <InstancesPreviewStrip embedded />
        </div>
        <div key="chart" className="grid-panel-wrap">
          <MarketChartPanel />
        </div>
        <div key="pnl" className="grid-panel-wrap">
          <AccountPnlPanel />
        </div>
        <div key="exposure" className="grid-panel-wrap">
          <PositionExposurePanel />
        </div>
        <div key="depth" className="grid-panel-wrap">
          <DepthLadderPanel />
        </div>
        <div key="fills" className="grid-panel-wrap">
          <FillsPanel />
        </div>
        <div key="activity" className="grid-panel-wrap">
          <Activity24hPanel />
        </div>
        <div key="gates" className="grid-panel-wrap">
          <BotGateBoardPanel />
        </div>
        <div key="data" className="grid-panel-wrap">
          <DataInPanel />
        </div>
        <div key="feed" className="grid-panel-wrap">
          <EventFeedPanel />
        </div>
      </ResponsiveGridLayout>
    </div>
  );
}
