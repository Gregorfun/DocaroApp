"""Welle 12: Naming-Templates fuer Output-Dateinamen.

Whitelist-basierter Template-Renderer mit Tokens:
  {supplier}, {date}, {date_iso}, {doc_number}, {doctype}, {year}, {month}, {day}

Beispiele:
  "{supplier}_{date}_{doc_number}"          -> "ACME_31-12-2026_R12345"
  "{date_iso}__{doctype}__{supplier}"       -> "2026-12-31__RECHNUNG__ACME"
  "{year}/{month}/{supplier}_{date}"        -> "2026/12/ACME_31-12-2026"

Subdir-Trennzeichen "/" wird in "_" umgewandelt (sicherer Dateiname),
da die eigentliche Ablage-Logik nicht angefasst wird.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Callable

#: Erlaubte Tokens; alles andere wird leer gerendert.
ALLOWED_TOKENS: frozenset[str] = frozenset({
    "supplier",
    "date",
    "date_iso",
    "doc_number",
    "doctype",
    "year",
    "month",
    "day",
})

#: Default-Template entspricht klassischem build_new_filename().
DEFAULT_TEMPLATE = "{supplier}_{date}_{doc_number}"

#: Maximale Template-Laenge (Schutz gegen Speicherausreisser).
MAX_TEMPLATE_LEN = 200

_TOKEN_RE = re.compile(r"\{([a-z_]+)\}")
# Sicheres Replacement fuer Datei-/Pfadtrenner und Steuerzeichen.
_UNSAFE_RE = re.compile(r"[<>:\"|?*\x00-\x1f]+")

# Welle 13A: Optionaler Provider, den build_new_filename befragt, wenn kein
# Template-Argument explizit uebergeben wird. Wird typischerweise von der
# App-Schicht beim Start registriert (liest user_prefs des aktiven Profils).
_ACTIVE_TEMPLATE_PROVIDER: "Callable[[], str] | None" = None


def set_active_template_provider(provider: "Callable[[], str] | None") -> None:
    """Registriert einen Callable, der das aktuell aktive Template liefert."""
    global _ACTIVE_TEMPLATE_PROVIDER
    _ACTIVE_TEMPLATE_PROVIDER = provider


def get_active_template() -> str:
    """Liefert das aktive Template (leer, wenn keiner gesetzt oder ungueltig)."""
    if _ACTIVE_TEMPLATE_PROVIDER is None:
        return ""
    try:
        value = str(_ACTIVE_TEMPLATE_PROVIDER() or "").strip()
    except Exception:
        return ""
    return value if is_valid_template(value) else ""


def is_valid_template(template: str) -> bool:
    """Prueft ob das Template ausschliesslich erlaubte Tokens nutzt."""
    if not isinstance(template, str):
        return False
    if not template.strip():
        return False
    if len(template) > MAX_TEMPLATE_LEN:
        return False
    for token in _TOKEN_RE.findall(template):
        if token not in ALLOWED_TOKENS:
            return False
    return True


def _sanitize(value: str) -> str:
    cleaned = _UNSAFE_RE.sub("", str(value or ""))
    cleaned = cleaned.replace("/", "_").replace("\\", "_")
    cleaned = re.sub(r"_+", "_", cleaned).strip("_-. ")
    return cleaned or ""


def build_context(
    supplier: str = "",
    date_obj: datetime | None = None,
    date_format: str = "%d-%m-%Y",
    doc_number: str = "",
    doctype: str = "",
) -> dict[str, str]:
    """Erstellt den Token-Kontext fuer render_template()."""
    if date_obj is not None:
        date_str = date_obj.strftime(date_format)
        date_iso = date_obj.strftime("%Y-%m-%d")
        year = date_obj.strftime("%Y")
        month = date_obj.strftime("%m")
        day = date_obj.strftime("%d")
    else:
        date_str = ""
        date_iso = ""
        year = ""
        month = ""
        day = ""
    return {
        "supplier": _sanitize(supplier),
        "date": date_str,
        "date_iso": date_iso,
        "doc_number": _sanitize(doc_number),
        "doctype": _sanitize(doctype),
        "year": year,
        "month": month,
        "day": day,
    }


def render_template(template: str, ctx: dict[str, Any]) -> str:
    """Rendert das Template; unbekannte Tokens werden leer ersetzt."""
    if not is_valid_template(template):
        template = DEFAULT_TEMPLATE

    def _sub(match: "re.Match[str]") -> str:
        token = match.group(1)
        if token not in ALLOWED_TOKENS:
            return ""
        return str(ctx.get(token) or "")

    rendered = _TOKEN_RE.sub(_sub, template)
    rendered = _sanitize(rendered)
    # Doppelte Trenner beseitigen, leere Segmente kollabieren.
    rendered = re.sub(r"[._-]{2,}", "_", rendered)
    rendered = rendered.strip("_-. ") or "Unbenannt"
    return rendered


def preview(template: str) -> str:
    """Liefert eine Vorschau mit Beispieldaten fuer das Settings-UI."""
    sample_ctx = build_context(
        supplier="ACME GmbH",
        date_obj=datetime(2026, 12, 31),
        date_format="%d-%m-%Y",
        doc_number="R12345",
        doctype="RECHNUNG",
    )
    base = render_template(template, sample_ctx)
    return f"{base}.pdf"
