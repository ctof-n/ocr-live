"""JPEG → boîtes de mots anglais décodés depuis les runes Tunic."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageDraw

from server.ocr import TextBox
from server.trunic.detect import Glyph, detect_all
from server.trunic.geometry import SEGMENTS, VERTICES, SEGMENT_ENDS
from server.trunic.phonemes import tokens_to_english


def _group_words(glyphs: list[Glyph], img_h: int) -> list[list[Glyph]]:
    if not glyphs:
        return []
    words: list[list[Glyph]] = [[glyphs[0]]]
    for glyph in glyphs[1:]:
        prev = words[-1][-1]
        same_line = abs(glyph.y0 - prev.y0) < max(12, (prev.y1 - prev.y0) * 0.35)
        gap = glyph.x0 - prev.x1
        glyph_w = max(1, prev.x1 - prev.x0)
        if same_line and gap < glyph_w * 0.55:
            words[-1].append(glyph)
        else:
            words.append([glyph])
    return words


def recognize_array(gray: np.ndarray) -> list[TextBox]:
    height, width = gray.shape
    glyphs = detect_all(gray)
    boxes: list[TextBox] = []
    for word in _group_words(glyphs, height):
        tokens = [tok for glyph in word for tok in glyph.tokens]
        english = tokens_to_english(tokens)
        if not english:
            continue
        x0 = min(g.x0 for g in word)
        y0 = min(g.y0 for g in word)
        x1 = max(g.x1 for g in word)
        y1 = max(g.y1 for g in word)
        boxes.append(
            TextBox(
                x=x0 / width,
                y=y0 / height,
                w=(x1 - x0) / width,
                h=(y1 - y0) / height,
                text=english,
                translated=english,
                confidence=0.7,
            )
        )
    return boxes


def recognize_jpeg(jpeg: bytes) -> list[TextBox]:
    image = Image.open(io.BytesIO(jpeg)).convert("L")
    max_w = 1400
    if image.width > max_w:
        ratio = max_w / image.width
        image = image.resize((max_w, max(1, int(image.height * ratio))), Image.Resampling.BILINEAR)
    gray = np.asarray(image, dtype=np.uint8)
    return recognize_array(gray)


def render_rune(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], mask: int, swap: bool = False) -> None:
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0

    def pt(name: str) -> tuple[float, float]:
        nx, ny = VERTICES[name]
        return x0 + nx * w, y0 + ny * h

    def line(a: str, b: str) -> None:
        draw.line([pt(a), pt(b)], fill=0, width=max(2, h // 18))

    line(*SEGMENT_ENDS["Base"])
    for name, bit in SEGMENTS.items():
        if bit is None:
            continue
        if mask & (1 << bit):
            line(*SEGMENT_ENDS[name])
    if swap:
        cx, cy = pt("swap")
        r = max(2, h // 22)
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=0, width=max(2, h // 24))
