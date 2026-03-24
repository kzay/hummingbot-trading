from __future__ import annotations

from controllers.epp_logging import CsvSplitLogger, _CsvBuffer


def test_csv_buffer_write_creates_file(tmp_path):
    path = tmp_path / "test.csv"
    buf = _CsvBuffer(path, flush_rows=1, flush_interval_s=0)
    buf.write({"a": "1", "b": "2"}, ["a", "b"])
    buf.flush()
    buf.close()
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "a,b" in text
    assert "1,2" in text


def test_csv_buffer_close_idempotent(tmp_path):
    path = tmp_path / "test.csv"
    buf = _CsvBuffer(path, flush_rows=1, flush_interval_s=0)
    buf.close()
    buf.close()


def test_csv_split_logger_log_fill(tmp_path):
    lgr = CsvSplitLogger(
        base_log_dir=str(tmp_path),
        instance_name="test_bot",
        variant="a",
        namespace="test",
        flush_rows=1,
    )
    lgr.log_fill({
        "ts": "2026-03-10T12:00:00+00:00",
        "bot_variant": "a",
        "exchange": "bitget_perpetual",
        "trading_pair": "BTC-USDT",
        "side": "buy",
        "price": "50000",
        "amount_base": "0.001",
        "notional_quote": "50",
        "fee_quote": "0.05",
        "order_id": "o1",
        "state": "filled",
        "regime": "neutral_low_vol",
    })
    lgr.flush_all()
    lgr.close_all()

    fills_dir = tmp_path / "test"
    assert fills_dir.exists()


def test_csv_split_logger_log_minute(tmp_path):
    lgr = CsvSplitLogger(
        base_log_dir=str(tmp_path),
        instance_name="test_bot",
        variant="a",
        namespace="test",
        flush_rows=1,
    )
    lgr.log_minute({"ts": "2026-03-10T12:00:00+00:00", "mid": "50000"})
    lgr.flush_all()
    lgr.close_all()
