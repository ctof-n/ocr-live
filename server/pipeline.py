"""OCR + traduction, seulement le texte qui reste stable à l’écran."""

from __future__ import annotations

import hashlib
import time

from server.ocr import TextBox, filter_min_words, merge_text_blocks, recognize_image, recognize_jpeg
from server.translate import translate_boxes
from server.trunic.recognize import recognize_jpeg as recognize_trunic

OCR_EVERY_SECONDS = 0.55
_POS_TOL = 0.05


def _norm_text(text: str) -> str:
    return " ".join(text.split()).casefold()


def boxes_match(left: TextBox, right: TextBox, tol: float = _POS_TOL) -> bool:
    if _norm_text(left.text) != _norm_text(right.text):
        return False
    return abs(left.x - right.x) <= tol and abs(left.y - right.y) <= tol


def stable_boxes(previous: list[TextBox], current: list[TextBox]) -> list[TextBox]:
    """Garde les boîtes déjà vues au même endroit (texte statique)."""
    if not previous:
        return []
    return [
        box
        for box in current
        if any(boxes_match(box, seen) for seen in previous)
    ]


class LiveOcr:
    def __init__(self) -> None:
        self.last_hash = ""
        self.last_run = 0.0
        self.busy = False
        self.boxes: list[TextBox] = []
        self._prev_raw: list[TextBox] = []
        self._last_raw: list[TextBox] = []
        self._awaiting_confirm = False

    def next_action(self, payload: bytes) -> str:
        """'ocr', 'confirm' (image figée) ou 'skip'."""
        if self.busy:
            return "skip"
        digest = hashlib.md5(payload).hexdigest()
        now = time.monotonic()
        if digest == self.last_hash:
            return "confirm" if self._awaiting_confirm else "skip"
        if now - self.last_run < OCR_EVERY_SECONDS:
            return "skip"
        self.last_hash = digest
        self.last_run = now
        return "ocr"

    def should_run(self, payload: bytes) -> bool:
        return self.next_action(payload) == "ocr"

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

    def _identified_payload(self, boxes: list[TextBox]) -> list[dict]:
        payload = []
        for box in boxes:
            item = box.as_dict()
            item["translated"] = ""
            item["pending"] = True
            payload.append(item)
        self.boxes = boxes
        return payload

    def _publish(self, boxes: list[TextBox], source: str, target: str) -> list[dict]:
        self.boxes = translate_boxes(boxes, source, target)
        return [box.as_dict() for box in self.boxes]

    def collect(
        self,
        source: str,
        jpeg: bytes | None = None,
        cgimage=None,
        min_words: int = 3,
        crop: tuple[float, float, float, float] = (0, 0, 0, 0),
    ) -> tuple[list[dict], list[TextBox]]:
        """OCR sans traduire. Laisse busy=True s’il reste une traduction à faire."""
        self.busy = True
        try:
            boxes = filter_min_words(
                merge_text_blocks(self._recognize(source, jpeg, cgimage, crop)),
                min_words,
            )
            stable = stable_boxes(self._prev_raw, boxes)
            self._last_raw = boxes
            self._awaiting_confirm = not bool(self._prev_raw)
            self._prev_raw = boxes
            identified = self._identified_payload(boxes)
            if not stable:
                self.busy = False
            return identified, stable
        except Exception:
            self.busy = False
            raise

    def translate_stable(
        self, boxes: list[TextBox], source: str, target: str
    ) -> list[dict]:
        try:
            return self._publish(boxes, source, target)
        finally:
            self.busy = False

    def confirm_static(self, source: str, target: str) -> list[dict] | None:
        """Image inchangée : le dernier OCR est du texte statique."""
        if self.busy or not self._awaiting_confirm or not self._last_raw:
            return None
        self.busy = True
        try:
            self._awaiting_confirm = False
            self._prev_raw = list(self._last_raw)
            return self._publish(list(self._last_raw), source, target)
        finally:
            self.busy = False

    def run_image(
        self,
        cgimage,
        source: str,
        target: str,
        jpeg: bytes | None = None,
        min_words: int = 3,
        crop: tuple[float, float, float, float] = (0, 0, 0, 0),
    ) -> list[dict]:
        identified, stable = self.collect(
            source, jpeg=jpeg, cgimage=cgimage, min_words=min_words, crop=crop
        )
        if not stable:
            return identified
        return self.translate_stable(stable, source, target)

    def run_jpeg(
        self,
        jpeg: bytes,
        source: str,
        target: str,
        min_words: int = 3,
        crop: tuple[float, float, float, float] = (0, 0, 0, 0),
    ) -> tuple[list[dict], list[TextBox]]:
        return self.collect(source, jpeg=jpeg, min_words=min_words, crop=crop)
