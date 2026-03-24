"""Paper budget checker — drop-in replacement for HB's BudgetChecker.

Extracted from hb_bridge.py to reduce file size and improve modularity.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)


class PaperBudgetChecker:
    """Drop-in replacement for HB's BudgetChecker.

    Patches HB's collateral/budget check system so order candidates
    pass validation regardless of real exchange balance. All methods
    return candidates unchanged (paper has unlimited budget within
    the configured paper_equity_quote).
    """

    def __init__(self, exchange: Any, paper_equity_quote: Decimal = Decimal("10000")):
        self._exchange = exchange
        self._paper_equity = paper_equity_quote

    def reset_locked_collateral(self) -> None:
        pass

    def adjust_candidates(self, order_candidates: Any, all_or_none: bool = True) -> list[Any]:
        return list(order_candidates)

    def adjust_candidate_and_lock_available_collateral(self, order_candidate: Any, all_or_none: bool = True) -> Any:
        return order_candidate

    def adjust_candidate(self, order_candidate: Any, all_or_none: bool = True) -> Any:
        return order_candidate

    def populate_collateral_entries(self, order_candidate: Any) -> Any:
        return order_candidate


def install_budget_checker(connector: Any, equity_quote: Decimal) -> None:
    """Install PaperBudgetChecker on a connector if it has a _budget_checker."""
    try:
        for attr in ("_budget_checker", "budget_checker"):
            if hasattr(connector, attr):
                setattr(connector, attr, PaperBudgetChecker(connector, equity_quote))
                logger.info("PaperBudgetChecker installed on %s", getattr(connector, "name", "connector"))
                return
    except Exception as exc:
        logger.debug("PaperBudgetChecker install failed (non-critical): %s", exc)
