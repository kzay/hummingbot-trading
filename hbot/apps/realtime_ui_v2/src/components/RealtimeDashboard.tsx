import { AccountPnlPanel } from "./AccountPnlPanel";
import { BotGateBoardPanel } from "./BotGateBoardPanel";
import { DataInPanel } from "./DataInPanel";
import { DepthLadderPanel } from "./DepthLadderPanel";
import { EventFeedPanel } from "./EventFeedPanel";
import { FillsPanel } from "./FillsPanel";
import { MarketChartPanel } from "./MarketChartPanel";
import { OrdersPanel } from "./OrdersPanel";
import { PayloadInspectorPanel } from "./PayloadInspectorPanel";
import { PositionExposurePanel } from "./PositionExposurePanel";

export function RealtimeDashboard() {
  return (
    <>
      <MarketChartPanel />
      <PositionExposurePanel />
      <AccountPnlPanel />
      <BotGateBoardPanel />
      <DepthLadderPanel />
      <OrdersPanel />
      <FillsPanel />
      <DataInPanel />
      <EventFeedPanel />
      <PayloadInspectorPanel />
    </>
  );
}
