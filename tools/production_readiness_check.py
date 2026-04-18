#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    severity: str
    name: str
    detail: str = ""
    hint: str = ""


_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}
_PLACEHOLDER_VALUES = {
    "change_me",
    "changeme",
    "todo",
    "tbd",
    "example",
    "example.com",
    "admin",
    "password",
    "secret",
    "set_me",
}


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def _merged_env(env_file: Path | None) -> dict[str, str]:
    merged: dict[str, str] = {}
    if env_file is not None:
        merged.update(_parse_env_file(env_file))
    merged.update(os.environ)
    return merged


def _parse_bool(value: str | None, default: bool | None = None) -> bool | None:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return default


def _looks_placeholder(value: str | None) -> bool:
    if value is None:
        return True
    normalized = str(value).strip().lower()
    if not normalized:
        return True
    if normalized in _PLACEHOLDER_VALUES:
        return True
    if normalized.startswith("<") and normalized.endswith(">"):
        return True
    return "change_me" in normalized or "todo" in normalized or "placeholder" in normalized


def _add_bool_expectation(
    checks: list[CheckResult],
    env: dict[str, str],
    name: str,
    expected: bool,
    default: bool | None,
    severity: str,
    detail: str,
    hint: str,
) -> None:
    actual = _parse_bool(env.get(name), default)
    ok = actual is expected
    checks.append(
        CheckResult(
            ok=ok,
            severity=severity,
            name=name,
            detail=f"{detail} (aktuell: {env.get(name, '<default>')})",
            hint="" if ok else hint,
        )
    )


def _add_required_value(
    checks: list[CheckResult],
    env: dict[str, str],
    name: str,
    severity: str,
    detail: str,
    hint: str,
) -> None:
    value = (env.get(name) or "").strip()
    ok = bool(value) and not _looks_placeholder(value)
    checks.append(CheckResult(ok=ok, severity=severity, name=name, detail=detail, hint="" if ok else hint))


def _check_file_exists(path: Path, severity: str, detail: str) -> CheckResult:
    return CheckResult(
        ok=path.exists(),
        severity=severity,
        name=str(path.relative_to(path.parents[1])) if len(path.parents) > 1 else str(path),
        detail=detail,
        hint="Datei fehlt und muss vor Freigabe vorhanden sein." if not path.exists() else "",
    )


def _check_template_markers(path: Path, severity: str, markers: Iterable[str], detail: str, hint: str) -> CheckResult:
    if not path.exists():
        return CheckResult(False, severity, str(path), detail, "Datei fehlt.")
    content = path.read_text(encoding="utf-8").lower()
    found = [marker for marker in markers if marker in content]
    return CheckResult(
        ok=not found,
        severity=severity,
        name=str(path.relative_to(path.parents[1])) if len(path.parents) > 1 else str(path),
        detail=detail if not found else f"{detail} Marker gefunden: {', '.join(found)}",
        hint="" if not found else hint,
    )


def _default_env_file(base_dir: Path) -> Path | None:
    deployed = Path("/etc/docaro/docaro.env")
    if deployed.exists():
        return deployed
    repo_example = base_dir / "deploy" / "docaro.env.example"
    if repo_example.exists():
        return repo_example
    return None


def _build_checks(base_dir: Path, env: dict[str, str]) -> list[CheckResult]:
    checks: list[CheckResult] = []

    _add_bool_expectation(
        checks,
        env,
        "DOCARO_AUTH_REQUIRED",
        expected=True,
        default=True,
        severity="error",
        detail="Login-Pflicht muss aktiv sein",
        hint="Setze DOCARO_AUTH_REQUIRED=1.",
    )
    _add_bool_expectation(
        checks,
        env,
        "DOCARO_ALLOW_SELF_REGISTER",
        expected=False,
        default=False,
        severity="error",
        detail="Selbstregistrierung muss deaktiviert sein",
        hint="Setze DOCARO_ALLOW_SELF_REGISTER=0.",
    )
    _add_bool_expectation(
        checks,
        env,
        "DOCARO_SESSION_COOKIE_SECURE",
        expected=True,
        default=True,
        severity="error",
        detail="Session-Cookies muessen nur ueber HTTPS transportiert werden",
        hint="Setze DOCARO_SESSION_COOKIE_SECURE=1.",
    )
    _add_bool_expectation(
        checks,
        env,
        "DOCARO_METRICS_PUBLIC",
        expected=False,
        default=False,
        severity="error",
        detail="/metrics darf nicht oeffentlich freigegeben sein",
        hint="Setze DOCARO_METRICS_PUBLIC=0.",
    )
    _add_bool_expectation(
        checks,
        env,
        "DOCARO_CSRF_STRICT",
        expected=True,
        default=False,
        severity="error",
        detail="CSRF-Strict-Mode muss aktiv sein",
        hint="Setze DOCARO_CSRF_STRICT=1.",
    )

    _add_required_value(
        checks,
        env,
        "DOCARO_RATE_LIMIT_LOGIN",
        severity="error",
        detail="Login-Rate-Limit muss gesetzt sein",
        hint="Setze z. B. DOCARO_RATE_LIMIT_LOGIN=10/5m.",
    )
    _add_required_value(
        checks,
        env,
        "DOCARO_RATE_LIMIT_UPLOAD",
        severity="error",
        detail="Upload-Rate-Limit muss gesetzt sein",
        hint="Setze z. B. DOCARO_RATE_LIMIT_UPLOAD=30/5m.",
    )

    _add_required_value(
        checks,
        env,
        "DOCARO_METRICS_TOKEN",
        severity="warning",
        detail="Metrics-Token sollte fuer Prometheus/Grafana-Scraping gesetzt sein",
        hint="Setze DOCARO_METRICS_TOKEN auf ein langes Zufallsgeheimnis.",
    )
    _add_required_value(
        checks,
        env,
        "DOCARO_GRAFANA_ADMIN_PASSWORD",
        severity="warning",
        detail="Grafana-Admin-Passwort sollte gesetzt sein, wenn der Monitoring-Stack genutzt wird",
        hint="Setze DOCARO_GRAFANA_ADMIN_PASSWORD auf ein individuelles Secret.",
    )

    _add_bool_expectation(
        checks,
        env,
        "DOCARO_RQ_DASHBOARD_ENABLED",
        expected=False,
        default=False,
        severity="warning",
        detail="RQ-Dashboard sollte standardmaessig deaktiviert bleiben",
        hint="Setze DOCARO_RQ_DASHBOARD_ENABLED=0, falls das Dashboard nicht aktiv benoetigt wird.",
    )

    if (env.get("DOCARO_SEED_PASSWORD") or "").strip():
        _add_required_value(
            checks,
            env,
            "DOCARO_SEED_PASSWORD",
            severity="error",
            detail="Seed-Passwort darf kein Platzhalter sein",
            hint="Verwende ein individuelles Passwort oder entferne die Variable nach dem initialen Seed.",
        )

    _add_required_value(
        checks,
        env,
        "DOCARO_RELEASE",
        severity="warning",
        detail="Release-Kennung sollte fuer Monitoring und Incident-Analyse gesetzt sein",
        hint="Setze DOCARO_RELEASE=z. B. docaro-<git-sha>.",
    )
    _add_required_value(
        checks,
        env,
        "DOCARO_SENTRY_DSN",
        severity="warning",
        detail="Sentry ist fuer Produktion empfohlen",
        hint="Setze DOCARO_SENTRY_DSN und DOCARO_SENTRY_ENABLED=1, falls externes Error-Tracking genutzt wird.",
    )

    legal_files = [
        base_dir / "LICENSE",
        base_dir / "EULA.md",
        base_dir / "PRIVACY.md",
        base_dir / "DPA_TEMPLATE.md",
        base_dir / "THIRD_PARTY_NOTICES.md",
        base_dir / "PRODUCTION_CHECKLIST.md",
        base_dir / "OPERATIONS_CONTACTS_TEMPLATE.md",
    ]
    for path in legal_files:
        checks.append(_check_file_exists(path, "error", "Pflichtdokument fuer produktiven Betrieb/Vermarktung"))

    checks.append(
        _check_template_markers(
            base_dir / "EULA.md",
            "warning",
            markers=["vorlage", "rechtlich geprueft", "lizenzmodell angepasst"],
            detail="EULA scheint noch nicht auf einen echten Vertrag umgestellt",
            hint="EULA vor Verkaufsstart juristisch finalisieren.",
        )
    )
    checks.append(
        _check_template_markers(
            base_dir / "PRIVACY.md",
            "warning",
            markers=["ersetzt keine juristische pruefung", "offene punkte vor verkaufsstart"],
            detail="Datenschutzdokument enthaelt noch offene/verbleibende Punkte",
            hint="Datenschutzdokument vor Go-Live finalisieren.",
        )
    )
    checks.append(
        _check_template_markers(
            base_dir / "DPA_TEMPLATE.md",
            "warning",
            markers=["vorlage", "muss vor verwendung", "geprueft und angepasst"],
            detail="AVV/DPA ist noch eine Vorlage",
            hint="AVV/DPA kundenspezifisch und juristisch finalisieren.",
        )
    )
    checks.append(
        _check_template_markers(
            base_dir / "THIRD_PARTY_NOTICES.md",
            "warning",
            markers=["vor auslieferung", "zu validieren"],
            detail="Third-Party-Notices wirken noch nicht build-validiert",
            hint="Notices gegen finalen Build und ausgelieferte Pakete abgleichen.",
        )
    )
    checks.append(
        _check_template_markers(
            base_dir / "OPERATIONS_CONTACTS_TEMPLATE.md",
            "warning",
            markers=["platzhalter", "eintragen", "template"],
            detail="Betriebs- und Eskalationskontakte sind noch nicht final eingetragen",
            hint="Konkrete Support-, Incident- und Datenschutzkontakte eintragen.",
        )
    )

    return checks


def _emit_text(checks: list[CheckResult], env_file: Path | None) -> None:
    print("Docaro Produktions-Gate")
    print(f"ENV-Datei: {env_file if env_file is not None else 'keine'}")
    print("")
    for check in checks:
        state = "OK" if check.ok else check.severity.upper()
        print(f"[{state}] {check.name}: {check.detail}")
        if check.hint and not check.ok:
            print(f"  -> {check.hint}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prueft technische Produktionsreife-Konfigurationen fuer Docaro.")
    parser.add_argument("--env-file", type=Path, default=None, help="Pfad zur zu pruefenden .env-Datei")
    parser.add_argument("--json", action="store_true", help="Ergebnis als JSON ausgeben")
    parser.add_argument(
        "--fail-on-warnings",
        action="store_true",
        help="Warnungen ebenfalls als Fehler behandeln",
    )
    args = parser.parse_args(argv)

    base_dir = Path(__file__).resolve().parents[1]
    env_file = args.env_file or _default_env_file(base_dir)
    env = _merged_env(env_file)
    checks = _build_checks(base_dir, env)

    error_count = sum(1 for check in checks if not check.ok and check.severity == "error")
    warning_count = sum(1 for check in checks if not check.ok and check.severity == "warning")
    ok = error_count == 0 and (warning_count == 0 if args.fail_on_warnings else True)

    payload = {
        "ok": ok,
        "env_file": str(env_file) if env_file is not None else "",
        "errors": error_count,
        "warnings": warning_count,
        "checks": [asdict(check) for check in checks],
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=True))
    else:
        _emit_text(checks, env_file)
        print("")
        print(f"Fehler: {error_count}, Warnungen: {warning_count}")

    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())