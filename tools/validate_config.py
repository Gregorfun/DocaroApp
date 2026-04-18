"""
Simple runtime configuration validation for Docaro.

Usage:
    python tools/validate_config.py
    python tools/validate_config.py --strict
"""

import argparse
from config import Config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true", help="Exit with error if config invalid")
    args = parser.parse_args()

    errors = Config.validate_runtime_configuration()

    if not errors:
        print("✔ Config validation passed")
        return 0

    print("❌ Config validation errors:")
    for err in errors:
        print(f" - {err}")

    return 1 if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
