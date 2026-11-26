"""Create printable ArUco scale cards with an adjacent ruler.

Input: marker IDs, physical size, output path. Output: a print-ready A4 PDF
whose scale can be checked with the ruler. Implements `docs/04_ARCHITECTURE.md`.
"""

from pathlib import Path

import cv2
from PIL import Image, ImageDraw, ImageFont

_PRINT_DPI = 300
_A4_WIDTH_MM = 210
_A4_HEIGHT_MM = 297
_MARKER_TOP_MM = 38
_MARKER_LABEL_GAP_MM = 8
_MARKER_LABEL_FONT_MM = 3.5
_PAGE_TITLE_FONT_MM = 5
_RULER_LENGTH_MM = 100
_RULER_LABEL_GAP_MM = 32
_RULER_LABEL_HEIGHT_MM = 10
_RULER_TICK_STEP_MM = 10
_RULER_MAJOR_TICK_STEP_MM = 50
_RULER_MAJOR_TICK_HEIGHT_MM = 5
_RULER_MINOR_TICK_HEIGHT_MM = 3
_PAGE_FOOTER_MM = 20
_ARUCO_4X4_50_COUNT = 50


def generate_marker_pdf(
    ids: tuple[int, ...], size_mm: float, out: Path, *, dpi: int = _PRINT_DPI
) -> Path:
    """Create A4 marker pages, retaining physical marker and ruler dimensions."""
    if not ids:
        raise ValueError("At least one marker ID is required")
    if size_mm <= 0:
        raise ValueError("Marker size must be positive")
    aruco = cv2.aruco
    dictionary_code = getattr(aruco, "DICT_4X4_50", None)
    if dictionary_code is None:
        raise RuntimeError("OpenCV ArUco dictionary unavailable: DICT_4X4_50")
    dictionary = aruco.getPredefinedDictionary(dictionary_code)
    page_w, page_h = _mm_to_px(_A4_WIDTH_MM, dpi), _mm_to_px(_A4_HEIGHT_MM, dpi)
    marker_side_px = _mm_to_px(size_mm, dpi)
    ruler_side_px = _mm_to_px(_RULER_LENGTH_MM, dpi)
    pages: list[Image.Image] = []
    for marker_id in ids:
        if not 0 <= marker_id < _ARUCO_4X4_50_COUNT:
            raise ValueError("DICT_4X4_50 marker IDs must be between 0 and 49")
        if hasattr(aruco, "generateImageMarker"):
            marker = aruco.generateImageMarker(dictionary, marker_id, marker_side_px)
        else:
            marker = aruco.drawMarker(dictionary, marker_id, marker_side_px)
        pages.append(
            _build_marker_page(
                marker,
                marker_id,
                size_mm,
                page_w,
                page_h,
                marker_side_px,
                ruler_side_px,
                dpi,
            )
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    pages[0].save(out, format="PDF", resolution=dpi, save_all=True, append_images=pages[1:])
    return out


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _mm_to_px(value: float, dpi: int) -> int:
    # One inch is exactly 25.4 mm; this preserves the intended printed scale.
    return round(value * dpi / 25.4)


def _build_marker_page(
    marker: object,
    marker_id: int,
    size_mm: float,
    page_w: int,
    page_h: int,
    marker_side_px: int,
    ruler_side_px: int,
    dpi: int,
) -> Image.Image:
    """Lay out a marker, ID, and ruler so print scaling is easy to verify."""
    page = Image.new("RGB", (page_w, page_h), "white")
    page.paste(
        Image.fromarray(marker).convert("RGB"),
        ((page_w - marker_side_px) // 2, _mm_to_px(_MARKER_TOP_MM, dpi)),
    )
    draw = ImageDraw.Draw(page)
    marker_bottom = _mm_to_px(_MARKER_TOP_MM, dpi) + marker_side_px
    _draw_marker_label(draw, page_w, marker_bottom, marker_id, size_mm, dpi)
    _draw_ruler(draw, page_w, marker_bottom, ruler_side_px, dpi)
    draw.text(
        (page_w // 2, page_h - _mm_to_px(_PAGE_FOOTER_MM, dpi)),
        "Print at 100% / actual size — no fit-to-page.",
        fill="black",
        font=_font(_mm_to_px(_PAGE_TITLE_FONT_MM, dpi)),
        anchor="ms",
    )
    return page


def _draw_marker_label(
    draw: ImageDraw.ImageDraw,
    page_w: int,
    marker_bottom: int,
    marker_id: int,
    size_mm: float,
    dpi: int,
) -> None:
    label = f"ArUco ID {marker_id}  |  intended marker size {size_mm:.1f} mm"
    draw.text(
        (page_w // 2, marker_bottom + _mm_to_px(_MARKER_LABEL_GAP_MM, dpi)),
        label,
        fill="black",
        font=_font(_mm_to_px(_MARKER_LABEL_FONT_MM, dpi)),
        anchor="mt",
    )


def _draw_ruler(
    draw: ImageDraw.ImageDraw,
    page_w: int,
    marker_bottom: int,
    ruler_side_px: int,
    dpi: int,
) -> None:
    """Draw a physical scale check so print-size errors are visible immediately."""
    ruler_x = (page_w - ruler_side_px) // 2
    ruler_y = marker_bottom + _mm_to_px(_RULER_LABEL_GAP_MM, dpi)
    draw.text(
        (page_w // 2, ruler_y - _mm_to_px(_RULER_LABEL_HEIGHT_MM, dpi)),
        f"{_RULER_LENGTH_MM} mm ruler line — verify print scale with a ruler",
        fill="black",
        font=_font(_mm_to_px(_MARKER_LABEL_FONT_MM, dpi)),
        anchor="ms",
    )
    draw.line((ruler_x, ruler_y, ruler_x + ruler_side_px, ruler_y), fill="black", width=5)
    for millimetres in range(0, _RULER_LENGTH_MM + 1, _RULER_TICK_STEP_MM):
        tick_x = ruler_x + _mm_to_px(millimetres, dpi)
        tick_mm = (
            _RULER_MAJOR_TICK_HEIGHT_MM
            if millimetres % _RULER_MAJOR_TICK_STEP_MM == 0
            else _RULER_MINOR_TICK_HEIGHT_MM
        )
        tick_height = _mm_to_px(tick_mm, dpi)
        draw.line(
            (tick_x, ruler_y - tick_height, tick_x, ruler_y + tick_height),
            fill="black",
            width=4,
        )
