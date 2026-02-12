from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "benchmark.json")
    threshold = float(sys.argv[2] if len(sys.argv) > 2 else "0.00005")

    if not path.exists():
        print(f"Benchmark file missing: {path}")
        return 1

    payload = json.loads(path.read_text(encoding="utf-8"))
    benches = payload.get("benchmarks") or []
    if not benches:
        print("No benchmarks found")
        return 1

    failed = []
    for bench in benches:
        name = str(bench.get("name") or "unknown")
        stats = bench.get("stats") or {}
        mean = float(stats.get("mean") or 0.0)
        if mean > threshold:
            failed.append((name, mean))

    if failed:
        for name, mean in failed:
            print(f"FAIL {name}: mean={mean:.8f}s > threshold={threshold:.8f}s")
        return 2

    print(f"All benchmark means <= {threshold:.8f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
