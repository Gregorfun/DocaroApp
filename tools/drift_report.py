from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

try:
    from evidently import Report
    from evidently.presets import DataDriftPreset
except Exception:  # pragma: no cover - optional dependency
    Report = None
    DataDriftPreset = None

import pandas as pd

AUDIT_PATH = Path("data/audit.jsonl")
OUT_DIR = Path("artifacts/drift")


def _load_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue
        extractions = entry.get("extractions") or {}
        supplier = str((extractions.get("supplier") or {}).get("value") or "")
        date_val = str((extractions.get("date") or {}).get("value") or "")
        doctype = str((extractions.get("doctype") or {}).get("value") or "")
        ocr_method = str(entry.get("ocr_method") or "")
        processing_time = float(entry.get("processing_time") or 0.0)
        ts = str(entry.get("created_at") or entry.get("reviewed_at") or "")
        rows.append(
            {
                "timestamp": ts,
                "supplier": supplier,
                "doc_type": doctype,
                "doc_date": date_val,
                "ocr_method": ocr_method,
                "processing_time": processing_time,
                "text_len_supplier": len(supplier),
                "text_len_doctype": len(doctype),
            }
        )
    return rows


def _split_reference_current(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df.empty:
        return df, df
    now = datetime.now()
    threshold = now - timedelta(days=7)
    ts = pd.to_datetime(df["timestamp"], errors="coerce")
    current = df[ts >= threshold]
    reference = df[ts < threshold]
    if reference.empty:
        reference = df.iloc[: max(1, len(df) // 2)]
    if current.empty:
        current = df.iloc[max(0, len(df) // 2) :]
    return reference, current


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = _load_rows(AUDIT_PATH)
    if not rows:
        print(f"No audit rows found at {AUDIT_PATH}")
        return 1

    df = pd.DataFrame(rows)
    ref, cur = _split_reference_current(df)

    if Report is None or DataDriftPreset is None:
        summary = {
            "rows_total": int(len(df)),
            "rows_reference": int(len(ref)),
            "rows_current": int(len(cur)),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "note": "evidently not installed; only dataset split summary generated",
        }
        out = OUT_DIR / "drift_summary.json"
        out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"Wrote fallback drift summary to {out}")
        return 0

    report = Report(metrics=[DataDriftPreset()])
    report.run(reference_data=ref, current_data=cur)

    html_out = OUT_DIR / "drift_report.html"
    json_out = OUT_DIR / "drift_report.json"
    report.save_html(str(html_out))
    json_out.write_text(report.json(), encoding="utf-8")

    print(f"Drift report written: {html_out}")
    print(f"Drift report JSON: {json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
