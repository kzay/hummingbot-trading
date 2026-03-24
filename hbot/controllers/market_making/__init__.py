"""HB loader-shim package — controller_type=market_making.

Hummingbot's ``v2_with_controllers.py`` resolves controller configs by
importing ``controllers.<controller_type>.<controller_name>``.  Each module
in this package re-exports the canonical Config/Controller pair so that
the HB loader can find them.

Do NOT place strategy logic here — only thin import shims.
"""
