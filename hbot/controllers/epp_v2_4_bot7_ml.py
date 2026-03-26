"""EPP lane wrapper for the bot7 pure ML signal-driven strategy."""
from controllers.bots.bot7.ml_v1 import Bot7MlV1Config, Bot7MlV1Controller


class EppV24Bot7MlConfig(Bot7MlV1Config):
    """Bot7 ML lane config with stable EPP controller_name."""

    controller_name: str = "epp_v2_4_bot7_ml"


class EppV24Bot7MlController(Bot7MlV1Controller):
    """EPP wrapper for bot7 ML signal-driven strategy."""
