from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

import pytest

os.environ["DOCARO_AUTH_REQUIRED"] = "0"
os.environ["DOCARO_ALLOW_SELF_REGISTER"] = "0"
os.environ["DOCARO_CSRF_STRICT"] = "0"

fitz = pytest.importorskip("fitz")
Image = pytest.importorskip("PIL.Image")
ImageDraw = pytest.importorskip("PIL.ImageDraw")

import app.app as app_module
import pdf_toolkit_routes as toolkit_routes


def _make_text_pdf(page_texts: list[str]) -> bytes:
    doc = fitz.open()
    for index, text in enumerate(page_texts, start=1):
        page = doc.new_page()
        page.insert_text((72, 72), f"{index}: {text}", fontsize=22)
    data = doc.tobytes()
    doc.close()
    return data


def _make_scanned_pdf(text: str, noise: bool = False) -> bytes:
    if noise:
        image = Image.effect_noise((1800, 2400), 60).convert("RGB")
    else:
        image = Image.new("RGB", (1800, 2400), "white")
    draw = ImageDraw.Draw(image)
    for idx in range(8):
        draw.text((120, 160 + idx * 220), f"{text} {idx + 1}", fill="black")

    image_buffer = io.BytesIO()
    image.save(image_buffer, format="PNG")

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=image_buffer.getvalue())
    data = doc.tobytes()
    doc.close()
    return data


def _make_ocr_ready_scanned_pdf(text: str) -> bytes:
    source = fitz.open()
    page = source.new_page(width=595, height=842)
    lines = [text, "RECHNUNG 12345", "DOCARO OCR TEST"]
    for idx, line in enumerate(lines):
        page.insert_text((50, 120 + idx * 120), line, fontsize=42)

    pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)

    scanned = fitz.open()
    scanned_page = scanned.new_page(width=595, height=842)
    scanned_page.insert_image(scanned_page.rect, pixmap=pix)
    data = scanned.tobytes()

    scanned.close()
    source.close()
    return data


def _page_count(pdf_bytes: bytes) -> int:
    with fitz.open("pdf", pdf_bytes) as doc:
        return doc.page_count


def _extract_text(pdf_bytes: bytes) -> str:
    with fitz.open("pdf", pdf_bytes) as doc:
        return "\n".join(page.get_text("text") for page in doc)


def _csrf_headers(client) -> dict[str, str]:
    response = client.get("/pdf-toolkit/")
    assert response.status_code == 200
    with client.session_transaction() as session_state:
        token = session_state.get("csrf_token")
    assert token
    return {"X-CSRF-Token": token}


@pytest.fixture
def client(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(toolkit_routes, "_tmp_dir", lambda: tmp_path)
    toolkit_routes._result_store.clear()
    clear_cache = getattr(toolkit_routes._installed_ocr_languages, "cache_clear", None)
    if clear_cache:
        clear_cache()
    yield app_module.app.test_client()
    toolkit_routes._result_store.clear()
    clear_cache = getattr(toolkit_routes._installed_ocr_languages, "cache_clear", None)
    if clear_cache:
        clear_cache()


def test_merge_route_merges_files_and_downloads_pdf(client):
    headers = _csrf_headers(client)
    response = client.post(
        "/pdf-toolkit/merge",
        data={
            "files": [
                (io.BytesIO(_make_text_pdf(["Alpha"])), "alpha.pdf"),
                (io.BytesIO(_make_text_pdf(["Beta"])), "beta.pdf"),
            ]
        },
        headers=headers,
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    payload = response.get_json()
    download = client.get(f"/pdf-toolkit/download/{payload['token']}")

    assert download.status_code == 200
    assert _page_count(download.data) == 2
    text = _extract_text(download.data)
    assert "Alpha" in text
    assert "Beta" in text


def test_split_route_pages_mode_creates_zip_per_page(client):
    headers = _csrf_headers(client)
    response = client.post(
        "/pdf-toolkit/split",
        data={
            "file": (io.BytesIO(_make_text_pdf(["Seite A", "Seite B", "Seite C"])), "mehrseitig.pdf"),
            "mode": "pages",
            "ranges": "",
        },
        headers=headers,
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["parts"] == 3

    download = client.get(f"/pdf-toolkit/download/{payload['token']}")
    assert download.status_code == 200

    with zipfile.ZipFile(io.BytesIO(download.data)) as archive:
        names = archive.namelist()
        assert names == ["seite_0001.pdf", "seite_0002.pdf", "seite_0003.pdf"]
        for name in names:
            assert _page_count(archive.read(name)) == 1


def test_split_route_ranges_mode_creates_requested_ranges(client):
    headers = _csrf_headers(client)
    response = client.post(
        "/pdf-toolkit/split",
        data={
            "file": (io.BytesIO(_make_text_pdf(["Eins", "Zwei", "Drei", "Vier"])), "ranges.pdf"),
            "mode": "ranges",
            "ranges": "1-2, 4",
        },
        headers=headers,
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["parts"] == 2

    download = client.get(f"/pdf-toolkit/download/{payload['token']}")
    assert download.status_code == 200

    with zipfile.ZipFile(io.BytesIO(download.data)) as archive:
        assert archive.namelist() == ["bereich_01_s1-2.pdf", "bereich_02_s4-4.pdf"]
        assert _page_count(archive.read("bereich_01_s1-2.pdf")) == 2
        assert _page_count(archive.read("bereich_02_s4-4.pdf")) == 1


def test_split_route_rejects_invalid_ranges(client):
    headers = _csrf_headers(client)
    response = client.post(
        "/pdf-toolkit/split",
        data={
            "file": (io.BytesIO(_make_text_pdf(["Nur eine Seite"])), "invalid.pdf"),
            "mode": "ranges",
            "ranges": "3-1",
        },
        headers=headers,
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert "Ungültige Seitenbereiche" in response.get_json()["error"]


def test_compress_route_supports_all_quality_levels(client):
    source_pdf = _make_scanned_pdf("Komprimierungstest", noise=True)
    results: dict[str, dict[str, int | str]] = {}
    headers = _csrf_headers(client)

    for quality in ("high", "medium", "low"):
        response = client.post(
            "/pdf-toolkit/compress",
            data={
                "file": (io.BytesIO(source_pdf), f"{quality}.pdf"),
                "quality": quality,
            },
            headers=headers,
            content_type="multipart/form-data",
        )

        assert response.status_code == 200
        payload = response.get_json()
        download = client.get(f"/pdf-toolkit/download/{payload['token']}")

        assert download.status_code == 200
        assert _page_count(download.data) == 1
        assert payload["filename"].endswith("_komprimiert.pdf")
        results[quality] = payload

    assert int(results["low"]["compressed_kb"]) <= int(results["high"]["compressed_kb"])
    assert int(results["medium"]["compressed_kb"]) <= int(results["high"]["compressed_kb"])


def test_toolkit_page_only_shows_installed_ocr_languages(client, monkeypatch):
    monkeypatch.setattr(toolkit_routes, "_installed_ocr_languages", lambda: frozenset({"deu", "eng", "osd"}))

    response = client.get("/pdf-toolkit/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Deutsch + Englisch" in html
    assert "Nur Deutsch" in html
    assert "Nur Englisch" in html
    assert 'option value="fra"' not in html
    assert 'option value="spa"' not in html
    assert 'option value="ita"' not in html


def test_ocr_route_rejects_unavailable_language(client, monkeypatch):
    monkeypatch.setattr(toolkit_routes, "_installed_ocr_languages", lambda: frozenset({"deu", "eng", "osd"}))
    headers = _csrf_headers(client)

    response = client.post(
        "/pdf-toolkit/ocr",
        data={
            "file": (io.BytesIO(_make_ocr_ready_scanned_pdf("OCR Test")), "ocr.pdf"),
            "lang": "fra",
        },
        headers=headers,
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert "nicht installiert" in response.get_json()["error"]


def test_ocr_route_works_for_all_installed_ui_languages(client):
    available = [option["value"] for option in toolkit_routes._available_ocr_options()]
    assert available

    scanned_pdf = _make_ocr_ready_scanned_pdf("OCR Funktionstest")
    seen_text_output = False
    headers = _csrf_headers(client)

    for lang in available:
        response = client.post(
            "/pdf-toolkit/ocr",
            data={
                "file": (io.BytesIO(scanned_pdf), f"ocr_{lang}.pdf"),
                "lang": lang,
            },
            headers=headers,
            content_type="multipart/form-data",
        )

        assert response.status_code == 200, (lang, response.get_json())
        payload = response.get_json()
        download = client.get(f"/pdf-toolkit/download/{payload['token']}")

        assert download.status_code == 200
        assert _page_count(download.data) == 1
        if _extract_text(download.data).strip():
            seen_text_output = True

    assert seen_text_output