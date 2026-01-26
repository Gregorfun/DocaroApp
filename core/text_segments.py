from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence


_RECIPIENT_KEYWORDS = [
    "versand-/lieferanschrift",
    "versand / lieferanschrift",
    "versandanschrift",
    "empfänger",
    "lieferadresse",
    "warenempfänger",
    "ship to",
    "deliver to",
    "lieferanschrift",
    "delivery address",
    "anlieferadresse",
    "kundenadresse",
    "recipient",
]

_SECTION_STOP_KEYWORDS = [
    # Häufige neue Abschnittsstarts
    "rechnung",
    "invoice",
    "lieferschein",
    "delivery note",
    "übernahmeschein",
    "uebernahmeschein",
    "positions",
    "position",
    "artikel",
    "summe",
    "gesamt",
]


@dataclass(frozen=True)
class SegmentedText:
    header_lines: list[str]
    body_lines: list[str]
    recipient_lines: list[str]


@dataclass(frozen=True)
class SegmentedHBF:
    header_lines: list[str]
    body_lines: list[str]
    footer_lines: list[str]


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _is_blank(line: str) -> bool:
    return not (line or "").strip()


def segment_text(
    text: str,
    *,
    header_max_lines: int = 25,
    recipient_max_lines: int = 15,
) -> SegmentedText:
    """Segmentiert OCR/Text in header/body/recipient.

    Heuristik:
    - header_lines: erste N Zeilen
    - recipient_lines: Block nach einem Recipient-Keyword bis Leerzeile/Abschnittswechsel/max lines
    - body_lines: Rest (ohne recipient_lines und ohne header_lines)

    Hinweis: Recipient-Lines werden auch aus dem Header herausgenommen,
    damit Supplier/DocType-Erkennung dort nicht triggert.
    """

    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    if not lines:
        return SegmentedText([], [], [])

    recipient_idx: set[int] = set()

    for i, line in enumerate(lines):
        low = _norm(line)
        if not low:
            continue
        if any(k in low for k in _RECIPIENT_KEYWORDS):
            # Block startet bei i
            recipient_idx.add(i)
            taken = 0
            j = i + 1
            while j < len(lines) and taken < recipient_max_lines:
                nxt = lines[j]
                low2 = _norm(nxt)
                if _is_blank(nxt):
                    break
                # Stop, wenn ein neuer Abschnitt beginnt
                if any(k in low2 for k in _SECTION_STOP_KEYWORDS):
                    break
                recipient_idx.add(j)
                taken += 1
                j += 1

    header_end = max(0, min(header_max_lines, len(lines)))
    header_idx = set(range(header_end))

    header_lines = [lines[i] for i in range(header_end) if i not in recipient_idx and not _is_blank(lines[i])]
    recipient_lines = [lines[i] for i in range(len(lines)) if i in recipient_idx and not _is_blank(lines[i])]

    body_lines: list[str] = []
    for i in range(header_end, len(lines)):
        if i in recipient_idx:
            continue
        if _is_blank(lines[i]):
            continue
        body_lines.append(lines[i])

    return SegmentedText(header_lines=header_lines, body_lines=body_lines, recipient_lines=recipient_lines)


def segment_header_body_footer(
    text: str,
    *,
    header_lines: int = 35,
    footer_lines: int = 35,
) -> SegmentedHBF:
    """Segmentiert Text in header/body/footer (für DocType)."""

    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    if not lines:
        return SegmentedHBF([], [], [])

    h = max(0, min(header_lines, len(lines)))
    f = max(0, min(footer_lines, len(lines)))

    header = [ln for ln in lines[:h] if not _is_blank(ln)]
    footer = [ln for ln in lines[-f:] if not _is_blank(ln)] if f > 0 else []
    body = [ln for ln in lines[h : max(h, len(lines) - f)] if not _is_blank(ln)]

    return SegmentedHBF(header_lines=header, body_lines=body, footer_lines=footer)
