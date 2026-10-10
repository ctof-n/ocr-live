"""OCR Apple Vision : texte + boîtes normalisées (origine en haut à gauche)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass

from Foundation import NSData
from Vision import VNImageRequestHandler, VNRecognizeTextRequest

VISION_LANGS = {
    "auto": ["ja-JP", "zh-Hans", "zh-Hant", "ko-KR", "en-US"],
    "ja": ["ja-JP"],
    "zh": ["zh-Hans", "zh-Hant"],
    "ko": ["ko-KR"],
    "en": ["en-US"],
}

MIN_CONFIDENCE = 0.3
_WORDS = re.compile(r"\S+")
_NUMERIC_EXTRA = set(".,:;/-–—+%#|_×xX=()[]~～'’`°*")
_SENTENCE_END = re.compile(r"[.!?。！？…][\"'」』)）]*\s*$")


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


def _recognize(handler, source: str) -> list[TextBox]:
    request = VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(0)  # accurate
    request.setUsesLanguageCorrection_(False)
    langs = VISION_LANGS.get(source, VISION_LANGS["auto"])
    request.setRecognitionLanguages_(langs)
    request.setAutomaticallyDetectsLanguage_(source == "auto")

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
        boxes.append(
            TextBox(
                x=float(box.origin.x),
                y=1.0 - float(box.origin.y) - height,
                w=width,
                h=height,
                text=text,
                translated=text,
                confidence=confidence,
            )
        )

    boxes.sort(key=lambda item: (round(item.y, 3), item.x))
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
    return " ".join(parts)


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


def _on_same_line(line: list[TextBox], box: TextBox) -> bool:
    ref = line[-1]
    thin = min(ref.h, box.h, 0.02)
    ref_mid = ref.y + ref.h / 2
    box_mid = box.y + box.h / 2
    if abs(ref_mid - box_mid) > thin * 0.35:
        return False
    gap = box.x - (ref.x + ref.w)
    return gap <= thin * 0.9


def _group_lines(boxes: list[TextBox]) -> list[list[TextBox]]:
    lines: list[list[TextBox]] = []
    for box in boxes:
        if lines and _on_same_line(lines[-1], box):
            lines[-1].append(box)
        else:
            lines.append([box])
    return lines


def _same_block(prev: TextBox, box: TextBox, origin: TextBox) -> bool:
    gap = box.y - (prev.y + prev.h)
    thin = min(prev.h, box.h)
    if thin <= 0:
        return False
    if gap < -thin * 0.04:
        return False
    if gap > min(thin * 0.35, 0.012):
        return False
    if box.y + box.h * 0.25 < prev.y + prev.h * 0.55:
        return False
    if max(prev.h, box.h) > min(prev.h, box.h) * 1.45:
        return False
    if abs(prev.x - box.x) > 0.02 or abs(origin.x - box.x) > 0.022:
        return False
    overlap = min(prev.x + prev.w, box.x + box.w) - max(prev.x, box.x)
    min_w = min(prev.w, box.w)
    max_w = max(prev.w, box.w)
    if min_w <= 0 or overlap / min_w < 0.6:
        return False
    return min_w / max_w >= 0.45


def _ends_sentence(text: str) -> bool:
    return bool(_SENTENCE_END.search(text.strip()))


def _can_continue_below(prev: TextBox, nxt: TextBox) -> bool:
    """Poursuit un paragraphe sans point final avec la phrase située en dessous."""
    if _ends_sentence(prev.text) or word_count(prev.text) < 3:
        return False
    gap = nxt.y - (prev.y + prev.h)
    thin = min(prev.h, nxt.h)
    if thin <= 0 or gap < -thin * 0.1:
        return False
    if gap > min(max(prev.h, nxt.h) * 2.2, 0.07):
        return False
    if abs(prev.x - nxt.x) > 0.045:
        return False
    overlap = min(prev.x + prev.w, nxt.x + nxt.w) - max(prev.x, nxt.x)
    min_w = min(prev.w, nxt.w)
    return min_w > 0 and overlap / min_w >= 0.4


def _merge_unfinished_paragraphs(blocks: list[TextBox]) -> list[TextBox]:
    merged: list[TextBox] = []
    for box in blocks:
        if merged and _can_continue_below(merged[-1], box):
            merged[-1] = _merge_boxes([merged[-1], box])
        else:
            merged.append(box)
    return merged


def merge_text_blocks(boxes: list[TextBox]) -> list[TextBox]:
    """Regroupe les lignes collées, puis continue tant que le paragraphe n’a pas de point."""
    if len(boxes) <= 1:
        return boxes
    line_boxes = [_merge_boxes(sorted(line, key=lambda item: item.x)) for line in _group_lines(boxes)]
    blocks: list[list[TextBox]] = []
    for line in line_boxes:
        current = blocks[-1] if blocks else None
        if current and len(current) < 8 and _same_block(current[-1], line, current[0]):
            current.append(line)
        else:
            blocks.append([line])
    return _merge_unfinished_paragraphs([_merge_boxes(block) for block in blocks])


def recognize_image(cgimage, source: str = "auto") -> list[TextBox]:
    handler = VNImageRequestHandler.alloc().initWithCGImage_options_(cgimage, None)
    return _recognize(handler, source)


def recognize_jpeg(jpeg: bytes, source: str = "auto") -> list[TextBox]:
    data = NSData.dataWithBytes_length_(jpeg, len(jpeg))
    handler = VNImageRequestHandler.alloc().initWithData_options_(data, None)
    return _recognize(handler, source)
