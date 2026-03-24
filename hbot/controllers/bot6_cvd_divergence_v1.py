"""Neutral convenience re-export for bot6 CVD-divergence lane.

Canonical implementation: ``controllers.bots.bot6.cvd_divergence_v1``
"""
from controllers.bots.bot6.cvd_divergence_v1 import (  # noqa: F401
    Bot6CvdDivergenceV1Config,
    Bot6CvdDivergenceV1Controller,
)

__all__ = ["Bot6CvdDivergenceV1Config", "Bot6CvdDivergenceV1Controller"]
