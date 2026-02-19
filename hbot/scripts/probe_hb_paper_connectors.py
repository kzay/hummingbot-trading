#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import subprocess
from dataclasses import asdict, dataclass
from typing import List


@dataclass
class ProbeResult:
    image: str
    ok: bool
    bitget_connectors: List[str]
    paper_connectors: List[str]
    has_bitget_paper: bool
    error: str = ""


def probe_image(image: str, timeout_s: int = 240) -> ProbeResult:
    inner = (
        "conda run --no-capture-output -n hummingbot python -c "
        "\"from hummingbot.client.settings import AllConnectorSettings as A; "
        "k=sorted(A.get_connector_settings().keys()); "
        "b=[x for x in k if 'bitget' in x]; "
        "p=[x for x in k if 'paper' in x]; "
        "import json; print(json.dumps({'bitget': b, 'paper': p}))\""
    )
    cmd = ["docker", "run", "--rm", image, "/bin/bash", "-lc", inner]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=timeout_s)
        payload = json.loads(out.strip().splitlines()[-1])
        bitget = payload.get("bitget", [])
        paper = payload.get("paper", [])
        has_bitget_paper = any("bitget" in c and "paper" in c for c in paper) or any(
            c == "paper_trade" for c in paper
        )
        return ProbeResult(
            image=image,
            ok=True,
            bitget_connectors=bitget,
            paper_connectors=paper,
            has_bitget_paper=has_bitget_paper,
        )
    except subprocess.CalledProcessError as exc:
        return ProbeResult(
            image=image,
            ok=False,
            bitget_connectors=[],
            paper_connectors=[],
            has_bitget_paper=False,
            error=exc.output.strip()[-1000:],
        )
    except Exception as exc:  # noqa: BLE001
        return ProbeResult(
            image=image,
            ok=False,
            bitget_connectors=[],
            paper_connectors=[],
            has_bitget_paper=False,
            error=str(exc),
        )


def main() -> None:
    tags = sys.argv[1:] or [
        "version-2.12.0",
        "version-2.13.0",
        "version-2.14.0",
        "version-2.15.0",
        "latest",
    ]
    results: List[ProbeResult] = []
    for tag in tags:
        image = f"hummingbot/hummingbot:{tag}"
        print(f"Probing {image} ...")
        results.append(probe_image(image))

    print("\n=== Probe Summary ===")
    for result in results:
        status = "OK" if result.ok else "ERROR"
        print(f"{result.image:<40} {status:<6} bitget_paper={result.has_bitget_paper}")
        if result.ok:
            print(f"  bitget: {result.bitget_connectors}")
            print(f"  paper : {result.paper_connectors}")
        else:
            print(f"  error : {result.error}")

    print("\n=== JSON ===")
    print(json.dumps([asdict(r) for r in results], indent=2))


if __name__ == "__main__":
    main()
