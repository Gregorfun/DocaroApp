"""
Gemeinsame Konstanten für Docaro.
"""

import re

# Datums-Regex-Patterns
DATE_REGEX_PATTERNS = {
    "iso": re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
    "ymd_slash": re.compile(r"\b(\d{4})/(\d{2})/(\d{2})\b"),
    "dmy_dot": re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b"),
    "dmy_dash": re.compile(r"\b(\d{1,2})-(\d{1,2})-(\d{4})\b"),
    "dmy_slash": re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"),
    "dmy_dot_short": re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{2})\b"),
    "dmy_dash_short": re.compile(r"\b(\d{1,2})-(\d{1,2})-(\d{2})\b"),
    "dmy_slash_short": re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2})\b"),
    "month_name": re.compile(r"\b(\d{1,2})[.\s]+([A-Za-z]+)[.\s]+(\d{4})\b", flags=re.IGNORECASE),
    "dmy_month_dash": re.compile(r"\b(\d{1,2})-([A-Za-z]{3})-(\d{4})\b", flags=re.IGNORECASE),
}
# Aliase für lieferantenspezifische Zugriffe – zeigen auf dieselben Objekte
DATE_REGEX_PATTERNS["vergoelst"] = DATE_REGEX_PATTERNS["dmy_dot_short"]
DATE_REGEX_PATTERNS["tadano"] = DATE_REGEX_PATTERNS["dmy_month_dash"]

# Label-Patterns für Datumserkennung
LABEL_PATTERNS = [
    (
        "lieferdatum",
        re.compile(
            r"\b(lieferscheindatum|lieferdatum|liefertermin|tag der lieferung|tag d[\w.]*ief|lieferschein[\s-]?termin)\b",
            re.IGNORECASE,
        ),
    ),
    ("belegdatum", re.compile(r"\b(beleg[-\s]?datum|beleg[-\s]?d[\w.]*|datum[-\s]?beleg)\b", re.IGNORECASE)),
    (
        "rechnungsdatum",
        re.compile(r"\b(rechn\.?-?\s*dat\.?|rechnungsdatum|rechnung[s-]?dat|rechn\s*d[\w.]*)\b", re.IGNORECASE),
    ),
    (
        "druckdatum",
        re.compile(
            r"\b(druckdatum(?:\s*[/\-]?\s*zeit)?|druckdatum/-zeit|druck[-\s]?dat|druck[-\s]?d[\w.]*)\b", re.IGNORECASE
        ),
    ),
    ("ausgang_wm", re.compile(r"\b(warenausgang|ausgang[\s-]?dat|warenausgang[\s-]?dat)\b", re.IGNORECASE)),
]

# Prioritäten für Labels
LABEL_PRIORITY = {
    "lieferdatum": 1,
    "ausgang_wm": 1,  # WM-spezifisches "Warenausgang" hat gleiche Priorität
    "belegdatum": 2,
    "rechnungsdatum": 3,
    "druckdatum": 4,
    "generic": 99,
}

# Datum-Labels für Suche
DATE_LABELS = ["datum", "date", "termin", "tag"]
