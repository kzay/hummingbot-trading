"""
BERT-based hype event filter.

Use this module to downweight strategy risk during hype-driven regimes from
X/news headlines before forwarding grid instructions.
"""

from __future__ import annotations

from typing import Iterable, List

try:
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
except Exception:  # pragma: no cover
    torch = None
    AutoTokenizer = None
    AutoModelForSequenceClassification = None


class BertHypeFilter:
    def __init__(self, model_name: str = "cardiffnlp/twitter-roberta-base-sentiment-latest"):
        self.model_name = model_name
        self._tokenizer = None
        self._model = None
        self._loaded = False

    def _ensure_loaded(self):
        if self._loaded:
            return
        self._loaded = True
        if AutoTokenizer is None or AutoModelForSequenceClassification is None:
            return
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self._model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
        self._model.eval()

    def hype_score(self, texts: Iterable[str]) -> float:
        self._ensure_loaded()
        if self._model is None or self._tokenizer is None:
            return 0.0

        rows: List[str] = [t for t in texts if t and t.strip()]
        if not rows:
            return 0.0

        with torch.no_grad():
            encoded = self._tokenizer(rows, padding=True, truncation=True, return_tensors="pt")
            logits = self._model(**encoded).logits
            probs = torch.softmax(logits, dim=-1)
            # Positive probability proxy for hype intensity.
            pos_idx = probs.shape[1] - 1
            hype = probs[:, pos_idx].mean().item()
        return max(0.0, min(1.0, float(hype)))

    def risk_multiplier(self, texts: Iterable[str]) -> float:
        # 1.0 = normal risk, 0.5 = reduce risk by 50%.
        h = self.hype_score(texts)
        return 1.0 - 0.5 * h
