from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def normalize_supplier_key(value: str) -> str:
    raw = (value or "").strip().lower()
    return re.sub(r"[^a-z0-9]+", "", raw)


def load_supplier_profiles(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, value in payload.items():
        if not isinstance(value, dict):
            continue
        norm = normalize_supplier_key(str(key))
        if not norm:
            continue
        out[norm] = value
    return out


def extract_doc_number_by_patterns(item: dict[str, Any], patterns: list[str]) -> str:
    if not patterns:
        return ""
    haystack_parts = [
        str(item.get("ocr_text") or ""),
        str(item.get("textlayer_text") or ""),
        str(item.get("supplier_guess_line") or ""),
        str(item.get("doc_type_evidence") or ""),
        str(item.get("date_evidence") or ""),
        str(item.get("original") or ""),
        str(item.get("out_name") or ""),
    ]
    haystack = "\n".join(part for part in haystack_parts if part).strip()
    if not haystack:
        return ""
    for raw in patterns:
        try:
            m = re.search(raw, haystack, flags=re.IGNORECASE)
        except re.error:
            continue
        if not m:
            continue
        candidate = (m.group(1) if m.groups() else m.group(0)).strip()
        candidate = re.sub(r"\s+", " ", candidate)
        candidate = re.sub(r"[^a-zA-Z0-9 ._\-/]+", "", candidate).strip(" ._-")
        if candidate:
            return candidate[:60]
    return ""


def apply_supplier_profile(item: dict[str, Any], profiles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    supplier = str(item.get("supplier") or "")
    key = normalize_supplier_key(supplier)
    profile = profiles.get(key)
    if not profile:
        return item

    item["supplier_profile"] = profile.get("name") or supplier

    if (item.get("doc_type") or "").strip() in ("", "SONSTIGES"):
        forced_doc_type = (profile.get("doc_type_force") or "").strip().upper()
        if forced_doc_type:
            item["doc_type"] = forced_doc_type
            item["doc_type_confidence"] = str(profile.get("doc_type_confidence", "0.85"))
            item["doc_type_evidence"] = "supplier_profile"

    if not (item.get("doc_number") or "").strip():
        patterns = profile.get("doc_number_patterns") or []
        if isinstance(patterns, list):
            extracted = extract_doc_number_by_patterns(item, [str(p) for p in patterns if p])
            if extracted:
                item["doc_number"] = extracted
                item["doc_number_source"] = "supplier_profile"
                item["doc_number_confidence"] = "medium"

    min_conf = profile.get("review_confidence_min")
    try:
        min_conf_val = float(min_conf)
    except (TypeError, ValueError):
        min_conf_val = None
    if min_conf_val is not None:
        item["supplier_profile_review_conf_min"] = min_conf_val

    route_tag = (profile.get("route_tag") or "").strip().lower()
    if route_tag:
        item["profile_route"] = route_tag

    return item


def derive_processing_route(item: dict[str, Any]) -> str:
    profile_route = (item.get("profile_route") or "").strip().lower()
    if profile_route:
        return profile_route
    doc_type = (item.get("doc_type") or "").strip().upper()
    mapping = {
        "RECHNUNG": "finance",
        "LIEFERSCHEIN": "logistics",
        "ÜBERNAHMESCHEIN": "warehouse",
        "KOMMISSIONIERLISTE": "warehouse",
        "PRÜFBERICHT": "quality",
        "SONSTIGES": "triage",
    }
    return mapping.get(doc_type, "triage")


def compute_review_priority(item: dict[str, Any]) -> float:
    score = 0.0
    if item.get("parsing_failed"):
        score += 90.0
    if item.get("supplier_missing"):
        score += 35.0
    if item.get("date_missing"):
        score += 30.0
    if item.get("supplier_broken"):
        score += 20.0
    if item.get("doc_type") in ("", "SONSTIGES"):
        score += 10.0

    try:
        conf = float(item.get("supplier_confidence") or 0)
    except (TypeError, ValueError):
        conf = 0.0
    score += max(0.0, (0.95 - conf) * 35.0)

    route = derive_processing_route(item)
    if route in {"finance", "quality"}:
        score += 8.0
    if route == "triage":
        score += 12.0
    return round(score, 2)
