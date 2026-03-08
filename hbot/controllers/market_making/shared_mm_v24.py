# Re-export shim for Hummingbot controller_type=market_making resolution.
# The actual controller lives at controllers/shared_mm_v24.py.
from controllers.shared_mm_v24 import SharedMmV24Config, SharedMmV24Controller  # noqa: F401
