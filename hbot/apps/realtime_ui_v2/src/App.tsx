import { Suspense, lazy } from "react";

import "./App.css";

import { AlertsStrip } from "./components/AlertsStrip";
import { ShortcutHelp } from "./components/ShortcutHelp";
import { Sidebar } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import { ViewErrorBoundary } from "./components/ViewErrorBoundary";
import { useRealtimeTransport } from "./hooks/useRealtimeTransport";
import { useKeyboardShortcuts } from "./hooks/useKeyboardShortcuts";
import { useReviewData } from "./hooks/useReviewData";

const RealtimeDashboard = lazy(() =>
  import("./components/RealtimeDashboard").then((module) => ({ default: module.RealtimeDashboard })),
);
const HistoryMonitorPanel = lazy(() =>
  import("./components/HistoryMonitorPanel").then((module) => ({ default: module.HistoryMonitorPanel })),
);
const ServiceMonitorPanel = lazy(() =>
  import("./components/ServiceMonitorPanel").then((module) => ({ default: module.ServiceMonitorPanel })),
);
const DailyReviewPanel = lazy(() =>
  import("./components/DailyReviewPanel").then((module) => ({ default: module.DailyReviewPanel })),
);
const WeeklyReviewPanel = lazy(() =>
  import("./components/WeeklyReviewPanel").then((module) => ({ default: module.WeeklyReviewPanel })),
);
const JournalReviewPanel = lazy(() =>
  import("./components/JournalReviewPanel").then((module) => ({ default: module.JournalReviewPanel })),
);
const BacktestPage = lazy(() =>
  import("./components/BacktestPage").then((module) => ({ default: module.BacktestPage })),
);
const ResearchPage = lazy(() =>
  import("./components/ResearchPage").then((module) => ({ default: module.ResearchPage })),
);
const MlFeaturesPanel = lazy(() =>
  import("./components/MlFeaturesPanel").then((module) => ({ default: module.MlFeaturesPanel })),
);

function App() {
  useRealtimeTransport();
  const review = useReviewData();
  const shortcuts = useKeyboardShortcuts(review.activeView, review.setActiveView);

  return (
    <div className="app-shell">
      <Sidebar activeView={review.activeView} onActiveViewChange={review.setActiveView} />
      <div className="app-content">
        <TopBar activeView={review.activeView} onActiveViewChange={review.setActiveView} />
        <AlertsStrip />
        <ShortcutHelp open={shortcuts.helpOpen} onClose={shortcuts.toggleHelp} />
        <main className="layout-grid">
        {review.activeView === "realtime" ? (
          <ViewErrorBoundary label="Realtime">
            <Suspense fallback={<section className="panel panel-span-12"><div className="panel-loading">Loading realtime view…</div></section>}>
              <div className="panel-span-12" style={{ display: "block" }}>
                <RealtimeDashboard />
              </div>
            </Suspense>
          </ViewErrorBoundary>
        ) : null}

        {review.activeView === "history" ? (
          <ViewErrorBoundary label="History">
            <Suspense fallback={<section className="panel panel-span-12"><div className="panel-loading">Loading history view…</div></section>}>
              <HistoryMonitorPanel />
            </Suspense>
          </ViewErrorBoundary>
        ) : null}

        {review.activeView === "service" ? (
          <ViewErrorBoundary label="Service">
            <Suspense fallback={<section className="panel panel-span-12"><div className="panel-loading">Loading service view…</div></section>}>
              <ServiceMonitorPanel />
            </Suspense>
          </ViewErrorBoundary>
        ) : null}

        {review.activeView === "daily" ? (
          <ViewErrorBoundary label="Daily review">
            <Suspense fallback={<section className="panel panel-span-12"><div className="panel-loading">Loading daily review…</div></section>}>
              <DailyReviewPanel
                day={review.dailyDay}
                onDayChange={review.setDailyDay}
                onRefresh={() => {
                  void review.refreshDaily();
                }}
                state={review.daily}
              />
            </Suspense>
          </ViewErrorBoundary>
        ) : null}

        {review.activeView === "weekly" ? (
          <ViewErrorBoundary label="Weekly review">
            <Suspense fallback={<section className="panel panel-span-12"><div className="panel-loading">Loading weekly review…</div></section>}>
              <WeeklyReviewPanel
                state={review.weekly}
                onRefresh={() => {
                  void review.refreshWeekly();
                }}
              />
            </Suspense>
          </ViewErrorBoundary>
        ) : null}

        {review.activeView === "journal" ? (
          <ViewErrorBoundary label="Journal">
            <Suspense fallback={<section className="panel panel-span-12"><div className="panel-loading">Loading journal…</div></section>}>
              <JournalReviewPanel
                state={review.journal}
                startDay={review.journalStartDay}
                endDay={review.journalEndDay}
                onStartDayChange={review.setJournalStartDay}
                onEndDayChange={review.setJournalEndDay}
                onRefresh={() => {
                  void review.refreshJournal();
                }}
                selectedTradeId={review.selectedTradeId}
                onSelectTrade={review.setSelectedTradeId}
                selectedTrade={review.selectedTrade}
              />
            </Suspense>
          </ViewErrorBoundary>
        ) : null}

        {review.activeView === "backtest" ? (
          <ViewErrorBoundary label="Backtest">
            <Suspense fallback={<section className="panel panel-span-12"><div className="panel-loading">Loading backtest…</div></section>}>
              <BacktestPage />
            </Suspense>
          </ViewErrorBoundary>
        ) : null}

        {review.activeView === "research" ? (
          <ViewErrorBoundary label="Research">
            <Suspense fallback={<section className="panel panel-span-12"><div className="panel-loading">Loading research…</div></section>}>
              <ResearchPage />
            </Suspense>
          </ViewErrorBoundary>
        ) : null}

        {review.activeView === "ml" ? (
          <ViewErrorBoundary label="ML Features">
            <Suspense fallback={<section className="panel panel-span-12"><div className="panel-loading">Loading ML features…</div></section>}>
              <MlFeaturesPanel />
            </Suspense>
          </ViewErrorBoundary>
        ) : null}
        </main>
      </div>
    </div>
  );
}

export default App;
