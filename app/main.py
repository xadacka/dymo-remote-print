from __future__ import annotations

import os
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from PIL import Image

from .detection import detect_label
from .documents import ALLOWED, DocumentStore, UnsupportedDocument
from .printing import list_printers, prepare_label, print_label

BASE = Path(__file__).resolve().parent
DATA = Path(os.getenv("DATA_DIR", tempfile.gettempdir())) / "label-local"
store = DocumentStore(DATA / "documents")
app = FastAPI(title="Label Local", docs_url=None, redoc_url=None)


class Crop(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)


class PrintRequest(BaseModel):
    document_id: str
    page: int = Field(ge=0, lt=30)
    crop: Crop
    rotation: int = 0
    contrast: float = Field(default=1.15, ge=0.5, le=2.5)
    copies: int = Field(default=1, ge=1, le=10)
    printer: str | None = None
    preview_only: bool = False


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/printers")
async def printers() -> dict[str, list[str]]:
    return {"printers": list_printers()}


@app.post("/api/documents")
async def upload(file: Annotated[UploadFile, File(...)]) -> dict:
    content = await file.read(25 * 1024 * 1024 + 1)
    return save_document(file.filename or "upload", content)


def save_document(filename: str, content: bytes) -> dict:
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(413, "Files are limited to 25 MB")
    try:
        doc_id, pages = store.create(filename, content)
    except (UnsupportedDocument, ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
    if not pages:
        raise HTTPException(400, "The document contains no pages")
    return {"document_id": doc_id, "filename": filename, "pages": len(pages)}


def shortcut_filename(filename: str | None, content: bytes, media_type: str | None) -> str:
    """Recover a usable filename when iOS sends an empty or temporary name."""
    supplied = Path(filename or "shortcut-upload").name
    if Path(supplied).suffix.lower() in ALLOWED:
        return supplied

    media = (media_type or "").split(";", 1)[0].lower()
    extension = {
        "application/pdf": ".pdf",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/tiff": ".tiff",
        "text/plain": ".txt",
        "text/markdown": ".md",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    }.get(media)

    if content.startswith(b"%PDF"):
        extension = ".pdf"
    elif content.startswith(b"\x89PNG\r\n\x1a\n"):
        extension = ".png"
    elif content.startswith(b"\xff\xd8\xff"):
        extension = ".jpg"
    elif content[:4] in {b"II*\x00", b"MM\x00*"}:
        extension = ".tiff"
    elif content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        extension = ".webp"
    elif content.startswith(b"PK"):
        try:
            with zipfile.ZipFile(BytesIO(content)) as archive:
                if "word/document.xml" in archive.namelist():
                    extension = ".docx"
        except zipfile.BadZipFile:
            pass

    if extension is None:
        try:
            content.decode("utf-8")
            extension = ".txt"
        except UnicodeDecodeError as exc:
            raise HTTPException(400, "Could not identify the shared file type") from exc

    stem = Path(supplied).stem if Path(supplied).suffix else supplied
    return f"{stem or 'shortcut-upload'}{extension}"


def shortcut_form_bytes(value: str) -> bytes:
    """Restore a filename-less multipart value decoded as text by Starlette."""
    utf8 = value.encode("utf-8")
    try:
        latin1 = value.encode("latin-1")
    except UnicodeEncodeError:
        return utf8
    signatures = (b"%PDF", b"\x89PNG", b"\xff\xd8\xff", b"II*\x00", b"MM\x00*", b"RIFF", b"PK")
    if any(latin1.startswith(signature) for signature in signatures) and not any(utf8.startswith(signature) for signature in signatures):
        return latin1
    return utf8


@app.post("/api/share")
async def shortcut_share(request: Request, filename: str | None = None) -> dict:
    """Accept a file from iOS Shortcuts, detect its label, and print it immediately."""
    content_type = request.headers.get("content-type", "")
    media_type: str | None = content_type
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        incoming = form.get("file")
        if incoming is None:
            incoming = next(iter(form.values()), None)
        if incoming is None:
            raise HTTPException(400, "The multipart request did not contain an attached file")
        if hasattr(incoming, "read"):
            content = await incoming.read(25 * 1024 * 1024 + 1)
            filename = getattr(incoming, "filename", None) or filename
            media_type = getattr(incoming, "content_type", None) or media_type
        elif isinstance(incoming, str):
            content = shortcut_form_bytes(incoming)
        elif isinstance(incoming, bytes):
            content = incoming
        else:
            raise HTTPException(400, "The multipart field was not a readable file")
    else:
        content = await request.body()
        filename = request.headers.get("x-filename") or filename
    filename = shortcut_filename(filename, content, media_type)
    document = save_document(filename, content)
    query = urlencode({
        "document": document["document_id"],
        "name": document["filename"],
    })
    document["open_url"] = f"{str(request.base_url).rstrip('/')}/?{query}"
    source = store.page(document["document_id"], 0)
    with Image.open(source) as image:
        detection = detect_label(image)
    crop = detection.as_dict()
    label = prepare_label(source, crop, contrast=1.15)
    output = DATA / f"print-{document['document_id']}-0.png"
    try:
        message = print_label(label, output, printer=None, copies=1)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    document.update({
        "status": "queued",
        "message": message,
        "crop": crop,
    })
    return document


@app.get("/api/documents/{document_id}")
async def document_details(document_id: str) -> dict:
    pages = store.pages(document_id)
    if not pages:
        raise HTTPException(404, "Document not found or expired")
    return {"document_id": document_id, "pages": len(pages)}


@app.get("/api/documents/{document_id}/pages/{page}.png")
async def page_image(document_id: str, page: int) -> Response:
    try:
        path = store.page(document_id, page)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Page not found") from exc
    return Response(path.read_bytes(), media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@app.post("/api/documents/{document_id}/pages/{page}/detect")
async def detect(document_id: str, page: int) -> dict:
    try:
        path = store.page(document_id, page)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Page not found") from exc
    with Image.open(path) as image:
        return detect_label(image).as_dict()


@app.post("/api/print")
async def submit_print(request: PrintRequest):
    try:
        source = store.page(request.document_id, request.page)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Page not found") from exc
    crop = request.crop.model_dump()
    if crop["x"] + crop["width"] > 1.001 or crop["y"] + crop["height"] > 1.001:
        raise HTTPException(422, "Crop extends beyond the page")
    label = prepare_label(source, crop, request.rotation, request.contrast)
    output = DATA / f"print-{request.document_id}-{request.page}.png"
    if request.preview_only:
        label.save(output, dpi=(300, 300), optimize=True)
        return Response(output.read_bytes(), media_type="image/png")
    try:
        message = print_label(label, output, request.printer, request.copies)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"status": "queued", "message": message}


app.mount("/", StaticFiles(directory=BASE / "static", html=True), name="static")
