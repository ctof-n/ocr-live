"""OCR + traduction, seulement quand l'image a changé."""

from __future__ import annotations

import hashlib
import time

from server.ocr import TextBox, filter_min_words, merge_text_blocks, recognize_image, recognize_jpeg
from server.translate import translate_boxes
from server.trunic.recognize import recognize_jpeg as recognize_trunic

OCR_EVERY_SECONDS = 0.55


class LiveOcr:
    def __init__(self) -> None:
        self.last_hash = ""
        self.last_run = 0.0
        self.busy = False
        self.boxes: list[TextBox] = []

    def should_run(self, payload: bytes) -> bool:
        if self.busy:
            return False
        digest = hashlib.md5(payload).hexdigest()
        now = time.monotonic()
        if digest == self.last_hash:
            return False
        if now - self.last_run < OCR_EVERY_SECONDS:
            return False
        self.last_hash = digest
        self.last_run = now
        return True

    def _recognize(
        self,
        source: str,
        jpeg: bytes | None,
        cgimage,
        crop: tuple[float, float, float, float],
    ) -> list[TextBox]:
        if source == "tunic":
            if not jpeg:
                return []
            return recognize_trunic(jpeg, crop)
        if cgimage is not None:
            return recognize_image(cgimage, source, crop)
        if jpeg:
            return recognize_jpeg(jpeg, source, crop)
        return []

    def run_image(
        self,
        cgimage,
        source: str,
        target: str,
        jpeg: bytes | None = None,
        min_words: int = 3,
        crop: tuple[float, float, float, float] = (0, 0, 0, 0),
    ) -> list[dict]:
        self.busy = True
        try:
            boxes = filter_min_words(
                merge_text_blocks(self._recognize(source, jpeg, cgimage, crop)),
                min_words,
            )
            lang = "en" if source == "tunic" else source
            self.boxes = translate_boxes(boxes, lang, target)
            return [box.as_dict() for box in self.boxes]
        finally:
            self.busy = False

    def run_jpeg(
        self,
        jpeg: bytes,
        source: str,
        target: str,
        min_words: int = 3,
        crop: tuple[float, float, float, float] = (0, 0, 0, 0),
    ) -> list[dict]:
        return self.run_image(
            None, source, target, jpeg=jpeg, min_words=min_words, crop=crop
        )
