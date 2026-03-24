"""One-shot script: copy main config, override end_date to January."""
import pathlib

import yaml

src = pathlib.Path("/workspace/hbot/data/backtest_configs/bot7_pullback.yml")
dst = pathlib.Path("/tmp/bt_r1.yml")
d = yaml.safe_load(src.read_text())
d["data_source"]["end_date"] = "2025-01-31"
dst.write_text(yaml.dump(d, default_flow_style=False, sort_keys=False))
print("Written", dst, "end_date =", d["data_source"]["end_date"])
