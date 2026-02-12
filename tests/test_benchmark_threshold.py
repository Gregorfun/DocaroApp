from __future__ import annotations

import json
from pathlib import Path

from tools.check_benchmark_threshold import main


def test_benchmark_threshold_pass(tmp_path: Path, monkeypatch) -> None:
    payload = {
        "benchmarks": [
            {"name": "x", "stats": {"mean": 0.00001}},
        ]
    }
    p = tmp_path / "bench.json"
    p.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check", str(p), "0.00005"])
    assert main() == 0


def test_benchmark_threshold_fail(tmp_path: Path, monkeypatch) -> None:
    payload = {
        "benchmarks": [
            {"name": "x", "stats": {"mean": 0.0002}},
        ]
    }
    p = tmp_path / "bench.json"
    p.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["check", str(p), "0.00005"])
    assert main() == 2
