import io
import asyncio
from pathlib import Path

import httpx
import pymupdf

import app.main as main
from app.documents import DocumentStore


def request(app, method: str, url: str, **kwargs):
    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, url, **kwargs)
    return asyncio.run(run())


def test_upload_detect_and_preview(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(main, "store", DocumentStore(tmp_path / "documents"))
    monkeypatch.setattr(main, "DATA", tmp_path)
    uploaded = request(main.app, "POST", "/api/documents", files={"file": ("label.txt", io.BytesIO(b"TO\nA CUSTOMER\nTRACKING 123"), "text/plain")})
    assert uploaded.status_code == 200
    doc = uploaded.json()

    page = request(main.app, "GET", f"/api/documents/{doc['document_id']}/pages/0.png")
    assert page.status_code == 200
    assert page.headers["content-type"] == "image/png"

    detection = request(main.app, "POST", f"/api/documents/{doc['document_id']}/pages/0/detect")
    assert detection.status_code == 200
    assert 0 < detection.json()["width"] <= 1

    preview = request(main.app, "POST", "/api/print", json={
        "document_id": doc["document_id"], "page": 0,
        "crop": {"x": 0, "y": 0, "width": 1, "height": 1},
        "preview_only": True,
    })
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"


def test_rejects_oversized_crop(tmp_path: Path, monkeypatch):
    store = DocumentStore(tmp_path / "documents")
    doc_id, _ = store.create("label.txt", b"label")
    monkeypatch.setattr(main, "store", store)
    response = request(main.app, "POST", "/api/print", json={
        "document_id": doc_id, "page": 0,
        "crop": {"x": 0.8, "y": 0, "width": 0.4, "height": 1},
        "preview_only": True,
    })
    assert response.status_code == 422


def test_shortcut_share_returns_editor_url(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(main, "store", DocumentStore(tmp_path / "documents"))
    monkeypatch.setattr(main, "DATA", tmp_path)
    printed = []
    monkeypatch.setattr(main, "print_label", lambda image, output, printer, copies: printed.append((image.size, copies)) or "queued")
    response = request(main.app, "POST", "/api/share", files={
        "file": ("vinted-label.txt", b"TO CUSTOMER\nTRACKING 123", "text/plain")
    })
    assert response.status_code == 200
    data = response.json()
    assert data["pages"] == 1
    assert data["filename"] == "vinted-label.txt"
    assert f"document={data['document_id']}" in data["open_url"]
    assert data["status"] == "queued"
    assert data["message"] == "queued"
    assert printed == [((1200, 1800), 1)]

    details = request(main.app, "GET", f"/api/documents/{data['document_id']}")
    assert details.json()["pages"] == 1


def test_shortcut_share_accepts_raw_body(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(main, "store", DocumentStore(tmp_path / "documents"))
    monkeypatch.setattr(main, "DATA", tmp_path)
    monkeypatch.setattr(main, "print_label", lambda *args, **kwargs: "queued")
    response = request(main.app, "POST", "/api/share?filename=note.txt", content=b"A label")
    assert response.status_code == 200
    assert response.json()["filename"] == "note.txt"


def test_shortcut_share_accepts_ios_attachment_without_filename(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(main, "store", DocumentStore(tmp_path / "documents"))
    monkeypatch.setattr(main, "DATA", tmp_path)
    monkeypatch.setattr(main, "print_label", lambda *args, **kwargs: "queued")
    pdf = pymupdf.open()
    pdf.new_page().insert_text((40, 80), "TO CUSTOMER TRACKING 123")
    response = request(main.app, "POST", "/api/share", files={
        "Shortcut Input": ("", pdf.tobytes(), "application/pdf")
    })
    assert response.status_code == 200
    assert response.json()["filename"].endswith(".pdf")


def test_shortcut_share_identifies_raw_pdf_without_filename(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(main, "store", DocumentStore(tmp_path / "documents"))
    monkeypatch.setattr(main, "DATA", tmp_path)
    monkeypatch.setattr(main, "print_label", lambda *args, **kwargs: "queued")
    pdf = pymupdf.open()
    pdf.new_page().insert_text((40, 80), "SHIPPING LABEL")
    response = request(
        main.app, "POST", "/api/share", content=pdf.tobytes(),
        headers={"Content-Type": "application/pdf"},
    )
    assert response.status_code == 200
    assert response.json()["filename"] == "shortcut-upload.pdf"


def test_shortcut_share_rejects_urlencoded_file_text(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(main, "store", DocumentStore(tmp_path / "documents"))
    monkeypatch.setattr(main, "print_label", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not print")))
    response = request(
        main.app, "POST", "/api/share", content=b"file=%EF%BF%BDPDF",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 400
    assert "not a downloadable HTTPS link" in response.json()["detail"]


def test_shortcut_share_downloads_shared_pdf_url(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(main, "store", DocumentStore(tmp_path / "documents"))
    monkeypatch.setattr(main, "DATA", tmp_path)
    monkeypatch.setattr(main, "print_label", lambda *args, **kwargs: "queued")
    pdf = pymupdf.open()
    pdf.new_page().insert_text((40, 80), "SHIPPING LABEL")
    pdf_bytes = pdf.tobytes()
    monkeypatch.setattr(main, "download_shared_url", lambda url: ("vinted.pdf", pdf_bytes, "application/pdf"))
    async def run_inline(function, *args):
        return function(*args)
    monkeypatch.setattr(main, "run_in_threadpool", run_inline)
    response = request(main.app, "POST", "/api/share?source_url=https%3A%2F%2Fexample.com%2Fvinted.pdf")
    assert response.status_code == 200
    assert response.json()["filename"] == "vinted.pdf"


def test_shortcut_share_rejects_html_without_pdf_link(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(main, "store", DocumentStore(tmp_path / "documents"))
    monkeypatch.setattr(main, "print_label", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not print")))
    response = request(main.app, "POST", "/api/share", content=b"<html><body>Vinted page</body></html>", headers={"Content-Type": "text/html"})
    assert response.status_code == 400
    assert "did not contain a direct PDF link" in response.json()["detail"]


def test_find_shared_url_accepts_signed_s3_pdf_without_pdf_path():
    url = (
        "https://example-bucket.s3.eu-central-1.amazonaws.com/object-token"
        "?response-content-type=application%2Fpdf&response-content-disposition=inline%3B%20filename%3D%22label.pdf%22"
    )
    assert main.find_shared_url(f"<html><a href=\"{url}\">Download</a></html>".encode()) == url


def test_shortcut_share_downloads_urlencoded_link(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(main, "store", DocumentStore(tmp_path / "documents"))
    monkeypatch.setattr(main, "DATA", tmp_path)
    monkeypatch.setattr(main, "print_label", lambda *args, **kwargs: "queued")
    pdf = pymupdf.open()
    pdf.new_page().insert_text((40, 80), "SHIPPING LABEL")
    pdf_bytes = pdf.tobytes()
    monkeypatch.setattr(main, "download_shared_url", lambda url: ("vinted.pdf", pdf_bytes, "application/pdf"))
    async def run_inline(function, *args):
        return function(*args)
    monkeypatch.setattr(main, "run_in_threadpool", run_inline)
    response = request(main.app, "POST", "/api/share", data={"file": "https://s3.example.test/label.pdf?X-Amz-Signature=abc"})
    assert response.status_code == 200
    assert response.json()["filename"] == "vinted.pdf"
