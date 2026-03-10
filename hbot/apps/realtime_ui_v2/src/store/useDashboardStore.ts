import { create } from "zustand";
import { subscribeWithSelector } from "zustand/middleware";

import type {
  ConnectionStatus,
  PayloadRecord,
  RestStatePayload,
  RuntimeEvent,
  SummaryActivity,
  SummaryAccount,
  SummaryAlert,
  SummarySystem,
  UiCandle,
  UiDepth,
  UiDepthLevel,
  UiFill,
  UiMarket,
  UiOrder,
  UiPosition,
  WsEventMessage,
  WsInboundMessage,
  WsSnapshotMessage,
} from "../types/realtime";
import { readLocalStorage, readSessionStorage, writeLocalStorage, writeSessionStorage } from "../utils/browserStorage";

const MAX_EVENT_LINES = 100;
const MAX_PAYLOAD_RECORDS = 20;
const MAX_FILLS = 220;
const MAX_CANDLES = 300;
const RUNTIME_EVENT_RETENTION_MS = 5 * 60 * 1000;
const MAX_RUNTIME_EVENTS = 600;
const LAST_MESSAGE_UI_UPDATE_MS = 250;

export interface DashboardSettings {
  apiBase: string;
  apiToken: string;
  instanceName: string;
  timeframeS: number;
  orderFilter: string;
  fillFilter: string;
  fillSide: "all" | "buy" | "sell";
  fillMaker: "all" | "maker" | "taker";
  eventFilter: string;
  feedPaused: boolean;
  autoScrollFeed: boolean;
}

interface HealthState {
  status: string;
  streamAgeMs: number | null;
  dbAvailable: boolean;
  redisAvailable: boolean;
  fallbackActive: boolean;
}

interface ConnectionState {
  status: ConnectionStatus;
  wsSessionId: number;
  connectedAtMs: number;
  lastMessageTsMs: number;
  lastEventType: string;
  reconnectCount: number;
  parseErrorCount: number;
  droppedMessageCount: number;
}

interface DataFreshnessState {
  marketTsMs: number;
  depthTsMs: number;
  positionTsMs: number;
  ordersTsMs: number;
  fillsTsMs: number;
  staleRestRejectCount: number;
}

interface DashboardState {
  settings: DashboardSettings;
  health: HealthState;
  connection: ConnectionState;
  freshness: DataFreshnessState;
  mode: string;
  source: string;
  summarySystem: SummarySystem;
  summaryActivity: SummaryActivity;
  summaryAccount: SummaryAccount;
  alerts: SummaryAlert[];
  market: UiMarket;
  depth: UiDepth;
  position: UiPosition;
  latestMid: number | null;
  midPriceDirection: "up" | "down" | "flat";
  latestQuoteTsMs: number;
  candles: UiCandle[];
  latestCandle: UiCandle | null;
  candleSeriesNonce: number;
  orders: UiOrder[];
  fills: UiFill[];
  fillsTotal: number;
  eventLines: string[];
  payloads: PayloadRecord[];
  selectedPayloadId: string | null;
  runtimeEvents: RuntimeEvent[];
  instanceNames: string[];
  updateSettings: (patch: Partial<DashboardSettings>) => void;
  setInstanceNames: (names: string[]) => void;
  setSelectedPayloadId: (id: string | null) => void;
  clearEventFeed: () => void;
  appendEventLine: (line: string) => void;
  setConnectionStatus: (status: ConnectionStatus) => void;
  beginSession: () => number;
  markConnected: () => void;
  markReconnectAttempt: () => void;
  markParseError: () => void;
  markDroppedMessage: () => void;
  markMessageReceived: (eventType?: string) => void;
  setHealth: (health: Partial<HealthState>) => void;
  pushPayloadRecord: (message: WsInboundMessage, receivedAtMs: number) => void;
  ingestSnapshot: (snapshot: WsSnapshotMessage) => void;
  ingestEventMessage: (message: WsEventMessage) => void;
  ingestRestState: (payload: RestStatePayload, requestedInstanceName?: string) => void;
  pruneRuntimeEvents: () => void;
  resetLiveData: () => void;
}

const DEFAULT_SETTINGS: DashboardSettings = {
  apiBase: readLocalStorage("hbV2ApiBase", "http://localhost:9910") || "http://localhost:9910",
  apiToken: readSessionStorage("hbV2ApiToken", ""),
  instanceName: readLocalStorage("hbV2InstanceName", "bot1") || "bot1",
  timeframeS: Number(readLocalStorage("hbV2TimeframeS", "60") || 60) || 60,
  orderFilter: "",
  fillFilter: "",
  fillSide: "all",
  fillMaker: "all",
  eventFilter: "",
  feedPaused: false,
  autoScrollFeed: true,
};

function defaultSummarySystem(): SummarySystem {
  return {
    fallback_active: false,
    latest_fill_ts_ms: 0,
    latest_market_ts_ms: 0,
    stream_age_ms: 0,
  };
}

function defaultSummaryActivity(): SummaryActivity {
  return {
    fills_total: 0,
    latest_fill_ts_ms: 0,
    realized_pnl_total_quote: 0,
    window_15m: {},
    window_1h: {},
  };
}

function defaultSummaryAccount(): SummaryAccount {
  return {};
}

function shallowEqualRecord(left: Record<string, unknown>, right: Record<string, unknown>): boolean {
  const leftEntries = Object.entries(left);
  const rightEntries = Object.entries(right);
  if (leftEntries.length !== rightEntries.length) {
    return false;
  }
  return leftEntries.every(([key, value]) => right[key] === value);
}

function mergeSummaryWindow(
  currentWindow: SummaryActivity["window_15m"] | SummaryActivity["window_1h"],
  incomingWindow: SummaryActivity["window_15m"] | SummaryActivity["window_1h"],
) {
  if (!incomingWindow) {
    return currentWindow;
  }
  const currentRecord = (currentWindow ?? {}) as Record<string, unknown>;
  const incomingRecord = incomingWindow as Record<string, unknown>;
  const mergedRecord = { ...currentRecord, ...incomingRecord };
  return shallowEqualRecord(currentRecord, mergedRecord) ? currentWindow : mergedRecord;
}

function mergeSummaryActivity(current: SummaryActivity, incoming?: SummaryActivity): SummaryActivity {
  if (!incoming) {
    return current;
  }
  const nextWindow15m = mergeSummaryWindow(current.window_15m, incoming.window_15m);
  const nextWindow1h = mergeSummaryWindow(current.window_1h, incoming.window_1h);
  const mergedActivity: SummaryActivity = {
    ...current,
    ...incoming,
    window_15m: nextWindow15m,
    window_1h: nextWindow1h,
  };
  return shallowEqualRecord(current as Record<string, unknown>, mergedActivity as Record<string, unknown>) ? current : mergedActivity;
}

function mergeSummarySystem(current: SummarySystem, incoming?: Partial<SummarySystem>): SummarySystem {
  if (!incoming) {
    return current;
  }
  const merged = { ...current, ...incoming };
  return shallowEqualRecord(current as Record<string, unknown>, merged as Record<string, unknown>) ? current : merged;
}

function mergeSummaryAccount(current: SummaryAccount, incoming?: Partial<SummaryAccount>): SummaryAccount {
  if (!incoming) {
    return current;
  }
  const merged = { ...current, ...incoming };
  return shallowEqualRecord(current as Record<string, unknown>, merged as Record<string, unknown>) ? current : merged;
}

function sameAlert(left: SummaryAlert, right: SummaryAlert): boolean {
  return (
    String(left.severity ?? "") === String(right.severity ?? "") &&
    String(left.title ?? "") === String(right.title ?? "") &&
    String(left.detail ?? "") === String(right.detail ?? "")
  );
}

function normalizeAlerts(alerts: SummaryAlert[]): SummaryAlert[] {
  return alerts.map((entry) => ({
    severity: String(entry.severity ?? ""),
    title: String(entry.title ?? ""),
    detail: String(entry.detail ?? ""),
  }));
}

function mergeAlerts(current: SummaryAlert[], incoming: unknown): SummaryAlert[] {
  if (!Array.isArray(incoming)) {
    return current;
  }
  const normalizedIncoming = normalizeAlerts(incoming as SummaryAlert[]);
  if (normalizedIncoming.length === 0) {
    return current.length === 0 ? current : EMPTY_ALERTS;
  }
  if (
    current.length === normalizedIncoming.length &&
    current.every((entry, index) => sameAlert(entry, normalizedIncoming[index]))
  ) {
    return current;
  }
  return normalizedIncoming;
}

function normalizeInstanceNames(names: string[]): string[] {
  return names.length === 0
    ? EMPTY_INSTANCE_NAMES
    : Array.from(new Set(names.map((entry) => String(entry || "").trim()).filter(Boolean))).sort((left, right) => left.localeCompare(right));
}

function sameStringArray(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((entry, index) => entry === right[index]);
}

function defaultHealth(): HealthState {
  return {
    status: "unknown",
    streamAgeMs: null,
    dbAvailable: false,
    redisAvailable: false,
    fallbackActive: false,
  };
}

function defaultConnection(): ConnectionState {
  return {
    status: "idle",
    wsSessionId: 0,
    connectedAtMs: 0,
    lastMessageTsMs: 0,
    lastEventType: "",
    reconnectCount: 0,
    parseErrorCount: 0,
    droppedMessageCount: 0,
  };
}

function defaultFreshness(): DataFreshnessState {
  return {
    marketTsMs: 0,
    depthTsMs: 0,
    positionTsMs: 0,
    ordersTsMs: 0,
    fillsTsMs: 0,
    staleRestRejectCount: 0,
  };
}

function toNum(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function toEpochMs(value: unknown): number {
  if (value instanceof Date) {
    return Number.isFinite(value.getTime()) ? value.getTime() : 0;
  }
  const numeric = Number(value);
  if (Number.isFinite(numeric) && numeric > 0) {
    if (numeric > 100_000_000_000) {
      return Math.trunc(numeric);
    }
    if (numeric > 1_000_000_000) {
      return Math.trunc(numeric * 1000);
    }
    return Math.trunc(numeric);
  }
  const raw = String(value ?? "").trim();
  if (!raw) {
    return 0;
  }
  const parsed = Date.parse(raw);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

function maxTsMs(...values: unknown[]): number {
  return values.reduce<number>((maxValue, value) => Math.max(maxValue, toEpochMs(value)), 0);
}

function keyInstanceName(key: unknown): string {
  if (key && typeof key === "object") {
    const safe = key as { instance_name?: unknown; instance?: unknown };
    return String(safe.instance_name ?? safe.instance ?? "").trim();
  }
  if (Array.isArray(key)) {
    return String(key[0] ?? "").trim();
  }
  return "";
}

function keyControllerId(key: unknown): string {
  if (key && typeof key === "object") {
    const safe = key as { controller_id?: unknown; controller?: unknown };
    return String(safe.controller_id ?? safe.controller ?? "").trim();
  }
  if (Array.isArray(key)) {
    return String(key[1] ?? "").trim();
  }
  return "";
}

function keyTradingPair(key: unknown): string {
  if (key && typeof key === "object") {
    const safe = key as { trading_pair?: unknown; pair?: unknown };
    return String(safe.trading_pair ?? safe.pair ?? "").trim();
  }
  if (Array.isArray(key)) {
    return String(key[2] ?? "").trim();
  }
  return "";
}

function snapshotInstanceName(snapshot: WsSnapshotMessage): string {
  const payload = snapshot.state ?? {};
  return String(
    snapshot.instance_name ??
      keyInstanceName(snapshot.key) ??
      keyInstanceName(payload.key) ??
      keyInstanceName(payload.stream?.key) ??
      "",
  ).trim();
}

function snapshotControllerId(snapshot: WsSnapshotMessage): string {
  const payload = snapshot.state ?? {};
  return String(
    snapshot.controller_id ??
      keyControllerId(snapshot.key) ??
      keyControllerId(payload.key) ??
      keyControllerId(payload.stream?.key) ??
      "",
  ).trim();
}

function snapshotTradingPair(snapshot: WsSnapshotMessage): string {
  const payload = snapshot.state ?? {};
  return String(
    snapshot.trading_pair ??
      keyTradingPair(snapshot.key) ??
      keyTradingPair(payload.key) ??
      keyTradingPair(payload.stream?.key) ??
      payload.stream?.market?.trading_pair ??
      payload.stream?.depth?.trading_pair ??
      payload.stream?.position?.trading_pair ??
      "",
  ).trim();
}

function messageInstanceName(message: WsEventMessage): string {
  const event = message.event;
  const eventInstance =
    event && typeof event === "object" && "instance_name" in event ? String((event as { instance_name?: unknown }).instance_name ?? "") : "";
  return String(message.instance_name ?? keyInstanceName(message.key) ?? eventInstance ?? "").trim();
}

function messageControllerId(message: WsEventMessage): string {
  const event = message.event;
  const eventController =
    event && typeof event === "object" && "controller_id" in event ? String((event as { controller_id?: unknown }).controller_id ?? "") : "";
  return String(message.controller_id ?? keyControllerId(message.key) ?? eventController ?? "").trim();
}

function messageTradingPair(message: WsEventMessage): string {
  const event = message.event;
  const eventTradingPair =
    event && typeof event === "object" && "trading_pair" in event ? String((event as { trading_pair?: unknown }).trading_pair ?? "") : "";
  return String(message.trading_pair ?? keyTradingPair(message.key) ?? eventTradingPair ?? "").trim();
}

function restStateInstanceName(payload: RestStatePayload): string {
  return String(
    keyInstanceName(payload.key) ??
      keyInstanceName(payload.stream?.key) ??
      "",
  ).trim();
}

function restStateControllerId(payload: RestStatePayload): string {
  return String(keyControllerId(payload.key) ?? keyControllerId(payload.stream?.key) ?? "").trim();
}

function restStateTradingPair(payload: RestStatePayload): string {
  return String(
    keyTradingPair(payload.key) ??
      keyTradingPair(payload.stream?.key) ??
      payload.stream?.market?.trading_pair ??
      payload.stream?.depth?.trading_pair ??
      payload.stream?.position?.trading_pair ??
      "",
  ).trim();
}

function matchesSelectedInstance(selected: string, incoming: string): boolean {
  if (!incoming || !selected) {
    return true;
  }
  return incoming === selected;
}

function normalizePair(value: unknown): string {
  return String(value ?? "")
    .trim()
    .toUpperCase()
    .replace(/[\/_\s]+/g, "-");
}

function resolvedStatePair(state: Pick<DashboardState, "market" | "depth" | "position">): string {
  return String(state.market.trading_pair ?? state.depth.trading_pair ?? state.position.trading_pair ?? "").trim();
}

function shouldAcceptSharedMarketEvent(
  state: Pick<DashboardState, "market" | "depth" | "position">,
  eventType: string,
  incomingInstanceName: string,
  incomingTradingPair: string,
): boolean {
  if (incomingInstanceName.trim()) {
    return true;
  }
  if (!["market_quote", "market_snapshot", "market_depth_snapshot"].includes(eventType)) {
    return true;
  }
  const activePair = normalizePair(resolvedStatePair(state));
  const eventPair = normalizePair(incomingTradingPair);
  if (!eventPair) {
    return false;
  }
  if (!activePair) {
    return false;
  }
  return activePair === eventPair;
}

function normalizeDepthLevel(value: unknown): UiDepthLevel | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const safe = value as UiDepthLevel;
  return {
    price: safe.price,
    size: safe.size,
  };
}

function normalizeDepth(value: unknown): UiDepth {
  if (!value || typeof value !== "object") {
    return {};
  }
  const safe = value as UiDepth;
  return {
    ...safe,
    bids: Array.isArray(safe.bids) ? safe.bids.map((entry) => normalizeDepthLevel(entry)).filter(Boolean) as UiDepthLevel[] : [],
    asks: Array.isArray(safe.asks) ? safe.asks.map((entry) => normalizeDepthLevel(entry)).filter(Boolean) as UiDepthLevel[] : [],
  };
}

function normalizeMarket(value: unknown): UiMarket {
  if (!value || typeof value !== "object") {
    return {};
  }
  return value as UiMarket;
}

function normalizePosition(value: unknown): UiPosition {
  if (!value || typeof value !== "object") {
    return {};
  }
  return value as UiPosition;
}

function sameDepthLevel(left: UiDepthLevel | undefined, right: UiDepthLevel | undefined): boolean {
  return Number(left?.price ?? NaN) === Number(right?.price ?? NaN) && Number(left?.size ?? NaN) === Number(right?.size ?? NaN);
}

function sameDepthLevels(left: UiDepthLevel[] | undefined, right: UiDepthLevel[] | undefined): boolean {
  const safeLeft = Array.isArray(left) ? left : [];
  const safeRight = Array.isArray(right) ? right : [];
  return safeLeft.length === safeRight.length && safeLeft.every((entry, index) => sameDepthLevel(entry, safeRight[index]));
}

function sameRecordObject(left: Record<string, unknown>, right: Record<string, unknown>): boolean {
  return shallowEqualRecord(left, right);
}

function sameMarket(left: UiMarket, right: UiMarket): boolean {
  return sameRecordObject(left as Record<string, unknown>, right as Record<string, unknown>);
}

function samePosition(left: UiPosition, right: UiPosition): boolean {
  return sameRecordObject(left as Record<string, unknown>, right as Record<string, unknown>);
}

function sameDepth(left: UiDepth, right: UiDepth): boolean {
  const { bids: leftBids = [], asks: leftAsks = [], ...leftRest } = left;
  const { bids: rightBids = [], asks: rightAsks = [], ...rightRest } = right;
  return sameRecordObject(leftRest as Record<string, unknown>, rightRest as Record<string, unknown>) &&
    sameDepthLevels(leftBids, rightBids) &&
    sameDepthLevels(leftAsks, rightAsks);
}

function normalizeFill(fill: unknown): UiFill {
  const raw = fill && typeof fill === "object" ? (fill as Record<string, unknown>) : {};
  const timestampMs = Number(raw.timestamp_ms ?? raw.ts ?? 0) || 0;
  const side = String(raw.side ?? "").toUpperCase();
  const price = Number(raw.price ?? 0) || 0;
  const amountBase = Number(raw.amount_base ?? raw.amount ?? 0) || 0;
  const notionalQuote = Number(raw.notional_quote ?? 0) || 0;
  const feeQuote = Number(raw.fee_quote ?? 0) || 0;
  const realized = Number(raw.realized_pnl_quote ?? 0) || 0;
  return {
    ...(raw as UiFill),
    timestamp_ms: timestampMs,
    side,
    price,
    amount_base: amountBase,
    notional_quote: notionalQuote,
    fee_quote: feeQuote,
    realized_pnl_quote: realized,
    is_maker: Boolean(raw.is_maker),
  };
}

function sameFill(left: UiFill, right: UiFill): boolean {
  return (
    Number(left.timestamp_ms ?? 0) === Number(right.timestamp_ms ?? 0) &&
    String(left.order_id ?? "") === String(right.order_id ?? "") &&
    String(left.side ?? "") === String(right.side ?? "") &&
    Number(left.price ?? 0) === Number(right.price ?? 0) &&
    Number(left.amount_base ?? 0) === Number(right.amount_base ?? 0) &&
    Number(left.notional_quote ?? 0) === Number(right.notional_quote ?? 0) &&
    Number(left.fee_quote ?? 0) === Number(right.fee_quote ?? 0) &&
    Number(left.realized_pnl_quote ?? 0) === Number(right.realized_pnl_quote ?? 0) &&
    Boolean(left.is_maker) === Boolean(right.is_maker)
  );
}

function sameFills(left: UiFill[], right: UiFill[]): boolean {
  return left.length === right.length && left.every((entry, index) => sameFill(entry, right[index]));
}

function mergeRecentFills(existingFills: UiFill[], incomingFills: UiFill[], maxRows: number): UiFill[] {
  const merged: UiFill[] = [];
  const seen = new Set<string>();
  const pushFill = (rawFill: UiFill) => {
    const fill = normalizeFill(rawFill);
    const key = [fill.order_id ?? "", fill.timestamp_ms ?? "", fill.side ?? "", fill.price ?? "", fill.amount_base ?? ""].join("|");
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    merged.push(fill);
  };
  existingFills.forEach(pushFill);
  incomingFills.forEach(pushFill);
  merged.sort((a, b) => Number(a.timestamp_ms ?? 0) - Number(b.timestamp_ms ?? 0));
  return merged.slice(-Math.max(20, maxRows));
}

function normalizeCandle(rawCandle: unknown): UiCandle | null {
  if (!rawCandle || typeof rawCandle !== "object") {
    return null;
  }
  const safe = rawCandle as { bucket_ms?: unknown; open?: unknown; high?: unknown; low?: unknown; close?: unknown };
  const time = Math.floor((Number(safe.bucket_ms ?? 0) || 0) / 1000);
  const open = Number(safe.open);
  const high = Number(safe.high);
  const low = Number(safe.low);
  const close = Number(safe.close);
  if (!Number.isFinite(time) || !Number.isFinite(open) || !Number.isFinite(high) || !Number.isFinite(low) || !Number.isFinite(close)) {
    return null;
  }
  return { time, open, high, low, close };
}

function applyCandleData(rawCandles: unknown[], fallbackMid: number | null): UiCandle[] {
  const candles = (rawCandles || []).map((entry) => normalizeCandle(entry)).filter(Boolean) as UiCandle[];
  if (candles.length === 0 && Number.isFinite(fallbackMid)) {
    const nowSec = Math.floor(Date.now() / 1000);
    candles.push({
      time: nowSec,
      open: Number(fallbackMid),
      high: Number(fallbackMid),
      low: Number(fallbackMid),
      close: Number(fallbackMid),
    });
  }
  return candles.slice(-MAX_CANDLES);
}

function sameCandle(left: UiCandle | null, right: UiCandle | null): boolean {
  if (left === right) {
    return true;
  }
  if (!left || !right) {
    return false;
  }
  return left.time === right.time && left.open === right.open && left.high === right.high && left.low === right.low && left.close === right.close;
}

function sameCandles(left: UiCandle[], right: UiCandle[]): boolean {
  return left.length === right.length && left.every((entry, index) => sameCandle(entry, right[index] ?? null));
}

interface CandleStreamState {
  candles: UiCandle[];
  latestCandle: UiCandle | null;
}

function pushMidCandle(candles: UiCandle[], latestCandle: UiCandle | null, tsMs: number, mid: number, timeframeS: number): CandleStreamState {
  const price = Number(mid);
  if (!Number.isFinite(price)) {
    return { candles, latestCandle };
  }
  const tfSec = Math.max(1, Number(timeframeS || 60));
  const bucketSec = Math.floor((Number(tsMs) || Date.now()) / 1000 / tfSec) * tfSec;
  const lastCandle = latestCandle ?? candles[candles.length - 1] ?? null;
  if (!lastCandle) {
    const firstCandle = { time: bucketSec, open: price, high: price, low: price, close: price };
    return { candles: [firstCandle], latestCandle: firstCandle };
  }
  if (lastCandle.time === bucketSec) {
    const nextLatestCandle: UiCandle = {
      time: lastCandle.time,
      open: lastCandle.open,
      high: Math.max(lastCandle.high, price),
      low: Math.min(lastCandle.low, price),
      close: price,
    };
    return { candles, latestCandle: nextLatestCandle };
  }
  if (bucketSec > lastCandle.time) {
    const syncedCandles =
      candles.length === 0
        ? []
        : [...candles.slice(0, Math.max(0, candles.length - 1)), lastCandle];
    const nextLatestCandle: UiCandle = {
      time: bucketSec,
      open: Number(lastCandle.close),
      high: price,
      low: price,
      close: price,
    };
    return {
      candles: [...syncedCandles, nextLatestCandle].slice(-MAX_CANDLES),
      latestCandle: nextLatestCandle,
    };
  }
  return { candles, latestCandle: lastCandle };
}

function depthMid(depth: UiDepth): number | null {
  const bestBid = toNum(depth.best_bid ?? depth.bids?.[0]?.price);
  const bestAsk = toNum(depth.best_ask ?? depth.asks?.[0]?.price);
  if (bestBid !== null && bestAsk !== null) {
    return (bestBid + bestAsk) / 2;
  }
  if (bestBid !== null) {
    return bestBid;
  }
  if (bestAsk !== null) {
    return bestAsk;
  }
  return null;
}

function orderTsMs(order: UiOrder): number {
  return maxTsMs(order.updated_ts_ms, order.created_ts_ms);
}

function fillsLatestTsMs(fills: UiFill[]): number {
  return fills.reduce((maxValue, fill) => Math.max(maxValue, maxTsMs(fill.timestamp_ms, fill.ts)), 0);
}

function ordersLatestTsMs(orders: UiOrder[], fallbackTsMs = 0): number {
  const resolved = orders.reduce((maxValue, order) => Math.max(maxValue, orderTsMs(order)), 0);
  return resolved || fallbackTsMs;
}

function positionTsMs(position: UiPosition, fallbackTsMs = 0): number {
  return maxTsMs(position.source_ts_ms, fallbackTsMs);
}

function marketTsMs(market: UiMarket, fallbackTsMs = 0): number {
  return maxTsMs(market.timestamp_ms, market.ts, fallbackTsMs);
}

function depthTsMs(depth: UiDepth, fallbackTsMs = 0): number {
  return maxTsMs(depth.timestamp_ms, depth.ts, fallbackTsMs);
}

function sameOrder(left: UiOrder, right: UiOrder): boolean {
  const leftRecord = left as Record<string, unknown>;
  const rightRecord = right as Record<string, unknown>;
  return (
    String(left.order_id ?? left.client_order_id ?? "") === String(right.order_id ?? right.client_order_id ?? "") &&
    String(left.side ?? "") === String(right.side ?? "") &&
    Number(left.price ?? 0) === Number(right.price ?? 0) &&
    Number(left.amount ?? left.quantity ?? 0) === Number(right.amount ?? right.quantity ?? 0) &&
    String(left.state ?? "") === String(right.state ?? "") &&
    String(left.trading_pair ?? "") === String(right.trading_pair ?? "") &&
    Number(leftRecord.created_ts_ms ?? 0) === Number(rightRecord.created_ts_ms ?? 0) &&
    Number(leftRecord.updated_ts_ms ?? 0) === Number(rightRecord.updated_ts_ms ?? 0)
  );
}

function sameOrders(left: UiOrder[], right: UiOrder[]): boolean {
  return left.length === right.length && left.every((entry, index) => sameOrder(entry, right[index]));
}

function stableMarket(current: UiMarket, next: UiMarket): UiMarket {
  return sameMarket(current, next) ? current : next;
}

function stableDepth(current: UiDepth, next: UiDepth): UiDepth {
  return sameDepth(current, next) ? current : next;
}

function stablePosition(current: UiPosition, next: UiPosition): UiPosition {
  return samePosition(current, next) ? current : next;
}

function stableOrders(current: UiOrder[], next: UiOrder[]): UiOrder[] {
  return sameOrders(current, next) ? current : next;
}

function stableFills(current: UiFill[], next: UiFill[]): UiFill[] {
  return sameFills(current, next) ? current : next;
}

function stableCandles(current: UiCandle[], next: UiCandle[]): UiCandle[] {
  return sameCandles(current, next) ? current : next;
}

function trimRuntimeEvents(events: RuntimeEvent[]): RuntimeEvent[] {
  if (events.length <= MAX_RUNTIME_EVENTS) {
    return events;
  }
  const cutoff = Date.now() - RUNTIME_EVENT_RETENTION_MS;
  const filtered = events.filter((entry) => entry.tsMs >= cutoff);
  return filtered.length > MAX_RUNTIME_EVENTS ? filtered.slice(-MAX_RUNTIME_EVENTS) : filtered;
}

function getPriceDirection(previousMid: number | null, nextMid: number | null): "up" | "down" | "flat" {
  if (previousMid === null || nextMid === null) {
    return "flat";
  }
  if (nextMid > previousMid) {
    return "up";
  }
  if (nextMid < previousMid) {
    return "down";
  }
  return "flat";
}

function shouldAppendFeedLine(eventType: string): boolean {
  const silentEvents = new Set(["market_quote", "market_snapshot", "market_depth_snapshot"]);
  return !silentEvents.has(eventType);
}

function buildPayloadRecord(message: WsInboundMessage, receivedAtMs: number): PayloadRecord {
  const safe = message as { type?: unknown; event_type?: unknown; event?: unknown; instance_name?: unknown };
  const messageType = String(safe.type ?? "unknown").trim() || "unknown";
  const eventType =
    String(
      safe.event_type ??
        (safe.event && typeof safe.event === "object" && "event_type" in safe.event
          ? (safe.event as { event_type?: unknown }).event_type
          : ""),
    ).trim() || "-";
  const instanceName =
    String(
      safe.instance_name ??
        (safe.event && typeof safe.event === "object" && "instance_name" in safe.event
          ? (safe.event as { instance_name?: unknown }).instance_name
          : ""),
    ).trim() || "-";
  return {
    id: `${receivedAtMs}-${Math.random().toString(36).slice(2, 9)}`,
    receivedAtMs,
    messageType,
    eventType,
    instanceName,
    payload: sanitizePayloadForInspector(message),
  };
}

function sanitizePayloadForInspector(value: unknown, depth = 0): unknown {
  if (value === null || value === undefined) {
    return value;
  }
  if (depth >= 4) {
    return "[truncated]";
  }
  if (Array.isArray(value)) {
    const limit = 6;
    const items = value.slice(0, limit).map((entry) => sanitizePayloadForInspector(entry, depth + 1));
    if (value.length > limit) {
      items.push(`... ${value.length - limit} more`);
    }
    return items;
  }
  if (typeof value !== "object") {
    if (typeof value === "string" && value.length > 400) {
      return `${value.slice(0, 400)}...`;
    }
    return value;
  }
  const safe = value as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const [key, entry] of Object.entries(safe)) {
    if (key === "candles" && Array.isArray(entry) && entry.length > 20) {
      out[key] = [`${entry.length} candles`, ...entry.slice(0, 5).map((item) => sanitizePayloadForInspector(item, depth + 1))];
      continue;
    }
    out[key] = sanitizePayloadForInspector(entry, depth + 1);
  }
  return out;
}

const EMPTY_MARKET: UiMarket = {};
const EMPTY_DEPTH: UiDepth = {};
const EMPTY_POSITION: UiPosition = {};
const EMPTY_ORDERS: UiOrder[] = [];
const EMPTY_FILLS: UiFill[] = [];
const EMPTY_CANDLES: UiCandle[] = [];
const EMPTY_EVENT_LINES: string[] = [];
const EMPTY_PAYLOADS: PayloadRecord[] = [];
const EMPTY_RUNTIME_EVENTS: RuntimeEvent[] = [];
const EMPTY_ALERTS: SummaryAlert[] = [];
const EMPTY_INSTANCE_NAMES: string[] = [];

export const useDashboardStore = create<DashboardState>()(
  subscribeWithSelector((set, get) => ({
      settings: DEFAULT_SETTINGS,
      health: defaultHealth(),
      connection: defaultConnection(),
      freshness: defaultFreshness(),
      mode: "",
      source: "",
      summarySystem: defaultSummarySystem(),
      summaryActivity: defaultSummaryActivity(),
      summaryAccount: defaultSummaryAccount(),
      alerts: EMPTY_ALERTS,
      market: EMPTY_MARKET,
      depth: EMPTY_DEPTH,
      position: EMPTY_POSITION,
      latestMid: null,
      midPriceDirection: "flat",
      latestQuoteTsMs: 0,
      candles: EMPTY_CANDLES,
      latestCandle: null,
      candleSeriesNonce: 0,
      orders: EMPTY_ORDERS,
      fills: EMPTY_FILLS,
      fillsTotal: 0,
      eventLines: EMPTY_EVENT_LINES,
      payloads: EMPTY_PAYLOADS,
      selectedPayloadId: null,
      runtimeEvents: EMPTY_RUNTIME_EVENTS,
      instanceNames: EMPTY_INSTANCE_NAMES,
      updateSettings: (patch) => {
        set((state) => {
          const nextSettings = { ...state.settings, ...patch };
          const hasChanged = Object.keys(patch).some((key) => {
            const typedKey = key as keyof DashboardSettings;
            return state.settings[typedKey] !== nextSettings[typedKey];
          });
          if (!hasChanged) {
            return {};
          }
          writeLocalStorage("hbV2ApiBase", nextSettings.apiBase);
          writeSessionStorage("hbV2ApiToken", nextSettings.apiToken);
          writeLocalStorage("hbV2InstanceName", nextSettings.instanceName);
          writeLocalStorage("hbV2TimeframeS", String(nextSettings.timeframeS));
          return { settings: nextSettings };
        });
      },
      setInstanceNames: (names) => {
        set((state) => {
          const nextInstanceNames = normalizeInstanceNames(names);
          return sameStringArray(state.instanceNames, nextInstanceNames) ? {} : { instanceNames: nextInstanceNames };
        });
      },
      setSelectedPayloadId: (id) => {
        set({ selectedPayloadId: id });
      },
      clearEventFeed: () => {
        set({ eventLines: [] });
      },
      appendEventLine: (line) => {
        set((state) => {
          if (state.settings.feedPaused) {
            return {};
          }
          const next = [...state.eventLines, `${new Date().toLocaleTimeString()} ${line}`];
          return { eventLines: next.slice(-MAX_EVENT_LINES) };
        });
      },
      setConnectionStatus: (status) => {
        set((state) => (state.connection.status === status ? {} : { connection: { ...state.connection, status } }));
      },
      beginSession: () => {
        const sessionId = Number(get().connection.wsSessionId || 0) + 1;
        set((state) => ({
          connection: {
            ...state.connection,
            wsSessionId: sessionId,
            status: "connecting",
            lastEventType: "",
            lastMessageTsMs: 0,
          },
        }));
        return sessionId;
      },
      markConnected: () => {
        set((state) =>
          state.connection.status === "connected"
            ? {}
            : {
                connection: {
                  ...state.connection,
                  status: "connected",
                  connectedAtMs: Date.now(),
                },
              },
        );
      },
      markReconnectAttempt: () => {
        set((state) => ({
          connection: {
            ...state.connection,
            reconnectCount: Number(state.connection.reconnectCount || 0) + 1,
          },
        }));
      },
      markParseError: () => {
        set((state) => ({
          connection: {
            ...state.connection,
            parseErrorCount: Number(state.connection.parseErrorCount || 0) + 1,
          },
        }));
      },
      markDroppedMessage: () => {
        set((state) => ({
          connection: {
            ...state.connection,
            droppedMessageCount: Number(state.connection.droppedMessageCount || 0) + 1,
          },
        }));
      },
      markMessageReceived: (eventType = "") => {
        set((state) => {
          const now = Date.now();
          const nextEventType = eventType || state.connection.lastEventType;
          const shouldRefreshTimestamp = now - Number(state.connection.lastMessageTsMs || 0) >= LAST_MESSAGE_UI_UPDATE_MS;
          if (!shouldRefreshTimestamp && nextEventType === state.connection.lastEventType) {
            return {};
          }
          return {
            connection: {
              ...state.connection,
              lastMessageTsMs: shouldRefreshTimestamp ? now : state.connection.lastMessageTsMs,
              lastEventType: nextEventType,
            },
          };
        });
      },
      setHealth: (health) => {
        set((state) => {
          const nextHealth = {
            ...state.health,
            status: "status" in health ? String(health.status ?? "") : state.health.status,
            streamAgeMs: "streamAgeMs" in health ? health.streamAgeMs ?? null : state.health.streamAgeMs,
            dbAvailable: "dbAvailable" in health ? Boolean(health.dbAvailable) : state.health.dbAvailable,
            redisAvailable: "redisAvailable" in health ? Boolean(health.redisAvailable) : state.health.redisAvailable,
            fallbackActive: "fallbackActive" in health ? Boolean(health.fallbackActive) : state.health.fallbackActive,
          };
          return (
            nextHealth.status === state.health.status &&
            nextHealth.streamAgeMs === state.health.streamAgeMs &&
            nextHealth.dbAvailable === state.health.dbAvailable &&
            nextHealth.redisAvailable === state.health.redisAvailable &&
            nextHealth.fallbackActive === state.health.fallbackActive
          )
            ? {}
            : { health: nextHealth };
        });
      },
      pushPayloadRecord: (message, receivedAtMs) => {
        set((state) => {
          const payloadRecord = buildPayloadRecord(message, receivedAtMs);
          const payloads = [...state.payloads, payloadRecord].slice(-MAX_PAYLOAD_RECORDS);
          const selectedPayloadId = payloads.some((entry) => entry.id === state.selectedPayloadId) ? state.selectedPayloadId : null;
          return {
            payloads,
            selectedPayloadId,
          };
        });
      },
      ingestSnapshot: (snapshot) => {
        const selected = String(get().settings.instanceName ?? "").trim();
        const incoming = snapshotInstanceName(snapshot);
        if (!matchesSelectedInstance(selected, incoming)) {
          get().markDroppedMessage();
          return;
        }
        const payload = snapshot.state ?? {};
        const stream = payload.stream ?? {};
        const fallback = payload.fallback ?? {};
        const market = normalizeMarket(stream.market);
        const depth = normalizeDepth(stream.depth);
        const position = normalizePosition(stream.position ?? fallback.position);
        const openOrders = Array.isArray(stream.open_orders)
          ? stream.open_orders
          : Array.isArray(fallback.open_orders)
            ? fallback.open_orders
            : [];
        const streamFills = Array.isArray(stream.fills) ? stream.fills : [];
        const fallbackFills = Array.isArray(fallback.fills) ? fallback.fills : [];
        const fills = streamFills.length > 0 ? streamFills : fallbackFills;
        const fillsTotal = Number(stream.fills_total ?? fallback.fills_total ?? fills.length ?? 0);
        const tsMs = Number(snapshot.ts_ms || Date.now()) || Date.now();
        const incomingControllerId = snapshotControllerId(snapshot);
        const incomingTradingPair = snapshotTradingPair(snapshot);

        set((state) => {
          const summarySystemBase = mergeSummarySystem(state.summarySystem, payload.summary?.system);
          const summaryActivity = mergeSummaryActivity(state.summaryActivity, payload.summary?.activity);
          const summaryAccountBase = mergeSummaryAccount(state.summaryAccount, payload.summary?.account);
          const alerts = mergeAlerts(state.alerts, payload.summary?.alerts);
          const normalizedSnapshotFills = fills.map((entry) => normalizeFill(entry));
          const incomingMarketTsMs = maxTsMs(summarySystemBase.latest_market_ts_ms, marketTsMs(market), tsMs);
          const incomingDepthTsMs = maxTsMs(summarySystemBase.latest_market_ts_ms, depthTsMs(depth), tsMs);
          const incomingPositionTsMs = maxTsMs(summarySystemBase.position_source_ts_ms, positionTsMs(position), tsMs);
          const incomingFillsTsMs = maxTsMs(summarySystemBase.latest_fill_ts_ms, fillsLatestTsMs(normalizedSnapshotFills));
          const incomingOrdersTsMs = ordersLatestTsMs(openOrders.slice(0, 200) as UiOrder[], incomingMarketTsMs);
          const snapshotMid = toNum(market.mid_price ?? fallback.minute?.mid);
          const latestMid = snapshotMid ?? state.latestMid;
          const midPriceDirection = getPriceDirection(state.latestMid, latestMid);
          const latestQuoteTsMs = snapshotMid !== null ? Math.max(state.latestQuoteTsMs, incomingMarketTsMs) : state.latestQuoteTsMs;
          const nextCandleState = Array.isArray(snapshot.candles)
            ? (() => {
                const candles = applyCandleData(snapshot.candles, latestMid);
                return {
                  candles,
                  latestCandle: candles[candles.length - 1] ?? null,
                  resetSeries: true,
                };
              })()
            : latestMid !== null
              ? {
                  ...pushMidCandle(
                    state.candles,
                    state.latestCandle,
                    Math.max(incomingMarketTsMs, incomingDepthTsMs, tsMs),
                    latestMid,
                    state.settings.timeframeS,
                  ),
                  resetSeries: false,
                }
              : { candles: state.candles, latestCandle: state.latestCandle, resetSeries: false };
          const nextSummarySystem = mergeSummarySystem(summarySystemBase, {
            latest_market_ts_ms: Math.max(toNum(summarySystemBase.latest_market_ts_ms) ?? 0, incomingMarketTsMs, incomingDepthTsMs),
            latest_fill_ts_ms: Math.max(toNum(summarySystemBase.latest_fill_ts_ms) ?? 0, incomingFillsTsMs),
            position_source_ts_ms: Math.max(toNum(summarySystemBase.position_source_ts_ms) ?? 0, incomingPositionTsMs),
          });
          const nextSummaryAccount =
            incomingControllerId && !String(summaryAccountBase.controller_id ?? "").trim()
              ? mergeSummaryAccount(summaryAccountBase, { controller_id: incomingControllerId })
              : summaryAccountBase;
          const nextMarket = stableMarket(
            state.market,
            {
              ...market,
              trading_pair: market.trading_pair ?? incomingTradingPair,
            },
          );
          const nextDepth = stableDepth(
            state.depth,
            {
              ...depth,
              trading_pair: depth.trading_pair ?? incomingTradingPair,
            },
          );
          const nextPosition = stablePosition(
            state.position,
            {
              ...position,
              trading_pair: position.trading_pair ?? incomingTradingPair,
            },
          );
          const nextOrders = stableOrders(state.orders, openOrders.slice(0, 200) as UiOrder[]);
          const nextFills = stableFills(state.fills, mergeRecentFills([], normalizedSnapshotFills, MAX_FILLS));
          const nextCandles = stableCandles(state.candles, nextCandleState.candles);
          const nextLatestCandle = sameCandle(state.latestCandle, nextCandleState.latestCandle) ? state.latestCandle : nextCandleState.latestCandle;
          return {
            mode: payload.mode ?? state.mode,
            source: payload.source ?? state.source,
            summarySystem: nextSummarySystem,
            summaryActivity,
            summaryAccount: nextSummaryAccount,
            freshness: {
              ...state.freshness,
              marketTsMs: Math.max(state.freshness.marketTsMs, incomingMarketTsMs),
              depthTsMs: Math.max(state.freshness.depthTsMs, incomingDepthTsMs),
              positionTsMs: Math.max(state.freshness.positionTsMs, incomingPositionTsMs),
              ordersTsMs: Math.max(state.freshness.ordersTsMs, incomingOrdersTsMs),
              fillsTsMs: Math.max(state.freshness.fillsTsMs, incomingFillsTsMs),
            },
            alerts,
            market: nextMarket,
            depth: nextDepth,
            position: nextPosition,
            latestMid,
            midPriceDirection,
            latestQuoteTsMs,
            candles: nextCandles,
            latestCandle: nextLatestCandle,
            candleSeriesNonce: nextCandleState.resetSeries ? state.candleSeriesNonce + 1 : state.candleSeriesNonce,
            orders: nextOrders,
            fills: nextFills,
            fillsTotal: Number.isFinite(fillsTotal) ? fillsTotal : fills.length,
            runtimeEvents: trimRuntimeEvents([
              ...state.runtimeEvents,
              { eventType: "snapshot", tsMs },
            ]),
          };
        });
      },
      ingestEventMessage: (message) => {
        const selected = String(get().settings.instanceName ?? "").trim();
        const incoming = messageInstanceName(message);
        if (!matchesSelectedInstance(selected, incoming)) {
          get().markDroppedMessage();
          return;
        }
        const eventType = String(message.event_type ?? ((message.event as { event_type?: unknown } | undefined)?.event_type ?? "")).trim();
        const eventTsMs = Number(message.ts_ms || Date.now()) || Date.now();
        const runtimeType = eventType || "event";
        const eventPayload = message.event && typeof message.event === "object" ? (message.event as Record<string, unknown>) : null;
        const incomingControllerId = messageControllerId(message);
        const incomingTradingPair = messageTradingPair(message);
        const currentState = get();
        if (!shouldAcceptSharedMarketEvent(currentState, eventType, incoming, incomingTradingPair)) {
          get().markDroppedMessage();
          return;
        }

        set((state) => {
          const nextRuntimeEvents = trimRuntimeEvents([
            ...state.runtimeEvents,
            { eventType: runtimeType, tsMs: eventTsMs },
          ]);

          let nextMarket = state.market;
          let nextDepth = state.depth;
          let nextPosition = state.position;
          let nextSummarySystem = state.summarySystem;
          let nextLatestMid = state.latestMid;
          let nextMidPriceDirection = state.midPriceDirection;
          let nextLatestQuoteTsMs = state.latestQuoteTsMs;
          let nextCandles = state.candles;
          let nextLatestCandle = state.latestCandle;
          let nextFreshness = state.freshness;

          const hasFreshQuote = Number(state.latestQuoteTsMs || 0) > 0 && Math.abs(eventTsMs - Number(state.latestQuoteTsMs || 0)) <= 5_000;

          if (eventType === "market_quote" && eventPayload) {
            nextMarket = normalizeMarket(eventPayload);
            if (incomingTradingPair && !String(nextMarket.trading_pair ?? "").trim()) {
              nextMarket = { ...nextMarket, trading_pair: incomingTradingPair };
            }
            const mid = toNum(nextMarket.mid_price);
            if (mid !== null) {
              nextMidPriceDirection = getPriceDirection(state.latestMid, mid);
              nextLatestMid = mid;
              nextLatestQuoteTsMs = eventTsMs;
              const nextCandleState = pushMidCandle(state.candles, state.latestCandle, eventTsMs, mid, state.settings.timeframeS);
              nextCandles = nextCandleState.candles;
              nextLatestCandle = nextCandleState.latestCandle;
            }
            nextSummarySystem = { ...nextSummarySystem, latest_market_ts_ms: Math.max(toNum(nextSummarySystem.latest_market_ts_ms) ?? 0, eventTsMs) };
            nextFreshness = { ...nextFreshness, marketTsMs: Math.max(nextFreshness.marketTsMs, eventTsMs) };
          }

          if (eventType === "market_snapshot" && eventPayload) {
            const marketSnapshot = normalizeMarket(eventPayload);
            if (incomingTradingPair && !String(marketSnapshot.trading_pair ?? "").trim()) {
              marketSnapshot.trading_pair = incomingTradingPair;
            }
            const mid = toNum(marketSnapshot.mid_price);
            if (!hasFreshQuote && mid !== null) {
              nextMidPriceDirection = getPriceDirection(state.latestMid, mid);
              nextMarket = marketSnapshot;
              nextLatestMid = mid;
              const nextCandleState = pushMidCandle(state.candles, state.latestCandle, eventTsMs, mid, state.settings.timeframeS);
              nextCandles = nextCandleState.candles;
              nextLatestCandle = nextCandleState.latestCandle;
            }
            nextSummarySystem = { ...nextSummarySystem, latest_market_ts_ms: Math.max(toNum(nextSummarySystem.latest_market_ts_ms) ?? 0, eventTsMs) };
            nextFreshness = { ...nextFreshness, marketTsMs: Math.max(nextFreshness.marketTsMs, eventTsMs) };
          }

          if (eventType === "market_depth_snapshot" && eventPayload) {
            nextDepth = normalizeDepth(eventPayload);
            if (incomingTradingPair && !String(nextDepth.trading_pair ?? "").trim()) {
              nextDepth = { ...nextDepth, trading_pair: incomingTradingPair };
            }
            const mid = depthMid(nextDepth);
            if (!hasFreshQuote && mid !== null) {
              nextMidPriceDirection = getPriceDirection(state.latestMid, mid);
              nextLatestMid = mid;
              const nextCandleState = pushMidCandle(state.candles, state.latestCandle, eventTsMs, mid, state.settings.timeframeS);
              nextCandles = nextCandleState.candles;
              nextLatestCandle = nextCandleState.latestCandle;
            }
            nextSummarySystem = { ...nextSummarySystem, latest_market_ts_ms: Math.max(toNum(nextSummarySystem.latest_market_ts_ms) ?? 0, eventTsMs) };
            nextFreshness = {
              ...nextFreshness,
              marketTsMs: Math.max(nextFreshness.marketTsMs, eventTsMs),
              depthTsMs: Math.max(nextFreshness.depthTsMs, eventTsMs),
            };
          }

          if ((eventType === "position_snapshot" || eventType === "position_update") && eventPayload) {
            nextPosition = normalizePosition(eventPayload);
            if (incomingTradingPair && !String(nextPosition.trading_pair ?? "").trim()) {
              nextPosition = { ...nextPosition, trading_pair: incomingTradingPair };
            }
            nextSummarySystem = {
              ...nextSummarySystem,
              position_source_ts_ms: Math.max(toNum(nextSummarySystem.position_source_ts_ms) ?? 0, positionTsMs(nextPosition, eventTsMs)),
            };
            nextFreshness = {
              ...nextFreshness,
              positionTsMs: Math.max(nextFreshness.positionTsMs, positionTsMs(nextPosition, eventTsMs)),
            };
          }

          let nextFills = state.fills;
          let nextFillsTotal = state.fillsTotal;
          if (eventType === "bot_fill" && eventPayload) {
            const incomingFill = normalizeFill(eventPayload);
            nextFills = mergeRecentFills(state.fills, [incomingFill], MAX_FILLS);
            nextFillsTotal = Math.max(Number(state.fillsTotal || 0) + 1, nextFills.length);
            const latestFillTsMs = maxTsMs(eventTsMs, incomingFill.timestamp_ms, incomingFill.ts);
            nextSummarySystem = { ...nextSummarySystem, latest_fill_ts_ms: Math.max(toNum(nextSummarySystem.latest_fill_ts_ms) ?? 0, latestFillTsMs) };
            nextFreshness = {
              ...nextFreshness,
              fillsTsMs: Math.max(nextFreshness.fillsTsMs, latestFillTsMs),
            };
          }

          let nextEventLines = state.eventLines;
          if (!state.settings.feedPaused && eventType && shouldAppendFeedLine(eventType)) {
            const line = `${new Date(eventTsMs).toLocaleTimeString()} [ws] ${message.stream || "stream"} ${eventType}`;
            nextEventLines = [...state.eventLines, line].slice(-MAX_EVENT_LINES);
          }

          return {
            market: stableMarket(state.market, nextMarket),
            depth: stableDepth(state.depth, nextDepth),
            position: stablePosition(state.position, nextPosition),
            summarySystem: nextSummarySystem,
            summaryAccount:
              incomingControllerId && !String(state.summaryAccount.controller_id ?? "").trim()
                ? mergeSummaryAccount(state.summaryAccount, { controller_id: incomingControllerId })
                : state.summaryAccount,
            freshness: nextFreshness,
            latestMid: nextLatestMid,
            midPriceDirection: nextMidPriceDirection,
            latestQuoteTsMs: nextLatestQuoteTsMs,
            candles: stableCandles(state.candles, nextCandles),
            latestCandle: sameCandle(state.latestCandle, nextLatestCandle) ? state.latestCandle : nextLatestCandle,
            fills: stableFills(state.fills, nextFills),
            fillsTotal: nextFillsTotal,
            runtimeEvents: nextRuntimeEvents,
            eventLines: nextEventLines,
          };
        });
      },
      ingestRestState: (payload, requestedInstanceName = "") => {
        const selected = String(get().settings.instanceName ?? "").trim();
        if (requestedInstanceName && selected && requestedInstanceName !== selected) {
          get().markDroppedMessage();
          return;
        }
        const incomingInstanceName = restStateInstanceName(payload);
        if (!matchesSelectedInstance(selected, incomingInstanceName)) {
          get().markDroppedMessage();
          return;
        }
        const stream = payload.stream ?? {};
        const fallback = payload.fallback ?? {};
        const market = normalizeMarket(stream.market);
        const depth = normalizeDepth(stream.depth);
        const position = normalizePosition(stream.position ?? fallback.position);
        const openOrders = Array.isArray(stream.open_orders)
          ? stream.open_orders
          : Array.isArray(fallback.open_orders)
            ? fallback.open_orders
            : [];
        const streamFills = Array.isArray(stream.fills) ? stream.fills : [];
        const fallbackFills = Array.isArray(fallback.fills) ? fallback.fills : [];
        const fills = streamFills.length > 0 ? streamFills : fallbackFills;
        const fillsTotal = Number(stream.fills_total ?? fallback.fills_total ?? fills.length ?? 0);
        const incomingControllerId = restStateControllerId(payload);
        const incomingTradingPair = restStateTradingPair(payload);
        const normalizedRestFills = fills.map((entry) => normalizeFill(entry));
        const currentFreshness = get().freshness;
        const incomingFreshness = {
          marketTsMs: maxTsMs(payload.summary?.system?.latest_market_ts_ms, marketTsMs(market)),
          depthTsMs: maxTsMs(payload.summary?.system?.latest_market_ts_ms, depthTsMs(depth)),
          positionTsMs: maxTsMs(payload.summary?.system?.position_source_ts_ms, positionTsMs(position)),
          ordersTsMs: ordersLatestTsMs(openOrders.slice(0, 200) as UiOrder[], maxTsMs(payload.summary?.system?.latest_market_ts_ms)),
          fillsTsMs: maxTsMs(payload.summary?.system?.latest_fill_ts_ms, fillsLatestTsMs(normalizedRestFills)),
        };
        const acceptMarket = !(currentFreshness.marketTsMs > 0 && incomingFreshness.marketTsMs > 0 && incomingFreshness.marketTsMs < currentFreshness.marketTsMs);
        const acceptDepth = !(currentFreshness.depthTsMs > 0 && incomingFreshness.depthTsMs > 0 && incomingFreshness.depthTsMs < currentFreshness.depthTsMs);
        const acceptPosition = !(currentFreshness.positionTsMs > 0 && incomingFreshness.positionTsMs > 0 && incomingFreshness.positionTsMs < currentFreshness.positionTsMs);
        const acceptOrders = !(currentFreshness.ordersTsMs > 0 && incomingFreshness.ordersTsMs > 0 && incomingFreshness.ordersTsMs < currentFreshness.ordersTsMs);
        const acceptFills = !(currentFreshness.fillsTsMs > 0 && incomingFreshness.fillsTsMs > 0 && incomingFreshness.fillsTsMs < currentFreshness.fillsTsMs);
        const rejectedReasons: string[] = [];
        if (!acceptMarket) {
          rejectedReasons.push(`market ${incomingFreshness.marketTsMs} < ${currentFreshness.marketTsMs}`);
        }
        if (!acceptDepth) {
          rejectedReasons.push(`depth ${incomingFreshness.depthTsMs} < ${currentFreshness.depthTsMs}`);
        }
        if (!acceptPosition) {
          rejectedReasons.push(`position ${incomingFreshness.positionTsMs} < ${currentFreshness.positionTsMs}`);
        }
        if (!acceptOrders) {
          rejectedReasons.push(`orders ${incomingFreshness.ordersTsMs} < ${currentFreshness.ordersTsMs}`);
        }
        if (!acceptFills) {
          rejectedReasons.push(`fills ${incomingFreshness.fillsTsMs} < ${currentFreshness.fillsTsMs}`);
        }
        const freshnessDecision = {
          acceptMarket,
          acceptDepth,
          acceptPosition,
          acceptOrders,
          acceptFills,
          reasons: rejectedReasons,
        };

        set((state) => {
          const currentSummaryMarketTsMs = toNum(state.summarySystem.latest_market_ts_ms) ?? 0;
          const incomingSummaryMarketTsMs = toNum(payload.summary?.system?.latest_market_ts_ms) ?? 0;
          const currentSummaryFillTsMs = toNum(state.summarySystem.latest_fill_ts_ms) ?? 0;
          const incomingSummaryFillTsMs = toNum(payload.summary?.system?.latest_fill_ts_ms) ?? 0;
          const allowRestMarket = freshnessDecision.acceptMarket && !(
            currentSummaryMarketTsMs > 0 &&
            incomingSummaryMarketTsMs > 0 &&
            incomingSummaryMarketTsMs < currentSummaryMarketTsMs
          );
          const allowRestFills = freshnessDecision.acceptFills && !(
            currentSummaryFillTsMs > 0 &&
            incomingSummaryFillTsMs > 0 &&
            incomingSummaryFillTsMs < currentSummaryFillTsMs
          );
          const summarySystem = mergeSummarySystem(state.summarySystem, {
            ...payload.summary?.system,
            latest_market_ts_ms: Math.max(toNum(state.summarySystem.latest_market_ts_ms) ?? 0, incomingFreshness.marketTsMs, incomingFreshness.depthTsMs),
            latest_fill_ts_ms: Math.max(toNum(state.summarySystem.latest_fill_ts_ms) ?? 0, incomingFreshness.fillsTsMs),
            position_source_ts_ms: Math.max(toNum(state.summarySystem.position_source_ts_ms) ?? 0, incomingFreshness.positionTsMs),
          });
          const summaryActivity = allowRestFills
            ? mergeSummaryActivity(state.summaryActivity, payload.summary?.activity)
            : state.summaryActivity;
          const summaryAccountBase =
            freshnessDecision.reasons.length === 0
              ? mergeSummaryAccount(state.summaryAccount, payload.summary?.account)
              : state.summaryAccount;
          const alerts = freshnessDecision.reasons.length === 0 ? mergeAlerts(state.alerts, payload.summary?.alerts) : state.alerts;
          const nextSummaryAccount =
            incomingControllerId && !String(summaryAccountBase.controller_id ?? "").trim()
              ? mergeSummaryAccount(summaryAccountBase, { controller_id: incomingControllerId })
              : summaryAccountBase;
          const nextMarket = allowRestMarket
            ? stableMarket(
                state.market,
                {
                  ...market,
                  trading_pair: market.trading_pair ?? incomingTradingPair,
                },
              )
            : state.market;
          const nextDepth = freshnessDecision.acceptDepth
            ? stableDepth(
                state.depth,
                {
                  ...depth,
                  trading_pair: depth.trading_pair ?? incomingTradingPair,
                },
              )
            : state.depth;
          const nextPosition = freshnessDecision.acceptPosition
            ? stablePosition(
                state.position,
                {
                  ...position,
                  trading_pair: position.trading_pair ?? incomingTradingPair,
                },
              )
            : state.position;
          const nextOrders = freshnessDecision.acceptOrders
            ? stableOrders(state.orders, openOrders.slice(0, 200) as UiOrder[])
            : state.orders;
          const nextFills = allowRestFills
            ? stableFills(state.fills, mergeRecentFills([], normalizedRestFills, MAX_FILLS))
            : state.fills;
          const candidateMid = toNum(nextMarket.mid_price ?? fallback.minute?.mid) ?? depthMid(nextDepth);
          const latestMid = candidateMid ?? state.latestMid;
          const midPriceDirection =
            candidateMid !== null && (allowRestMarket || freshnessDecision.acceptDepth)
              ? getPriceDirection(state.latestMid, latestMid)
              : state.midPriceDirection;
          const candleReferenceTsMs = Math.max(incomingFreshness.marketTsMs, incomingFreshness.depthTsMs, Date.now());
          const nextCandleState =
            candidateMid !== null && (allowRestMarket || freshnessDecision.acceptDepth)
              ? pushMidCandle(state.candles, state.latestCandle, candleReferenceTsMs, candidateMid, state.settings.timeframeS)
              : { candles: state.candles, latestCandle: state.latestCandle };
          const nextCandles = stableCandles(state.candles, nextCandleState.candles);
          const nextLatestCandle = sameCandle(state.latestCandle, nextCandleState.latestCandle) ? state.latestCandle : nextCandleState.latestCandle;
          const nextEventLines =
            freshnessDecision.reasons.length > 0 && !state.settings.feedPaused
              ? [
                  ...state.eventLines,
                  `${new Date().toLocaleTimeString()} [state] ignored stale segments: ${freshnessDecision.reasons.join(", ")}`,
                ].slice(-MAX_EVENT_LINES)
              : state.eventLines;
          return {
            mode: payload.mode ?? state.mode,
            source: payload.source ?? state.source,
            summarySystem,
            summaryActivity,
            summaryAccount: nextSummaryAccount,
            freshness: {
              ...state.freshness,
              marketTsMs: allowRestMarket ? Math.max(state.freshness.marketTsMs, incomingFreshness.marketTsMs) : state.freshness.marketTsMs,
              depthTsMs: freshnessDecision.acceptDepth ? Math.max(state.freshness.depthTsMs, incomingFreshness.depthTsMs) : state.freshness.depthTsMs,
              positionTsMs: freshnessDecision.acceptPosition ? Math.max(state.freshness.positionTsMs, incomingFreshness.positionTsMs) : state.freshness.positionTsMs,
              ordersTsMs: freshnessDecision.acceptOrders ? Math.max(state.freshness.ordersTsMs, incomingFreshness.ordersTsMs) : state.freshness.ordersTsMs,
              fillsTsMs: allowRestFills ? Math.max(state.freshness.fillsTsMs, incomingFreshness.fillsTsMs) : state.freshness.fillsTsMs,
              staleRestRejectCount: state.freshness.staleRestRejectCount + (freshnessDecision.reasons.length > 0 ? 1 : 0),
            },
            alerts,
            market: nextMarket,
            depth: nextDepth,
            position: nextPosition,
            latestMid,
            midPriceDirection,
            latestQuoteTsMs:
              candidateMid !== null && (allowRestMarket || freshnessDecision.acceptDepth)
                ? Math.max(state.latestQuoteTsMs, incomingFreshness.marketTsMs, incomingFreshness.depthTsMs)
                : state.latestQuoteTsMs,
            candles: nextCandles,
            latestCandle: nextLatestCandle,
            orders: nextOrders,
            fills: nextFills,
            fillsTotal: allowRestFills ? (Number.isFinite(fillsTotal) ? fillsTotal : fills.length) : state.fillsTotal,
            eventLines: nextEventLines,
          };
        });
      },
      pruneRuntimeEvents: () => {
        set((state) => ({ runtimeEvents: trimRuntimeEvents(state.runtimeEvents) }));
      },
      resetLiveData: () => {
        set({
          mode: "",
          source: "",
          summarySystem: defaultSummarySystem(),
          summaryActivity: defaultSummaryActivity(),
          summaryAccount: defaultSummaryAccount(),
          freshness: defaultFreshness(),
          alerts: EMPTY_ALERTS,
          market: EMPTY_MARKET,
          depth: EMPTY_DEPTH,
          position: EMPTY_POSITION,
          latestMid: null,
          midPriceDirection: "flat",
          latestQuoteTsMs: 0,
          candles: EMPTY_CANDLES,
          latestCandle: null,
          candleSeriesNonce: get().candleSeriesNonce + 1,
          orders: EMPTY_ORDERS,
          fills: EMPTY_FILLS,
          fillsTotal: 0,
          eventLines: EMPTY_EVENT_LINES,
          payloads: EMPTY_PAYLOADS,
          selectedPayloadId: null,
          runtimeEvents: EMPTY_RUNTIME_EVENTS,
        });
      },
    })),
);
