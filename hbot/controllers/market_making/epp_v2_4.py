# Re-export shim for Hummingbot controller_type=market_making resolution.
# `controllers.epp_v2_4` is now a legacy compatibility wrapper over the
# canonical shared market-making implementation in `controllers.shared_mm_v24`.
from controllers.epp_v2_4 import EppV24Config, EppV24Controller  # noqa: F401
