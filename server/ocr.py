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
    """Écarte les groupes trop courts et ceux qui ne sont que des chiffres."""
    kept = [box for box in boxes if not is_numeric_group(box.text)]
    if min_words <= 1:
        return kept
    return [box for box in kept if word_count(box.text) >= min_words]


def recognize_image(cgimage, source: str = "auto") -> list[TextBox]:
    handler = VNImageRequestHandler.alloc().initWithCGImage_options_(cgimage, None)
    return _recognize(handler, source)


def recognize_jpeg(jpeg: bytes, source: str = "auto") -> list[TextBox]:
    data = NSData.dataWithBytes_length_(jpeg, len(jpeg))
    handler = VNImageRequestHandler.alloc().initWithData_options_(data, None)
    return _recognize(handler, source)
