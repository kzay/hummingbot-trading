# Re-export shim for Hummingbot controller_type=market_making resolution.
# The actual controller lives at controllers/epp_v2_4.py.
from controllers.epp_v2_4 import EppV24Config, EppV24Controller  # noqa: F401
