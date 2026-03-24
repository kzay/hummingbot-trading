from __future__ import annotations

from platform_lib.core.utils import parse_iso_ts


def _safe_iso_ts_to_epoch(value: str) -> float | None:
    dt = parse_iso_ts(value)
    return dt.timestamp() if dt else None


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _fmt_labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    pairs = [f'{k}="{_escape_label(v)}"' for k, v in labels.items()]
    return "{" + ",".join(pairs) + "}"


def _median(lst: list) -> float:
    """Compute median of a numeric list; return 0.0 for empty input."""
    if not lst:
        return 0.0
    s = sorted(lst)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    q = max(0.0, min(1.0, float(q)))
    idx = q * (len(ordered) - 1)
    low = int(idx)
    high = min(low + 1, len(ordered) - 1)
    if low == high:
        return float(ordered[low])
    weight = idx - low
    return float(ordered[low] * (1.0 - weight) + ordered[high] * weight)


def _split_reasons(raw: str) -> list[str]:
    if not raw:
        return []
    parts = [p.strip() for p in raw.split("|")]
    return [p for p in parts if p and p.lower() != "none"]


def _headroom_ratio(current: float, threshold: float, lower_is_worse: bool) -> float:
    if abs(threshold) <= 1e-9:
        # Threshold disabled or unset -> treat as healthy/neutral headroom.
        return 1.0
    denom = abs(threshold)
    if lower_is_worse:
        return (current - threshold) / denom
    return (threshold - current) / denom
