export function toNum(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function formatNumber(value: unknown, digits = 2): string {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return "n/a";
  }
  return parsed.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

export function formatSigned(value: unknown, digits = 2): string {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return "n/a";
  }
  const abs = formatNumber(Math.abs(parsed), digits);
  if (parsed > 0) {
    return `+${abs}`;
  }
  if (parsed < 0) {
    return `-${abs}`;
  }
  return abs;
}

export function formatPct(value: unknown, digits = 2): string {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return "n/a";
  }
  return `${(parsed * 100).toFixed(digits)}%`;
}

export function formatAgeMs(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "n/a";
  }
  const ms = Number(value);
  if (!Number.isFinite(ms) || ms < 0) {
    return "n/a";
  }
  if (ms < 1_000) {
    return `${Math.round(ms)} ms`;
  }
  const seconds = ms / 1_000;
  if (seconds < 60) {
    return `${seconds.toFixed(1)} s`;
  }
  const minutes = seconds / 60;
  if (minutes < 60) {
    return `${minutes.toFixed(1)} m`;
  }
  return `${(minutes / 60).toFixed(1)} h`;
}

export function formatTs(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "n/a";
  }
  const numeric = Number(value);
  if (Number.isFinite(numeric) && numeric > 0) {
    return new Date(numeric).toLocaleString();
  }
  const parsedIso = Date.parse(String(value));
  if (!Number.isFinite(parsedIso) || parsedIso <= 0) {
    return "n/a";
  }
  return new Date(parsedIso).toLocaleString();
}

export function formatRelativeTs(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "n/a";
  }
  const numeric = Number(value);
  const parsed = Number.isFinite(numeric) && numeric > 0 ? numeric : Date.parse(String(value));
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return "n/a";
  }
  return `${formatAgeMs(Date.now() - parsed)} ago`;
}

export function normalizeSide(value: unknown): string {
  return String(value ?? "")
    .trim()
    .toLowerCase();
}
