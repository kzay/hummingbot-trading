"""Backward-compat re-export shim.

The canonical implementation now lives in ``services.common.research_api``.
This file is kept so that any stale imports resolve without errors.
"""
from services.common.research_api import create_research_routes  # noqa: F401

__all__ = ["create_research_routes"]
