"""OCR Apple Vision : texte + boîtes normalisées (origine en haut à gauche)."""

from __future__ import annotations

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


def recognize_image(cgimage, source: str = "auto") -> list[TextBox]:
    handler = VNImageRequestHandler.alloc().initWithCGImage_options_(cgimage, None)
    return _recognize(handler, source)


def recognize_jpeg(jpeg: bytes, source: str = "auto") -> list[TextBox]:
    data = NSData.dataWithBytes_length_(jpeg, len(jpeg))
    handler = VNImageRequestHandler.alloc().initWithData_options_(data, None)
    return _recognize(handler, source)
