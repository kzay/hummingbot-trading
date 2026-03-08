(function () {
  function emptyWindow() {
    return {
      fill_count: 0,
      buy_count: 0,
      sell_count: 0,
      maker_count: 0,
      maker_ratio: 0,
      volume_base: 0,
      notional_quote: 0,
      realized_pnl_quote: 0,
      avg_fill_size: 0,
      avg_fill_price: 0,
    };
  }

  function emptySummary() {
    return {
      activity: {
        fills_total: 0,
        latest_fill_ts_ms: 0,
        window_15m: emptyWindow(),
        window_1h: emptyWindow(),
      },
      account: {
        equity_quote: 0,
        quote_balance: 0,
        equity_open_quote: 0,
        equity_peak_quote: 0,
        realized_pnl_quote: 0,
        controller_state: "",
        regime: "",
        pnl_governor_active: false,
        pnl_governor_reason: "",
        risk_reasons: "",
        daily_loss_pct: 0,
        max_daily_loss_pct_hard: 0,
        drawdown_pct: 0,
        max_drawdown_pct_hard: 0,
        order_book_stale: false,
        snapshot_ts: "",
      },
      alerts: [],
      system: {
        redis_available: false,
        db_available: false,
        fallback_active: false,
        stream_age_ms: null,
        latest_market_ts_ms: 0,
        latest_fill_ts_ms: 0,
        position_source_ts_ms: 0,
        subscriber_count: 0,
        market_key_count: 0,
        depth_key_count: 0,
        fills_key_count: 0,
        paper_event_key_count: 0,
      },
    };
  }

  const state = {
    apiBase: localStorage.getItem("hbApiBase") || "http://localhost:9910",
    apiToken: localStorage.getItem("hbApiToken") || "",
    instanceName: "bot1",
    instancePinned: false,
    selectionRevision: 0,
    controllerId: "",
    tradingPair: "BTC-USDT",
    timeframeS: 60,
    eventLines: [],
    latestMid: null,
    chartPriceLines: [],
    chartOverlaySignature: "",
    latestQuoteTsMs: 0,
    latestDepthTsMs: 0,
    lastDepthRenderTsMs: 0,
    ws: null,
    wsReconnectTimer: null,
    wsReconnectDelayMs: 1500,
    wsManualClose: false,
    runtimeEvents: [],
    health: {
      status: "unknown",
      stream_age_ms: null,
      db_available: false,
      redis_available: false,
      fallback_active: false,
      metrics: {},
    },
    instances: {
      names: [],
      statuses: [],
    },
    connection: {
      wsStatus: "idle",
      wsSessionId: 0,
      connectedAtMs: 0,
      lastMessageTsMs: 0,
      lastEventType: "",
    },
    ui: {
      denseMode: localStorage.getItem("hbDenseMode") === "1",
      activeView: localStorage.getItem("hbActiveView") || "realtime",
      executionFilter: "",
      fillSide: "all",
      fillMaker: "all",
      eventFilter: "",
    },
    dailyReview: {
      day: new Date().toISOString().slice(0, 10),
      source: "",
      review: null,
      error: "",
    },
    weeklyReview: {
      source: "",
      review: null,
      error: "",
    },
    journalReview: {
      startDay: "",
      endDay: "",
      source: "",
      review: null,
      error: "",
      selectedTradeId: "",
    },
    live: {
      mode: "",
      source: "",
      market: {},
      depth: {},
      position: {},
      openOrders: [],
      fills: [],
      fillsTotal: 0,
      candles: [],
      summary: emptySummary(),
    },
  };

  const els = {
    apiBaseInput: document.getElementById("apiBaseInput"),
    apiTokenInput: document.getElementById("apiTokenInput"),
    applyConnectionBtn: document.getElementById("applyConnectionBtn"),
    healthBadge: document.getElementById("healthBadge"),
    alertStrip: document.getElementById("alertStrip"),
    instanceInput: document.getElementById("instanceInput"),
    timeframeSelect: document.getElementById("timeframeSelect"),
    refreshBtn: document.getElementById("refreshBtn"),
    viewTabs: Array.from(document.querySelectorAll("[data-view-tab]")),
    denseModeBtn: document.getElementById("denseModeBtn"),
    resetLayoutBtn: document.getElementById("resetLayoutBtn"),
    instanceStatusBoard: document.getElementById("instanceStatusBoard"),
    heroStats: document.getElementById("heroStats"),
    chartPanel: document.getElementById("chartPanel"),
    chartMeta: document.getElementById("chartMeta"),
    positionMeta: document.getElementById("positionMeta"),
    accountMeta: document.getElementById("accountMeta"),
    fillsMeta: document.getElementById("fillsMeta"),
    positionSummary: document.getElementById("positionSummary"),
    accountSummaryGrid: document.getElementById("accountSummaryGrid"),
    activitySummaryGrid: document.getElementById("activitySummaryGrid"),
    gateBoardMeta: document.getElementById("gateBoardMeta"),
    gateBoardTableBody: document.getElementById("gateBoardTableBody"),
    liveActivityGrid: document.getElementById("liveActivityGrid"),
    systemSummaryGrid: document.getElementById("systemSummaryGrid"),
    dailyDayInput: document.getElementById("dailyDayInput"),
    dailyRefreshBtn: document.getElementById("dailyRefreshBtn"),
    dailyMeta: document.getElementById("dailyMeta"),
    dailyNarrative: document.getElementById("dailyNarrative"),
    dailySummaryGrid: document.getElementById("dailySummaryGrid"),
    dailyHourlyTableBody: document.getElementById("dailyHourlyTableBody"),
    dailyFillsTableBody: document.getElementById("dailyFillsTableBody"),
    dailyGateTableBody: document.getElementById("dailyGateTableBody"),
    weeklyMeta: document.getElementById("weeklyMeta"),
    weeklyNarrative: document.getElementById("weeklyNarrative"),
    weeklySummaryGrid: document.getElementById("weeklySummaryGrid"),
    weeklyDaysTableBody: document.getElementById("weeklyDaysTableBody"),
    journalStartDayInput: document.getElementById("journalStartDayInput"),
    journalEndDayInput: document.getElementById("journalEndDayInput"),
    journalRefreshBtn: document.getElementById("journalRefreshBtn"),
    journalMeta: document.getElementById("journalMeta"),
    journalNarrative: document.getElementById("journalNarrative"),
    journalSummaryGrid: document.getElementById("journalSummaryGrid"),
    journalTradesTableBody: document.getElementById("journalTradesTableBody"),
    journalDrilldownMeta: document.getElementById("journalDrilldownMeta"),
    journalMiniChartMeta: document.getElementById("journalMiniChartMeta"),
    journalMiniChart: document.getElementById("journalMiniChart"),
    journalDrilldownSummaryGrid: document.getElementById("journalDrilldownSummaryGrid"),
    journalFillsTableBody: document.getElementById("journalFillsTableBody"),
    journalPathTableBody: document.getElementById("journalPathTableBody"),
    journalGateTableBody: document.getElementById("journalGateTableBody"),
    depthTableBody: document.getElementById("depthTableBody"),
    ordersTableBody: document.getElementById("ordersTableBody"),
    ordersPanelMeta: document.getElementById("ordersPanelMeta"),
    executionFilterInput: document.getElementById("executionFilterInput"),
    fillsTableBody: document.getElementById("fillsTableBody"),
    fillSideFilter: document.getElementById("fillSideFilter"),
    fillMakerFilter: document.getElementById("fillMakerFilter"),
    eventFilterInput: document.getElementById("eventFilterInput"),
    clearEventFeedBtn: document.getElementById("clearEventFeedBtn"),
    eventFeed: document.getElementById("eventFeed"),
  };

  const chart = LightweightCharts.createChart(document.getElementById("chartContainer"), {
    layout: { background: { color: "#151c28" }, textColor: "#dce3f0" },
    grid: { vertLines: { color: "#273244" }, horzLines: { color: "#273244" } },
    timeScale: { timeVisible: true, secondsVisible: true },
    rightPriceScale: { borderColor: "#3c4555" },
  });
  const candleSeries = chart.addCandlestickSeries({
    upColor: "#1f9d55",
    downColor: "#d64545",
    borderVisible: false,
    wickUpColor: "#1f9d55",
    wickDownColor: "#d64545",
  });
  let journalMiniChart = null;
  let journalMiniSeries = null;
  let liveStateRefreshTimer = null;
  let liveStateRefreshInFlight = false;
  let instanceRefreshTimer = null;

  function headers() {
    const out = { "Content-Type": "application/json" };
    if (state.apiToken) {
      out.Authorization = `Bearer ${state.apiToken}`;
    }
    return out;
  }

  async function fetchJson(path) {
    const res = await fetch(`${state.apiBase}${path}`, { headers: headers() });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    return res.json();
  }

  function updateDerivedSelection(meta = {}) {
    const controllerId = String(meta.controller_id ?? state.controllerId ?? "").trim();
    const tradingPair = String(meta.trading_pair ?? state.tradingPair ?? "").trim().toUpperCase();
    if (controllerId) {
      state.controllerId = controllerId;
    }
    if (tradingPair) {
      state.tradingPair = tradingPair;
    }
  }

  function bumpSelectionRevision() {
    state.selectionRevision = Number(state.selectionRevision || 0) + 1;
    return state.selectionRevision;
  }

  function selectionStillCurrent(revision, instanceName) {
    return Number(revision || 0) === Number(state.selectionRevision || 0) && String(instanceName || "").trim() === String(state.instanceName || "").trim();
  }

  function keyInstanceName(key) {
    if (Array.isArray(key)) {
      return String(key[0] || "").trim();
    }
    if (key && typeof key === "object") {
      return String(key.instance_name || key.instance || "").trim();
    }
    return "";
  }

  function snapshotInstanceName(snapshot) {
    const payload = snapshot?.state || {};
    const stream = payload.stream || {};
    const fallback = payload.fallback || {};
    return String(
      snapshot?.instance_name ||
        keyInstanceName(snapshot?.key) ||
        keyInstanceName(stream?.key) ||
        stream?.position?.instance_name ||
        fallback?.position?.instance_name ||
        ""
    ).trim();
  }

  function messageInstanceName(msg) {
    return String(msg?.instance_name || keyInstanceName(msg?.key) || msg?.event?.instance_name || "").trim();
  }

  function wsUrl() {
    const base = new URL(state.apiBase);
    const protocol = base.protocol === "https:" ? "wss:" : "ws:";
    const url = new URL(`${protocol}//${base.host}/api/v1/ws`);
    if (state.instanceName) url.searchParams.set("instance_name", state.instanceName);
    url.searchParams.set("timeframe_s", String(state.timeframeS || 60));
    url.searchParams.set("limit", "300");
    if (state.apiToken) url.searchParams.set("token", state.apiToken);
    return url.toString();
  }

  function setBadge(status) {
    const normalized = status || "unknown";
    els.healthBadge.textContent = normalized;
    els.healthBadge.className = `badge ${normalized === "ok" ? "ok" : normalized === "disabled" ? "disabled" : "fail"}`;
  }

  function pushEventLine(line) {
    state.eventLines.push(`${new Date().toLocaleTimeString()} ${line}`);
    if (state.eventLines.length > 140) {
      state.eventLines = state.eventLines.slice(state.eventLines.length - 140);
    }
    renderEventFeed();
  }

  function toNum(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  function formatNumber(value, digits = 2) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "n/a";
    return n.toLocaleString(undefined, {
      minimumFractionDigits: 0,
      maximumFractionDigits: digits,
    });
  }

  function formatSigned(value, digits = 2) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "n/a";
    const formatted = formatNumber(Math.abs(n), digits);
    if (n > 0) return `+${formatted}`;
    if (n < 0) return `-${formatted}`;
    return formatted;
  }

  function formatPct(value, digits = 1) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "n/a";
    return `${(n * 100).toFixed(digits)}%`;
  }

  function formatAgeMs(value) {
    const ms = Number(value);
    if (!Number.isFinite(ms) || ms < 0) return "n/a";
    if (ms < 1000) return `${Math.round(ms)} ms`;
    const seconds = ms / 1000;
    if (seconds < 60) return `${seconds.toFixed(1)} s`;
    const minutes = seconds / 60;
    if (minutes < 60) return `${minutes.toFixed(1)} m`;
    return `${(minutes / 60).toFixed(1)} h`;
  }

  function formatTs(value) {
    if (value instanceof Date) {
      return value.toLocaleString();
    }
    let ts = Number(value);
    if (!Number.isFinite(ts) || ts <= 0) {
      const raw = String(value ?? "").trim();
      ts = raw ? Date.parse(raw) : NaN;
    }
    if (!Number.isFinite(ts) || ts <= 0) return "n/a";
    return new Date(ts).toLocaleString();
  }

  function formatRelativeTs(value) {
    let ts = Number(value);
    if (!Number.isFinite(ts) || ts <= 0) {
      const raw = String(value ?? "").trim();
      ts = raw ? Date.parse(raw) : NaN;
    }
    if (!Number.isFinite(ts) || ts <= 0) return "n/a";
    const delta = Date.now() - Number(ts);
    return `${formatAgeMs(delta)} ago`;
  }

  function classifySigned(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "value-neutral";
    if (n > 0) return "value-positive";
    if (n < 0) return "value-negative";
    return "value-neutral";
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function statusPill(label, tone) {
    return `<span class="status-pill ${tone || "neutral"}">${escapeHtml(label)}</span>`;
  }

  function gateTone(status) {
    return status === "pass" || status === "quoting" || status === "ready"
      ? "ok"
      : status === "fail" || status === "blocked" || status === "not quoting"
        ? "fail"
        : status === "warn" || status === "limited" || status === "waiting"
          ? "warn"
          : "neutral";
  }

  function gatePriority(status) {
    const tone = gateTone(status);
    return tone === "fail" ? 0 : tone === "warn" ? 1 : tone === "neutral" ? 2 : 3;
  }

  function renderGateTimelineTable(target, timeline, emptyMessage) {
    if (!target) return;
    const rows = Array.isArray(timeline) ? timeline : [];
    if (rows.length === 0) {
      target.innerHTML = `<tr><td colspan="6">${escapeHtml(emptyMessage || "No gate transitions available.")}</td></tr>`;
      return;
    }
    target.innerHTML = rows
      .slice()
      .reverse()
      .map(
        (row) => `
          <tr>
            <td><div>${formatTs(row.start_ts || row.start_ts_ms)}</div><div class="hero-subvalue">${formatRelativeTs(row.start_ts || row.start_ts_ms)}</div></td>
            <td><div>${formatTs(row.end_ts || row.end_ts_ms)}</div><div class="hero-subvalue">${formatRelativeTs(row.end_ts || row.end_ts_ms)}</div></td>
            <td>${formatAgeMs((Number(row.duration_seconds || 0) || 0) * 1000)}</td>
            <td>${statusPill(row.quoting_status || "n/a", gateTone(row.quoting_status || row.status))}</td>
            <td><div>${escapeHtml(row.quoting_reason || "n/a")}</div><div class="hero-subvalue">Orders ${escapeHtml(String(row.orders_active ?? "0"))}</div></td>
            <td><div>${escapeHtml(row.controller_state || "n/a")} / ${escapeHtml(String(row.regime || "n/a").replaceAll("_", " "))}</div><div class="hero-subvalue">${escapeHtml(row.risk_reasons || "no risk tags")}</div></td>
          </tr>
        `
      )
      .join("");
  }

  function currentMarkPrice() {
    const market = state.live.market || {};
    const depth = state.live.depth || {};
    return toNum(market.mid_price || state.latestMid || depthMid(depth));
  }

  function getLiveAccountMetrics() {
    const summary = ensureSummary();
    const account = summary.account || {};
    const position = state.live.position || {};
    const mark = currentMarkPrice();
    const qtyRaw = toNum(position.quantity);
    const qtyAbs = Number.isFinite(qtyRaw) ? Math.abs(qtyRaw) : 0;
    const avgEntryPrice = toNum(position.avg_entry_price);
    const storedUnrealized = toNum(position.unrealized_pnl);
    const side = String(position.side || "").trim().toLowerCase();
    let direction = 0;
    if (qtyAbs > 0) {
      direction = side === "short" ? -1 : side === "long" ? 1 : qtyRaw < 0 ? -1 : 1;
    }
    let unrealizedPnl = storedUnrealized;
    if (Number.isFinite(mark) && Number.isFinite(avgEntryPrice) && avgEntryPrice > 0 && qtyAbs > 0 && direction !== 0) {
      unrealizedPnl = (mark - avgEntryPrice) * qtyAbs * direction;
    }
    const realizedPnl = toNum(account.realized_pnl_quote);
    const quoteBalance = toNum(account.quote_balance);
    const snapshotEquity = toNum(account.equity_quote);
    const equityOpenQuote = toNum(account.equity_open_quote);
    const equityPeakQuote = toNum(account.equity_peak_quote);
    let equityQuote = snapshotEquity;
    if (Number.isFinite(snapshotEquity) && Number.isFinite(unrealizedPnl)) {
      equityQuote = snapshotEquity - (Number.isFinite(storedUnrealized) ? storedUnrealized : 0) + unrealizedPnl;
    } else if (Number.isFinite(quoteBalance) && Number.isFinite(unrealizedPnl)) {
      equityQuote = quoteBalance + unrealizedPnl;
    }
    const totalPnl =
      Number.isFinite(realizedPnl) || Number.isFinite(unrealizedPnl)
        ? Number(realizedPnl || 0) + Number(unrealizedPnl || 0)
        : null;
    const deltaVsOpenQuote =
      Number.isFinite(equityQuote) && Number.isFinite(equityOpenQuote) ? equityQuote - equityOpenQuote : null;
    const deltaVsPeakQuote =
      Number.isFinite(equityQuote) && Number.isFinite(equityPeakQuote) ? equityQuote - equityPeakQuote : null;
    const returnVsOpen =
      Number.isFinite(deltaVsOpenQuote) && Number.isFinite(equityOpenQuote) && equityOpenQuote !== 0
        ? deltaVsOpenQuote / equityOpenQuote
        : null;
    return {
      mark,
      side,
      positionQty: qtyRaw,
      avgEntryPrice,
      unrealizedPnl,
      realizedPnl,
      equityQuote,
      equityOpenQuote,
      equityPeakQuote,
      totalPnl,
      deltaVsOpenQuote,
      deltaVsPeakQuote,
      returnVsOpen,
      quoteBalance,
    };
  }

  function getOpenOrderState() {
    const summary = ensureSummary();
    const account = summary.account || {};
    const openOrders = Array.isArray(state.live.openOrders) ? state.live.openOrders : [];
    const confirmed = openOrders.length;
    const runtime = Math.max(0, Number(account.orders_active || 0) || 0);
    return {
      confirmed,
      runtime,
      display: confirmed > 0 ? confirmed : runtime,
      isRuntimeFallback: confirmed === 0 && runtime > 0,
    };
  }

  function getOpenOrderBreakdown(orders) {
    const safeOrders = Array.isArray(orders) ? orders : [];
    let runtimeDerived = 0;
    let estimated = 0;
    let confirmed = 0;
    safeOrders.forEach((order) => {
      if (!order || typeof order !== "object") {
        return;
      }
      if (order.estimate_source === "runtime") {
        runtimeDerived += 1;
      } else if (order.is_estimated) {
        estimated += 1;
      } else {
        confirmed += 1;
      }
    });
    return {
      total: safeOrders.length,
      confirmed,
      runtimeDerived,
      estimated,
    };
  }

  function sourceTone(source, fallbackActive) {
    if (fallbackActive || String(source || "").includes("degraded")) {
      return "warn";
    }
    if (String(source || "").includes("stream")) {
      return "ok";
    }
    if (source) {
      return "neutral";
    }
    return "neutral";
  }

  function setInstanceOptions(instances, preferredSelection) {
    if (!els.instanceInput) {
      return preferredSelection || "";
    }
    const safeInstances = Array.isArray(instances)
      ? Array.from(new Set(instances.map((value) => String(value || "").trim()).filter(Boolean))).sort((a, b) => a.localeCompare(b))
      : [];
    const fallbackSelection = String(preferredSelection || state.instanceName || "bot1").trim() || "bot1";
    const options = safeInstances.length > 0 ? safeInstances : [fallbackSelection];
    const selected = options.includes(fallbackSelection) ? fallbackSelection : options[0];
    els.instanceInput.innerHTML = options
      .map((instance) => `<option value="${escapeHtml(instance)}"${instance === selected ? " selected" : ""}>${escapeHtml(instance)}</option>`)
      .join("");
    els.instanceInput.value = selected;
    return selected;
  }

  function chooseAutoInstance(statuses, preferredSelection, pinned) {
    const rows = Array.isArray(statuses) ? statuses : [];
    const preferred = String(preferredSelection || "").trim();
    const byName = new Map(rows.map((row) => [String(row?.instance_name || "").trim(), row]));
    if (preferred) {
      const preferredRow = byName.get(preferred);
      if (pinned) {
        return preferred;
      }
      if (preferredRow && ["live", "stale"].includes(String(preferredRow.freshness || ""))) {
        return preferred;
      }
    }
    const liveRow = rows.find((row) => String(row?.freshness || "") === "live");
    if (liveRow?.instance_name) {
      return String(liveRow.instance_name);
    }
    const staleRow = rows.find((row) => String(row?.freshness || "") === "stale");
    if (staleRow?.instance_name) {
      return String(staleRow.instance_name);
    }
    if (preferred) {
      return preferred;
    }
    return rows[0]?.instance_name ? String(rows[0].instance_name) : "";
  }

  function renderInstanceStatusBoard() {
    if (!els.instanceStatusBoard) {
      return;
    }
    const rows = Array.isArray(state.instances.statuses) ? state.instances.statuses : [];
    if (rows.length === 0) {
      els.instanceStatusBoard.innerHTML = `<div class="hero-subvalue">No detected instances yet.</div>`;
      return;
    }
    els.instanceStatusBoard.innerHTML = rows
      .map((row) => {
        const instanceName = String(row.instance_name || "");
        const tone = String(row.tone || "neutral");
        const freshnessLabel = String(row.freshness || row.quoting_status || "unknown");
        const isActive = instanceName === state.instanceName;
        const equityValue = formatNumber(row.equity_quote, 2);
        const dailyPnlValue = formatSigned(row.realized_pnl_quote, 2);
        return `
          <button type="button" class="instance-status-card ${escapeHtml(tone)}${isActive ? " active" : ""}" data-instance-name="${escapeHtml(instanceName)}">
            <span class="instance-status-dot ${escapeHtml(tone)}" aria-hidden="true"></span>
            <span class="instance-status-inline bot">${escapeHtml(instanceName || "instance")}</span>
            <span class="instance-status-inline status">${escapeHtml(freshnessLabel)}</span>
            <span class="instance-status-inline metric">Eq ${escapeHtml(equityValue)}</span>
            <span class="instance-status-inline metric ${classifySigned(row.realized_pnl_quote)}">Day ${escapeHtml(dailyPnlValue)}</span>
            <span class="instance-status-inline pair">${escapeHtml(row.trading_pair || "")}</span>
            <div class="instance-status-sr">
              ${escapeHtml(row.controller_id || "detecting")} / ${escapeHtml(row.trading_pair || "pair n/a")} · Quote ${escapeHtml(row.quoting_status || "n/a")} · Orders ${escapeHtml(String(row.orders_active ?? 0))}
            </div>
          </button>
        `;
      })
      .join("");
  }

  async function fetchInstances() {
    try {
      const payload = await fetchJson("/api/v1/instances");
      const instances = Array.isArray(payload?.instances) ? payload.instances : [];
      state.instances.names = instances;
      state.instances.statuses = Array.isArray(payload?.statuses) ? payload.statuses : [];
      const previousSelection = String(els.instanceInput?.value || state.instanceName || "").trim();
      const preferredSelection = chooseAutoInstance(state.instances.statuses, previousSelection, state.instancePinned);
      const nextSelection = setInstanceOptions(instances, preferredSelection || previousSelection);
      if (nextSelection) {
        state.instanceName = nextSelection;
      }
      renderInstanceStatusBoard();
      return { instances, previousSelection, nextSelection };
    } catch (_err) {
      const fallbackSelection = setInstanceOptions([state.instanceName || "bot1"], state.instanceName || "bot1");
      state.instances.names = [fallbackSelection];
      state.instances.statuses = [];
      state.instanceName = fallbackSelection;
      renderInstanceStatusBoard();
      return { instances: [fallbackSelection], previousSelection: fallbackSelection, nextSelection: fallbackSelection };
    }
  }

  function sidePill(value) {
    const raw = String(value || "").trim().toLowerCase();
    const tone = raw === "buy" || raw === "long" ? raw : raw === "sell" || raw === "short" ? raw : "flat";
    return `<span class="side-pill ${tone}">${escapeHtml(raw || "flat")}</span>`;
  }

  function makerPill(isMaker) {
    return `<span class="maker-pill ${isMaker ? "maker" : "taker"}">${isMaker ? "maker" : "taker"}</span>`;
  }

  function miniBar(pct) {
    const width = Math.max(0, Math.min(100, Number(pct) || 0));
    return `<div class="mini-bar"><span style="width:${width}%"></span></div>`;
  }

  function splitBar(leftPct) {
    const safeLeft = Math.max(0, Math.min(100, Number(leftPct) || 0));
    const safeRight = Math.max(0, 100 - safeLeft);
    return `<div class="split-bar"><span class="split-bar-buy" style="width:${safeLeft}%"></span><span class="split-bar-sell" style="width:${safeRight}%"></span></div>`;
  }

  function getAccountState(metrics) {
    const equity = toNum(metrics?.equityQuote);
    const open = toNum(metrics?.equityOpenQuote);
    const peak = toNum(metrics?.equityPeakQuote);
    const deltaOpen = toNum(metrics?.deltaVsOpenQuote);
    const deltaPeak = toNum(metrics?.deltaVsPeakQuote);
    const recoveryPct =
      Number.isFinite(equity) && Number.isFinite(open) && Number.isFinite(peak) && peak > open
        ? ((equity - open) / (peak - open)) * 100
        : Number.isFinite(deltaOpen) && deltaOpen >= 0
          ? 100
          : 0;
    const drawdownPct =
      Number.isFinite(peak) && peak > 0 && Number.isFinite(deltaPeak) && deltaPeak < 0 ? (Math.abs(deltaPeak) / peak) * 100 : 0;
    if (!Number.isFinite(deltaOpen)) {
      return {
        label: "unknown",
        tone: "neutral",
        recoveryPct: Math.max(0, Math.min(100, recoveryPct)),
        drawdownPct: Math.max(0, drawdownPct),
      };
    }
    if (deltaOpen >= 0 && (!Number.isFinite(deltaPeak) || deltaPeak >= -0.0005 * Math.max(peak || 0, 1))) {
      return {
        label: "at highs",
        tone: "ok",
        recoveryPct: Math.max(0, Math.min(100, recoveryPct)),
        drawdownPct: Math.max(0, drawdownPct),
      };
    }
    if (deltaOpen >= 0) {
      return {
        label: "green drawdown",
        tone: "warn",
        recoveryPct: Math.max(0, Math.min(100, recoveryPct)),
        drawdownPct: Math.max(0, drawdownPct),
      };
    }
    return {
      label: "below open",
      tone: "fail",
      recoveryPct: Math.max(0, Math.min(100, recoveryPct)),
      drawdownPct: Math.max(0, drawdownPct),
    };
  }

  function getRiskState(account = {}) {
    const controllerState = String(account.controller_state || "").trim().toLowerCase();
    const riskReasons = String(account.risk_reasons || "").trim();
    const governorActive = Boolean(account.pnl_governor_active);
    const bookStale = Boolean(account.order_book_stale);
    if (controllerState === "hard_stop") {
      return { label: "hard stop", tone: "fail" };
    }
    if (riskReasons) {
      return { label: "risk active", tone: "warn" };
    }
    if (bookStale) {
      return { label: "book stale", tone: "warn" };
    }
    if (governorActive) {
      return { label: "governor", tone: "warn" };
    }
    if (controllerState) {
      return { label: controllerState.replaceAll("_", " "), tone: "ok" };
    }
    return { label: "unknown", tone: "neutral" };
  }

  function applyDenseMode() {
    document.body.classList.toggle("dense-mode", Boolean(state.ui.denseMode));
    if (els.denseModeBtn) {
      els.denseModeBtn.textContent = state.ui.denseMode ? "Comfort mode" : "Dense mode";
    }
  }

  function resizeChartToPanel() {
    if (!els.chartPanel) return;
    const panelHeight = els.chartPanel.clientHeight || 0;
    const headerHeight = Array.from(els.chartPanel.querySelectorAll(".panel-head")).reduce(
      (acc, el) => acc + (el instanceof HTMLElement ? el.offsetHeight : 0),
      0
    );
    const nextHeight = Math.max(280, panelHeight - headerHeight - 34);
    const width = Math.max(320, els.chartPanel.clientWidth - 28);
    const chartEl = document.getElementById("chartContainer");
    if (chartEl) {
      chartEl.style.height = `${nextHeight}px`;
    }
    chart.resize(width, nextHeight);
  }

  function ensureJournalMiniChart() {
    if (journalMiniChart || !els.journalMiniChart) return;
    const width = Math.max(280, els.journalMiniChart.clientWidth || 280);
    const height = Math.max(180, els.journalMiniChart.clientHeight || 220);
    journalMiniChart = LightweightCharts.createChart(els.journalMiniChart, {
      width,
      height,
      layout: { background: { color: "#111827" }, textColor: "#dce3f0" },
      grid: { vertLines: { color: "#273244" }, horzLines: { color: "#273244" } },
      timeScale: { timeVisible: true, secondsVisible: true, borderColor: "#3c4555" },
      rightPriceScale: { borderColor: "#3c4555" },
      crosshair: { mode: 0 },
    });
    journalMiniSeries = journalMiniChart.addLineSeries({
      color: "#5ea7ff",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
    });
  }

  function resizeJournalMiniChart() {
    if (!journalMiniChart || !els.journalMiniChart) return;
    const width = Math.max(280, els.journalMiniChart.clientWidth || 280);
    const height = Math.max(180, els.journalMiniChart.clientHeight || 220);
    journalMiniChart.resize(width, height);
  }

  function renderJournalMiniChart(trade) {
    ensureJournalMiniChart();
    if (!journalMiniChart || !journalMiniSeries) {
      return;
    }
    const side = String(trade?.side || "").trim().toLowerCase();
    const tone = side === "long" ? { color: "#22c55e", entryColor: "#86efac", exitColor: "#bbf7d0" } : side === "short" ? { color: "#ef4444", entryColor: "#fca5a5", exitColor: "#fecaca" } : { color: "#5ea7ff", entryColor: "#93c5fd", exitColor: "#dbeafe" };
    const pathPoints = Array.isArray(trade?.path_points) ? trade.path_points : [];
    const seriesData = pathPoints
      .map((point) => ({
        time: Math.floor((Number(point.timestamp_ms || 0) || 0) / 1000),
        value: Number(point.mid || 0),
      }))
      .filter((point) => Number.isFinite(point.time) && point.time > 0 && Number.isFinite(point.value) && point.value > 0);
    journalMiniSeries.applyOptions({
      color: tone.color,
      lastValueVisible: true,
      priceLineVisible: false,
    });
    journalMiniSeries.setData(seriesData);
    if (typeof journalMiniSeries.setMarkers === "function") {
      const markers = [];
      if (seriesData.length > 0) {
        markers.push({
          time: seriesData[0].time,
          position: side === "short" ? "aboveBar" : "belowBar",
          color: tone.entryColor,
          shape: "arrowUp",
          text: "Entry",
        });
      }
      if (seriesData.length > 1) {
        markers.push({
          time: seriesData[seriesData.length - 1].time,
          position: side === "short" ? "belowBar" : "aboveBar",
          color: tone.exitColor,
          shape: "arrowDown",
          text: "Exit",
        });
      }
      journalMiniSeries.setMarkers(markers);
    }
    if (els.journalMiniChartMeta) {
      const summary = trade?.path_summary || {};
      els.journalMiniChartMeta.innerHTML = trade
        ? [
            `<span class="meta-pill">Direction ${escapeHtml(side || "n/a")}</span>`,
            `<span class="meta-pill">Path ${escapeHtml(String(seriesData.length || 0))} points</span>`,
            `<span class="meta-pill">Open ${formatNumber(summary.mid_open, 4)}</span>`,
            `<span class="meta-pill">High ${formatNumber(summary.mid_high, 4)}</span>`,
            `<span class="meta-pill">Low ${formatNumber(summary.mid_low, 4)}</span>`,
            `<span class="meta-pill">Close ${formatNumber(summary.mid_close, 4)}</span>`,
          ].join("")
        : `<span class="meta-pill">No trade selected</span>`;
    }
    window.setTimeout(() => {
      resizeJournalMiniChart();
      if (seriesData.length > 1) {
        journalMiniChart.timeScale().fitContent();
      }
    }, 0);
  }

  function initResizableLayout() {
    resizeChartToPanel();
    if (typeof ResizeObserver === "undefined" || !els.chartPanel) {
      window.addEventListener("resize", resizeChartToPanel);
      window.addEventListener("resize", resizeJournalMiniChart);
      return;
    }
    const observer = new ResizeObserver(() => resizeChartToPanel());
    observer.observe(els.chartPanel);
    if (els.journalMiniChart) {
      const journalObserver = new ResizeObserver(() => resizeJournalMiniChart());
      journalObserver.observe(els.journalMiniChart);
    }
  }

  function resetResizablePanels() {
    document.querySelectorAll(".resizable-panel").forEach((panel) => {
      if (panel instanceof HTMLElement) {
        panel.style.height = "";
      }
    });
    window.setTimeout(() => resizeChartToPanel(), 0);
  }

  function renderHeroStats() {
    const market = state.live.market || {};
    const depth = state.live.depth || {};
    const position = state.live.position || {};
    const summary = ensureSummary();
    const system = summary.system || {};
    const liveMetrics = getLiveAccountMetrics();
    const orderState = getOpenOrderState();
    const bestBid = toNum(market.best_bid || depth.best_bid || depth?.bids?.[0]?.price);
    const bestAsk = toNum(market.best_ask || depth.best_ask || depth?.asks?.[0]?.price);
    const mid = toNum(market.mid_price || state.latestMid);
    const spread = Number.isFinite(bestBid) && Number.isFinite(bestAsk) && bestAsk >= bestBid ? bestAsk - bestBid : null;
    const cards = [
      {
        label: "Market",
        value: formatNumber(mid, 4),
        subvalue: `Spread ${formatNumber(spread, 4)}`,
      },
      {
        label: "Position",
        value: formatNumber(position.quantity, 6),
        subvalue: `Side ${String(position.side || "flat").toUpperCase()}`,
      },
      {
        label: "Unrealized PnL",
        value: `<span class="${classifySigned(liveMetrics.unrealizedPnl)}">${formatSigned(liveMetrics.unrealizedPnl, 4)}</span>`,
        subvalue: `Entry ${formatNumber(liveMetrics.avgEntryPrice, 4)}`,
      },
      {
        label: "Realized PnL",
        value: `<span class="${classifySigned(liveMetrics.realizedPnl)}">${formatSigned(liveMetrics.realizedPnl, 4)}</span>`,
        subvalue: `Snapshot ${formatRelativeTs(summary.account?.snapshot_ts)}`,
      },
      {
        label: "Equity",
        value: formatNumber(liveMetrics.equityQuote, 4),
        subvalue: `Vs open ${formatSigned(liveMetrics.deltaVsOpenQuote, 4)}`,
      },
      {
        label: "Open Orders",
        value: String(orderState.display || 0),
        subvalue: orderState.isRuntimeFallback
          ? `Runtime inferred · Trades ${String(state.live.fillsTotal || 0)}`
          : `Trades ${String(state.live.fillsTotal || 0)}`,
      },
      {
        label: "Websocket",
        value: statusPill(state.connection.wsStatus || "idle", state.connection.wsStatus || "neutral"),
        subvalue: `Last msg ${formatAgeMs(Date.now() - Number(state.connection.lastMessageTsMs || 0))}`,
      },
      {
        label: "Stream Freshness",
        value: formatAgeMs(system.stream_age_ms ?? state.health.stream_age_ms),
        subvalue: `${system.db_available || state.health.db_available ? "DB" : "DB down"} · ${system.redis_available || state.health.redis_available ? "Redis" : "Redis down"}`,
      },
    ];
    els.heroStats.innerHTML = cards
      .map(
        (card) => `
          <div class="hero-stat">
            <div class="hero-label">${card.label}</div>
            <div class="hero-value">${card.value}</div>
            <div class="hero-subvalue">${card.subvalue}</div>
          </div>
        `
      )
      .join("");
  }

  function renderEventFeed() {
    const query = String(state.ui.eventFilter || "").trim().toLowerCase();
    const filtered = query
      ? state.eventLines.filter((line) => String(line || "").toLowerCase().includes(query))
      : state.eventLines;
    els.eventFeed.textContent = filtered.join("\n");
  }

  function renderChartMeta() {
    const market = state.live.market || {};
    const depth = state.live.depth || {};
    const system = ensureSummary().system || {};
    const orderBreakdown = getOpenOrderBreakdown(state.live.openOrders);
    const bestBid = toNum(market.best_bid || depth.best_bid || depth?.bids?.[0]?.price);
    const bestAsk = toNum(market.best_ask || depth.best_ask || depth?.asks?.[0]?.price);
    const spreadPct =
      Number.isFinite(bestBid) && Number.isFinite(bestAsk) && bestAsk >= bestBid && bestAsk + bestBid > 0
        ? ((bestAsk - bestBid) / ((bestAsk + bestBid) / 2)) * 100
        : null;
    els.chartMeta.innerHTML = [
      statusPill(state.live.mode || "n/a", state.live.mode === "active" ? "ok" : state.live.mode === "shadow" ? "warn" : "neutral"),
      statusPill(state.live.source || "source", sourceTone(state.live.source || "", system.fallback_active || state.health.fallback_active)),
      `<span class="meta-pill">Fallback ${statusPill(system.fallback_active || state.health.fallback_active ? "active" : "off", system.fallback_active || state.health.fallback_active ? "warn" : "neutral")}</span>`,
      `<span class="meta-pill">Overlay ${escapeHtml(String(orderBreakdown.confirmed))} confirmed / ${escapeHtml(String(orderBreakdown.runtimeDerived))} runtime</span>`,
      `<span class="meta-pill">Spread ${formatNumber(spreadPct, 3)}%</span>`,
      `<span class="meta-pill">Last tick ${formatRelativeTs(system.latest_market_ts_ms)}</span>`,
    ].join("");
  }

  function renderActiveView() {
    const activeView = state.ui.activeView || "realtime";
    document.querySelectorAll("[data-view]").forEach((el) => {
      if (!(el instanceof HTMLElement)) return;
      el.hidden = el.getAttribute("data-view") !== activeView;
    });
    els.viewTabs.forEach((btn) => {
      if (!(btn instanceof HTMLElement)) return;
      btn.classList.toggle("active", btn.getAttribute("data-view-tab") === activeView);
    });
    if (activeView === "realtime") {
      window.setTimeout(() => resizeChartToPanel(), 0);
    }
    if (activeView === "journal") {
      window.setTimeout(() => resizeJournalMiniChart(), 0);
    }
  }

  function renderAlerts() {
    if (!els.alertStrip) return;
    const alerts = Array.isArray(ensureSummary().alerts) ? ensureSummary().alerts : [];
    if (alerts.length === 0) {
      els.alertStrip.hidden = true;
      els.alertStrip.innerHTML = "";
      return;
    }
    els.alertStrip.hidden = state.ui.activeView !== "realtime";
    els.alertStrip.innerHTML = alerts
      .map((alert) => {
        const severity = String(alert?.severity || "info").toLowerCase();
        const pillTone = severity === "info" ? "neutral" : severity;
        return `
          <div class="alert-item ${severity}">
            <div class="alert-title">${statusPill(severity, pillTone)} ${escapeHtml(alert?.title || "Alert")}</div>
            <div class="alert-detail">${escapeHtml(alert?.detail || "")}</div>
          </div>
        `;
      })
      .join("");
  }

  function normalizeFill(fill) {
    const normalized = fill && typeof fill === "object" ? { ...fill } : {};
    normalized.timestamp_ms = Number(normalized.timestamp_ms || normalized.ts || 0) || 0;
    normalized.side = String(normalized.side || "").toUpperCase();
    normalized.price = Number(normalized.price || 0) || 0;
    normalized.amount_base = Number(normalized.amount_base || normalized.amount || 0) || 0;
    normalized.notional_quote = Number(normalized.notional_quote || 0) || 0;
    normalized.fee_quote = Number(normalized.fee_quote || 0) || 0;
    normalized.realized_pnl_quote = Number(normalized.realized_pnl_quote || 0) || 0;
    normalized.is_maker = Boolean(normalized.is_maker);
    return normalized;
  }

  function ensureSummary() {
    if (!state.live.summary || typeof state.live.summary !== "object") {
      state.live.summary = emptySummary();
    }
    if (!state.live.summary.activity) {
      state.live.summary.activity = emptySummary().activity;
    }
    if (!state.live.summary.account) {
      state.live.summary.account = emptySummary().account;
    }
    if (!Array.isArray(state.live.summary.alerts)) {
      state.live.summary.alerts = emptySummary().alerts;
    }
    if (!state.live.summary.system) {
      state.live.summary.system = emptySummary().system;
    }
    state.live.summary.activity.window_15m = {
      ...emptyWindow(),
      ...(state.live.summary.activity.window_15m || {}),
    };
    state.live.summary.activity.window_1h = {
      ...emptyWindow(),
      ...(state.live.summary.activity.window_1h || {}),
    };
    state.live.summary.account = {
      ...emptySummary().account,
      ...(state.live.summary.account || {}),
    };
    state.live.summary.alerts = Array.isArray(state.live.summary.alerts) ? state.live.summary.alerts : [];
    state.live.summary.system = {
      ...emptySummary().system,
      ...(state.live.summary.system || {}),
    };
    return state.live.summary;
  }

  function summarizeClientFills(fills, fillsTotal) {
    const nowMs = Date.now();
    const windows = {
      window_15m: { ms: 15 * 60 * 1000, bucket: emptyWindow() },
      window_1h: { ms: 60 * 60 * 1000, bucket: emptyWindow() },
    };
    let latestFillTsMs = 0;
    (fills || []).forEach((rawFill) => {
      const fill = normalizeFill(rawFill);
      if (!fill.timestamp_ms) return;
      latestFillTsMs = Math.max(latestFillTsMs, fill.timestamp_ms);
      const ageMs = nowMs - fill.timestamp_ms;
      Object.values(windows).forEach(({ ms, bucket }) => {
        if (ageMs > ms) return;
        bucket.fill_count += 1;
        if (String(fill.side).toLowerCase() === "buy") bucket.buy_count += 1;
        if (String(fill.side).toLowerCase() === "sell") bucket.sell_count += 1;
        if (fill.is_maker) bucket.maker_count += 1;
        bucket.volume_base += Math.abs(fill.amount_base || 0);
        bucket.notional_quote += Math.abs(fill.amount_base || 0) * (fill.price || 0);
        bucket.realized_pnl_quote += fill.realized_pnl_quote || 0;
        bucket.avg_fill_size += Math.abs(fill.amount_base || 0);
        bucket.avg_fill_price += fill.price || 0;
      });
    });
    Object.values(windows).forEach(({ bucket }) => {
      if (bucket.fill_count > 0) {
        bucket.maker_ratio = bucket.maker_count / bucket.fill_count;
        bucket.avg_fill_size = bucket.avg_fill_size / bucket.fill_count;
        bucket.avg_fill_price = bucket.avg_fill_price / bucket.fill_count;
      }
    });
    return {
      fills_total: Math.max(Number(fillsTotal || 0), (fills || []).length),
      latest_fill_ts_ms: latestFillTsMs,
      window_15m: windows.window_15m.bucket,
      window_1h: windows.window_1h.bucket,
    };
  }

  function mergeRecentFills(existingFills, incomingFills, maxRows) {
    const merged = [];
    const seen = new Set();
    const pushFill = (fill) => {
      if (!fill || typeof fill !== "object") return;
      const normalized = normalizeFill(fill);
      const key = [
        normalized.order_id || "",
        normalized.timestamp_ms || normalized.ts || "",
        normalized.side || "",
        normalized.price || "",
        normalized.amount_base || "",
      ].join("|");
      if (seen.has(key)) return;
      seen.add(key);
      merged.push(normalized);
    };
    (existingFills || []).forEach(pushFill);
    (incomingFills || []).forEach(pushFill);
    merged.sort((a, b) => Number(a.timestamp_ms || 0) - Number(b.timestamp_ms || 0));
    return merged.slice(-Math.max(20, Number(maxRows) || 200));
  }

  function updateActivitySummaryWithFill(rawFill) {
    const fill = normalizeFill(rawFill);
    const summary = ensureSummary();
    const activity = summary.activity;
    summary.account.realized_pnl_quote = Number(summary.account.realized_pnl_quote || 0) + Number(fill.realized_pnl_quote || 0);
    activity.fills_total = Math.max(Number(activity.fills_total || 0) + 1, Number(state.live.fillsTotal || 0));
    activity.latest_fill_ts_ms = Math.max(Number(activity.latest_fill_ts_ms || 0), Number(fill.timestamp_ms || 0));
    ["window_15m", "window_1h"].forEach((key) => {
      const bucket = activity[key];
      bucket.fill_count += 1;
      if (String(fill.side).toLowerCase() === "buy") bucket.buy_count += 1;
      if (String(fill.side).toLowerCase() === "sell") bucket.sell_count += 1;
      if (fill.is_maker) bucket.maker_count += 1;
      bucket.volume_base += Math.abs(fill.amount_base || 0);
      bucket.notional_quote += Math.abs(fill.amount_base || 0) * (fill.price || 0);
      bucket.realized_pnl_quote += fill.realized_pnl_quote || 0;
      bucket.avg_fill_size =
        bucket.fill_count > 0
          ? (bucket.avg_fill_size * (bucket.fill_count - 1) + Math.abs(fill.amount_base || 0)) / bucket.fill_count
          : 0;
      bucket.avg_fill_price =
        bucket.fill_count > 0 ? (bucket.avg_fill_price * (bucket.fill_count - 1) + (fill.price || 0)) / bucket.fill_count : 0;
      bucket.maker_ratio = bucket.fill_count > 0 ? bucket.maker_count / bucket.fill_count : 0;
    });
  }

  function renderSummaryCards(target, cards) {
    target.innerHTML = cards
      .map((card) => {
        const rows = (card.rows || [])
          .map((row) => `<dt>${row[0]}</dt><dd>${row[1]}</dd>`)
          .join("");
        const highlight = card.highlight
          ? `<div class="summary-highlight"><div class="summary-highlight-value ${card.highlight.className || ""}">${card.highlight.value}</div><div class="summary-highlight-label">${card.highlight.label || ""}</div>${card.highlight.meter || ""}</div>`
          : "";
        return `<div class="summary-card"><h3>${card.title}</h3>${highlight}<dl>${rows}</dl></div>`;
      })
      .join("");
  }

  function renderPosition(summary) {
    const orderState = getOpenOrderState();
    const system = ensureSummary().system || {};
    const breakdown = getOpenOrderBreakdown(state.live.openOrders);
    if (els.positionMeta) {
      els.positionMeta.innerHTML = [
        `<span class="meta-pill">Source ${statusPill(summary.source || "n/a", sourceTone(summary.source || "", system.fallback_active || state.health.fallback_active))}</span>`,
        `<span class="meta-pill">Updated ${escapeHtml(formatRelativeTs(summary.updatedTs))}</span>`,
        `<span class="meta-pill">Orders ${escapeHtml(String(breakdown.confirmed))} confirmed / ${escapeHtml(String(breakdown.runtimeDerived))} runtime</span>`,
      ].join("");
    }
    const values = [
      ["Mode", statusPill(summary.mode || "n/a", summary.mode === "active" ? "ok" : summary.mode === "shadow" ? "warn" : "neutral")],
      ["Source", `<span class="mono">${escapeHtml(summary.source || "n/a")}</span>`],
      ["Mid", formatNumber(summary.mid, 4)],
      ["Best Bid", formatNumber(summary.bestBid, 4)],
      ["Best Ask", formatNumber(summary.bestAsk, 4)],
      ["Side", sidePill(summary.side || "flat")],
      ["Position Qty", formatNumber(summary.positionQty, 6)],
      ["Avg Entry", formatNumber(summary.avgEntryPrice, 4)],
      ["Unrealized PnL", `<span class="${classifySigned(summary.unrealizedPnl)}">${formatSigned(summary.unrealizedPnl, 4)}</span>`],
      ["Realized PnL", `<span class="${classifySigned(summary.realizedPnl)}">${formatSigned(summary.realizedPnl, 4)}</span>`],
      ["Equity", `<span class="${classifySigned(summary.equityQuote)}">${formatNumber(summary.equityQuote, 4)}</span>`],
      ["Open Orders", orderState.isRuntimeFallback ? `${orderState.display} (runtime)` : String(summary.openOrders || 0)],
      ["Trade Count", String(summary.recentFills || 0)],
      ["Updated", formatTs(summary.updatedTs)],
    ];
    els.positionSummary.innerHTML = values
      .map(([k, v]) => `<div class="kv-card"><div class="kv-label">${k}</div><div class="kv-value">${v}</div></div>`)
      .join("");
  }

  function renderAccountSummary() {
    const summary = ensureSummary();
    const account = summary.account || {};
    const system = summary.system || {};
    const liveMetrics = getLiveAccountMetrics();
    const accountState = getAccountState(liveMetrics);
    const riskState = getRiskState(account);
    const quoteGates = Array.isArray(account.quote_gates) ? account.quote_gates : [];
    const dailyLossPct = Number(account.daily_loss_pct || 0) || 0;
    const dailyLossHardPct = Number(account.max_daily_loss_pct_hard || 0) || 0;
    const drawdownPct = Number(account.drawdown_pct || 0) || 0;
    const drawdownHardPct = Number(account.max_drawdown_pct_hard || 0) || 0;
    const dailyLossUsagePct = dailyLossHardPct > 0 ? Math.min(100, (dailyLossPct / dailyLossHardPct) * 100) : 0;
    const drawdownUsagePct = drawdownHardPct > 0 ? Math.min(100, (drawdownPct / drawdownHardPct) * 100) : 0;
    if (els.accountMeta) {
      els.accountMeta.innerHTML = [
        `<span class="meta-pill">Source ${statusPill(state.live.source || "n/a", sourceTone(state.live.source || "", system.fallback_active || state.health.fallback_active))}</span>`,
        `<span class="meta-pill">Snapshot ${escapeHtml(formatRelativeTs(account.snapshot_ts))}</span>`,
        `<span class="meta-pill">Fallback ${statusPill(system.fallback_active || state.health.fallback_active ? "active" : "off", system.fallback_active || state.health.fallback_active ? "warn" : "neutral")}</span>`,
      ].join("");
    }
    renderSummaryCards(els.accountSummaryGrid, [
      {
        title: "Equity",
        highlight: {
          value: `<span class="${classifySigned(liveMetrics.equityQuote)}">${formatNumber(liveMetrics.equityQuote, 4)}</span>`,
          label: `Snapshot ${formatRelativeTs(account.snapshot_ts)}`,
          meter: miniBar(accountState.recoveryPct),
        },
        rows: [
          ["Status", statusPill(accountState.label, accountState.tone)],
          ["Quote Balance", formatNumber(liveMetrics.quoteBalance, 4)],
          ["Open Equity", formatNumber(liveMetrics.equityOpenQuote, 4)],
          ["Peak Equity", formatNumber(liveMetrics.equityPeakQuote, 4)],
          ["Vs Open", `<span class="${classifySigned(liveMetrics.deltaVsOpenQuote)}">${formatSigned(liveMetrics.deltaVsOpenQuote, 4)}</span>`],
          ["Vs Peak", `<span class="${classifySigned(liveMetrics.deltaVsPeakQuote)}">${formatSigned(liveMetrics.deltaVsPeakQuote, 4)}</span>`],
          ["Drawdown", `${formatNumber(accountState.drawdownPct, 2)}% ${miniBar(Math.min(100, accountState.drawdownPct * 4))}`],
          ["Return vs Open", `<span class="${classifySigned(liveMetrics.returnVsOpen)}">${formatPct(liveMetrics.returnVsOpen, 2)}</span>`],
        ],
      },
      {
        title: "PnL Stack",
        highlight: {
          value: `<span class="${classifySigned(liveMetrics.totalPnl)}">${formatSigned(liveMetrics.totalPnl, 4)}</span>`,
          label: "Realized + unrealized",
        },
        rows: [
          ["Realized PnL", `<span class="${classifySigned(liveMetrics.realizedPnl)}">${formatSigned(liveMetrics.realizedPnl, 4)}</span>`],
          ["Unrealized PnL", `<span class="${classifySigned(liveMetrics.unrealizedPnl)}">${formatSigned(liveMetrics.unrealizedPnl, 4)}</span>`],
          ["Mark", formatNumber(liveMetrics.mark, 4)],
          ["Avg Entry", formatNumber(liveMetrics.avgEntryPrice, 4)],
          ["Position Qty", formatNumber(liveMetrics.positionQty, 6)],
          ["Quote Buffer", formatNumber(liveMetrics.quoteBalance, 4)],
        ],
      },
      {
        title: "Risk State",
        highlight: {
          value: statusPill(riskState.label, riskState.tone),
          label: account.regime ? `Regime ${escapeHtml(String(account.regime).replaceAll("_", " "))}` : "Runtime controls",
        },
        rows: [
          ["Controller", account.controller_state ? `<span class="mono">${escapeHtml(String(account.controller_state))}</span>` : "n/a"],
          ["Governor", statusPill(account.pnl_governor_active ? (account.pnl_governor_reason || "active") : "off", account.pnl_governor_active ? "warn" : "neutral")],
          ["Risk Reasons", account.risk_reasons ? `<span class="mono">${escapeHtml(String(account.risk_reasons))}</span>` : "none"],
          ["Daily Loss", `${formatPct(dailyLossPct, 2)} / ${formatPct(dailyLossHardPct, 2)} ${miniBar(dailyLossUsagePct)}`],
          ["Drawdown", `${formatPct(drawdownPct, 2)} / ${formatPct(drawdownHardPct, 2)} ${miniBar(drawdownUsagePct)}`],
          ["Order Book", statusPill(account.order_book_stale ? "stale" : "fresh", account.order_book_stale ? "warn" : "ok")],
        ],
      },
      {
        title: "Quote Gates",
        highlight: {
          value: statusPill(account.quoting_status || "n/a", gateTone(account.quoting_status || "")),
          label: account.quoting_reason ? escapeHtml(String(account.quoting_reason)) : "Why bot is quoting or not",
        },
        rows: quoteGates.length
          ? quoteGates.map((gate) => [
              escapeHtml(gate.label || gate.key || "gate"),
              `${statusPill(gate.status || "n/a", gateTone(gate.status))} <span class="mono">${escapeHtml(gate.detail || "")}</span>`,
            ])
          : [["Status", "No gate data available"]],
      },
    ]);
  }

  function renderGateBoard() {
    if (!els.gateBoardTableBody) {
      return;
    }
    const summary = ensureSummary();
    const account = summary.account || {};
    const orderState = getOpenOrderState();
    const quoteGates = Array.isArray(account.quote_gates) ? account.quote_gates : [];
    const sortedQuoteGates = quoteGates
      .slice()
      .sort((left, right) => {
        const priorityDelta = gatePriority(left.status || "") - gatePriority(right.status || "");
        if (priorityDelta !== 0) {
          return priorityDelta;
        }
        return String(left.label || left.key || "").localeCompare(String(right.label || right.key || ""));
      });
    const primaryGate = sortedQuoteGates.find((gate) => gatePriority(gate.status || "") < 2) || null;
    if (els.gateBoardMeta) {
      const meta = [
        `<span class="meta-pill">Quote ${statusPill(account.quoting_status || "n/a", gateTone(account.quoting_status || ""))}</span>`,
        `<span class="meta-pill">${escapeHtml(account.quoting_reason || "No quoting reason")}</span>`,
        `<span class="meta-pill">${escapeHtml(orderState.isRuntimeFallback ? `Orders ${orderState.display} runtime` : `Orders ${orderState.display}`)}</span>`,
      ];
      if (primaryGate) {
        meta.push(
          `<span class="meta-pill">Top gate ${escapeHtml(primaryGate.label || primaryGate.key || "gate")} ${statusPill(primaryGate.status || "n/a", gateTone(primaryGate.status || ""))}</span>`
        );
      }
      els.gateBoardMeta.innerHTML = meta.join("");
    }
    if (sortedQuoteGates.length === 0) {
      els.gateBoardTableBody.innerHTML = `<tr><td colspan="3">No gate status available.</td></tr>`;
      return;
    }
    els.gateBoardTableBody.innerHTML = sortedQuoteGates
      .map(
        (gate, index) => `
          <tr class="gate-board-row gate-board-row-${gateTone(gate.status || "")}${index === 0 && gatePriority(gate.status || "") < 2 ? " primary" : ""}">
            <td>${escapeHtml(gate.label || gate.key || "gate")}</td>
            <td>${statusPill(gate.status || "n/a", gateTone(gate.status || ""))}</td>
            <td class="mono">${escapeHtml(gate.detail || "")}</td>
          </tr>
        `
      )
      .join("");
  }

  function renderDailyReview() {
    if (!els.dailySummaryGrid || !els.dailyHourlyTableBody || !els.dailyFillsTableBody || !els.dailyGateTableBody) {
      return;
    }
    const payload = state.dailyReview.review || {};
    const summary = payload.summary || {};
    const fills = Array.isArray(payload.fills) ? payload.fills : [];
    const hourly = Array.isArray(payload.hourly) ? payload.hourly : [];
    const gateTimeline = Array.isArray(payload.gate_timeline) ? payload.gate_timeline : [];
    if (els.dailyMeta) {
      els.dailyMeta.innerHTML = [
        `<span class="meta-pill">Source ${escapeHtml(state.dailyReview.source || "n/a")}</span>`,
        `<span class="meta-pill">Day ${escapeHtml(payload.day || state.dailyReview.day || "n/a")}</span>`,
        `<span class="meta-pill">Pair ${escapeHtml(payload.trading_pair || state.tradingPair || "n/a")}</span>`,
      ].join("");
    }
    if (els.dailyNarrative) {
      els.dailyNarrative.textContent = state.dailyReview.error || payload.narrative || "No daily review loaded.";
    }
    renderSummaryCards(els.dailySummaryGrid, [
      {
        title: "Session",
        highlight: {
          value: `<span class="${classifySigned(summary.realized_pnl_day_quote)}">${formatSigned(summary.realized_pnl_day_quote, 4)}</span>`,
          label: "Realized PnL",
        },
        rows: [
          ["Open Equity", formatNumber(summary.equity_open_quote, 4)],
          ["Close Equity", formatNumber(summary.equity_close_quote, 4)],
          ["High / Low", `${formatNumber(summary.equity_high_quote, 4)} / ${formatNumber(summary.equity_low_quote, 4)}`],
          ["Unrealized EOD", `<span class="${classifySigned(summary.unrealized_pnl_end_quote)}">${formatSigned(summary.unrealized_pnl_end_quote, 4)}</span>`],
          ["Quote Balance", formatNumber(summary.quote_balance_end_quote, 4)],
          ["Minute Points", String(summary.minute_points || 0)],
        ],
      },
      {
        title: "Execution",
        highlight: {
          value: `${summary.fill_count || 0} fills`,
          label: `Maker ${formatPct(summary.maker_ratio || 0, 1)}`,
          meter: miniBar((summary.maker_ratio || 0) * 100),
        },
        rows: [
          ["Buy / Sell", `${summary.buy_count || 0} / ${summary.sell_count || 0}`],
          ["Notional", formatNumber(summary.notional_quote, 2)],
          ["Fees", formatNumber(summary.fees_quote, 4)],
          ["State", statusPill(summary.controller_state_end || "n/a", summary.controller_state_end === "hard_stop" ? "fail" : "ok")],
          ["Regime", summary.regime_end ? escapeHtml(String(summary.regime_end).replaceAll("_", " ")) : "n/a"],
          ["Risk", summary.risk_reasons_end ? `<span class="mono">${escapeHtml(summary.risk_reasons_end)}</span>` : "none"],
        ],
      },
    ]);
    if (hourly.length === 0) {
      els.dailyHourlyTableBody.innerHTML = `<tr><td colspan="6">No hourly activity available for this day.</td></tr>`;
    } else {
      els.dailyHourlyTableBody.innerHTML = hourly
        .map(
          (bucket) => `
            <tr>
              <td>${formatTs(bucket.hour_ts_ms)}</td>
              <td>${bucket.fill_count || 0}</td>
              <td>${bucket.buy_count || 0} / ${bucket.sell_count || 0}</td>
              <td>${formatPct(bucket.maker_ratio || 0, 1)}</td>
              <td>${formatNumber(bucket.notional_quote || 0, 2)}</td>
              <td><span class="${classifySigned(bucket.realized_pnl_quote || 0)}">${formatSigned(bucket.realized_pnl_quote || 0, 4)}</span></td>
            </tr>
          `
        )
        .join("");
    }
    if (fills.length === 0) {
      els.dailyFillsTableBody.innerHTML = `<tr><td colspan="8">No fills available for this day.</td></tr>`;
    } else {
      els.dailyFillsTableBody.innerHTML = fills
        .slice()
        .reverse()
        .map((rawFill) => {
          const fill = normalizeFill(rawFill);
          const notional = Number(fill.notional_quote || 0) || Math.abs(fill.amount_base || 0) * (fill.price || 0);
          const fee = Number(fill.fee_quote || 0) || 0;
          return `
            <tr>
              <td><div>${fill.ts || formatTs(fill.timestamp_ms)}</div><div class="hero-subvalue">${formatRelativeTs(fill.timestamp_ms)}</div></td>
              <td>${sidePill(fill.side || "")}</td>
              <td>${formatNumber(fill.price, 4)}</td>
              <td>${formatNumber(fill.amount_base, 6)}</td>
              <td>${formatNumber(notional, 2)}</td>
              <td>${formatNumber(fee, 4)}</td>
              <td><span class="${classifySigned(fill.realized_pnl_quote)}">${formatSigned(fill.realized_pnl_quote, 4)}</span></td>
              <td class="mono">${escapeHtml(fill.order_id || "")}</td>
            </tr>
          `;
        })
        .join("");
    }
    renderGateTimelineTable(els.dailyGateTableBody, gateTimeline, "No gate transitions available for this day.");
  }

  function renderActivitySummary(activity) {
    const safe = activity || summarizeClientFills(state.live.fills, state.live.fillsTotal);
    const total15 = Math.max(1, Number(safe.window_15m?.fill_count || 0));
    const total1h = Math.max(1, Number(safe.window_1h?.fill_count || 0));
    renderSummaryCards(els.activitySummaryGrid, [
      {
        title: "Last 15m",
        highlight: {
          value: `${safe.window_15m?.fill_count || 0} fills`,
          label: `Total trades ${safe.fills_total || state.live.fillsTotal || 0}`,
          meter: splitBar(((safe.window_15m?.buy_count || 0) / total15) * 100),
        },
        rows: [
          ["Buy / Sell", `${safe.window_15m?.buy_count || 0} / ${safe.window_15m?.sell_count || 0}`],
          ["Maker Ratio", `${formatPct(safe.window_15m?.maker_ratio || 0)} ${miniBar((safe.window_15m?.maker_ratio || 0) * 100)}`],
          ["Base Volume", formatNumber(safe.window_15m?.volume_base || 0, 6)],
          ["Notional", formatNumber(safe.window_15m?.notional_quote || 0, 2)],
          ["Realized PnL", `<span class="${classifySigned(safe.window_15m?.realized_pnl_quote || 0)}">${formatSigned(safe.window_15m?.realized_pnl_quote || 0, 4)}</span>`],
          ["Avg Fill Size", formatNumber(safe.window_15m?.avg_fill_size || 0, 6)],
          ["Avg Fill Price", formatNumber(safe.window_15m?.avg_fill_price || 0, 4)],
        ],
      },
      {
        title: "Last 1h",
        highlight: {
          value: `${safe.window_1h?.fill_count || 0} fills`,
          label: `Last fill ${formatRelativeTs(safe.latest_fill_ts_ms)}`,
          meter: splitBar(((safe.window_1h?.buy_count || 0) / total1h) * 100),
        },
        rows: [
          ["Buy / Sell", `${safe.window_1h?.buy_count || 0} / ${safe.window_1h?.sell_count || 0}`],
          ["Maker Ratio", `${formatPct(safe.window_1h?.maker_ratio || 0)} ${miniBar((safe.window_1h?.maker_ratio || 0) * 100)}`],
          ["Base Volume", formatNumber(safe.window_1h?.volume_base || 0, 6)],
          ["Notional", formatNumber(safe.window_1h?.notional_quote || 0, 2)],
          ["Realized PnL", `<span class="${classifySigned(safe.window_1h?.realized_pnl_quote || 0)}">${formatSigned(safe.window_1h?.realized_pnl_quote || 0, 4)}</span>`],
          ["Avg Fill Size", formatNumber(safe.window_1h?.avg_fill_size || 0, 6)],
          ["Avg Fill Price", formatNumber(safe.window_1h?.avg_fill_price || 0, 4)],
        ],
      },
    ]);
  }

  function pruneRuntimeEvents() {
    const cutoff = Date.now() - 60 * 60 * 1000;
    state.runtimeEvents = state.runtimeEvents.filter((evt) => Number(evt.tsMs || 0) >= cutoff);
  }

  function recordRuntimeEvent(eventType, tsMs) {
    state.runtimeEvents.push({ eventType: String(eventType || ""), tsMs: Number(tsMs || Date.now()) || Date.now() });
    pruneRuntimeEvents();
  }

  function countRuntimeEvents(eventTypes, windowMs) {
    const types = new Set(Array.isArray(eventTypes) ? eventTypes : [eventTypes]);
    const cutoff = Date.now() - windowMs;
    return state.runtimeEvents.filter((evt) => evt.tsMs >= cutoff && types.has(evt.eventType)).length;
  }

  function renderLiveActivity() {
    renderSummaryCards(els.liveActivityGrid, [
      {
        title: "Realtime Flow",
        highlight: {
          value: `${countRuntimeEvents(["market_quote", "market_depth_snapshot", "bot_fill", "paper_event"], 60 * 1000)} ev/min`,
          label: "Observed local event pace",
        },
        rows: [
          ["Quotes 60s", String(countRuntimeEvents("market_quote", 60 * 1000))],
          ["Depth 60s", String(countRuntimeEvents("market_depth_snapshot", 60 * 1000))],
          ["Fills 60s", String(countRuntimeEvents("bot_fill", 60 * 1000))],
          ["Paper Events 60s", String(countRuntimeEvents("paper_event", 60 * 1000))],
        ],
      },
      {
        title: "Session",
        highlight: {
          value: statusPill(state.connection.wsStatus || "idle", state.connection.wsStatus || "neutral"),
          label: `Connected ${formatRelativeTs(state.connection.connectedAtMs)}`,
        },
        rows: [
          ["Last Event", `<span class="mono">${escapeHtml(state.connection.lastEventType || "n/a")}</span>`],
          ["Last WS Msg", formatAgeMs(Date.now() - Number(state.connection.lastMessageTsMs || 0))],
          ["Connected Since", formatTs(state.connection.connectedAtMs)],
        ],
      },
    ]);
  }

  function renderSystemSummary() {
    const summary = ensureSummary();
    const system = summary.system || {};
    const health = state.health || {};
    const freshness = Number(system.stream_age_ms ?? health.stream_age_ms);
    renderSummaryCards(els.systemSummaryGrid, [
      {
        title: "Health",
        highlight: {
          value:
            freshness <= 1500
              ? statusPill("healthy", "ok")
              : Number.isFinite(freshness) && freshness <= 15000
                ? statusPill("stale", "warn")
                : statusPill("degraded", "fail"),
          label: `Market tick ${formatRelativeTs(system.latest_market_ts_ms)}`,
        },
        rows: [
          ["API Status", statusPill(health.status || "unknown", health.status === "ok" ? "ok" : health.status === "disabled" ? "warn" : "fail")],
          ["Redis", statusPill(system.redis_available || health.redis_available ? "up" : "down", system.redis_available || health.redis_available ? "ok" : "fail")],
          ["DB", statusPill(system.db_available || health.db_available ? "up" : "down", system.db_available || health.db_available ? "ok" : "fail")],
          ["Fallback", statusPill(system.fallback_active || health.fallback_active ? "active" : "off", system.fallback_active || health.fallback_active ? "warn" : "neutral")],
          ["Stream Age", formatAgeMs(system.stream_age_ms ?? health.stream_age_ms)],
          ["Last Market Tick", formatTs(system.latest_market_ts_ms)],
        ],
      },
      {
        title: "Capacity",
        highlight: {
          value: `${system.subscriber_count || 0} subs`,
          label: `Last fill ${formatRelativeTs(system.latest_fill_ts_ms)}`,
        },
        rows: [
          ["Subscribers", String(system.subscriber_count || 0)],
          ["Market Keys", String(system.market_key_count || 0)],
          ["Depth Keys", String(system.depth_key_count || 0)],
          ["Fill Buffers", String(system.fills_key_count || 0)],
          ["Paper Buffers", String(system.paper_event_key_count || 0)],
          ["Last Fill", formatTs(system.latest_fill_ts_ms)],
        ],
      },
    ]);
  }

  function renderDepth(depth) {
    const bids = Array.isArray(depth?.bids) ? depth.bids : [];
    const asks = Array.isArray(depth?.asks) ? depth.asks : [];
    if (bids.length === 0 && asks.length === 0) {
      els.depthTableBody.innerHTML = `<tr><td colspan="4">No depth available for current selection.</td></tr>`;
      return;
    }
    const maxRows = Math.max(bids.length, asks.length, 12);
    const rows = [];
    for (let i = 0; i < maxRows; i += 1) {
      const bid = bids[i] || {};
      const ask = asks[i] || {};
      rows.push(`
        <tr class="${bid.price ? "row-bid" : ""} ${ask.price ? "row-ask" : ""}">
          <td>${formatNumber(bid.size, 6)}</td>
          <td>${formatNumber(bid.price, 4)}</td>
          <td>${formatNumber(ask.price, 4)}</td>
          <td>${formatNumber(ask.size, 6)}</td>
        </tr>
      `);
    }
    els.depthTableBody.innerHTML = rows.join("");
  }

  function renderOrders(orders) {
    const safeOrders = Array.isArray(orders) ? orders : [];
    const orderState = getOpenOrderState();
    const breakdown = getOpenOrderBreakdown(safeOrders);
    if (els.ordersPanelMeta) {
      const pills = [
        `<span class="meta-pill">Confirmed ${escapeHtml(String(breakdown.confirmed))}</span>`,
        `<span class="meta-pill">Runtime ${escapeHtml(String(breakdown.runtimeDerived))}</span>`,
      ];
      if (breakdown.estimated > 0) {
        pills.push(`<span class="meta-pill">Estimated ${escapeHtml(String(breakdown.estimated))}</span>`);
      }
      if (orderState.isRuntimeFallback && breakdown.runtimeDerived === 0 && orderState.runtime > 0) {
        pills.push(`<span class="meta-pill">Awaiting detail ${escapeHtml(String(orderState.runtime))}</span>`);
      }
      els.ordersPanelMeta.innerHTML = pills.join("");
    }
    const query = String(state.ui.executionFilter || "").trim().toLowerCase();
    const filteredOrders = query
      ? safeOrders.filter((order) =>
          [
            order.order_id,
            order.client_order_id,
            order.side,
            order.price,
            order.amount,
            order.quantity,
            order.state,
          ]
            .join(" ")
            .toLowerCase()
            .includes(query)
        )
      : safeOrders;
    if (filteredOrders.length === 0) {
      els.ordersTableBody.innerHTML = `<tr><td colspan="4">${
        orderState.isRuntimeFallback
          ? `No open-order details yet. Runtime reports ${escapeHtml(String(orderState.runtime))} active orders.`
          : "No open orders."
      }</td></tr>`;
      return;
    }
    const rows = filteredOrders.slice(0, 50).map((order) => {
      const label = order.is_estimated ? (order.estimate_source === "runtime" ? "(runtime)" : "(est.)") : "";
      const runtimeHint = order.estimate_source === "runtime"
        ? [order.trading_pair, order.price_hint_source].filter(Boolean).join(" · ")
        : "";
      const stateParts = [order.state, runtimeHint].filter(Boolean);
      const stateLabel = stateParts.length ? ` [${stateParts.join(" · ")}]` : "";
      const side = String(order.side || "").toLowerCase();
      return `
        <tr>
          <td class="mono">${escapeHtml(order.order_id || order.client_order_id || "")} ${label}${stateLabel}</td>
          <td>${sidePill(side)}</td>
          <td>${formatNumber(order.price, 4)}</td>
          <td>${formatNumber(order.amount || order.quantity || order.amount_base, 6)}</td>
        </tr>
      `;
    });
    els.ordersTableBody.innerHTML = rows.join("");
  }

  function renderFills(fills) {
    const safeFills = Array.isArray(fills) ? fills : [];
    const system = ensureSummary().system || {};
    const latestFillTsMs = safeFills.reduce((latest, rawFill) => {
      const fill = normalizeFill(rawFill);
      return Math.max(latest, Number(fill.timestamp_ms || 0) || 0);
    }, 0);
    if (els.fillsMeta) {
      els.fillsMeta.innerHTML = [
        `<span class="meta-pill">Source ${statusPill(state.live.source || "n/a", sourceTone(state.live.source || "", system.fallback_active || state.health.fallback_active))}</span>`,
        `<span class="meta-pill">Fallback ${statusPill(system.fallback_active || state.health.fallback_active ? "active" : "off", system.fallback_active || state.health.fallback_active ? "warn" : "neutral")}</span>`,
        `<span class="meta-pill">Shown ${escapeHtml(String(safeFills.length))} / ${escapeHtml(String(state.live.fillsTotal || safeFills.length || 0))}</span>`,
        `<span class="meta-pill">Latest ${escapeHtml(formatRelativeTs(latestFillTsMs || system.latest_fill_ts_ms || 0))}</span>`,
      ].join("");
    }
    const search = String(state.ui.executionFilter || "").trim().toLowerCase();
    const sideFilter = String(state.ui.fillSide || "all").toLowerCase();
    const makerFilter = String(state.ui.fillMaker || "all").toLowerCase();
    const filteredFills = safeFills.filter((rawFill) => {
      const fill = normalizeFill(rawFill);
      const haystack = [
        fill.order_id,
        fill.side,
        fill.price,
        fill.amount_base,
        fill.realized_pnl_quote,
        fill.timestamp_ms,
      ]
        .join(" ")
        .toLowerCase();
      if (search && !haystack.includes(search)) return false;
      if (sideFilter !== "all" && String(fill.side || "").toLowerCase() !== sideFilter) return false;
      if (makerFilter === "maker" && !fill.is_maker) return false;
      if (makerFilter === "taker" && fill.is_maker) return false;
      return true;
    });
    if (filteredFills.length === 0) {
      els.fillsTableBody.innerHTML = `<tr><td colspan="8">No fills received yet.</td></tr>`;
      return;
    }
    const rows = filteredFills.slice(-100).reverse().map((rawFill) => {
      const fill = normalizeFill(rawFill);
      const notional = Math.abs(fill.amount_base || 0) * (fill.price || 0);
      return `
        <tr>
          <td><div>${fill.ts || formatTs(fill.timestamp_ms)}</div><div class="hero-subvalue">${formatRelativeTs(fill.timestamp_ms)}</div></td>
          <td>${sidePill(fill.side || "")}</td>
          <td>${formatNumber(fill.price, 4)}</td>
          <td>${formatNumber(fill.amount_base, 6)}</td>
          <td>${formatNumber(notional, 2)}</td>
          <td><span class="${classifySigned(fill.realized_pnl_quote)}">${formatSigned(fill.realized_pnl_quote, 4)}</span></td>
          <td>${makerPill(fill.is_maker)}</td>
          <td class="mono">${escapeHtml(fill.order_id || "")}</td>
        </tr>
      `;
    });
    els.fillsTableBody.innerHTML = rows.join("");
  }

  function clearOrderPriceLines() {
    const lines = Array.isArray(state.chartPriceLines) ? state.chartPriceLines : [];
    lines.forEach((line) => {
      try {
        candleSeries.removePriceLine(line);
      } catch (_err) {
        // no-op
      }
    });
    state.chartPriceLines = [];
  }

  function renderChartPriceLines(orders, position) {
    const safeOrders = Array.isArray(orders) ? orders : [];
    const overlaySignature = JSON.stringify({
      orders: safeOrders
        .filter((order) => Number.isFinite(Number(order?.price)))
        .slice(0, 12)
        .map((order) => ({
          id: order.order_id || order.client_order_id || "",
          side: String(order.side || "").toLowerCase(),
          price: Number(order.price),
          amount: Number(order.amount || order.quantity || order.amount_base || 0),
          state: String(order.state || ""),
          est: Boolean(order.is_estimated),
        })),
      position: {
        qty: Number(position?.quantity || 0),
        avg: Number(position?.avg_entry_price || 0),
        side: String(position?.side || ""),
      },
    });
    if (overlaySignature === state.chartOverlaySignature) {
      return;
    }
    state.chartOverlaySignature = overlaySignature;
    clearOrderPriceLines();
    safeOrders
      .filter((order) => Number.isFinite(Number(order?.price)))
      .slice(0, 12)
      .forEach((order) => {
        const side = String(order.side || "").toLowerCase();
        const color = side === "buy" ? "#1f9d55" : side === "sell" ? "#d64545" : "#8aa0bf";
        const shortId = String(order.order_id || order.client_order_id || "").slice(0, 8);
        const estimated = order.is_estimated ? "~" : "";
        const line = candleSeries.createPriceLine({
          price: Number(order.price),
          color,
          lineWidth: 2,
          lineStyle: 2,
          axisLabelVisible: true,
          title: `${side || "ord"} ${shortId}${estimated}`,
        });
        state.chartPriceLines.push(line);
      });
    const qty = Number(position?.quantity || 0);
    const avgEntry = Number(position?.avg_entry_price || 0);
    if (Number.isFinite(avgEntry) && avgEntry > 0 && Math.abs(qty) > 0) {
      const side = String(position?.side || (qty > 0 ? "long" : qty < 0 ? "short" : "flat")).toLowerCase();
      const color = side === "short" ? "#ff8f8f" : "#7ec8ff";
      const entryLine = candleSeries.createPriceLine({
        price: avgEntry,
        color,
        lineWidth: 2,
        lineStyle: 0,
        axisLabelVisible: true,
        title: `pos ${side} ${formatNumber(qty, 6)}`,
      });
      state.chartPriceLines.push(entryLine);
    }
  }

  function renderMarketFrame() {
    const market = state.live.market || {};
    const depth = state.live.depth || {};
    const position = state.live.position || {};
    const openOrders = Array.isArray(state.live.openOrders) ? state.live.openOrders : [];
    const fills = Array.isArray(state.live.fills) ? state.live.fills : [];
    const liveMetrics = getLiveAccountMetrics();
    renderPosition({
      mode: state.live.mode || "",
      source: state.live.source || "",
      mid: market.mid_price || state.latestMid || "",
      bestBid: market.best_bid || depth.best_bid || depth?.bids?.[0]?.price || "",
      bestAsk: market.best_ask || depth.best_ask || depth?.asks?.[0]?.price || "",
      side: position.side || "",
      positionQty: position.quantity || "",
      avgEntryPrice: liveMetrics.avgEntryPrice,
      unrealizedPnl: liveMetrics.unrealizedPnl,
      realizedPnl: liveMetrics.realizedPnl,
      equityQuote: liveMetrics.equityQuote,
      openOrders: openOrders.length,
      recentFills: state.live.fillsTotal || fills.length,
      updatedTs: position.source_ts_ms || ensureSummary().system?.position_source_ts_ms || ensureSummary().account?.snapshot_ts || "",
    });
    renderAccountSummary();
    renderHeroStats();
    renderChartMeta();
  }

  function renderDepthThrottled(force = false) {
    const nowMs = Date.now();
    if (!force && nowMs - Number(state.lastDepthRenderTsMs || 0) < 250) {
      return;
    }
    state.lastDepthRenderTsMs = nowMs;
    renderDepth(state.live.depth || {});
  }

  async function refreshHealth() {
    try {
      const health = await fetchJson("/health");
      state.health = {
        status: health.status || "unknown",
        stream_age_ms: health.stream_age_ms,
        db_available: Boolean(health.db_available),
        redis_available: Boolean(health.redis_available),
        fallback_active: Boolean(health.fallback_active),
        metrics: health.metrics || {},
      };
      setBadge(state.health.status);
      renderSystemSummary();
    } catch (err) {
      state.health = { status: "fail", stream_age_ms: null, db_available: false, redis_available: false, fallback_active: false, metrics: {} };
      setBadge("fail");
      pushEventLine(`[health] ${err.message}`);
      renderSystemSummary();
    }
  }

  async function fetchLiveState() {
    if (!state.instanceName || liveStateRefreshInFlight) {
      return;
    }
    liveStateRefreshInFlight = true;
    const requestRevision = state.selectionRevision;
    const requestInstance = state.instanceName;
    const params = new URLSearchParams();
    params.set("instance_name", state.instanceName);
    if (state.controllerId) {
      params.set("controller_id", state.controllerId);
    }
    if (state.tradingPair) {
      params.set("trading_pair", state.tradingPair);
    }
    try {
      const payload = await fetchJson(`/api/v1/state?${params.toString()}`);
      if (!selectionStillCurrent(requestRevision, requestInstance)) {
        return;
      }
      const stream = payload?.stream || {};
      const fallback = payload?.fallback || {};
      const position = stream.position || fallback.position || {};
      const openOrders = Array.isArray(stream.open_orders)
        ? stream.open_orders
        : Array.isArray(fallback.open_orders)
          ? fallback.open_orders
          : [];
      const streamFills = Array.isArray(stream.fills) ? stream.fills : [];
      const fallbackFills = Array.isArray(fallback.fills) ? fallback.fills : [];
      const fills = streamFills.length > 0 ? streamFills : fallbackFills;
      const fillsTotal = Number(stream.fills_total || fallback.fills_total || state.live.fillsTotal || fills.length || 0);
      state.live.mode = payload.mode || state.live.mode;
      state.live.source = payload.source || state.live.source;
      state.live.position = position;
      state.live.openOrders = openOrders;
      state.live.fills = mergeRecentFills([], fills, 220);
      state.live.fillsTotal = Number.isFinite(fillsTotal) ? fillsTotal : state.live.fills.length;
      if (payload.summary) {
        state.live.summary = payload.summary;
      }
      updateDerivedSelection({
        controller_id: stream?.key?.controller_id || position?.controller_id || state.controllerId,
        trading_pair: stream?.market?.trading_pair || stream?.depth?.trading_pair || position?.trading_pair || state.tradingPair,
      });
      renderLiveState();
    } catch (err) {
      pushEventLine(`[state] ${err.message}`);
    } finally {
      liveStateRefreshInFlight = false;
    }
  }

  function scheduleLiveStateRefresh(delayMs = 250) {
    if (liveStateRefreshTimer) {
      clearTimeout(liveStateRefreshTimer);
    }
    liveStateRefreshTimer = setTimeout(() => {
      liveStateRefreshTimer = null;
      fetchLiveState();
    }, Math.max(0, Number(delayMs) || 0));
  }

  async function fetchDailyReview() {
    const requestRevision = state.selectionRevision;
    const requestInstance = state.instanceName;
    const params = new URLSearchParams();
    params.set("instance_name", state.instanceName);
    if (state.tradingPair) {
      params.set("trading_pair", state.tradingPair);
    }
    params.set("day", state.dailyReview.day);
    state.dailyReview.error = "";
    try {
      const payload = await fetchJson(`/api/v1/review/daily?${params.toString()}`);
      if (!selectionStillCurrent(requestRevision, requestInstance)) {
        return;
      }
      state.dailyReview.source = payload.source || "";
      state.dailyReview.review = payload.review || null;
      if (payload?.review?.day) {
        state.dailyReview.day = payload.review.day;
        if (els.dailyDayInput) {
          els.dailyDayInput.value = state.dailyReview.day;
        }
      }
    } catch (err) {
      if (!selectionStillCurrent(requestRevision, requestInstance)) {
        return;
      }
      state.dailyReview.review = null;
      state.dailyReview.source = "";
      state.dailyReview.error = `Daily review unavailable: ${err.message}`;
    }
    renderDailyReview();
  }

  async function fetchWeeklyReview() {
    const requestRevision = state.selectionRevision;
    const requestInstance = state.instanceName;
    const params = new URLSearchParams();
    params.set("instance_name", state.instanceName);
    state.weeklyReview.error = "";
    try {
      const payload = await fetchJson(`/api/v1/review/weekly?${params.toString()}`);
      if (!selectionStillCurrent(requestRevision, requestInstance)) {
        return;
      }
      state.weeklyReview.source = payload.source || "";
      state.weeklyReview.review = payload.review || null;
    } catch (err) {
      if (!selectionStillCurrent(requestRevision, requestInstance)) {
        return;
      }
      state.weeklyReview.review = null;
      state.weeklyReview.source = "";
      state.weeklyReview.error = `Weekly review unavailable: ${err.message}`;
    }
    renderWeeklyReview();
  }

  async function fetchJournalReview() {
    const requestRevision = state.selectionRevision;
    const requestInstance = state.instanceName;
    const params = new URLSearchParams();
    params.set("instance_name", state.instanceName);
    if (state.tradingPair) {
      params.set("trading_pair", state.tradingPair);
    }
    if (state.journalReview.startDay) {
      params.set("start_day", state.journalReview.startDay);
    }
    if (state.journalReview.endDay) {
      params.set("end_day", state.journalReview.endDay);
    }
    state.journalReview.error = "";
    try {
      const payload = await fetchJson(`/api/v1/review/journal?${params.toString()}`);
      if (!selectionStillCurrent(requestRevision, requestInstance)) {
        return;
      }
      state.journalReview.source = payload.source || "";
      state.journalReview.review = payload.review || null;
      const trades = Array.isArray(payload.review?.trades) ? payload.review.trades : [];
      const hasSelected = trades.some((trade) => String(trade.trade_id || "") === state.journalReview.selectedTradeId);
      state.journalReview.selectedTradeId = hasSelected ? state.journalReview.selectedTradeId : String(trades.at(-1)?.trade_id || "");
    } catch (err) {
      if (!selectionStillCurrent(requestRevision, requestInstance)) {
        return;
      }
      state.journalReview.review = null;
      state.journalReview.source = "";
      state.journalReview.error = `Journal unavailable: ${err.message}`;
      state.journalReview.selectedTradeId = "";
    }
    renderJournalReview();
  }

  function renderLiveState() {
    const position = state.live.position || {};
    const openOrders = Array.isArray(state.live.openOrders) ? state.live.openOrders : [];
    const fills = Array.isArray(state.live.fills) ? state.live.fills : [];
    const summary = ensureSummary();
    renderMarketFrame();
    renderActivitySummary(summary.activity);
    renderGateBoard();
    renderSystemSummary();
    renderLiveActivity();
    renderDepthThrottled(true);
    renderOrders(openOrders);
    renderFills(fills);
    renderChartPriceLines(openOrders, position);
    renderAlerts();
  }

  function renderWeeklyReview() {
    if (!els.weeklySummaryGrid || !els.weeklyDaysTableBody) {
      return;
    }
    const payload = state.weeklyReview.review || {};
    const summary = payload.summary || {};
    const days = Array.isArray(payload.days) ? payload.days : [];
    const regimeBreakdown = payload.regime_breakdown || {};
    const regimeTotal = Object.values(regimeBreakdown).reduce((acc, value) => acc + (Number(value) || 0), 0);
    const regimeLeader = Object.entries(regimeBreakdown)
      .sort((a, b) => (Number(b[1]) || 0) - (Number(a[1]) || 0))
      .slice(0, 3)
      .map(([name, count]) => `${String(name || "n/a").replaceAll("_", " ")} ${regimeTotal > 0 ? formatPct((Number(count) || 0) / regimeTotal, 1) : "0.0%"}`)
      .join(" · ");
    if (els.weeklyMeta) {
      els.weeklyMeta.innerHTML = [
        `<span class="meta-pill">Source ${escapeHtml(state.weeklyReview.source || "n/a")}</span>`,
        `<span class="meta-pill">Window ${escapeHtml(summary.period_start || "n/a")} → ${escapeHtml(summary.period_end || "n/a")}</span>`,
        `<span class="meta-pill">Days ${escapeHtml(String(summary.days_with_data || 0))} / ${escapeHtml(String(summary.n_days || 0))}</span>`,
      ].join("");
    }
    if (els.weeklyNarrative) {
      els.weeklyNarrative.textContent = state.weeklyReview.error || payload.narrative || "No weekly review loaded.";
    }
    renderSummaryCards(els.weeklySummaryGrid, [
      {
        title: "Performance",
        highlight: {
          value: `<span class="${classifySigned(summary.total_net_pnl_quote)}">${formatSigned(summary.total_net_pnl_quote, 4)}</span>`,
          label: "Total net PnL",
        },
        rows: [
          ["Mean / Day", `<span class="${classifySigned(summary.mean_daily_pnl_quote)}">${formatSigned(summary.mean_daily_pnl_quote, 4)}</span>`],
          ["Mean Bps", `<span class="${classifySigned(summary.mean_daily_net_pnl_bps)}">${formatSigned(summary.mean_daily_net_pnl_bps, 2)}</span>`],
          ["Sharpe", formatNumber(summary.sharpe_annualized, 3)],
          ["Win Rate", formatPct(summary.win_rate || 0, 1)],
          ["Winning / Losing", `${summary.winning_days || 0} / ${summary.losing_days || 0}`],
          ["Total Fills", String(summary.total_fills || 0)],
        ],
      },
      {
        title: "Risk / Gate",
        highlight: {
          value: statusPill(summary.gate_pass ? "pass" : "fail", summary.gate_pass ? "ok" : "fail"),
          label: "ROAD-1 gate",
        },
        rows: [
          ["Max DD", formatPct(summary.max_single_day_drawdown_pct || 0, 2)],
          ["Hard Stop Days", String(summary.hard_stop_days || 0)],
          ["Dominant Source", escapeHtml(summary.dominant_source || "n/a")],
          ["Spread Capture", statusPill(summary.spread_capture_dominant_source ? "dominant" : "not dominant", summary.spread_capture_dominant_source ? "ok" : "warn")],
          ["Dominant Regime", escapeHtml(String(summary.dominant_regime || "n/a").replaceAll("_", " "))],
          ["Failed Criteria", Array.isArray(summary.gate_failed_criteria) && summary.gate_failed_criteria.length > 0 ? `<span class="mono">${escapeHtml(summary.gate_failed_criteria.join(", "))}</span>` : "none"],
        ],
      },
      {
        title: "Warnings / Regimes",
        highlight: {
          value: `${(summary.warnings || []).length || 0} warnings`,
          label: regimeLeader || "No regime mix available",
        },
        rows: [
          ["Warnings", Array.isArray(summary.warnings) && summary.warnings.length > 0 ? `<span class="mono">${escapeHtml(summary.warnings.join(", "))}</span>` : "none"],
          ["Regime Mix", regimeLeader || "n/a"],
          ["Window Start", escapeHtml(summary.period_start || "n/a")],
          ["Window End", escapeHtml(summary.period_end || "n/a")],
          ["Days With Data", String(summary.days_with_data || 0)],
          ["Coverage Days", String(summary.n_days || 0)],
        ],
      },
    ]);
    if (days.length === 0) {
      els.weeklyDaysTableBody.innerHTML = `<tr><td colspan="7">No weekly breakdown available.</td></tr>`;
      return;
    }
    els.weeklyDaysTableBody.innerHTML = days
      .map(
        (day) => `
          <tr>
            <td>${escapeHtml(day.date || "")}</td>
            <td><span class="${classifySigned(day.net_pnl_quote || 0)}">${formatSigned(day.net_pnl_quote || 0, 4)}</span></td>
            <td><span class="${classifySigned(day.net_pnl_bps || 0)}">${formatSigned(day.net_pnl_bps || 0, 2)}</span></td>
            <td>${formatPct(day.drawdown_pct || 0, 2)}</td>
            <td>${day.fills || 0}</td>
            <td>${formatNumber(day.turnover_x || 0, 3)}</td>
            <td>${escapeHtml(String(day.dominant_regime || "n/a").replaceAll("_", " "))}</td>
          </tr>
        `
      )
      .join("");
  }

  function renderJournalReview() {
    if (!els.journalSummaryGrid || !els.journalTradesTableBody) {
      return;
    }
    const payload = state.journalReview.review || {};
    const summary = payload.summary || {};
    const trades = Array.isArray(payload.trades) ? payload.trades : [];
    const entryRegimes = summary.entry_regime_breakdown || {};
    const exitReasons = summary.exit_reason_breakdown || {};
    const topEntryRegimes = Object.entries(entryRegimes)
      .sort((a, b) => (Number(b[1]) || 0) - (Number(a[1]) || 0))
      .slice(0, 3)
      .map(([name, count]) => `${String(name || "unknown").replaceAll("_", " ")} ${count}`)
      .join(" · ");
    const topExitReasons = Object.entries(exitReasons)
      .sort((a, b) => (Number(b[1]) || 0) - (Number(a[1]) || 0))
      .slice(0, 3)
      .map(([name, count]) => `${String(name || "unknown")} ${count}`)
      .join(" · ");
    if (els.journalMeta) {
      els.journalMeta.innerHTML = [
        `<span class="meta-pill">Source ${escapeHtml(state.journalReview.source || "n/a")}</span>`,
        `<span class="meta-pill">Start ${escapeHtml(payload.start_day || state.journalReview.startDay || "all")}</span>`,
        `<span class="meta-pill">End ${escapeHtml(payload.end_day || state.journalReview.endDay || "all")}</span>`,
      ].join("");
    }
    if (els.journalNarrative) {
      els.journalNarrative.textContent = state.journalReview.error || payload.narrative || "No journal loaded.";
    }
    renderSummaryCards(els.journalSummaryGrid, [
      {
        title: "Trade Outcomes",
        highlight: {
          value: `<span class="${classifySigned(summary.realized_pnl_quote_total)}">${formatSigned(summary.realized_pnl_quote_total, 4)}</span>`,
          label: "Total realized PnL",
        },
        rows: [
          ["Closed Trades", String(summary.trade_count || 0)],
          ["Win Rate", formatPct(summary.win_rate || 0, 1)],
          ["Winning / Losing", `${summary.winning_trades || 0} / ${summary.losing_trades || 0}`],
          ["Avg Trade", `<span class="${classifySigned(summary.avg_realized_pnl_quote)}">${formatSigned(summary.avg_realized_pnl_quote, 4)}</span>`],
          ["Avg Win", `<span class="${classifySigned(summary.avg_win_quote)}">${formatSigned(summary.avg_win_quote, 4)}</span>`],
          ["Avg Loss", `<span class="${classifySigned(summary.avg_loss_quote)}">${formatSigned(summary.avg_loss_quote, 4)}</span>`],
          ["Avg MFE", `<span class="${classifySigned(summary.avg_mfe_quote)}">${formatSigned(summary.avg_mfe_quote, 4)}</span>`],
          ["Avg MAE", `<span class="${classifySigned(summary.avg_mae_quote)}">${formatSigned(summary.avg_mae_quote, 4)}</span>`],
        ],
      },
      {
        title: "Execution Cost / Timing",
        highlight: {
          value: formatNumber(summary.fees_quote_total, 4),
          label: "Total fees",
        },
        rows: [
          ["Avg Hold", formatAgeMs((summary.avg_hold_seconds || 0) * 1000)],
          ["First Entry", formatTs(summary.start_ts)],
          ["Last Exit", formatTs(summary.end_ts)],
          ["Scope Start", escapeHtml(payload.start_day || state.journalReview.startDay || "all")],
          ["Scope End", escapeHtml(payload.end_day || state.journalReview.endDay || "all")],
          ["Pair", escapeHtml(payload.trading_pair || state.tradingPair || "n/a")],
        ],
      },
      {
        title: "Context / Exit Mix",
        highlight: {
          value: topExitReasons || "n/a",
          label: "Top exit labels",
        },
        rows: [
          ["Entry Regimes", topEntryRegimes || "n/a"],
          ["Exit Reasons", topExitReasons || "n/a"],
          ["Minute Context", state.journalReview.source.includes("minute_log") ? "available" : "fills only"],
          ["Trades Shown", String(trades.length || 0)],
          ["First Entry", formatTs(summary.start_ts)],
          ["Last Exit", formatTs(summary.end_ts)],
        ],
      },
    ]);
    if (trades.length === 0) {
      els.journalTradesTableBody.innerHTML = `<tr><td colspan="12">No closed trades available for the selected range.</td></tr>`;
      renderJournalDrilldown(null);
      return;
    }
    els.journalTradesTableBody.innerHTML = trades
      .slice()
      .reverse()
      .map(
        (trade) => `
          <tr class="journal-trade-row ${String(trade.trade_id || "") === state.journalReview.selectedTradeId ? "selected" : ""}" data-trade-id="${escapeHtml(String(trade.trade_id || ""))}">
            <td><div>${formatTs(trade.entry_ts)}</div><div class="hero-subvalue">${formatRelativeTs(trade.entry_ts)}</div></td>
            <td><div>${formatTs(trade.exit_ts)}</div><div class="hero-subvalue">${formatRelativeTs(trade.exit_ts)}</div></td>
            <td>${sidePill(trade.side || "")}</td>
            <td>${formatNumber(trade.quantity, 6)}</td>
            <td>${formatNumber(trade.avg_entry_price, 4)}</td>
            <td>${formatNumber(trade.avg_exit_price, 4)}</td>
            <td>${formatAgeMs((Number(trade.hold_seconds || 0) || 0) * 1000)}</td>
            <td>
              <div>${escapeHtml(String(trade.entry_regime || "n/a").replaceAll("_", " "))} -> ${escapeHtml(String(trade.exit_regime || "n/a").replaceAll("_", " "))}</div>
              <div class="hero-subvalue">${escapeHtml(trade.entry_state || "n/a")} -> ${escapeHtml(trade.exit_state || "n/a")}</div>
            </td>
            <td>
              <div><span class="${classifySigned(trade.mfe_quote)}">${formatSigned(trade.mfe_quote, 4)}</span> / <span class="${classifySigned(trade.mae_quote)}">${formatSigned(trade.mae_quote, 4)}</span></div>
              <div class="hero-subvalue">${escapeHtml(Array.isArray(trade.risk_reasons_seen) && trade.risk_reasons_seen.length ? trade.risk_reasons_seen.join(", ") : "no risk tags")}</div>
            </td>
            <td>${formatNumber(trade.fees_quote, 4)}</td>
            <td>
              <div>${escapeHtml(trade.exit_reason_label || "n/a")}</div>
              <div class="hero-subvalue">${trade.pnl_governor_seen ? "pnl governor" : trade.order_book_stale_seen ? "book stale seen" : escapeHtml(trade.context_source || "fills only")}</div>
            </td>
            <td><span class="${classifySigned(trade.realized_pnl_quote)}">${formatSigned(trade.realized_pnl_quote, 4)}</span></td>
          </tr>
        `
      )
      .join("");
    const selectedTrade = trades.find((trade) => String(trade.trade_id || "") === state.journalReview.selectedTradeId) || trades[trades.length - 1] || null;
    if (selectedTrade && String(selectedTrade.trade_id || "") !== state.journalReview.selectedTradeId) {
      state.journalReview.selectedTradeId = String(selectedTrade.trade_id || "");
    }
    renderJournalDrilldown(selectedTrade);
  }

  function renderJournalDrilldown(trade) {
    if (!els.journalDrilldownSummaryGrid || !els.journalFillsTableBody || !els.journalPathTableBody || !els.journalGateTableBody) {
      return;
    }
    if (!trade) {
      if (els.journalDrilldownMeta) {
        els.journalDrilldownMeta.innerHTML = `<span class="meta-pill">No trade selected</span>`;
      }
      renderJournalMiniChart(null);
      els.journalDrilldownSummaryGrid.innerHTML = "";
      els.journalFillsTableBody.innerHTML = `<tr><td colspan="8">No fill cluster available.</td></tr>`;
      els.journalPathTableBody.innerHTML = `<tr><td colspan="5">No intratrade path available.</td></tr>`;
      els.journalGateTableBody.innerHTML = `<tr><td colspan="6">No gate transitions available.</td></tr>`;
      return;
    }
    const fills = Array.isArray(trade.fills) ? trade.fills : [];
    const pathPoints = Array.isArray(trade.path_points) ? trade.path_points : [];
    const gateTimeline = Array.isArray(trade.gate_timeline) ? trade.gate_timeline : [];
    const pathSummary = trade.path_summary || {};
    if (els.journalDrilldownMeta) {
      els.journalDrilldownMeta.innerHTML = [
        `<span class="meta-pill">Trade ${escapeHtml(trade.trade_id || "n/a")}</span>`,
        `<span class="meta-pill">Side ${escapeHtml(trade.side || "n/a")}</span>`,
        `<span class="meta-pill">Fills ${escapeHtml(String(trade.fill_count || fills.length || 0))}</span>`,
        `<span class="meta-pill">Path points ${escapeHtml(String(pathSummary.point_count || pathPoints.length || 0))}</span>`,
      ].join("");
    }
    renderJournalMiniChart(trade);
    renderSummaryCards(els.journalDrilldownSummaryGrid, [
      {
        title: "Selected Trade",
        highlight: {
          value: `<span class="${classifySigned(trade.realized_pnl_quote)}">${formatSigned(trade.realized_pnl_quote, 4)}</span>`,
          label: "Realized PnL",
        },
        rows: [
          ["Entry", formatTs(trade.entry_ts)],
          ["Exit", formatTs(trade.exit_ts)],
          ["Hold", formatAgeMs((Number(trade.hold_seconds || 0) || 0) * 1000)],
          ["Quantity", formatNumber(trade.quantity, 6)],
          ["Fees", formatNumber(trade.fees_quote, 4)],
          ["Exit Label", escapeHtml(trade.exit_reason_label || "n/a")],
        ],
      },
      {
        title: "Context",
        highlight: {
          value: `${escapeHtml(String(trade.entry_regime || "n/a").replaceAll("_", " "))} -> ${escapeHtml(String(trade.exit_regime || "n/a").replaceAll("_", " "))}`,
          label: `${escapeHtml(trade.entry_state || "n/a")} -> ${escapeHtml(trade.exit_state || "n/a")}`,
        },
        rows: [
          ["Risk Tags", escapeHtml(Array.isArray(trade.risk_reasons_seen) && trade.risk_reasons_seen.length ? trade.risk_reasons_seen.join(", ") : "none")],
          ["Pnl Governor", trade.pnl_governor_seen ? "seen" : "not seen"],
          ["Book Stale", trade.order_book_stale_seen ? "seen" : "not seen"],
          ["Maker Ratio", formatPct(trade.maker_ratio || 0, 1)],
          ["MFE", `<span class="${classifySigned(trade.mfe_quote)}">${formatSigned(trade.mfe_quote, 4)}</span>`],
          ["MAE", `<span class="${classifySigned(trade.mae_quote)}">${formatSigned(trade.mae_quote, 4)}</span>`],
        ],
      },
      {
        title: "Path Summary",
        highlight: {
          value: `${formatNumber(pathSummary.mid_open, 4)} -> ${formatNumber(pathSummary.mid_close, 4)}`,
          label: "Mid open to close",
        },
        rows: [
          ["Mid High", formatNumber(pathSummary.mid_high, 4)],
          ["Mid Low", formatNumber(pathSummary.mid_low, 4)],
          ["Equity Open", formatNumber(pathSummary.equity_open_quote, 4)],
          ["Equity Close", formatNumber(pathSummary.equity_close_quote, 4)],
          ["Sampled Points", String(pathSummary.point_count || pathPoints.length || 0)],
          ["Context Source", escapeHtml(trade.context_source || "n/a")],
        ],
      },
    ]);
    els.journalFillsTableBody.innerHTML = fills.length
      ? fills
          .map(
            (fill) => `
              <tr>
                <td><div>${formatTs(fill.ts)}</div><div class="hero-subvalue">${formatRelativeTs(fill.ts)}</div></td>
                <td>${escapeHtml(fill.role || "n/a")}</td>
                <td>${sidePill(fill.side || "")}</td>
                <td>${formatNumber(fill.amount_base, 6)}</td>
                <td>${formatNumber(fill.price, 4)}</td>
                <td>${formatNumber(fill.notional_quote, 4)}</td>
                <td>${formatNumber(fill.fee_quote, 4)}</td>
                <td><span class="${classifySigned(fill.realized_pnl_quote)}">${formatSigned(fill.realized_pnl_quote, 4)}</span></td>
              </tr>
            `
          )
          .join("")
      : `<tr><td colspan="8">No fill cluster available.</td></tr>`;
    els.journalPathTableBody.innerHTML = pathPoints.length
      ? pathPoints
          .map(
            (point) => `
              <tr>
                <td><div>${formatTs(point.ts)}</div><div class="hero-subvalue">${formatRelativeTs(point.ts)}</div></td>
                <td>${formatNumber(point.mid, 4)}</td>
                <td>${formatNumber(point.equity_quote, 4)}</td>
                <td>${escapeHtml(point.state || "n/a")}</td>
                <td>${escapeHtml(String(point.regime || "n/a").replaceAll("_", " "))}</td>
              </tr>
            `
          )
          .join("")
      : `<tr><td colspan="5">No intratrade path available.</td></tr>`;
    renderGateTimelineTable(els.journalGateTableBody, gateTimeline, "No gate transitions available for this trade.");
  }

  function applyCandleData(rawCandles) {
    const candles = (rawCandles || [])
      .map((c) => ({
        time: Math.floor((Number(c.bucket_ms || 0) || 0) / 1000),
        open: Number(c.open),
        high: Number(c.high),
        low: Number(c.low),
        close: Number(c.close),
      }))
      .filter(
        (c) =>
          Number.isFinite(c.time) &&
          Number.isFinite(c.open) &&
          Number.isFinite(c.high) &&
          Number.isFinite(c.low) &&
          Number.isFinite(c.close)
      );
    if (candles.length === 0 && Number.isFinite(state.latestMid)) {
      const nowSec = Math.floor(Date.now() / 1000);
      candles.push({
        time: nowSec,
        open: state.latestMid,
        high: state.latestMid,
        low: state.latestMid,
        close: state.latestMid,
      });
    }
    state.live.candles = candles;
    candleSeries.setData(candles);
  }

  function pushMidCandle(tsMs, mid) {
    const price = Number(mid);
    if (!Number.isFinite(price)) {
      return;
    }
    const tfSec = Math.max(1, Number(state.timeframeS) || 60);
    const bucketSec = Math.floor((Number(tsMs) || Date.now()) / 1000 / tfSec) * tfSec;
    const candles = Array.isArray(state.live.candles) ? state.live.candles.slice() : [];
    if (candles.length === 0) {
      const first = { time: bucketSec, open: price, high: price, low: price, close: price };
      candles.push(first);
      state.live.candles = candles;
      candleSeries.setData(candles);
      return;
    }
    const last = candles[candles.length - 1];
    if (last.time === bucketSec) {
      last.high = Math.max(last.high, price);
      last.low = Math.min(last.low, price);
      last.close = price;
      state.live.candles = candles;
      candleSeries.update(last);
    } else if (bucketSec > last.time) {
      const next = {
        time: bucketSec,
        open: Number(last.close),
        high: price,
        low: price,
        close: price,
      };
      candles.push(next);
      state.live.candles = candles.slice(-300);
      candleSeries.update(next);
    }
  }

  function applySnapshot(snapshot) {
    const selectedInstance = String(state.instanceName || "").trim();
    const incomingInstance = snapshotInstanceName(snapshot);
    if (incomingInstance && selectedInstance && incomingInstance !== selectedInstance) {
      return;
    }
    const payload = snapshot?.state || {};
    const stream = payload.stream || {};
    const fallback = payload.fallback || {};
    const market = stream.market || {};
    const depth = stream.depth || {};
    const position = stream.position || fallback.position || {};
    const stateKey = stream.key || {};
    const openOrders = Array.isArray(stream.open_orders)
      ? stream.open_orders
      : Array.isArray(fallback.open_orders)
        ? fallback.open_orders
        : [];
    const streamFills = Array.isArray(stream.fills) ? stream.fills : [];
    const fallbackFills = Array.isArray(fallback.fills) ? fallback.fills : [];
    const fills = streamFills.length > 0 ? streamFills : fallbackFills;
    const fillsTotal = Number(stream.fills_total || fallback.fills_total || fills.length || 0);

    state.live.mode = payload.mode || state.live.mode;
    state.live.source = payload.source || state.live.source;
    state.live.market = market;
    state.live.depth = depth;
    state.live.position = position;
    state.live.openOrders = openOrders;
    state.live.fills = mergeRecentFills([], fills, 220);
    state.live.fillsTotal = Number.isFinite(fillsTotal) ? fillsTotal : state.live.fills.length;
    state.live.summary = payload.summary || {
      activity: summarizeClientFills(state.live.fills, state.live.fillsTotal),
      system: emptySummary().system,
    };
    updateDerivedSelection({
      controller_id: stateKey.controller_id || state.controllerId,
      trading_pair: market.trading_pair || depth.trading_pair || position.trading_pair || state.tradingPair,
    });
    state.latestMid = toNum(market.mid_price || fallback.minute?.mid || state.latestMid);
    if (Number.isFinite(Number(market.mid_price))) {
      state.latestQuoteTsMs = Number(snapshot?.ts_ms || Date.now());
    }
    if (state.latestMid !== null) {
      ensureSummary().system.latest_market_ts_ms = Number(snapshot?.ts_ms || Date.now());
    }
    if (Array.isArray(snapshot?.candles)) {
      applyCandleData(snapshot.candles);
    } else if (Number.isFinite(state.latestMid)) {
      pushMidCandle(Date.now(), state.latestMid);
    }
    renderLiveState();
  }

  function depthMid(depth) {
    const bestBid = toNum(depth?.best_bid ?? depth?.bids?.[0]?.price);
    const bestAsk = toNum(depth?.best_ask ?? depth?.asks?.[0]?.price);
    if (Number.isFinite(bestBid) && Number.isFinite(bestAsk)) {
      return (bestBid + bestAsk) / 2;
    }
    if (Number.isFinite(bestBid)) return bestBid;
    if (Number.isFinite(bestAsk)) return bestAsk;
    return null;
  }

  function applyEventMessage(msg) {
    const eventType = String(msg?.event_type || msg?.event?.event_type || "").trim();
    const event = msg?.event || {};
    const selectedInstance = String(state.instanceName || "").trim();
    const incomingInstance = messageInstanceName(msg);
    if (incomingInstance && selectedInstance && incomingInstance !== selectedInstance) {
      return;
    }
    const tsMs = Number(msg?.ts_ms || Date.now());
    updateDerivedSelection({
      controller_id: event.controller_id || state.controllerId,
      trading_pair: event.trading_pair || state.tradingPair,
    });
    recordRuntimeEvent(eventType === "paper_exchange_event" ? "paper_event" : eventType, tsMs);
    state.connection.lastEventType = eventType || state.connection.lastEventType;
    ensureSummary().system.latest_market_ts_ms =
      eventType === "market_quote" || eventType === "market_snapshot" || eventType === "market_depth_snapshot"
        ? tsMs
        : ensureSummary().system.latest_market_ts_ms;
    const hasFreshQuote = Number(state.latestQuoteTsMs || 0) > 0 && Math.abs(tsMs - Number(state.latestQuoteTsMs || 0)) <= 5000;

    if (eventType === "market_quote") {
      state.live.market = event;
      const mid = toNum(event.mid_price);
      if (Number.isFinite(mid)) {
        state.latestMid = mid;
        state.latestQuoteTsMs = tsMs;
        pushMidCandle(tsMs, mid);
      }
      renderMarketFrame();
      return;
    }
    if (eventType === "market_snapshot") {
      const mid = toNum(event.mid_price);
      if (!hasFreshQuote && Number.isFinite(mid)) {
        state.live.market = event;
        state.latestMid = mid;
        pushMidCandle(tsMs, mid);
        renderMarketFrame();
      }
      return;
    }
    if (eventType === "market_depth_snapshot") {
      state.live.depth = event;
      state.latestDepthTsMs = tsMs;
      const mid = depthMid(event);
      if (!hasFreshQuote && Number.isFinite(mid)) {
        state.latestMid = mid;
        pushMidCandle(tsMs, mid);
      }
      renderMarketFrame();
      renderDepthThrottled(false);
      return;
    }
    if (eventType === "bot_fill") {
      state.live.fills = mergeRecentFills(state.live.fills, [event], 220);
      state.live.fillsTotal = Math.max(Number(state.live.fillsTotal || 0) + 1, state.live.fills.length);
      updateActivitySummaryWithFill(event);
      ensureSummary().system.latest_fill_ts_ms = tsMs;
      scheduleLiveStateRefresh(150);
      renderLiveState();
      return;
    }
    if (eventType === "paper_exchange_event") {
      scheduleLiveStateRefresh(150);
    }
    if (eventType) {
      pushEventLine(`[ws] ${msg.stream || "stream"} ${eventType}`);
      renderLiveActivity();
    }
  }

  function scheduleWsReconnect() {
    if (state.wsReconnectTimer) {
      clearTimeout(state.wsReconnectTimer);
    }
    state.wsReconnectTimer = setTimeout(() => {
      connectWebSocket();
    }, state.wsReconnectDelayMs);
  }

  function closeWebSocket(manual = false) {
    state.wsManualClose = manual;
    if (state.wsReconnectTimer) {
      clearTimeout(state.wsReconnectTimer);
      state.wsReconnectTimer = null;
    }
    if (state.ws) {
      try {
        state.ws.close();
      } catch (_err) {
        // no-op
      }
      state.ws = null;
    }
  }

  function connectWebSocket() {
    closeWebSocket(true);
    const url = wsUrl();
    const sessionId = Number(state.connection.wsSessionId || 0) + 1;
    const selectedInstance = String(state.instanceName || "").trim();
    state.connection.wsSessionId = sessionId;
    state.connection.wsStatus = "connecting";
    renderSystemSummary();
    renderLiveActivity();
    try {
      const ws = new WebSocket(url);
      state.ws = ws;
      state.wsManualClose = false;
      ws.onopen = () => {
        if (sessionId !== state.connection.wsSessionId || ws !== state.ws) {
          return;
        }
        state.connection.wsStatus = "connected";
        state.connection.connectedAtMs = Date.now();
        pushEventLine("[ws] connected");
        renderSystemSummary();
        renderLiveActivity();
      };
      ws.onmessage = (evt) => {
        if (sessionId !== state.connection.wsSessionId || ws !== state.ws || selectedInstance !== String(state.instanceName || "").trim()) {
          return;
        }
        state.connection.lastMessageTsMs = Date.now();
        let msg = null;
        try {
          msg = JSON.parse(evt.data);
        } catch (_err) {
          pushEventLine("[ws] invalid message");
          return;
        }
        const incomingInstance = msg.type === "snapshot" ? snapshotInstanceName(msg) : messageInstanceName(msg);
        if (incomingInstance && selectedInstance && incomingInstance !== selectedInstance) {
          return;
        }
        if (msg.type === "snapshot") {
          state.connection.lastEventType = "snapshot";
          applySnapshot(msg);
          return;
        }
        if (msg.type === "event") {
          applyEventMessage(msg);
          return;
        }
        if (msg.type === "keepalive") {
          state.connection.lastEventType = "keepalive";
          renderLiveActivity();
        }
      };
      ws.onerror = () => {
        if (sessionId !== state.connection.wsSessionId || ws !== state.ws) {
          return;
        }
        state.connection.wsStatus = "error";
        pushEventLine("[ws] error");
        renderSystemSummary();
        renderLiveActivity();
      };
      ws.onclose = () => {
        if (sessionId !== state.connection.wsSessionId) {
          return;
        }
        const manual = state.wsManualClose;
        state.ws = null;
        state.connection.wsStatus = manual ? "closed" : "reconnecting";
        renderSystemSummary();
        renderLiveActivity();
        if (!manual) {
          pushEventLine("[ws] disconnected; reconnecting");
          scheduleWsReconnect();
        }
      };
    } catch (err) {
      state.connection.wsStatus = "error";
      pushEventLine(`[ws] connect failed: ${err.message}`);
      renderSystemSummary();
      renderLiveActivity();
      scheduleWsReconnect();
    }
  }

  function resetLiveState() {
    if (liveStateRefreshTimer) {
      clearTimeout(liveStateRefreshTimer);
      liveStateRefreshTimer = null;
    }
    clearOrderPriceLines();
    state.eventLines = [];
    state.connection.lastMessageTsMs = 0;
    state.connection.lastEventType = "";
    state.latestMid = null;
    state.chartOverlaySignature = "";
    state.latestQuoteTsMs = 0;
    state.latestDepthTsMs = 0;
    state.lastDepthRenderTsMs = 0;
    state.runtimeEvents = [];
    state.live = {
      mode: "",
      source: "",
      market: {},
      depth: {},
      position: {},
      openOrders: [],
      fills: [],
      fillsTotal: 0,
      candles: [],
      summary: emptySummary(),
    };
    candleSeries.setData([]);
    renderEventFeed();
    renderLiveState();
  }

  function reconnectRealtime() {
    bumpSelectionRevision();
    resetLiveState();
    connectWebSocket();
  }

  function syncInputsToState() {
    state.apiBase = els.apiBaseInput.value.trim() || "http://localhost:9910";
    state.apiToken = els.apiTokenInput.value.trim();
    state.instanceName = els.instanceInput.value.trim();
    state.controllerId = "";
    state.tradingPair = "";
    state.timeframeS = Number(els.timeframeSelect.value) || 60;
    localStorage.setItem("hbApiBase", state.apiBase);
    localStorage.setItem("hbApiToken", state.apiToken);
  }

  function bindEvents() {
    els.applyConnectionBtn.addEventListener("click", () => {
      syncInputsToState();
      fetchInstances().finally(() => {
        syncInputsToState();
        refreshHealth();
        fetchDailyReview();
        fetchWeeklyReview();
        fetchJournalReview();
        reconnectRealtime();
      });
    });
    els.instanceInput.addEventListener("change", () => {
      state.instancePinned = true;
      syncInputsToState();
      renderInstanceStatusBoard();
      refreshHealth();
      fetchDailyReview();
      fetchWeeklyReview();
      fetchJournalReview();
      reconnectRealtime();
    });
    if (els.instanceStatusBoard) {
      els.instanceStatusBoard.addEventListener("click", (event) => {
        const target = event.target instanceof Element ? event.target.closest("[data-instance-name]") : null;
        if (!target || !els.instanceInput) {
          return;
        }
        const nextInstance = String(target.getAttribute("data-instance-name") || "").trim();
        if (!nextInstance || nextInstance === state.instanceName) {
          return;
        }
        state.instancePinned = true;
        els.instanceInput.value = nextInstance;
        syncInputsToState();
        renderInstanceStatusBoard();
        refreshHealth();
        fetchDailyReview();
        fetchWeeklyReview();
        fetchJournalReview();
        reconnectRealtime();
      });
    }
    els.refreshBtn.addEventListener("click", () => {
      syncInputsToState();
      fetchInstances().finally(() => {
        syncInputsToState();
        refreshHealth();
        fetchDailyReview();
        fetchWeeklyReview();
        fetchJournalReview();
        reconnectRealtime();
      });
    });
    els.timeframeSelect.addEventListener("change", () => {
      syncInputsToState();
      reconnectRealtime();
    });
    els.denseModeBtn.addEventListener("click", () => {
      state.ui.denseMode = !state.ui.denseMode;
      localStorage.setItem("hbDenseMode", state.ui.denseMode ? "1" : "0");
      applyDenseMode();
      resizeChartToPanel();
    });
    els.resetLayoutBtn.addEventListener("click", () => {
      resetResizablePanels();
    });
    if (els.executionFilterInput) {
      els.executionFilterInput.addEventListener("input", () => {
        state.ui.executionFilter = els.executionFilterInput.value.trim();
        renderOrders(state.live.openOrders);
        renderFills(state.live.fills);
      });
    }
    els.fillSideFilter.addEventListener("change", () => {
      state.ui.fillSide = els.fillSideFilter.value;
      renderFills(state.live.fills);
    });
    els.fillMakerFilter.addEventListener("change", () => {
      state.ui.fillMaker = els.fillMakerFilter.value;
      renderFills(state.live.fills);
    });
    els.eventFilterInput.addEventListener("input", () => {
      state.ui.eventFilter = els.eventFilterInput.value.trim();
      renderEventFeed();
    });
    els.clearEventFeedBtn.addEventListener("click", () => {
      state.eventLines = [];
      renderEventFeed();
    });
    els.viewTabs.forEach((btn) => {
      btn.addEventListener("click", () => {
        const nextView = btn.getAttribute("data-view-tab") || "realtime";
        state.ui.activeView = nextView;
        localStorage.setItem("hbActiveView", nextView);
        renderActiveView();
        renderAlerts();
        if (nextView === "daily") {
          fetchDailyReview();
        }
        if (nextView === "weekly") {
          fetchWeeklyReview();
        }
        if (nextView === "journal") {
          fetchJournalReview();
        }
      });
    });
    if (els.dailyDayInput) {
      els.dailyDayInput.addEventListener("change", () => {
        state.dailyReview.day = els.dailyDayInput.value || state.dailyReview.day;
        if (state.ui.activeView === "daily") {
          fetchDailyReview();
        }
      });
    }
    if (els.dailyRefreshBtn) {
      els.dailyRefreshBtn.addEventListener("click", () => {
        state.dailyReview.day = els.dailyDayInput?.value || state.dailyReview.day;
        fetchDailyReview();
      });
    }
    if (els.journalStartDayInput) {
      els.journalStartDayInput.addEventListener("change", () => {
        state.journalReview.startDay = els.journalStartDayInput.value || "";
        if (state.ui.activeView === "journal") {
          fetchJournalReview();
        }
      });
    }
    if (els.journalEndDayInput) {
      els.journalEndDayInput.addEventListener("change", () => {
        state.journalReview.endDay = els.journalEndDayInput.value || "";
        if (state.ui.activeView === "journal") {
          fetchJournalReview();
        }
      });
    }
    if (els.journalRefreshBtn) {
      els.journalRefreshBtn.addEventListener("click", () => {
        state.journalReview.startDay = els.journalStartDayInput?.value || "";
        state.journalReview.endDay = els.journalEndDayInput?.value || "";
        fetchJournalReview();
      });
    }
    if (els.journalTradesTableBody) {
      els.journalTradesTableBody.addEventListener("click", (event) => {
        const row = event.target instanceof Element ? event.target.closest("[data-trade-id]") : null;
        if (!row) {
          return;
        }
        const nextTradeId = row.getAttribute("data-trade-id") || "";
        if (!nextTradeId) {
          return;
        }
        state.journalReview.selectedTradeId = nextTradeId;
        renderJournalReview();
      });
    }
  }

  async function init() {
    els.apiBaseInput.value = state.apiBase;
    els.apiTokenInput.value = state.apiToken;
    setInstanceOptions([state.instanceName || "bot1"], state.instanceName || "bot1");
    if (els.executionFilterInput) {
      els.executionFilterInput.value = state.ui.executionFilter;
    }
    els.fillSideFilter.value = state.ui.fillSide;
    els.fillMakerFilter.value = state.ui.fillMaker;
    els.eventFilterInput.value = state.ui.eventFilter;
    if (els.dailyDayInput) {
      els.dailyDayInput.value = state.dailyReview.day;
    }
    if (els.journalStartDayInput) {
      els.journalStartDayInput.value = state.journalReview.startDay;
    }
    if (els.journalEndDayInput) {
      els.journalEndDayInput.value = state.journalReview.endDay;
    }
    applyDenseMode();
    initResizableLayout();
    bindEvents();
    await fetchInstances();
    syncInputsToState();
    renderActiveView();
    renderLiveState();
    renderDailyReview();
    renderWeeklyReview();
    renderJournalReview();
    renderEventFeed();
    renderInstanceStatusBoard();
    refreshHealth();
    fetchDailyReview();
    fetchWeeklyReview();
    fetchJournalReview();
    reconnectRealtime();
    setInterval(refreshHealth, 10000);
    instanceRefreshTimer = window.setInterval(() => {
      fetchInstances().then(({ previousSelection, nextSelection }) => {
        if (nextSelection && previousSelection && nextSelection !== previousSelection) {
          syncInputsToState();
          refreshHealth();
          fetchDailyReview();
          fetchWeeklyReview();
          fetchJournalReview();
          reconnectRealtime();
        }
      });
    }, 30000);
    setInterval(() => {
      pruneRuntimeEvents();
      renderLiveActivity();
      renderSystemSummary();
    }, 5000);
  }

  init();
})();
