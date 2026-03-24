"""Compatibility wrappers for legacy bot1 EPP lane names.

Preferred implementation lives at ``controllers.bots.bot1.baseline_v1``.
"""
from controllers.bots.bot1.baseline_v1 import Bot1BaselineV1Config, Bot1BaselineV1Controller


class EppV24Bot1Config(Bot1BaselineV1Config):
    """Legacy bot1 config alias (keeps existing controller_name stable)."""

    controller_name: str = "epp_v2_4_bot1"


class EppV24Bot1Controller(Bot1BaselineV1Controller):
    """Legacy bot1 controller alias."""
