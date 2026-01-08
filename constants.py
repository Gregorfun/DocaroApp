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
    "vergoelst": re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{2})\b"),
    "tadano": re.compile(r"\b(\d{1,2})-([A-Za-z]{3})-(\d{4})\b", flags=re.IGNORECASE),
}

# Label-Patterns für Datumserkennung
LABEL_PATTERNS = [
    ("lieferdatum", re.compile(r"\b(lieferscheindatum|lieferdatum|liefertermin|tag der lieferung)\b", re.IGNORECASE)),
    ("belegdatum", re.compile(r"\b(beleg[-\s]?datum)\b", re.IGNORECASE)),
    ("rechnungsdatum", re.compile(r"\b(rechn\.?-?\s*dat\.?|rechnungsdatum)\b", re.IGNORECASE)),
    ("druckdatum", re.compile(r"\b(druckdatum(?:\s*[/\-]?\s*zeit)?|druckdatum/-zeit)\b", re.IGNORECASE)),
]

# Prioritäten für Labels
LABEL_PRIORITY = {
    "lieferdatum": 1,
    "belegdatum": 2,
    "rechnungsdatum": 3,
    "druckdatum": 4,
    "generic": 99,
}

# Datum-Labels für Suche
DATE_LABELS = ["datum", "date", "termin", "tag"]