from pathlib import Path

from PIL import Image, ImageDraw

from app.detection import detect_label
from app.printing import LABEL_SIZE, prepare_label


def synthetic_page() -> Image.Image:
    image = Image.new("RGB", (1400, 900), "white")
    draw = ImageDraw.Draw(image)
    draw.multiline_text((60, 80), "INSTRUCTIONS\nPack the parcel carefully\nTake it to the post office", fill="black", spacing=16)
    draw.rectangle((820, 50, 1340, 840), outline="black", width=7)
    draw.text((860, 100), "EXPRESS POST\nFROM\nTO\nDELIVERY", fill="black", spacing=18)
    for x in range(880, 1290, 12):
        draw.rectangle((x, 560, x + (4 if x % 24 else 8), 760), fill="black")
    return image


def test_detects_label_region():
    result = detect_label(synthetic_page())
    assert result.x > 0.45
    assert result.y < 0.15
    assert result.width > 0.25
    assert result.height > 0.65
    assert result.confidence >= 0.45


def test_prepared_label_is_dymo_resolution(tmp_path: Path):
    source = tmp_path / "page.png"
    synthetic_page().save(source)
    label = prepare_label(source, {"x": 0.58, "y": 0.05, "width": 0.38, "height": 0.88}, contrast=1.2)
    assert label.size == LABEL_SIZE
    assert label.mode == "L"


def test_crop_coordinates_apply_after_rotation(tmp_path: Path):
    source = tmp_path / "page.png"
    image = Image.new("RGB", (400, 200), "white")
    ImageDraw.Draw(image).rectangle((0, 0, 199, 199), fill="black")
    image.save(source)
    label = prepare_label(source, {"x": 0, "y": 0, "width": 1, "height": 0.5}, rotation=90)
    assert label.getpixel((LABEL_SIZE[0] // 2, LABEL_SIZE[1] // 2)) == 0


def test_small_source_is_enlarged_to_printable_area(tmp_path: Path):
    source = tmp_path / "small.png"
    Image.new("RGB", (300, 450), "black").save(source)
    label = prepare_label(source, {"x": 0, "y": 0, "width": 1, "height": 1})
    assert label.getextrema() == (0, 0)


def test_photo_without_a_label_uses_the_full_frame():
    photo = Image.new("RGB", (900, 900), "gray")
    result = detect_label(photo)
    assert (result.x, result.y, result.width, result.height) == (0, 0, 1, 1)
    assert result.confidence < 0.3


def test_full_frame_photo_fills_the_page_with_no_borders(tmp_path: Path):
    source = tmp_path / "photo.png"
    image = Image.new("RGB", (900, 900), "black")
    ImageDraw.Draw(image).ellipse((100, 100, 800, 800), fill="white")
    image.save(source)
    label = prepare_label(source, {"x": 0, "y": 0, "width": 1, "height": 1})
    assert label.size == LABEL_SIZE
    assert label.getpixel((2, 2)) == 0
    assert label.getpixel((LABEL_SIZE[0] - 2, 2)) == 0
    assert label.getpixel((2, LABEL_SIZE[1] - 2)) == 0
    assert label.getpixel((LABEL_SIZE[0] - 2, LABEL_SIZE[1] - 2)) == 0
