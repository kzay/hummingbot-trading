def __getattr__(name: str):
    if name in ("Bot1BaselineV1Config", "Bot1BaselineV1Controller"):
        from controllers.bots.bot1.baseline_v1 import (
            Bot1BaselineV1Config,
            Bot1BaselineV1Controller,
        )
        return {"Bot1BaselineV1Config": Bot1BaselineV1Config, "Bot1BaselineV1Controller": Bot1BaselineV1Controller}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "Bot1BaselineV1Config",
    "Bot1BaselineV1Controller",
]
