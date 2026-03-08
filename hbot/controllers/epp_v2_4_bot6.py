"""Compatibility wrappers for legacy bot6 EPP lane names.

Preferred implementation lives at `controllers.bots.bot6.cvd_divergence_v1`.
"""

from controllers.bots.bot6.cvd_divergence_v1 import Bot6CvdDivergenceV1Config, Bot6CvdDivergenceV1Controller


class EppV24Bot6Config(Bot6CvdDivergenceV1Config):
    """Legacy bot6 config alias (keeps existing controller_name stable)."""

    controller_name: str = "epp_v2_4_bot6"


class EppV24Bot6Controller(Bot6CvdDivergenceV1Controller):
    """Legacy bot6 controller alias."""
