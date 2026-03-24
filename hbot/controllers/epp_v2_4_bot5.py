"""Compatibility wrappers for legacy bot5 EPP lane names.

Preferred implementation lives at ``controllers.bots.bot5.ift_jota_v1``.
"""
from controllers.bots.bot5.ift_jota_v1 import Bot5IftJotaV1Config, Bot5IftJotaV1Controller


class EppV24Bot5Config(Bot5IftJotaV1Config):
    """Legacy bot5 config alias (keeps existing controller_name stable)."""

    controller_name: str = "epp_v2_4_bot5"


class EppV24Bot5Controller(Bot5IftJotaV1Controller):
    """Legacy bot5 controller alias."""
