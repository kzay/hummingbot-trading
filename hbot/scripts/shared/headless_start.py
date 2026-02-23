#!/usr/bin/env python3
"""Headless startup wrapper that patches wait_for_gateway_ready to handle
paper-trade connectors whose settings return None from AllConnectorSettings."""
import importlib.util
import sys
import os

# Load hummingbot_quickstart as a module from file path
spec = importlib.util.spec_from_file_location(
    "hummingbot_quickstart",
    os.path.join(os.path.dirname(__file__), "hummingbot_quickstart.py"),
)
qs = importlib.util.module_from_spec(spec)
sys.modules["hummingbot_quickstart"] = qs

_original_wait = None


async def _safe_wait_for_gateway_ready(hb):
    """Skip gateway check for paper-trade connectors whose settings are None."""
    try:
        from hummingbot.client.settings import AllConnectorSettings
        exchange_settings = [
            AllConnectorSettings.get_connector_settings().get(e, None)
            for e in hb.trading_core.connector_manager.connectors.keys()
        ]
        uses_gateway = any(
            s.uses_gateway_generic_connector()
            for s in exchange_settings
            if s is not None
        )
        if not uses_gateway:
            return
        if _original_wait is not None:
            await _original_wait(hb)
    except Exception:
        return


# Execute the module, then patch and re-enter via main()
spec.loader.exec_module(qs)

# Patch after loading so the function exists
_original_wait = qs.wait_for_gateway_ready
qs.wait_for_gateway_ready = _safe_wait_for_gateway_ready

# Run
qs.main()
