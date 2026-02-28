from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from urllib import error, request


ALLOWED_DOC_TYPES = {
    "RECHNUNG",
    "LIEFERSCHEIN",
    "UEBERNAHMESCHEIN",
    "ÜBERNAHMESCHEIN",
    "KOMMISSIONIERLISTE",
    "PRUEFBERICHT",
    "PRÜFBERICHT",
    "SONSTIGES",
}


@dataclass
class LLMAssistSuggestion:
    supplier: str = ""
    supplier_confidence: float = 0.0
    doc_type: str = ""
    doc_type_confidence: float = 0.0
    date_iso: str = ""
    date_confidence: float = 0.0
    doc_number: str = ""
    doc_number_confidence: float = 0.0
    raw_json: str = ""
    error: str = ""


def _clamp_conf(value: object) -> float:
    try:
        conf = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(conf, 1.0))


def _sanitize_supplier(value: object) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^a-zA-Z0-9 ._&\-/äöüÄÖÜß]+", "", text)
    return text[:80].strip()


def _normalize_doc_type(value: object) -> str:
    raw = str(value or "").strip().upper()
    raw = raw.replace("PRUEFBERICHT", "PRÜFBERICHT").replace("UEBERNAHMESCHEIN", "ÜBERNAHMESCHEIN")
    if raw not in {"RECHNUNG", "LIEFERSCHEIN", "ÜBERNAHMESCHEIN", "KOMMISSIONIERLISTE", "PRÜFBERICHT", "SONSTIGES"}:
        return ""
    return raw


def _normalize_doc_number(value: object) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[^a-zA-Z0-9._\-/]+", "", text)
    return text[:80]


def _normalize_date_iso(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    candidates = [
        ("%Y-%m-%d", raw),
        ("%d.%m.%Y", raw),
        ("%d-%m-%Y", raw),
        ("%d/%m/%Y", raw),
    ]
    for fmt, val in candidates:
        try:
            return datetime.strptime(val, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def _extract_json_object(text: str) -> Optional[str]:
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw, flags=re.IGNORECASE).strip()
        raw = re.sub(r"```$", "", raw).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < 0 or end <= start:
        return None
    return raw[start : end + 1]


def parse_llm_suggestion(payload_text: str) -> LLMAssistSuggestion:
    obj_text = _extract_json_object(payload_text or "")
    if not obj_text:
        return LLMAssistSuggestion(error="no_json_object")
    try:
        data = json.loads(obj_text)
    except Exception as exc:
        return LLMAssistSuggestion(error=f"json_decode_failed: {exc}", raw_json=obj_text[:4000])
    if not isinstance(data, dict):
        return LLMAssistSuggestion(error="json_not_object", raw_json=obj_text[:4000])

    return LLMAssistSuggestion(
        supplier=_sanitize_supplier(data.get("supplier")),
        supplier_confidence=_clamp_conf(data.get("supplier_confidence")),
        doc_type=_normalize_doc_type(data.get("doc_type")),
        doc_type_confidence=_clamp_conf(data.get("doc_type_confidence")),
        date_iso=_normalize_date_iso(data.get("date_iso") or data.get("date")),
        date_confidence=_clamp_conf(data.get("date_confidence")),
        doc_number=_normalize_doc_number(data.get("doc_number")),
        doc_number_confidence=_clamp_conf(data.get("doc_number_confidence")),
        raw_json=obj_text[:4000],
        error="",
    )


def build_ollama_prompt(*, text: str, current_supplier: str, current_doc_type: str, current_date: str, current_doc_number: str) -> str:
    snippet = (text or "").strip()
    if len(snippet) > 9000:
        snippet = snippet[:9000]
    return (
        "Du bist ein strikt formatierter Information-Extraction Assistent fuer deutsche Dokumente.\n"
        "Extrahiere nur, wenn mit hoher Sicherheit vorhanden.\n"
        "Antworte NUR als JSON-Objekt mit diesen Feldern:\n"
        "{\n"
        '  "supplier": "string",\n'
        '  "supplier_confidence": 0.0,\n'
        '  "doc_type": "RECHNUNG|LIEFERSCHEIN|UEBERNAHMESCHEIN|KOMMISSIONIERLISTE|PRUEFBERICHT|SONSTIGES",\n'
        '  "doc_type_confidence": 0.0,\n'
        '  "date_iso": "YYYY-MM-DD",\n'
        '  "date_confidence": 0.0,\n'
        '  "doc_number": "string",\n'
        '  "doc_number_confidence": 0.0\n'
        "}\n"
        "Wenn ein Feld nicht sicher ist: leere Zeichenkette und Confidence 0.\n"
        "Aktueller Stand (kann falsch sein):\n"
        f"- supplier: {current_supplier}\n"
        f"- doc_type: {current_doc_type}\n"
        f"- date_iso: {current_date}\n"
        f"- doc_number: {current_doc_number}\n\n"
        "Dokumenttext:\n"
        f"{snippet}"
    )


def query_ollama_assist(
    *,
    endpoint: str,
    model: str,
    timeout_seconds: float,
    prompt: str,
) -> LLMAssistSuggestion:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
    }
    req = request.Request(
        endpoint.rstrip("/") + "/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=max(1.0, timeout_seconds)) as resp:
            response_text = resp.read().decode("utf-8", errors="replace")
    except error.URLError as exc:
        return LLMAssistSuggestion(error=f"ollama_unreachable: {exc}")
    except Exception as exc:
        return LLMAssistSuggestion(error=f"ollama_request_failed: {exc}")

    try:
        raw = json.loads(response_text)
    except Exception as exc:
        return LLMAssistSuggestion(error=f"ollama_non_json: {exc}")
    if not isinstance(raw, dict):
        return LLMAssistSuggestion(error="ollama_invalid_response")

    answer = str(raw.get("response") or "")
    parsed = parse_llm_suggestion(answer)
    if parsed.error:
        parsed.error = f"ollama_parse_failed: {parsed.error}"
    return parsed
