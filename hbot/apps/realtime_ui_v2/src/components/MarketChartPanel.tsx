import { useEffect, useMemo, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  LineStyle,
  createSeriesMarkers,
  createChart,
  type CandlestickData,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type Time,
} from "lightweight-charts";
import { useShallow } from "zustand/react/shallow";

import { useDashboardStore } from "../store/useDashboardStore";
import type { UiCandle } from "../types/realtime";
import { formatNumber, toNum } from "../utils/format";
import { getDepthStats } from "../utils/metrics";
import { Panel } from "./Panel";

const EMPTY_DEPTH_LEVELS: [] = [];
const LATEST_CANDLE_UPDATE_MS = 750;

export function MarketChartPanel() {
  const {
    candles,
    latestCandle,
    candleSeriesNonce,
    orders,
    fills,
    position,
    marketMidPrice,
    midPriceDirection,
    depthBestBid,
    depthBestAsk,
    depthBids,
    depthAsks,
    latestMid,
  } = useDashboardStore(
    useShallow((state) => ({
      candles: state.candles,
      latestCandle: state.latestCandle,
      candleSeriesNonce: state.candleSeriesNonce,
      orders: state.orders,
      fills: state.fills,
      position: state.position,
      marketMidPrice: state.market.mid_price,
      midPriceDirection: state.midPriceDirection,
      depthBestBid: state.depth.best_bid,
      depthBestAsk: state.depth.best_ask,
      depthBids: state.depth.bids,
      depthAsks: state.depth.asks,
      latestMid: state.latestMid,
    })),
  );
  const timeframeS = useDashboardStore((state) => state.settings.timeframeS);
  const updateSettings = useDashboardStore((state) => state.updateSettings);
  const chartRootRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick", Time> | null>(null);
  const priceLinesRef = useRef<IPriceLine[]>([]);
  const fillMarkersRef = useRef<ReturnType<typeof createSeriesMarkers<Time>> | null>(null);
  const overlaySignatureRef = useRef("");
  const latestAppliedCandleRef = useRef("");
  const queuedLatestCandleRef = useRef<UiCandle | null>(null);
  const latestCandleTimerRef = useRef<number | null>(null);

  const stats = useMemo(
    () =>
      getDepthStats({
        best_bid: depthBestBid,
        best_ask: depthBestAsk,
        bids: depthBids ?? EMPTY_DEPTH_LEVELS,
        asks: depthAsks ?? EMPTY_DEPTH_LEVELS,
      }),
    [depthAsks, depthBestAsk, depthBestBid, depthBids],
  );
  const chartCandles = useMemo(
    () =>
      candles.map((entry) => ({
        time: entry.time as Time,
        open: entry.open,
        high: entry.high,
        low: entry.low,
        close: entry.close,
      })),
    [candles],
  );
  const displayMid = toNum(marketMidPrice) ?? toNum(latestMid);
  const priceDirectionClass = midPriceDirection === "up" ? "value-positive" : midPriceDirection === "down" ? "value-negative" : "value-neutral";
  const fillMarkers = useMemo(
    () =>
      fills
        .filter((fill) => {
          const tsMs = Number(fill.timestamp_ms ?? 0);
          const price = Number(fill.price ?? 0);
          return Number.isFinite(tsMs) && tsMs > 0 && Number.isFinite(price) && price > 0;
        })
        .slice(-60)
        .map((fill) => {
          const isSell = String(fill.side || "").toLowerCase() === "sell";
          return {
            time: Math.floor(Number(fill.timestamp_ms) / 1000) as Time,
            position: (isSell ? "aboveBar" : "belowBar") as "aboveBar" | "belowBar",
            color: isSell ? "#ff8f8f" : "#8ef7b2",
            shape: (isSell ? "arrowDown" : "arrowUp") as "arrowDown" | "arrowUp",
            price: Number(fill.price ?? 0),
            text: `${String(fill.side || "").toUpperCase()} ${formatNumber(fill.price, 2)}`,
          };
        }),
    [fills],
  );

  useEffect(() => {
    const root = chartRootRef.current;
    if (!root) {
      return;
    }
    const chart = createChart(root, {
      layout: {
        background: { type: ColorType.Solid, color: "#121a28" },
        textColor: "#dce3f0",
      },
      grid: {
        vertLines: { color: "#273244" },
        horzLines: { color: "#273244" },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: true,
        borderColor: "#3c4555",
      },
      rightPriceScale: {
        borderColor: "#3c4555",
      },
      crosshair: {
        mode: 0,
      },
      width: Math.max(320, root.clientWidth),
      height: Math.max(260, root.clientHeight || 360),
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#1f9d55",
      downColor: "#d64545",
      borderVisible: false,
      wickUpColor: "#1f9d55",
      wickDownColor: "#d64545",
    });
    chartRef.current = chart;
    candleSeriesRef.current = series;
    fillMarkersRef.current = createSeriesMarkers(series, []);

    const resize = () => {
      const width = Math.max(320, root.clientWidth);
      const height = Math.max(260, root.clientHeight || 360);
      chart.applyOptions({ width, height });
    };
    resize();
    const resizeObserver = new ResizeObserver(() => {
      resize();
    });
    resizeObserver.observe(root);

    return () => {
      resizeObserver.disconnect();
      if (latestCandleTimerRef.current !== null) {
        window.clearTimeout(latestCandleTimerRef.current);
        latestCandleTimerRef.current = null;
      }
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      priceLinesRef.current = [];
      fillMarkersRef.current = null;
      overlaySignatureRef.current = "";
      latestAppliedCandleRef.current = "";
      queuedLatestCandleRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!candleSeriesRef.current) {
      return;
    }
    candleSeriesRef.current.setData(chartCandles as CandlestickData[]);
    const lastChartCandle = chartCandles[chartCandles.length - 1] ?? null;
    latestAppliedCandleRef.current = lastChartCandle
      ? `${lastChartCandle.time}-${lastChartCandle.close}-${lastChartCandle.high}-${lastChartCandle.low}`
      : "";
  }, [candleSeriesNonce, chartCandles]);

  useEffect(() => {
    if (!candleSeriesRef.current || !latestCandle) {
      return;
    }
    queuedLatestCandleRef.current = latestCandle;
    if (latestCandleTimerRef.current !== null) {
      return;
    }
    latestCandleTimerRef.current = window.setTimeout(() => {
      latestCandleTimerRef.current = null;
      const queuedLatestCandle = queuedLatestCandleRef.current;
      if (!candleSeriesRef.current || !queuedLatestCandle) {
        return;
      }
      const nextKey = `${queuedLatestCandle.time}-${queuedLatestCandle.close}-${queuedLatestCandle.high}-${queuedLatestCandle.low}`;
      if (latestAppliedCandleRef.current === nextKey) {
        return;
      }
      candleSeriesRef.current.update({
        time: queuedLatestCandle.time as Time,
        open: queuedLatestCandle.open,
        high: queuedLatestCandle.high,
        low: queuedLatestCandle.low,
        close: queuedLatestCandle.close,
      });
      latestAppliedCandleRef.current = nextKey;
    }, LATEST_CANDLE_UPDATE_MS);
  }, [latestCandle]);

  useEffect(() => {
    fillMarkersRef.current?.setMarkers(fillMarkers);
  }, [fillMarkers]);

  useEffect(() => {
    const series = candleSeriesRef.current;
    if (!series) {
      return;
    }
    const overlaySignature = JSON.stringify({
      orders: orders
        .filter((order) => Number.isFinite(Number(order.price)))
        .slice(0, 12)
        .map((order) => ({
          id: String(order.order_id || order.client_order_id || "").slice(0, 8),
          side: String(order.side || "").toLowerCase(),
          price: Number(order.price),
        })),
      position: {
        avgEntry: toNum(position.avg_entry_price),
        qty: toNum(position.quantity),
        side: String(position.side || "").toLowerCase(),
      },
    });
    if (overlaySignatureRef.current === overlaySignature) {
      return;
    }
    overlaySignatureRef.current = overlaySignature;
    priceLinesRef.current.forEach((line) => {
      try {
        series.removePriceLine(line);
      } catch {
        // no-op
      }
    });
    priceLinesRef.current = [];

    orders
      .filter((order) => Number.isFinite(Number(order.price)))
      .slice(0, 12)
      .forEach((order) => {
        const side = String(order.side || "").toLowerCase();
        const color = side === "buy" ? "#1f9d55" : side === "sell" ? "#d64545" : "#8aa0bf";
        const shortId = String(order.order_id || order.client_order_id || "").slice(0, 8);
        const line = series.createPriceLine({
          price: Number(order.price),
          color,
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: `${side || "ord"} ${shortId}`,
        });
        priceLinesRef.current.push(line);
      });

    const avgEntry = toNum(position.avg_entry_price);
    const qty = toNum(position.quantity);
    if (avgEntry !== null && avgEntry > 0 && qty !== null && Math.abs(qty) > 0) {
      const side = String(position.side || (qty > 0 ? "long" : "short")).toLowerCase();
      const color = side === "short" ? "#ff8f8f" : "#7ec8ff";
      const line = series.createPriceLine({
        price: avgEntry,
        color,
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: `pos ${side} ${formatNumber(qty, 6)}`,
      });
      priceLinesRef.current.push(line);
    }
  }, [orders, position]);

  return (
    <Panel
      title="Price Chart"
      subtitle="Realtime candles with open-order and position overlays."
      className="panel-span-8 chart-panel"
      actions={
        <label className="chart-control">
          <span>Timeframe</span>
          <select
            value={String(timeframeS)}
            onChange={(event) => {
              updateSettings({ timeframeS: Number(event.target.value) || 60 });
            }}
          >
            <option value="15">15s</option>
            <option value="30">30s</option>
            <option value="60">1m</option>
            <option value="300">5m</option>
          </select>
        </label>
      }
    >
      <div className="panel-meta-row">
        <span className={`meta-pill ${priceDirectionClass}`.trim()}>Mid {formatNumber(displayMid, 4)}</span>
        <span className="meta-pill">Bid {formatNumber(stats.bestBid, 4)}</span>
        <span className="meta-pill">Ask {formatNumber(stats.bestAsk, 4)}</span>
        <span className="meta-pill">Spread {formatNumber(stats.spreadPct, 3)}%</span>
        <span className="meta-pill">Candles {candles.length}</span>
        <span className="meta-pill">Last {formatNumber(latestCandle?.close, 4)}</span>
      </div>
      <div ref={chartRootRef} className="chart-root" />
    </Panel>
  );
}
