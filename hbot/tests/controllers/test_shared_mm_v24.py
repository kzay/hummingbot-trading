from __future__ import annotations

import importlib.util

import pytest


def _hummingbot_available() -> bool:
    try:
        return importlib.util.find_spec("hummingbot") is not None
    except ValueError:
        return False


HUMMINGBOT_AVAILABLE = _hummingbot_available()

if HUMMINGBOT_AVAILABLE:
    from controllers.epp_v2_4 import EppV24Config, EppV24Controller
    from controllers.runtime.base import StrategyRuntimeV24Config, StrategyRuntimeV24Controller
    from controllers.shared_mm_v24 import SharedMmV24Config, SharedMmV24Controller
else:  # pragma: no cover - exercised only in stripped test environments
    EppV24Config = object
    EppV24Controller = object
    SharedMmV24Config = object
    SharedMmV24Controller = object
    StrategyRuntimeV24Config = object
    StrategyRuntimeV24Controller = object

pytestmark = pytest.mark.skipif(not HUMMINGBOT_AVAILABLE, reason="hummingbot not installed")


def test_shared_mm_v24_aliases_runtime_stack() -> None:
    assert issubclass(SharedMmV24Config, StrategyRuntimeV24Config)
    assert issubclass(SharedMmV24Controller, StrategyRuntimeV24Controller)
    assert issubclass(SharedMmV24Config, EppV24Config)
    assert issubclass(SharedMmV24Controller, EppV24Controller)
    assert SharedMmV24Config.controller_name == "shared_mm_v24"
