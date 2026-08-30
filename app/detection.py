from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
import pytesseract
from PIL import Image


@dataclass(frozen=True)
class Detection:
    x: float
    y: float
    width: float
    height: float
    confidence: float
    reason: str

    def as_dict(self) -> dict[str, float | str]:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "confidence": self.confidence,
            "reason": self.reason,
        }


def _clamp_box(x: int, y: int, w: int, h: int, iw: int, ih: int) -> tuple[int, int, int, int]:
    pad = max(4, int(min(iw, ih) * 0.008))
    return max(0, x - pad), max(0, y - pad), min(iw - max(0, x - pad), w + 2 * pad), min(ih - max(0, y - pad), h + 2 * pad)


def _ocr_hint(gray: np.ndarray) -> tuple[tuple[int, int, int, int] | None, float]:
    try:
        data = pytesseract.image_to_data(gray, config="--psm 11", output_type=pytesseract.Output.DICT)
    except (pytesseract.TesseractError, FileNotFoundError):
        return None, 0.0
    terms = {"to", "from", "post", "expresspost", "tracking", "ship", "delivery", "parcel"}
    hits: list[tuple[int, int, int, int]] = []
    for i, raw in enumerate(data.get("text", [])):
        token = "".join(ch for ch in raw.lower() if ch.isalnum())
        if token in terms or any(term in token for term in ("tracking", "expresspost", "delivery")):
            hits.append((data["left"][i], data["top"][i], data["width"][i], data["height"][i]))
    if not hits:
        return None, 0.0
    x1 = min(x for x, _, _, _ in hits)
    y1 = min(y for _, y, _, _ in hits)
    x2 = max(x + w for x, _, w, _ in hits)
    y2 = max(y + h for _, y, _, h in hits)
    return (x1, y1, x2 - x1, y2 - y1), min(1.0, len(hits) / 4)


def detect_label(image: Image.Image) -> Detection:
    """Find the most label-like rectangular region and return normalized coordinates."""
    rgb = np.asarray(image.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    ih, iw = gray.shape
    scale = min(1.0, 1800 / max(iw, ih))
    work = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else gray
    wh, ww = work.shape

    edges = cv2.Canny(work, 45, 140)
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15)), iterations=2)
    contours, _ = cv2.findContours(closed, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    ocr_box, ocr_strength = _ocr_hint(work)
    candidates: list[tuple[float, tuple[int, int, int, int], str]] = []

    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area_ratio = (w * h) / (ww * wh)
        if not 0.08 <= area_ratio <= 0.72 or w < ww * 0.2 or h < wh * 0.25:
            continue
        aspect = w / h
        if not 0.45 <= aspect <= 1.35:
            continue
        roi_edges = edges[y : y + h, x : x + w]
        edge_density = float(np.count_nonzero(roi_edges)) / max(1, w * h)
        rectangularity = (w * h) / max(1.0, cv2.contourArea(contour))
        rectangularity_score = max(0.0, 1.0 - abs(rectangularity - 1.0))
        border = min(x, y, ww - (x + w), wh - (y + h)) / max(1, min(ww, wh))
        score = area_ratio * 1.8 + min(edge_density * 8, 0.45) + rectangularity_score * 0.15 + min(border, 0.08)
        reason = "document geometry and barcode-like detail"
        if ocr_box:
            ox, oy, ow, oh = ocr_box
            overlap_x = max(0, min(x + w, ox + ow) - max(x, ox))
            overlap_y = max(0, min(y + h, oy + oh) - max(y, oy))
            if overlap_x * overlap_y > 0:
                score += 0.25 * ocr_strength
                reason = "label wording, border, and barcode-like detail"
        candidates.append((score, (x, y, w, h), reason))

    if candidates:
        score, (x, y, w, h), reason = max(candidates, key=lambda item: item[0])
        x, y, w, h = _clamp_box(x, y, w, h, ww, wh)
        confidence = min(0.96, max(0.45, score))
    else:
        # Safe fallback: prefer the denser half of the page, but make uncertainty explicit.
        halves = [(0, 0, ww // 2, wh), (ww // 2, 0, ww - ww // 2, wh)] if ww >= wh else [(0, 0, ww, wh // 2), (0, wh // 2, ww, wh - wh // 2)]
        x, y, w, h = max(halves, key=lambda b: float(np.std(work[b[1] : b[1] + b[3], b[0] : b[0] + b[2]])))
        confidence, reason = 0.2, "best visual region; please adjust"

    return Detection(x / ww, y / wh, w / ww, h / wh, confidence, reason)

