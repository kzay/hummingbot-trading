from __future__ import annotations

from pathlib import Path

from scripts.ops.ops_db_restore_drill import _counts_match, _latest_manifest, _safe_db_name


def test_latest_manifest_picks_most_recent_name(tmp_path: Path) -> None:
    old = tmp_path / "pg_backup_20260301T000000Z.manifest.json"
    new = tmp_path / "pg_backup_20260302T000000Z.manifest.json"
    old.write_text("{}", encoding="utf-8")
    new.write_text("{}", encoding="utf-8")
    assert _latest_manifest(tmp_path) == new


def test_counts_match_uses_expected_values() -> None:
    expected = {"bot_snapshot_minute": 5, "fills": 3, "event_envelope_raw": 7}
    restored_ok = {"bot_snapshot_minute": 5, "fills": 3, "event_envelope_raw": 7}
    restored_bad = {"bot_snapshot_minute": 5, "fills": 2, "event_envelope_raw": 7}
    assert _counts_match(expected, restored_ok) is True
    assert _counts_match(expected, restored_bad) is False


def test_safe_db_name_rejects_unsafe_values() -> None:
    assert _safe_db_name("restore_db_1") == "restore_db_1"
    try:
        _safe_db_name("restore-db;drop")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for unsafe db name")
