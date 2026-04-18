"""Tests fuer Welle 6: Skeleton-Loader, Optimistic Updates, Virtualisierung."""

from __future__ import annotations

import os
from pathlib import Path

os.environ["DOCARO_AUTH_REQUIRED"] = "0"
os.environ["DOCARO_ALLOW_SELF_REGISTER"] = "0"
os.environ["DOCARO_CSRF_STRICT"] = "0"
os.environ["DOCARO_DESKTOP_MODE"] = "1"


REPO = Path(__file__).resolve().parents[1]


def test_index_template_has_skeleton_classes():
    html = (REPO / "app" / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'class="stats-panel is-loading"' in html
    assert "skeleton-text" in html
    assert "skeleton-block" in html


def test_index_template_has_optimistic_helpers():
    html = (REPO / "app" / "templates" / "index.html").read_text(encoding="utf-8")
    assert "applyOptimistic" in html
    assert "function statusPillFor" in html
    # window.location.reload darf nicht mehr in den Bulk-Status/Doctype-Pfaden stehen.
    # Heuristik: kein reload() mehr im Welle-3-Bulk-Block.
    assert html.count("window.location.reload()") == 0


def test_style_has_welle6_block():
    css = (REPO / "app" / "static" / "style.css").read_text(encoding="utf-8")
    assert "Welle 6: Performance" in css
    assert "@keyframes docaroSkeletonPulse" in css
    assert "content-visibility: auto" in css
    assert "contain-intrinsic-size" in css


def test_style_print_block_overrides_virtualisation():
    css = (REPO / "app" / "static" / "style.css").read_text(encoding="utf-8")
    # Im Print-Block muss content-visibility: visible erzwungen werden.
    assert "content-visibility: visible !important" in css
