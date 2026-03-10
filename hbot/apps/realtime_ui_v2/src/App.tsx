import { Suspense, lazy } from "react";

import "./App.css";

import { AlertsStrip } from "./components/AlertsStrip";
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

function App() {
  useRealtimeTransport();
  const review = useReviewData();
  useKeyboardShortcuts(review.activeView, review.setActiveView);

  return (
    <div className="app-shell">
      <TopBar activeView={review.activeView} onActiveViewChange={review.setActiveView} />
      <AlertsStrip />
      <main className="layout-grid">
        {review.activeView === "realtime" ? (
          <ViewErrorBoundary label="Realtime">
            <Suspense fallback={<section className="panel panel-span-12">Loading realtime view...</section>}>
              <RealtimeDashboard />
            </Suspense>
          </ViewErrorBoundary>
        ) : null}

        {review.activeView === "history" ? (
          <ViewErrorBoundary label="History">
            <Suspense fallback={<section className="panel panel-span-12">Loading history view...</section>}>
              <HistoryMonitorPanel />
            </Suspense>
          </ViewErrorBoundary>
        ) : null}

        {review.activeView === "service" ? (
          <ViewErrorBoundary label="Service">
            <Suspense fallback={<section className="panel panel-span-12">Loading service view...</section>}>
              <ServiceMonitorPanel />
            </Suspense>
          </ViewErrorBoundary>
        ) : null}

        {review.activeView === "daily" ? (
          <ViewErrorBoundary label="Daily review">
            <Suspense fallback={<section className="panel panel-span-12">Loading daily review...</section>}>
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
            <Suspense fallback={<section className="panel panel-span-12">Loading weekly review...</section>}>
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
            <Suspense fallback={<section className="panel panel-span-12">Loading journal review...</section>}>
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
      </main>
    </div>
  );
}

export default App;
