"""EPP lane wrapper for the bot7 trend-aligned pullback grid strategy."""
from controllers.bots.bot7.pullback_v1 import PullbackV1Config, PullbackV1Controller


class EppV24Bot7PullbackConfig(PullbackV1Config):
    """Bot7 pullback lane config with stable EPP controller_name."""

    controller_name: str = "epp_v2_4_bot7_pullback"


class EppV24Bot7PullbackController(PullbackV1Controller):
    """EPP wrapper for bot7 trend-aligned pullback grid strategy."""
