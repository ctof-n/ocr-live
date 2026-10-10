"""OCR Apple Vision : texte + boîtes normalisées (origine en haut à gauche)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass

from Foundation import NSData
from Quartz import CGRectMake
from Vision import VNImageRequestHandler, VNRecognizeTextRequest

VISION_LANGS = {
    "auto": ["ja-JP", "zh-Hans", "zh-Hant", "ko-KR", "en-US"],
    "ja": ["ja-JP"],
    "zh": ["zh-Hans", "zh-Hant"],
    "ko": ["ko-KR"],
    "en": ["en-US"],
}

MIN_CONFIDENCE = 0.3
MAX_CROP = 0.45
_WORDS = re.compile(r"\S+")
_NUMERIC_EXTRA = set(".,:;/-–—+%#|_×xX=()[]~～'’`°*")
_SENTENCE_END = re.compile(r"([.!?。！？…][\"'」』)）]*|[」』])\s*$")
_NEW_UTTERANCE = re.compile(r"^[「『“\"]")
_MAX_BLOCK_LINES = 8
_LINE_GAP = 0.8
_CONTINUE_GAP = 1.4
_LINE_OVERLAP = 0.4
_COLUMN_SLACK = 0.045
_PAGE_GUTTER = 0.08
_PAGE_MIN_BOXES = 2
_PAGE_MIN_SPAN = 0.08
_PAGE_MAX_WIDTH = 0.52
_SAME_LINE_GAP = 0.04


@dataclass
class TextBox:
    x: float
    y: float
    w: float
    h: float
    text: str
    translated: str
    confidence: float

    def as_dict(self) -> dict:
        return asdict(self)


def normalize_crop(
    top: float = 0.0,
    right: float = 0.0,
    bottom: float = 0.0,
    left: float = 0.0,
) -> tuple[float, float, float, float]:
    """Bornes normalisées (haut, droite, bas, gauche), chacune dans [0, 0.45]."""

    def clamp(value: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        if number > 1:
            number /= 100.0
        return min(MAX_CROP, max(0.0, number))

    top, right, bottom, left = (clamp(top), clamp(right), clamp(bottom), clamp(left))
    if top + bottom > 0.9:
        scale = 0.9 / (top + bottom)
        top *= scale
        bottom *= scale
    if left + right > 0.9:
        scale = 0.9 / (left + right)
        left *= scale
        right *= scale
    return top, right, bottom, left


def box_in_crop(box: TextBox, crop: tuple[float, float, float, float]) -> bool:
    top, right, bottom, left = crop
    cx = box.x + box.w / 2
    cy = box.y + box.h / 2
    return left <= cx <= 1 - right and top <= cy <= 1 - bottom


def _apply_roi(request, crop: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    top, right, bottom, left = normalize_crop(*crop)
    width = 1 - left - right
    height = 1 - top - bottom
    if width < 0.999 or height < 0.999 or left > 0 or bottom > 0:
        request.setRegionOfInterest_(CGRectMake(left, bottom, width, height))
    return top, right, bottom, left


def _recognize(handler, source: str, crop: tuple[float, float, float, float] = (0, 0, 0, 0)) -> list[TextBox]:
    request = VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(0)  # accurate
    request.setUsesLanguageCorrection_(False)
    langs = VISION_LANGS.get(source, VISION_LANGS["auto"])
    request.setRecognitionLanguages_(langs)
    request.setAutomaticallyDetectsLanguage_(source == "auto")
    crop = _apply_roi(request, crop)

    ok = handler.performRequests_error_([request], None)
    if isinstance(ok, tuple):
        ok = ok[0]
    if not ok:
        return []

    boxes: list[TextBox] = []
    for observation in request.results() or []:
        candidates = observation.topCandidates_(1)
        if not candidates:
            continue
        candidate = candidates[0]
        text = str(candidate.string() or "").strip()
        confidence = float(candidate.confidence())
        if not text or confidence < MIN_CONFIDENCE:
            continue

        box = observation.boundingBox()
        width = float(box.size.width)
        height = float(box.size.height)
        item = TextBox(
            x=float(box.origin.x),
            y=1.0 - float(box.origin.y) - height,
            w=width,
            h=height,
            text=text,
            translated=text,
            confidence=confidence,
        )
        if box_in_crop(item, crop):
            boxes.append(item)

    # Vision renvoie déjà l’ordre de lecture (page gauche, puis page droite).
    return boxes


def _is_atomic_char(ch: str) -> bool:
    code = ord(ch)
    return (
        0x3040 <= code <= 0x30FF
        or 0x3400 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0xAC00 <= code <= 0xD7AF
        or 0xFF66 <= code <= 0xFF9D
    )


def _token_spans(text: str) -> list[tuple[int, int]]:
    if any(_is_atomic_char(ch) for ch in text):
        spans: list[tuple[int, int]] = []
        latin_start: int | None = None
        for index, char in enumerate(text):
            if char.isspace():
                if latin_start is not None:
                    spans.append((latin_start, index))
                    latin_start = None
                continue
            if _is_atomic_char(char):
                if latin_start is not None:
                    spans.append((latin_start, index))
                    latin_start = None
                spans.append((index, index + 1))
            elif latin_start is None:
                latin_start = index
        if latin_start is not None:
            spans.append((latin_start, len(text)))
        return spans
    return [(match.start(), match.end()) for match in _WORDS.finditer(text)]


def word_count(text: str) -> int:
    return len(_token_spans(text))


def is_numeric_group(text: str) -> bool:
    """Vrai si le groupe n’est que des chiffres (scores, timers, HP…)."""
    stripped = text.strip()
    if not stripped:
        return False
    has_digit = False
    for char in stripped:
        if char.isspace():
            continue
        if unicodedata.category(char) == "Nd":
            has_digit = True
            continue
        if char in _NUMERIC_EXTRA:
            continue
        return False
    return has_digit


def filter_min_words(boxes: list[TextBox], min_words: int) -> list[TextBox]:
    """Écarte chiffres, libellés d’1–2 mots, et les groupes sous le seuil choisi."""
    required = max(3, min_words)
    return [
        box
        for box in boxes
        if not is_numeric_group(box.text) and word_count(box.text) >= required
    ]


def _join_block_text(texts: list[str]) -> str:
    parts = [text.strip() for text in texts if text.strip()]
    if not parts:
        return ""
    if any(_is_atomic_char(char) for text in parts for char in text):
        return "".join(parts)
    joined = parts[0]
    for part in parts[1:]:
        if joined.endswith("-") and part[:1].islower():
            joined = joined[:-1] + part
        else:
            joined = f"{joined} {part}"
    return joined


def _merge_boxes(boxes: list[TextBox]) -> TextBox:
    x = min(box.x for box in boxes)
    y = min(box.y for box in boxes)
    right = max(box.x + box.w for box in boxes)
    bottom = max(box.y + box.h for box in boxes)
    text = _join_block_text([box.text for box in boxes])
    return TextBox(
        x=x,
        y=y,
        w=right - x,
        h=bottom - y,
        text=text,
        translated=text,
        confidence=max(box.confidence for box in boxes),
    )


def _vertical_gap(prev: TextBox, box: TextBox) -> float:
    return box.y - (prev.y + prev.h)


def _similar_height(a: TextBox, b: TextBox) -> bool:
    thin = min(a.h, b.h)
    return thin > 0 and max(a.h, b.h) <= thin * 1.6


def _similar_line_size(prev: TextBox, nxt: TextBox) -> bool:
    """Accepte une ligne sous un paragraphe déjà fusionné (boîte plus haute)."""
    if _similar_height(prev, nxt):
        return True
    return nxt.h > 0 and prev.h > nxt.h * 1.6 and prev.h <= nxt.h * _MAX_BLOCK_LINES * 1.25


def _similar_width(a: TextBox, b: TextBox) -> bool:
    thin = min(a.w, b.w)
    return thin > 0 and max(a.w, b.w) <= thin * 3.5


def _is_vertical_label(box: TextBox) -> bool:
    return box.w > 0 and box.h >= box.w * 1.15


def _same_column(a: TextBox, b: TextBox) -> bool:
    if abs(a.x - b.x) <= _COLUMN_SLACK:
        return True
    if _similar_width(a, b) and abs((a.x + a.w) - (b.x + b.w)) <= 0.08:
        return True
    return abs(a.x - b.x) <= 0.08 and (
        min(a.x + a.w, b.x + b.w) - max(a.x, b.x) > 0
    )


def _horizontal_overlap_ratio(a: TextBox, b: TextBox) -> float:
    overlap = min(a.x + a.w, b.x + b.w) - max(a.x, b.x)
    min_w = min(a.w, b.w)
    if min_w <= 0 or overlap <= 0:
        return 0.0
    return overlap / min_w


def _on_same_line(line: list[TextBox], box: TextBox) -> bool:
    ref = min(line, key=lambda item: abs((item.y + item.h / 2) - (box.y + box.h / 2)))
    thin = min(ref.h, box.h)
    if thin <= 0:
        return False
    if abs((ref.y + ref.h / 2) - (box.y + box.h / 2)) > thin * 0.4:
        return False
    leftmost = min(line, key=lambda item: item.x)
    rightmost = max(line, key=lambda item: item.x + item.w)
    if box.x >= rightmost.x:
        gap = box.x - (rightmost.x + rightmost.w)
    elif box.x + box.w <= leftmost.x:
        gap = leftmost.x - (box.x + box.w)
    else:
        return True
    return 0 <= gap <= min(max(thin * 2.2, 0.02), _SAME_LINE_GAP)


def _group_lines(boxes: list[TextBox]) -> list[list[TextBox]]:
    lines: list[list[TextBox]] = []
    for box in boxes:
        match = next((line for line in lines if _on_same_line(line, box)), None)
        if match is not None:
            match.append(box)
        else:
            lines.append([box])
    lines.sort(key=lambda line: (min(item.y for item in line), min(item.x for item in line)))
    return lines


def _same_block(prev: TextBox, box: TextBox, origin: TextBox) -> bool:
    """Lignes d’un même paragraphe : interligne serré, même colonne, taille proche."""
    if _is_vertical_label(prev) or _is_vertical_label(box):
        return False
    if not _similar_height(prev, box) or not _similar_width(prev, box):
        return False
    thin = min(prev.h, box.h)
    gap = _vertical_gap(prev, box)
    if gap < -thin * _LINE_OVERLAP:
        return False
    if gap > thin * _LINE_GAP:
        return False
    if box.y < prev.y + prev.h * 0.35:
        return False
    if not _same_column(prev, box) or not _same_column(origin, box):
        return False
    return _horizontal_overlap_ratio(prev, box) >= 0.35 or abs(prev.x - box.x) <= _COLUMN_SLACK


def _ends_sentence(text: str) -> bool:
    return bool(_SENTENCE_END.search(text.strip()))


def _can_continue_below(prev: TextBox, nxt: TextBox) -> bool:
    """Poursuit un paragraphe sans clôture avec la ligne située juste en dessous."""
    if _ends_sentence(prev.text) or word_count(prev.text) < 3:
        return False
    if _NEW_UTTERANCE.match(nxt.text.strip()):
        return False
    if _is_vertical_label(prev) or _is_vertical_label(nxt):
        return False
    if not _similar_line_size(prev, nxt) or not _similar_width(prev, nxt):
        return False
    thin = min(prev.h, nxt.h)
    gap = _vertical_gap(prev, nxt)
    if thin <= 0 or gap < -thin * _LINE_OVERLAP:
        return False
    if gap > thin * _CONTINUE_GAP:
        return False
    if not _same_column(prev, nxt):
        return False
    return _horizontal_overlap_ratio(prev, nxt) >= 0.3 or abs(prev.x - nxt.x) <= _COLUMN_SLACK


def _attach_to_block(blocks: list[list[TextBox]], line: TextBox) -> bool:
    for current in reversed(blocks):
        if len(current) < _MAX_BLOCK_LINES and _same_block(current[-1], line, current[0]):
            current.append(line)
            return True
    return False


def _merge_unfinished_paragraphs(blocks: list[TextBox]) -> list[TextBox]:
    merged: list[TextBox] = []
    for box in blocks:
        idx = next(
            (i for i in range(len(merged) - 1, -1, -1) if _can_continue_below(merged[i], box)),
            None,
        )
        if idx is not None:
            merged[idx] = _merge_boxes([merged[idx], box])
        else:
            merged.append(box)
    return merged


def _vertical_span(boxes: list[TextBox]) -> float:
    return max(box.y + box.h for box in boxes) - min(box.y for box in boxes)


def _page_gutter(boxes: list[TextBox]) -> float | None:
    """Milieu de la gouttière d’un livre : plus grand écart entre centres des lignes."""
    centers = sorted(
        box.x + box.w / 2 for box in boxes if 0.04 <= box.w < _PAGE_MAX_WIDTH
    )
    if len(centers) < _PAGE_MIN_BOXES * 2:
        return None
    best_gap = 0.0
    split: float | None = None
    for left_x, right_x in zip(centers, centers[1:]):
        gap = right_x - left_x
        if gap > best_gap:
            best_gap = gap
            split = (left_x + right_x) / 2
    if split is None or best_gap < _PAGE_GUTTER:
        return None
    left = [box for box in boxes if box.x + box.w / 2 < split]
    right = [box for box in boxes if box.x + box.w / 2 >= split]
    if len(left) < _PAGE_MIN_BOXES or len(right) < _PAGE_MIN_BOXES:
        return None
    if _vertical_span(left) < _PAGE_MIN_SPAN or _vertical_span(right) < _PAGE_MIN_SPAN:
        return None
    return split


def _merge_column(boxes: list[TextBox]) -> list[TextBox]:
    if len(boxes) <= 1:
        return list(boxes)
    line_boxes = [_merge_boxes(sorted(line, key=lambda item: item.x)) for line in _group_lines(boxes)]
    blocks: list[list[TextBox]] = []
    for line in line_boxes:
        if not _attach_to_block(blocks, line):
            blocks.append([line])
    return _merge_unfinished_paragraphs([_merge_boxes(block) for block in blocks])


def merge_text_blocks(boxes: list[TextBox]) -> list[TextBox]:
    """Regroupe les lignes, page gauche puis page droite si la mise en page est un livre."""
    if len(boxes) <= 1:
        return boxes
    split = _page_gutter(boxes)
    if split is None:
        return _merge_column(boxes)
    spanning = [box for box in boxes if box.x < split and box.x + box.w > split]
    left = [box for box in boxes if box.x + box.w / 2 < split and box not in spanning]
    right = [box for box in boxes if box.x + box.w / 2 >= split and box not in spanning]
    return _merge_column(spanning) + _merge_column(left) + _merge_column(right)


def recognize_image(
    cgimage, source: str = "auto", crop: tuple[float, float, float, float] = (0, 0, 0, 0)
) -> list[TextBox]:
    handler = VNImageRequestHandler.alloc().initWithCGImage_options_(cgimage, None)
    return _recognize(handler, source, crop)


def recognize_jpeg(
    jpeg: bytes, source: str = "auto", crop: tuple[float, float, float, float] = (0, 0, 0, 0)
) -> list[TextBox]:
    data = NSData.dataWithBytes_length_(jpeg, len(jpeg))
    handler = VNImageRequestHandler.alloc().initWithData_options_(data, None)
    return _recognize(handler, source, crop)
