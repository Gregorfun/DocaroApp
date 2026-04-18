from __future__ import annotations

import argparse
import io
import json
import re
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from http.cookiejar import CookieJar
from pathlib import Path
from urllib import request as urlrequest

import fitz


def _wait_for_port(host: str, port: int, timeout: float) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError(f"Server {host}:{port} wurde nicht rechtzeitig erreichbar")


def _make_text_pdf(page_texts: list[str]) -> bytes:
    doc = fitz.open()
    for index, text in enumerate(page_texts, start=1):
        page = doc.new_page()
        page.insert_text((72, 72), f"{index}: {text}", fontsize=22)
    data = doc.tobytes()
    doc.close()
    return data


def _make_scanned_pdf(text: str) -> bytes:
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


def _extract_text(pdf_bytes: bytes) -> str:
    with fitz.open("pdf", pdf_bytes) as doc:
        return "\n".join(page.get_text("text") for page in doc)


def _page_count(pdf_bytes: bytes) -> int:
    with fitz.open("pdf", pdf_bytes) as doc:
        return doc.page_count


def _multipart_payload(fields: dict[str, str], files: list[tuple[str, str, bytes, str]]) -> tuple[str, bytes]:
    boundary = "----DocaroBoundary" + uuid.uuid4().hex
    parts: list[bytes] = []
    for key, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        parts.append(value.encode())
        parts.append(b"\r\n")
    for field_name, filename, content, mime in files:
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode()
        )
        parts.append(f"Content-Type: {mime}\r\n\r\n".encode())
        parts.append(content)
        parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return boundary, b"".join(parts)


class ToolkitClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.jar = CookieJar()
        self.opener = urlrequest.build_opener(urlrequest.HTTPCookieProcessor(self.jar))
        self.csrf_token = self._fetch_csrf_token()

    def _fetch_csrf_token(self) -> str:
        response = self.opener.open(f"{self.base_url}/pdf-toolkit/", timeout=30)
        html = response.read().decode("utf-8", errors="replace")
        match = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
        if not match:
            raise RuntimeError("CSRF-Token im Toolkit nicht gefunden")
        return match.group(1)

    def post_toolkit(self, path: str, fields: dict[str, str], files: list[tuple[str, str, bytes, str]]) -> dict[str, object]:
        boundary, payload = _multipart_payload(fields, files)
        request = urlrequest.Request(
            f"{self.base_url}{path}",
            data=payload,
            headers={
                "X-CSRF-Token": self.csrf_token,
                "Accept": "application/json",
                "Origin": self.base_url,
                "Referer": f"{self.base_url}/pdf-toolkit/",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        with self.opener.open(request, timeout=180) as response:
            body = response.read().decode("utf-8", errors="replace")
            if response.status != 200:
                raise RuntimeError(f"{path} antwortete mit {response.status}: {body}")
            return json.loads(body)

    def download(self, token: str) -> bytes:
        response = self.opener.open(f"{self.base_url}/pdf-toolkit/download/{token}", timeout=60)
        if response.status != 200:
            raise RuntimeError(f"Download fuer Token {token} antwortete mit {response.status}")
        return response.read()


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_smoke_test(base_url: str) -> None:
    client = ToolkitClient(base_url)

    merge_payload = client.post_toolkit(
        "/pdf-toolkit/merge",
        fields={},
        files=[
            ("files", "alpha.pdf", _make_text_pdf(["Alpha"]), "application/pdf"),
            ("files", "beta.pdf", _make_text_pdf(["Beta"]), "application/pdf"),
        ],
    )
    merged = client.download(str(merge_payload["token"]))
    merged_text = _extract_text(merged)
    _assert(_page_count(merged) == 2, "Merge sollte 2 Seiten erzeugen")
    _assert("Alpha" in merged_text and "Beta" in merged_text, "Merge-Inhalt fehlt")

    split_pages_payload = client.post_toolkit(
        "/pdf-toolkit/split",
        fields={"mode": "pages", "ranges": ""},
        files=[("file", "split_pages.pdf", _make_text_pdf(["A", "B", "C"]), "application/pdf")],
    )
    split_pages_zip = client.download(str(split_pages_payload["token"]))
    with zipfile.ZipFile(io.BytesIO(split_pages_zip)) as archive:
        _assert(archive.namelist() == ["seite_0001.pdf", "seite_0002.pdf", "seite_0003.pdf"], "Split-Pages Namen unerwartet")

    split_ranges_payload = client.post_toolkit(
        "/pdf-toolkit/split",
        fields={"mode": "ranges", "ranges": "1-2,4"},
        files=[("file", "split_ranges.pdf", _make_text_pdf(["Eins", "Zwei", "Drei", "Vier"]), "application/pdf")],
    )
    split_ranges_zip = client.download(str(split_ranges_payload["token"]))
    with zipfile.ZipFile(io.BytesIO(split_ranges_zip)) as archive:
        _assert(archive.namelist() == ["bereich_01_s1-2.pdf", "bereich_02_s4-4.pdf"], "Split-Ranges Namen unerwartet")

    source_pdf = _make_scanned_pdf("Komprimierungstest")
    for quality in ("high", "medium", "low"):
        compress_payload = client.post_toolkit(
            "/pdf-toolkit/compress",
            fields={"quality": quality},
            files=[("file", f"{quality}.pdf", source_pdf, "application/pdf")],
        )
        compressed = client.download(str(compress_payload["token"]))
        _assert(_page_count(compressed) == 1, f"Compress {quality} sollte 1 Seite behalten")

    ocr_payload = client.post_toolkit(
        "/pdf-toolkit/ocr",
        fields={"lang": "deu+eng"},
        files=[("file", "desktop_ocr.pdf", _make_scanned_pdf("Desktop EXE OCR 12345"), "application/pdf")],
    )
    ocr_pdf = client.download(str(ocr_payload["token"]))
    ocr_text = _extract_text(ocr_pdf)
    _assert("Desktop EXE OCR 12345" in ocr_text, "OCR-Text fehlt")
    _assert("RECHNUNG 12345" in ocr_text, "OCR-Text enthaelt Rechnung nicht")


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-Test fuer die gebaute DocaroApp Desktop-EXE")
    parser.add_argument("--exe", type=Path, default=Path("dist/DocaroApp/DocaroApp.exe"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--startup-timeout", type=float, default=40.0)
    args = parser.parse_args()

    if not args.exe.exists():
        raise SystemExit(f"EXE nicht gefunden: {args.exe}")

    process = subprocess.Popen([str(args.exe)])
    try:
        _wait_for_port(args.host, args.port, args.startup_timeout)
        run_smoke_test(f"http://{args.host}:{args.port}")
        print("Desktop-EXE-Smoke-Test erfolgreich")
        return 0
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except Exception:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())