from __future__ import annotations

import gzip
import json
from pathlib import Path

from scripts.ops.pg_backup import _copy_parity_sidecar, _verify_gzip


def test_verify_gzip_validates_expected_file(tmp_path: Path) -> None:
    path = tmp_path / "pg_backup_20260302T000000Z.sql.gz"
    with gzip.open(path, "wb") as fp:
        fp.write(b"select 1;")
    assert _verify_gzip(path) is True


def test_copy_parity_sidecar_copies_and_hashes_payload(tmp_path: Path) -> None:
    parity_path = tmp_path / "parity_latest.json"
    parity_path.write_text(
        json.dumps({"ts_utc": "2026-03-02T00:00:00+00:00", "status": "pass", "bots": []}),
        encoding="utf-8",
    )
    result = _copy_parity_sidecar(parity_path, tmp_path, "20260302T000001Z")
    assert result["status"] == "pass"
    assert result["sha256"]
    assert Path(str(result["path"])).exists()
