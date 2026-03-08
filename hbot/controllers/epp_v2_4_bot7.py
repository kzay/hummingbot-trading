"""Compatibility wrappers for legacy bot7 EPP lane names.

Preferred implementation lives at `controllers.bots.bot7.adaptive_grid_v1`.
"""

from controllers.bots.bot7.adaptive_grid_v1 import Bot7AdaptiveGridV1Config, Bot7AdaptiveGridV1Controller


class EppV24Bot7Config(Bot7AdaptiveGridV1Config):
    """Legacy bot7 config alias (keeps existing controller_name stable)."""

    controller_name: str = "epp_v2_4_bot7"


class EppV24Bot7Controller(Bot7AdaptiveGridV1Controller):
    """Legacy bot7 controller alias."""
