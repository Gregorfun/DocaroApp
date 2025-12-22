from __future__ import annotations

import argparse
from pathlib import Path

from core.extractor import process_folder

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
DEFAULT_INPUT = DATA_DIR / "eingang"
DEFAULT_OUTPUT = DATA_DIR / "fertig"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Lieferscheine-PDFs per OCR auslesen und umbenennen."
    )
    parser.add_argument(
        "--input",
        "-i",
        type=str,
        default=str(DEFAULT_INPUT),
        help="Ordner mit den eingehenden PDF-Dateien.",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=str(DEFAULT_OUTPUT),
        help="Zielordner fuer umbenannte Dateien.",
    )
    args = parser.parse_args()

    input_dir = Path(args.input)
    output_dir = Path(args.output)

    results = process_folder(input_dir, output_dir)
    print(f"{len(results)} PDF-Datei(en) verarbeitet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
