from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps

LABEL_SIZE = (1200, 1800)  # 4 by 6 inches at the DYMO 4XL's 300 DPI.


def list_printers() -> list[str]:
    try:
        result = subprocess.run(["lpstat", "-p"], capture_output=True, text=True, timeout=5, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    return [line.split()[1] for line in result.stdout.splitlines() if line.startswith("printer ") and len(line.split()) > 1]


def prepare_label(source: Path, crop: dict[str, float], rotation: int = 0, contrast: float = 1.0) -> Image.Image:
    image = Image.open(source).convert("RGB")
    if rotation % 360:
        image = image.rotate(-rotation, expand=True, fillcolor="white")
    width, height = image.size
    x1 = max(0, min(width - 1, round(crop["x"] * width)))
    y1 = max(0, min(height - 1, round(crop["y"] * height)))
    x2 = max(x1 + 1, min(width, round((crop["x"] + crop["width"]) * width)))
    y2 = max(y1 + 1, min(height, round((crop["y"] + crop["height"]) * height)))
    image = image.crop((x1, y1, x2, y2))
    image = ImageEnhance.Contrast(ImageOps.grayscale(image)).enhance(max(0.5, min(2.5, contrast)))
    image.thumbnail(LABEL_SIZE, Image.Resampling.LANCZOS)
    canvas = Image.new("L", LABEL_SIZE, "white")
    canvas.paste(image, ((LABEL_SIZE[0] - image.width) // 2, (LABEL_SIZE[1] - image.height) // 2))
    return canvas


def print_label(image: Image.Image, output: Path, printer: str | None, copies: int) -> str:
    image.save(output, dpi=(300, 300), optimize=True)
    command = ["lp"]
    selected = printer or os.getenv("PRINTER_NAME")
    if selected:
        command += ["-d", selected]
    command += ["-n", str(max(1, min(10, copies))), "-o", "media=Custom.4x6in", "-o", "fit-to-page", str(output)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
    except FileNotFoundError as exc:
        raise RuntimeError("CUPS printing tools are not installed") from exc
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "The print service rejected the job")
    return result.stdout.strip() or "Print job submitted"
