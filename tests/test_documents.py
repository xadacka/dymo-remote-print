from pathlib import Path

import pymupdf
from PIL import Image

from app.documents import DocumentStore, UnsupportedDocument


def test_text_document_becomes_page(tmp_path: Path):
    store = DocumentStore(tmp_path)
    doc_id, pages = store.create("note.txt", b"Hello from Label Local")
    assert len(doc_id) == 32
    assert len(pages) == 1
    assert Image.open(pages[0]).size == (1240, 1754)


def test_rejects_unknown_format(tmp_path: Path):
    store = DocumentStore(tmp_path)
    try:
        store.create("payload.exe", b"nope")
    except UnsupportedDocument:
        pass
    else:
        raise AssertionError("unsupported input was accepted")


def test_pdf_becomes_png_page(tmp_path: Path):
    pdf = pymupdf.open()
    page = pdf.new_page(width=842, height=595)
    page.insert_text((50, 80), "Shipping label")
    store = DocumentStore(tmp_path)
    _, pages = store.create("label.pdf", pdf.tobytes())
    assert len(pages) == 1
    assert Image.open(pages[0]).size == (1684, 1190)
