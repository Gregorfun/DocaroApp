from __future__ import annotations

from PIL import Image

import core.extractor as extractor


def test_upscale_for_ocr_enlarges_small_scan_renderings():
    image = Image.new("RGB", (640, 480), color="white")

    upscaled = extractor._upscale_for_ocr(image)

    assert upscaled.size[0] > image.size[0]
    assert upscaled.size[1] > image.size[1]


def test_ocr_single_image_tries_more_robust_variants_when_default_is_weak(monkeypatch):
    image = Image.new("RGB", (900, 700), color="white")
    calls: list[tuple[str, bool]] = []

    def fake_ocr_image(img, rotation, config="", timeout=None, use_paddle=False, aggressive_preprocess=False):
        calls.append((config, aggressive_preprocess))
        responses = {
            ("", False): "abc",
            ("", True): "schwach",
            ("--psm 6", False): "lieferschein lieferschein lieferdatum belegnummer 2026 2026 2026 2026",
            ("--psm 6", True): "",
            ("--psm 11", False): "",
            ("--psm 11", True): "",
        }
        return responses.get((config, aggressive_preprocess), "")

    monkeypatch.setattr(extractor, "_ocr_image", fake_ocr_image)

    result = extractor._ocr_single_image(image)

    assert result["text"].startswith("lieferschein")
    assert result["ocr_variant"] == "psm6"
    assert ("--psm 6", False) in calls


def test_ocr_single_image_keeps_default_when_variants_do_not_help(monkeypatch):
    image = Image.new("RGB", (1200, 900), color="white")

    def fake_ocr_image(img, rotation, config="", timeout=None, use_paddle=False, aggressive_preprocess=False):
        responses = {
            ("", False): "lieferschein lieferdatum 2026 belegnummer 123456",
            ("", True): "lieferschein 2026",
            ("--psm 6", False): "lieferschein",
            ("--psm 6", True): "",
            ("--psm 11", False): "",
            ("--psm 11", True): "",
        }
        return responses.get((config, aggressive_preprocess), "")

    monkeypatch.setattr(extractor, "_ocr_image", fake_ocr_image)

    result = extractor._ocr_single_image(image)

    assert result["ocr_variant"] == "default"