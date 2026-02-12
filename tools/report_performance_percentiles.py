from __future__ import annotations

import csv
import statistics
from pathlib import Path

RUN_LOG = Path("data/logs/run.csv")


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    values = sorted(values)
    idx = (len(values) - 1) * q
    lo = int(idx)
    hi = min(lo + 1, len(values) - 1)
    frac = idx - lo
    return values[lo] * (1 - frac) + values[hi] * frac


def main() -> int:
    if not RUN_LOG.exists():
        print(f"No run log found: {RUN_LOG}")
        return 1

    metrics: dict[str, list[float]] = {
        "timing_render_ms": [],
        "timing_ocr_ms": [],
        "timing_total_ms": [],
    }

    with RUN_LOG.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            for key in metrics:
                raw = str((row or {}).get(key, "") or "").strip()
                if not raw:
                    continue
                try:
                    metrics[key].append(float(raw))
                except ValueError:
                    continue

    for key, vals in metrics.items():
        if not vals:
            print(f"{key}: no data")
            continue
        print(
            f"{key}: count={len(vals)} mean={statistics.fmean(vals):.1f} "
            f"p50={_percentile(vals, 0.50):.1f} "
            f"p95={_percentile(vals, 0.95):.1f} "
            f"p99={_percentile(vals, 0.99):.1f}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
