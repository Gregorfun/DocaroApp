from __future__ import annotations

from pathlib import Path
import shutil

SRC = Path("data/ml/ground_truth.jsonl")
DST = Path("artifacts/ml/ground_truth_snapshot.jsonl")


def main() -> int:
    DST.parent.mkdir(parents=True, exist_ok=True)
    if not SRC.exists():
        DST.write_text("", encoding="utf-8")
        print(f"No source found ({SRC}), wrote empty snapshot to {DST}")
        return 0
    shutil.copy2(SRC, DST)
    print(f"Snapshot exported: {SRC} -> {DST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
