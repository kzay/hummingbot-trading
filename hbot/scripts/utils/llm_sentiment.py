"""
LLM Sentiment Analyzer — Standalone Module
============================================

Queries Grok (xAI) or OpenAI for crypto market sentiment scoring.
Designed to run in a background thread to avoid blocking the trading loop.

Supports:
  - Primary + fallback provider
  - Automatic caching with configurable TTL
  - Exponential back-off on consecutive failures
  - JSON response parsing with markdown-fence stripping
  - Thread-safe score/reasoning properties

Usage::

    from llm_sentiment import SentimentEngine

    engine = SentimentEngine(
        provider="grok",
        api_key="xai-...",
        query_interval=600,
    )

    # Inside your tick loop:
    engine.tick(now=time.time(), pair="BTC-USDT")
    score = engine.score         # 0–100, 50 = neutral
    text  = engine.reasoning     # one-sentence explanation
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class SentimentEngine:
    """
    Non-blocking LLM sentiment scorer.

    Call :meth:`tick` on every strategy tick.  The engine manages
    query scheduling, background HTTP calls, result caching,
    and graceful degradation.
    """

    PROVIDERS: Dict[str, Dict[str, str]] = {
        "grok": {
            "url": "https://api.x.ai/v1/chat/completions",
            "model": "grok-3",
        },
        "openai": {
            "url": "https://api.openai.com/v1/chat/completions",
            "model": "gpt-4o-mini",
        },
    }

    def __init__(
        self,
        provider: str = "grok",
        api_key: str = "",
        fallback_provider: str = "openai",
        fallback_api_key: str = "",
        query_interval: int = 600,
        request_timeout: int = 15,
    ):
        self.provider = provider.lower()
        self.api_key = api_key
        self.fallback_provider = fallback_provider.lower()
        self.fallback_api_key = fallback_api_key
        self.query_interval = query_interval
        self.request_timeout = request_timeout

        self._score: float = 50.0
        self._reasoning: str = "Awaiting first query"
        self._last_query_ts: float = 0.0
        self._pool = ThreadPoolExecutor(max_workers=1,
                                        thread_name_prefix="llm-sentiment")
        self._future: Optional[Future] = None
        self._failures: int = 0

    # ── Public API ─────────────────────────────────────────────────────

    @property
    def score(self) -> float:
        """Current sentiment score (0 = very bearish, 100 = very bullish)."""
        return self._score

    @property
    def reasoning(self) -> str:
        """One-sentence explanation from the LLM."""
        return self._reasoning

    @property
    def is_stale(self) -> bool:
        """True if the cached score is older than 3× the query interval."""
        if self._last_query_ts == 0:
            return True
        return (time.time() - self._last_query_ts) > self.query_interval * 3

    def tick(self, now: float, pair: str) -> None:
        """
        Call once per strategy tick.

        Harvests completed background queries, and schedules new ones
        when the query interval has elapsed.
        """
        # Harvest
        if self._future is not None and self._future.done():
            try:
                res = self._future.result()
                if res is not None:
                    self._score = res["score"]
                    self._reasoning = res["reasoning"]
                    self._last_query_ts = now
                    self._failures = 0
                    logger.info("LLM sentiment updated: %.1f — %s",
                                self._score, self._reasoning[:100])
                else:
                    self._failures += 1
            except Exception as exc:
                self._failures += 1
                logger.warning("LLM future raised: %s", exc)
            finally:
                self._future = None

        # Schedule
        if self._future is None:
            elapsed = now - self._last_query_ts
            if elapsed >= self.query_interval:
                if self._failures >= 5:
                    backoff = min(
                        self.query_interval * (2 ** self._failures), 3600
                    )
                    if elapsed < backoff:
                        return
                self._future = self._pool.submit(self._query, pair)

    def shutdown(self) -> None:
        """Gracefully shut down the background thread pool."""
        self._pool.shutdown(wait=False)

    # ── Internal ───────────────────────────────────────────────────────

    def _query(self, pair: str) -> Optional[Dict[str, Any]]:
        try:
            import requests as _req  # noqa: delayed import
        except ImportError:
            logger.error("'requests' package not installed — LLM disabled")
            return None

        base = pair.split("-")[0] if "-" in pair else pair
        prompt = (
            f"Analyze the current real-time market sentiment for {base} "
            f"({pair}) based on recent X/Twitter posts, crypto news, "
            f"and on-chain signals.  "
            f"Provide a sentiment score from 0 to 100:\n"
            f"  0-20  Very bearish\n"
            f"  20-40 Bearish\n"
            f"  40-60 Neutral\n"
            f"  60-80 Bullish\n"
            f"  80-100 Very bullish\n\n"
            f"Respond with ONLY valid JSON:\n"
            f'{{"score": <int>, "reasoning": "<one sentence>"}}'
        )

        result = self._call_provider(self.provider, self.api_key, prompt)
        if result is not None:
            return result

        if self.fallback_api_key:
            logger.info("Primary LLM failed — trying fallback (%s)",
                        self.fallback_provider)
            return self._call_provider(
                self.fallback_provider, self.fallback_api_key, prompt
            )
        return None

    def _call_provider(
        self, provider: str, key: str, prompt: str
    ) -> Optional[Dict[str, Any]]:
        import requests as _req

        if not key:
            return None
        cfg = self.PROVIDERS.get(provider)
        if cfg is None:
            logger.error("Unknown LLM provider: %s", provider)
            return None

        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": cfg["model"],
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a crypto market sentiment analyst. "
                        "Reply ONLY with the requested JSON, no markdown."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 150,
        }

        try:
            resp = _req.post(
                cfg["url"], headers=headers, json=body,
                timeout=self.request_timeout,
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()

            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            parsed = json.loads(text)
            score = max(0.0, min(100.0, float(parsed["score"])))
            reasoning = str(parsed.get("reasoning", ""))
            return {"score": score, "reasoning": reasoning}

        except Exception as exc:
            logger.warning("LLM %s request failed: %s", provider, exc)
            return None
