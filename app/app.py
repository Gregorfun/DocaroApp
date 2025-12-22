from __future__ import annotations

from io import BytesIO
from datetime import datetime
from pathlib import Path
from typing import Optional
import sys
import zipfile

import os

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.utils import secure_filename

APP_DIR = Path(__file__).resolve().parent
BASE_DIR = APP_DIR.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.extractor import (
    load_suppliers_db,
    normalize_text,
    process_folder,
    get_unique_path,
    save_suppliers_db,
)
DATA_DIR = BASE_DIR / "data"
INBOX_DIR = DATA_DIR / "eingang"
OUT_DIR = DATA_DIR / "fertig"
TMP_DIR = DATA_DIR / "tmp"

ALLOWED_EXTENSIONS = {".pdf"}
ALLOWED_DATE_FORMATS = {"%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%Y%m%d"}

app = Flask(__name__)
app.secret_key = os.getenv("DOCARO_SECRET_KEY", "docaro-dev-key")


def _allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


@app.get("/")
def index():
    files = sorted([p.name for p in OUT_DIR.glob("*.pdf")]) if OUT_DIR.exists() else []
    reset_done = request.args.get("reset") == "1"
    results = session.get("last_results")
    return render_template("index.html", results=results, files=files, reset_done=reset_done)


@app.post("/upload")
def upload():
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    uploaded = request.files.getlist("files")
    if not uploaded:
        return render_template("index.html", results=[], files=_list_finished())

    date_fmt = request.form.get("date_fmt", "").strip()
    if date_fmt not in ALLOWED_DATE_FORMATS:
        date_fmt = "%Y-%m-%d"

    for storage in uploaded:
        if not storage or not storage.filename:
            continue
        safe_name = secure_filename(storage.filename)
        if not safe_name or not _allowed_file(safe_name):
            continue
        target_path = get_unique_path(INBOX_DIR, safe_name)
        storage.save(target_path)

    results = process_folder(INBOX_DIR, OUT_DIR, date_format=date_fmt)
    session["last_results"] = results
    return render_template("index.html", results=results, files=_list_finished(), reset_done=False)


@app.get("/upload")
def upload_overview():
    return redirect(url_for("index"))


def _list_finished():
    return sorted([p.name for p in OUT_DIR.glob("*.pdf")]) if OUT_DIR.exists() else []


def _clear_pdfs(dir_path: Path) -> None:
    if not dir_path.exists():
        return
    for pdf in dir_path.glob("*.pdf"):
        try:
            pdf.unlink()
        except OSError:
            continue


@app.post("/reset")
def reset_downloads():
    for folder in (OUT_DIR, INBOX_DIR, TMP_DIR):
        _clear_pdfs(folder)
    return redirect(url_for("index", reset="1"))


@app.post("/confirm_supplier")
def confirm_supplier():
    supplier_name = request.form.get("supplier_name", "").strip()
    filename_raw = request.form.get("filename", "").strip()
    filename = _safe_pdf_name(filename_raw) if filename_raw else ""
    return_to = request.form.get("return_to", "")

    def _redirect_after_confirm():
        if return_to == "viewer" and filename:
            return redirect(url_for("view_pdf", filename=filename))
        return redirect(url_for("index"))

    if len(supplier_name) < 2:
        flash("Lieferant ungueltig.")
        return _redirect_after_confirm()

    use_alias = request.form.get("use_alias") == "1" or request.form.get("alias_from_ocr") in ("1", "on", "true")
    alias = ""
    if use_alias:
        alias = request.form.get("supplier_guess_line", "").strip()

    data = load_suppliers_db()
    suppliers = data.get("suppliers", [])
    target = None
    target_key = normalize_text(supplier_name)
    for entry in suppliers:
        name = str(entry.get("name", "")).strip()
        if normalize_text(name) == target_key:
            target = entry
            break

    if target is None:
        target = {
            "name": supplier_name,
            "aliases": [],
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        suppliers.append(target)

    if alias:
        aliases = target.setdefault("aliases", [])
        if all(normalize_text(a) != normalize_text(alias) for a in aliases):
            aliases.append(alias)

    data["suppliers"] = suppliers
    save_suppliers_db(data)
    if filename:
        _update_last_results(filename, supplier_name)
    flash("Lieferant gespeichert.")
    return _redirect_after_confirm()


def _update_last_results(filename: str, supplier_name: str) -> None:
    if not filename:
        return
    results = session.get("last_results")
    if not results:
        return
    for item in results:
        if item.get("out_name") == filename:
            item["supplier"] = supplier_name
            item["supplier_source"] = "db"
            item["supplier_confidence"] = "0.90"
            break
    session["last_results"] = results


def _safe_pdf_name(filename: str) -> str:
    safe_name = secure_filename(filename)
    if not safe_name or safe_name != filename:
        return ""
    if not _allowed_file(safe_name):
        return ""
    return safe_name


def _find_pdf_path(filename: str) -> Optional[Path]:
    for folder in (INBOX_DIR, OUT_DIR):
        candidate = folder / filename
        if candidate.exists():
            return candidate
    return None


def _result_for_filename(filename: str):
    results = session.get("last_results") or []
    for item in results:
        if item.get("out_name") == filename:
            return item
    return None


def _is_review_needed(item: dict) -> bool:
    supplier = (item.get("supplier") or "").strip()
    if not supplier or supplier == "Unbekannt":
        return True
    if item.get("supplier_source") == "heuristic":
        return True
    try:
        confidence = float(item.get("supplier_confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0
    return confidence < 0.85


def _review_list():
    results = session.get("last_results") or []
    return [item for item in results if _is_review_needed(item)]


@app.get("/view/<path:filename>")
def view_pdf(filename: str):
    safe_name = _safe_pdf_name(filename)
    if not safe_name:
        abort(404)
    pdf_path = _find_pdf_path(safe_name)
    if not pdf_path:
        abort(404)
    result = _result_for_filename(safe_name) or {}
    supplier = result.get("supplier") or "Unbekannt"
    supplier_guess_line = result.get("supplier_guess_line") or ""
    supplier_source = result.get("supplier_source") or ""
    supplier_confidence = result.get("supplier_confidence") or ""
    review_items = _review_list()
    review_total = len(review_items)
    review_index = 0
    if review_total:
        for idx, item in enumerate(review_items, start=1):
            if item.get("out_name") == safe_name:
                review_index = idx
                break
    title = f"Docaro | {supplier} | {safe_name}"
    return render_template(
        "view_pdf.html",
        title=title,
        filename=safe_name,
        supplier=supplier,
        supplier_guess_line=supplier_guess_line,
        supplier_source=supplier_source,
        supplier_confidence=supplier_confidence,
        review_index=review_index,
        review_total=review_total,
    )


@app.get("/pdf/<path:filename>")
def pdf_file(filename: str):
    safe_name = _safe_pdf_name(filename)
    if not safe_name:
        abort(404)
    pdf_path = _find_pdf_path(safe_name)
    if not pdf_path:
        abort(404)
    return send_file(pdf_path, mimetype="application/pdf", as_attachment=False)


@app.get("/raw/<path:filename>")
def raw_pdf(filename: str):
    safe_name = _safe_pdf_name(filename)
    if not safe_name:
        return "PDF nicht gefunden.", 404
    pdf_path = _find_pdf_path(safe_name)
    if not pdf_path:
        return "PDF nicht gefunden.", 404
    return send_file(pdf_path, mimetype="application/pdf", as_attachment=False)


@app.get("/review/next")
def review_next():
    current_raw = request.args.get("current", "").strip()
    current = _safe_pdf_name(current_raw) if current_raw else ""
    review_items = _review_list()
    if not review_items:
        flash("Keine weiteren unbekannten PDFs - fertig!")
        return redirect(url_for("upload_overview"))

    filenames = [item.get("out_name") for item in review_items]
    next_name = filenames[0]
    if current and current in filenames:
        idx = filenames.index(current)
        next_name = filenames[(idx + 1) % len(filenames)]
    if not next_name:
        flash("Keine weiteren unbekannten PDFs - fertig!")
        return redirect(url_for("upload_overview"))
    return redirect(url_for("view_pdf", filename=next_name))


def _find_supplier_entry(suppliers, name: str):
    target_key = normalize_text(name)
    for entry in suppliers:
        entry_name = str(entry.get("name", "")).strip()
        if normalize_text(entry_name) == target_key:
            return entry
    return None


def _merge_aliases(target, aliases):
    existing = target.setdefault("aliases", [])
    for alias in aliases:
        if alias and all(normalize_text(a) != normalize_text(alias) for a in existing):
            existing.append(alias)


@app.get("/suppliers")
def suppliers():
    data = load_suppliers_db()
    suppliers_list = sorted(data.get("suppliers", []), key=lambda item: item.get("name", "").lower())
    return render_template("suppliers.html", suppliers=suppliers_list)


@app.post("/suppliers/rename")
def suppliers_rename():
    old_name = request.form.get("old_name", "").strip()
    new_name = request.form.get("new_name", "").strip()
    if len(old_name) < 2 or len(new_name) < 2:
        flash("Lieferantenname ungueltig.")
        return redirect(url_for("suppliers"))

    data = load_suppliers_db()
    suppliers_list = data.get("suppliers", [])
    target = _find_supplier_entry(suppliers_list, old_name)
    if not target:
        flash("Lieferant nicht gefunden.")
        return redirect(url_for("suppliers"))

    existing = _find_supplier_entry(suppliers_list, new_name)
    if existing and existing is not target:
        _merge_aliases(existing, target.get("aliases", []))
        suppliers_list.remove(target)
    else:
        target["name"] = new_name

    data["suppliers"] = suppliers_list
    save_suppliers_db(data)
    flash("Lieferant aktualisiert.")
    return redirect(url_for("suppliers"))


@app.post("/suppliers/alias/add")
def suppliers_alias_add():
    supplier_name = request.form.get("supplier_name", "").strip()
    alias = request.form.get("alias", "").strip()
    if len(supplier_name) < 2 or len(alias) < 2:
        flash("Alias ungueltig.")
        return redirect(url_for("suppliers"))

    data = load_suppliers_db()
    suppliers_list = data.get("suppliers", [])
    target = _find_supplier_entry(suppliers_list, supplier_name)
    if not target:
        flash("Lieferant nicht gefunden.")
        return redirect(url_for("suppliers"))

    _merge_aliases(target, [alias])
    data["suppliers"] = suppliers_list
    save_suppliers_db(data)
    flash("Alias gespeichert.")
    return redirect(url_for("suppliers"))


@app.post("/suppliers/alias/remove")
def suppliers_alias_remove():
    supplier_name = request.form.get("supplier_name", "").strip()
    alias = request.form.get("alias", "").strip()
    if len(supplier_name) < 2 or not alias:
        flash("Alias ungueltig.")
        return redirect(url_for("suppliers"))

    data = load_suppliers_db()
    suppliers_list = data.get("suppliers", [])
    target = _find_supplier_entry(suppliers_list, supplier_name)
    if not target:
        flash("Lieferant nicht gefunden.")
        return redirect(url_for("suppliers"))

    aliases = target.get("aliases", [])
    target["aliases"] = [a for a in aliases if normalize_text(a) != normalize_text(alias)]
    data["suppliers"] = suppliers_list
    save_suppliers_db(data)
    flash("Alias entfernt.")
    return redirect(url_for("suppliers"))


@app.post("/suppliers/delete")
def suppliers_delete():
    supplier_name = request.form.get("supplier_name", "").strip()
    if len(supplier_name) < 2:
        flash("Lieferant ungueltig.")
        return redirect(url_for("suppliers"))

    data = load_suppliers_db()
    suppliers_list = data.get("suppliers", [])
    target = _find_supplier_entry(suppliers_list, supplier_name)
    if not target:
        flash("Lieferant nicht gefunden.")
        return redirect(url_for("suppliers"))

    suppliers_list.remove(target)
    data["suppliers"] = suppliers_list
    save_suppliers_db(data)
    flash("Lieferant geloescht.")
    return redirect(url_for("suppliers"))


@app.get("/download/<path:filename>")
def download(filename: str):
    safe_name = secure_filename(filename)
    if not safe_name or safe_name != filename:
        abort(404)
    if not _allowed_file(safe_name):
        abort(404)
    if not (OUT_DIR / safe_name).exists():
        abort(404)
    return send_from_directory(OUT_DIR, safe_name, as_attachment=True)


@app.get("/download_all.zip")
def download_all():
    if not OUT_DIR.exists():
        abort(404)
    pdfs = sorted(OUT_DIR.glob("*.pdf"))
    if not pdfs:
        abort(404)

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for pdf in pdfs:
            zf.write(pdf, arcname=pdf.name)
    buffer.seek(0)

    return send_file(
        buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name="docaro_fertig.zip",
    )


if __name__ == "__main__":
    app.run(debug=False)
