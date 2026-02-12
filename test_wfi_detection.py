#!/usr/bin/env python3
"""Test WFI und Ortjohann Detection"""

from core.extractor import (
    detect_supplier_detailed, 
    _normalize_supplier_text,
)

# Test-Text aus WFI Lieferschein
wfi_text = """
Wireless Funk- u. Informationstechnik GmbH
WFI GmbH & Co. KG
Neckarsulmer Str. 47
74196 Neuenstadt
Franz Bracht
Kran-Vermietung GmbH
Bruchfeld 91
47809 Krefeld
"""

# Test-Text aus Ortjohann Lieferschein
ortjohann_text = """
Ortjohann und Kraft Werkzeug- und Maschinenhandel GmbH, Siemensstraße 6
ORTJOHANN + KRAFT
Franz Bracht
Kran-Vermietung GmbH
Bruchfeld 91
47809 Krefeld
"""

print("=" * 60)
print("WFI TEST")
print("=" * 60)
norm_wfi = _normalize_supplier_text(wfi_text)
print(f"Normalized text contains 'wfi': {'wfi' in norm_wfi}")
print(f"Normalized text contains 'wireless': {'wireless' in norm_wfi}")
print(f"Normalized text (first 200 chars): {norm_wfi[:200]}")

supplier, conf, source, guess, cands = detect_supplier_detailed(wfi_text)
print(f"\nDetected supplier: {supplier}")
print(f"Confidence: {conf}")
print(f"Source: {source}")
print(f"Top 5 candidates:")
for i, c in enumerate(cands[:5]):
    print(f"  {i+1}. {c.get('canonical')} ({c.get('confidence')}) - {c.get('source')}")

print("\n" + "=" * 60)
print("ORTJOHANN TEST")
print("=" * 60)
norm_ort = _normalize_supplier_text(ortjohann_text)
print(f"Normalized text contains 'ortjohann': {'ortjohann' in norm_ort}")
print(f"Normalized text (first 200 chars): {norm_ort[:200]}")

supplier, conf, source, guess, cands = detect_supplier_detailed(ortjohann_text)
print(f"\nDetected supplier: {supplier}")
print(f"Confidence: {conf}")
print(f"Source: {source}")
print(f"Top 5 candidates:")
for i, c in enumerate(cands[:5]):
    print(f"  {i+1}. {c.get('canonical')} ({c.get('confidence')}) - {c.get('source')}")
