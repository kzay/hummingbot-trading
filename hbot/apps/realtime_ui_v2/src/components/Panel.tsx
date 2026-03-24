import { memo, useEffect, useId, useState } from "react";
import type { PropsWithChildren, ReactNode } from "react";

import { STATE_REFRESH_STALE_AFTER_MS } from "../constants";

interface PanelProps extends PropsWithChildren {
  title: ReactNode;
  subtitle?: string;
  actions?: ReactNode;
  className?: string;
  loading?: boolean;
  loadingLabel?: string;
  error?: string | null;
  empty?: boolean;
  emptyLabel?: string;
  freshnessTsMs?: number | null;
}

function useIsStale(freshnessTsMs: number | null | undefined): boolean {
  const [stale, setStale] = useState(false);

  useEffect(() => {
    if (freshnessTsMs == null || freshnessTsMs <= 0) {
      queueMicrotask(() => setStale(false));
      return;
    }
    const check = () => setStale(Date.now() - freshnessTsMs > STATE_REFRESH_STALE_AFTER_MS);
    queueMicrotask(check);
    const id = window.setInterval(check, 2_000);
    return () => window.clearInterval(id);
  }, [freshnessTsMs]);

  return stale;
}

export const Panel = memo(function Panel({
  title,
  subtitle,
  actions,
  className = "",
  loading,
  loadingLabel,
  error,
  empty,
  emptyLabel,
  freshnessTsMs,
  children,
}: PanelProps) {
  const isStale = useIsStale(freshnessTsMs);
  const headingId = useId();

  let body: ReactNode;
  if (error) {
    body = <div className="panel-error" role="alert">{error}</div>;
  } else if (loading) {
    body = <div className="panel-loading">{loadingLabel || "Connecting\u2026"}</div>;
  } else if (empty) {
    body = <div className="panel-empty">{emptyLabel || "No data"}</div>;
  } else {
    body = children;
  }

  return (
    <section className={`panel ${className}`.trim()} style={{ position: "relative" }} role="region" aria-labelledby={headingId}>
      <header className="panel-head">
        <div>
          <h2 id={headingId}>{title}</h2>
          {subtitle ? <p className="panel-subtitle">{subtitle}</p> : null}
        </div>
        {actions ? <div className="panel-actions">{actions}</div> : null}
      </header>
      {body}
      {isStale && (
        <div className="panel-stale-overlay" aria-label="Data is stale">
          <span>STALE DATA</span>
        </div>
      )}
    </section>
  );
});
