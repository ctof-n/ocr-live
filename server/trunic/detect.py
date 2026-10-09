"""Détection des glyphes et lecture des 12 segments."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from server.trunic.geometry import SEGMENTS, SEGMENT_ENDS, VERTICES
from server.trunic.phonemes import decode_mask

MIN_HEIGHT = 16
MAX_GLYPHS_PER_WORD = 24


@dataclass
class Glyph:
    x0: int
    y0: int
    x1: int
    y1: int
    mask: int
    swap: bool
    tokens: list[str]


def otsu(gray: np.ndarray) -> int:
    hist, _ = np.histogram(gray.ravel(), 256, (0, 256))
    total = gray.size
    sum1 = np.dot(np.arange(256), hist)
    sum_b = 0.0
    w_b = 0
    maximum = 0.0
    thresh = 127
    for i, count in enumerate(hist):
        w_b += int(count)
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += i * int(count)
        m_b = sum_b / w_b
        m_f = (sum1 - sum_b) / w_f
        between = w_b * w_f * (m_b - m_f) ** 2
        if between >= maximum:
            maximum = between
            thresh = i
    return int(thresh)


def _sample(ink: np.ndarray, x: float, y: float, radius: int = 1) -> float:
    h, w = ink.shape
    cx, cy = int(round(x)), int(round(y))
    x0, x1 = max(0, cx - radius), min(w, cx + radius + 1)
    y0, y1 = max(0, cy - radius), min(h, cy + radius + 1)
    patch = ink[y0:y1, x0:x1]
    if patch.size == 0:
        return 0.0
    return float(patch.mean())


def read_glyph(ink: np.ndarray, x0: int, y0: int, x1: int, y1: int) -> Glyph | None:
    bw = max(1, x1 - x0)
    bh = max(1, y1 - y0)
    if bh < MIN_HEIGHT or bw < 8:
        return None

    def to_px(nx: float, ny: float) -> tuple[float, float]:
        return x0 + nx * bw, y0 + ny * bh

    def segment_score(name: str) -> float:
        start_n, end_n = SEGMENT_ENDS[name]
        p0, p1 = to_px(*VERTICES[start_n]), to_px(*VERTICES[end_n])
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        length = max((dx * dx + dy * dy) ** 0.5, 1.0)
        nx, ny = -dy / length, dx / length
        reach = max(2.0, min(bw, bh) * 0.06)
        scores = []
        for step in range(7):
            t = 0.24 + 0.52 * step / 6
            px, py = p0[0] + dx * t, p0[1] + dy * t
            best = 0.0
            for offset in range(-4, 5):
                s = offset / 4 * reach
                best = max(best, _sample(ink, px + nx * s, py + ny * s))
            scores.append(best)
        return float(sum(scores) / len(scores))

    base = segment_score("Base")
    bg = float(
        np.mean([_sample(ink, *to_px(px, py)) for px, py in [(0.02, 0.02), (0.98, 0.02), (0.02, 0.98), (0.98, 0.98)]])
    )
    if base - bg < 0.12:
        return None

    threshold = (base + bg) / 2
    mask = 0
    for name, bit in SEGMENTS.items():
        if bit is None:
            continue
        if segment_score(name) >= threshold:
            mask |= 1 << bit

    swap_pos = VERTICES["swap"]
    swap = _sample(ink, *to_px(*swap_pos), radius=2) >= threshold
    tokens = decode_mask(mask, swap)
    if not tokens:
        return None
    return Glyph(x0, y0, x1, y1, mask, swap, tokens)


def _canonical_box(
    ink: np.ndarray, x0: int, y0: int, x1: int, y1: int
) -> tuple[int, int, int, int] | None:
    roi = ink[max(0, y0) : y1, max(0, x0) : x1]
    if roi.size == 0:
        return None
    row_sums = roi.sum(axis=1)
    col_sums = roi.sum(axis=0)
    if row_sums.max() == 0 or col_sums.max() == 0:
        return None
    base_local = int(row_sums.argmax())
    rows = np.where(row_sums > row_sums.max() * 0.08)[0]
    cols = np.where(col_sums > 0)[0]
    top, bottom = int(rows[0]), int(rows[-1])
    left, right = int(cols[0]), int(cols[-1])
    h_top = max(1, base_local - top)
    h_bot = max(1, bottom - base_local)
    full_h = max(h_top / 0.44, h_bot / 0.40, (bottom - top) / 0.84) * 0.94
    full_w = max((right - left) / 0.72, full_h * 0.50) * 0.96
    cx = x0 + (left + right) / 2
    base_y = y0 + base_local
    nx0 = int(round(cx - full_w / 2))
    ny0 = int(round(base_y - 0.50 * full_h))
    return nx0, ny0, int(round(nx0 + full_w)), int(round(ny0 + full_h))


def _split_word(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int, int, int]]:
    width = x1 - x0
    height = y1 - y0
    if height <= 0 or width / height < 0.85:
        return [(x0, y0, x1, y1)]
    glyph_w = max(8, height * 0.55)
    count = max(1, min(MAX_GLYPHS_PER_WORD, round(width / glyph_w)))
    if count <= 1:
        return [(x0, y0, x1, y1)]
    return [
        (x0 + int(i * width / count), y0, x0 + int((i + 1) * width / count), y1)
        for i in range(count)
    ]


def find_glyphs(ink: np.ndarray) -> list[Glyph]:
    closed = ndimage.binary_closing(ink, structure=np.ones((2, 2)))
    labeled, count = ndimage.label(closed)
    if count == 0:
        return []

    glyphs: list[Glyph] = []
    for index in range(1, count + 1):
        ys, xs = np.where(labeled == index)
        if ys.size < 80:
            continue
        x0, x1 = int(xs.min()), int(xs.max()) + 1
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        height = y1 - y0
        width = x1 - x0
        if height < MIN_HEIGHT or width < 8:
            continue
        if height > ink.shape[0] * 0.7 or width > ink.shape[1] * 0.98:
            continue
        for slice_box in _split_word(x0, y0, x1, y1):
            canon = _canonical_box(ink, *slice_box)
            if not canon:
                continue
            glyph = read_glyph(ink, *canon)
            if glyph:
                glyphs.append(glyph)

    glyphs.sort(key=lambda g: (round(g.y0 / 8), g.x0))
    return glyphs


def _quality(glyphs: list[Glyph]) -> float:
    if not glyphs:
        return 0.0
    return float(sum((g.x1 - g.x0) * (g.y1 - g.y0) for g in glyphs))


def detect_all(gray: np.ndarray) -> list[Glyph]:
    thresh = otsu(gray)
    dark = gray < thresh
    light = gray > thresh
    g_dark = find_glyphs(dark)
    g_light = find_glyphs(light)
    return g_dark if _quality(g_dark) >= _quality(g_light) else g_light
