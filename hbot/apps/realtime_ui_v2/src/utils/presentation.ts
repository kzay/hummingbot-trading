export function signedClass(value: unknown): "value-positive" | "value-negative" | "value-neutral" {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return "value-neutral";
  }
  if (parsed > 0) {
    return "value-positive";
  }
  if (parsed < 0) {
    return "value-negative";
  }
  return "value-neutral";
}

export function sideTone(side: string): "good" | "bad" | "neutral" {
  const normalized = String(side || "").trim().toLowerCase();
  if (normalized === "buy" || normalized === "long") {
    return "good";
  }
  if (normalized === "sell" || normalized === "short") {
    return "bad";
  }
  return "neutral";
}

export function gateTone(status: string): "ok" | "warn" | "fail" | "neutral" {
  const normalized = String(status || "").trim().toLowerCase();
  if (!normalized) {
    return "neutral";
  }
  if (["blocked", "hard_stop", "fail", "error"].includes(normalized)) {
    return "fail";
  }
  if (["limited", "waiting", "warn", "degraded", "stale"].includes(normalized)) {
    return "warn";
  }
  if (["quoting", "active", "pass", "ok", "ready"].includes(normalized)) {
    return "ok";
  }
  return "neutral";
}

export function gatePriority(status: string): number {
  const tone = gateTone(status);
  if (tone === "fail") {
    return 0;
  }
  if (tone === "warn") {
    return 1;
  }
  if (tone === "ok") {
    return 2;
  }
  return 3;
}
