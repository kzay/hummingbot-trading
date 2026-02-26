"""Tests for the EventJournal append-only event log (Phase 4).

Covers:
- Append and iterate entries
- Filtering by min_ts_ns
- Journal survives multiple appends
- DeskStateStore journal integration
- Replay determinism: same sequence of events produces identical state
"""
import json
import time
from decimal import Decimal
from pathlib import Path

import pytest

from controllers.paper_engine_v2.state_store import DeskStateStore, EventJournal


# ---------------------------------------------------------------------------
# EventJournal unit tests
# ---------------------------------------------------------------------------

class TestEventJournal:
    def test_append_and_iter(self, tmp_path):
        j = EventJournal(str(tmp_path), prefix="test_events")
        j.append("fill", {"price": "100", "qty": "1"})
        j.append("fill", {"price": "200", "qty": "2"})
        entries = list(j.iter_since(0))
        assert len(entries) == 2
        assert entries[0]["event_type"] == "fill"
        assert entries[0]["price"] == "100"
        assert entries[1]["price"] == "200"
        j.close()

    def test_iter_since_filters(self, tmp_path):
        j = EventJournal(str(tmp_path), prefix="test_events")
        j.append("fill", {"idx": "1"})
        # Flush and capture timestamps from written entries to get a reliable cutoff.
        first_entries = list(j.iter_since(0))
        assert len(first_entries) == 1
        # Use a cutoff 1ns after the first entry's timestamp.
        cutoff_ns = first_entries[0]["ts_ns"] + 1
        time.sleep(0.01)  # Ensure next event has a higher ts_ns
        j.append("fill", {"idx": "2"})
        all_entries = list(j.iter_since(0))
        later_entries = list(j.iter_since(cutoff_ns))
        assert len(all_entries) == 2
        assert len(later_entries) == 1
        assert later_entries[0]["idx"] == "2"
        j.close()

    def test_append_never_raises_on_bad_payload(self, tmp_path):
        """Journal must not crash the trading loop even with non-serializable data."""
        j = EventJournal(str(tmp_path))
        # object() is not JSON serializable — but default=str should handle it
        j.append("test", {"data": object()})
        j.close()

    def test_entries_have_ts_ns(self, tmp_path):
        j = EventJournal(str(tmp_path))
        j.append("ping", {})
        entries = list(j.iter_since(0))
        assert "ts_ns" in entries[0]
        assert isinstance(entries[0]["ts_ns"], int)
        j.close()

    def test_multi_append_persists_to_jsonl(self, tmp_path):
        j = EventJournal(str(tmp_path), prefix="persist_test")
        for i in range(5):
            j.append("fill", {"i": str(i)})
        j.close()
        # Verify the file exists and is valid JSONL
        files = list(tmp_path.glob("persist_test_*.jsonl"))
        assert len(files) == 1
        lines = [json.loads(l) for l in files[0].read_text().splitlines() if l.strip()]
        assert len(lines) == 5
        assert [l["i"] for l in lines] == [str(i) for i in range(5)]


# ---------------------------------------------------------------------------
# DeskStateStore journal integration
# ---------------------------------------------------------------------------

class TestDeskStateStoreJournal:
    def test_journal_event_stored(self, tmp_path):
        store = DeskStateStore(
            file_path=str(tmp_path / "state.json"),
            journal_dir=str(tmp_path),
        )
        store.journal_event("order_filled", {"price": "100", "qty": "1.5"})
        entries = list(store.iter_journal(0))
        assert len(entries) >= 1
        fill_entries = [e for e in entries if e["event_type"] == "order_filled"]
        assert len(fill_entries) == 1
        assert fill_entries[0]["price"] == "100"
        store.close()

    def test_save_journals_snapshot(self, tmp_path):
        store = DeskStateStore(
            file_path=str(tmp_path / "state.json"),
            journal_dir=str(tmp_path),
        )
        snap = {"balances": {"USDT": "1000"}, "positions": {}}
        store.save(snap, time.time(), force=True)
        entries = list(store.iter_journal(0))
        snap_entries = [e for e in entries if e["event_type"] == "desk_snapshot"]
        assert len(snap_entries) >= 1
        store.close()


# ---------------------------------------------------------------------------
# Replay determinism test
# ---------------------------------------------------------------------------

class TestReplayDeterminism:
    def test_same_fills_produce_same_state(self):
        """Replay accounting.apply_fill() with same sequence → identical result."""
        from controllers.paper_engine_v2.accounting import PositionState, apply_fill

        _Z = Decimal("0")
        s0 = PositionState(quantity=_Z, avg_entry_price=_Z, realized_pnl=_Z, opened_at_ns=0)

        fills = [
            ("buy", "2", "100"),
            ("buy", "1", "200"),
            ("sell", "1", "150"),
            ("sell", "3", "180"),
        ]

        def run_sequence(state, fills):
            for side, qty, price in fills:
                r = apply_fill(state, side, Decimal(qty), Decimal(price), now_ns=1)
                state = r.new_state
            return state

        state_a = run_sequence(s0, fills)
        state_b = run_sequence(s0, fills)

        assert state_a.quantity == state_b.quantity
        assert state_a.avg_entry_price == state_b.avg_entry_price
        assert state_a.realized_pnl == state_b.realized_pnl
