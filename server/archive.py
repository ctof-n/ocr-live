"""Une image JPEG unique par scène. Les textes proches y sont rattachés."""

from __future__ import annotations

import hashlib
import io
import json
import re
import threading
from difflib import SequenceMatcher
from pathlib import Path

from PIL import Image

_HEX = frozenset("0123456789abcdef")
_PUNCT = re.compile(r"[^\w\s]+", re.UNICODE)
_HASH_SIZE = 16
_HAMMING_MAX = 12
_HAMMING_SPLIT = 24


def text_key(text: str) -> str:
    return " ".join(_PUNCT.sub(" ", str(text)).casefold().split())


def unique_texts(boxes: list) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for box in boxes:
        if isinstance(box, dict):
            raw = box.get("text")
        else:
            raw = getattr(box, "text", "")
        cleaned = " ".join(str(raw or "").split()).strip()
        key = text_key(cleaned)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def valid_image_id(image_id: str) -> bool:
    return len(image_id) == 64 and all(char in _HEX for char in image_id)


def _token_subsequence(short: str, long: str) -> bool:
    words = short.split()
    if len(words) < 3:
        return False
    cursor = iter(long.split())
    return all(word in cursor for word in words)


def similar_text(left: str, right: str) -> bool:
    a, b = text_key(left), text_key(right)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) >= 12 and short in long:
        return True
    if _token_subsequence(short, long):
        return True
    ratio = SequenceMatcher(None, a, b).ratio()
    if min(len(a), len(b)) <= 8:
        return ratio >= 0.9
    if min(len(a), len(b)) <= 20:
        return ratio >= 0.84
    return ratio >= 0.78


def _significant(text: str) -> bool:
    key = text_key(text)
    return len(key) >= 10 or len(key.split()) >= 3


def average_hash(jpeg: bytes) -> int | None:
    """Hash de différence 16×16 : deux JPEG de la même scène restent proches."""
    try:
        image = Image.open(io.BytesIO(jpeg)).convert("L").resize(
            (_HASH_SIZE + 1, _HASH_SIZE), Image.Resampling.BILINEAR
        )
    except Exception:
        return None
    pixels = list(image.getdata())
    width = _HASH_SIZE + 1
    bits = 0
    for y in range(_HASH_SIZE):
        row = y * width
        for x in range(_HASH_SIZE):
            bits = (bits << 1) | int(pixels[row + x] > pixels[row + x + 1])
    return bits


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def scenes_overlap(left: list[str], right: list[str]) -> bool:
    sig_left = [text for text in left if _significant(text)] or list(left)
    sig_right = [text for text in right if _significant(text)] or list(right)
    return any(similar_text(a, b) for a in sig_left for b in sig_right)


class CaptureStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.images_dir = self.root / "images"
        self.index_path = self.root / "index.json"
        self._lock = threading.Lock()
        self._images: dict[str, list[str]] = {}
        self._order: list[str] = []
        self._text_to_id: dict[str, str] = {}
        self._phash: dict[str, int] = {}
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self._load()
        self._hash_all()
        self.compact()

    def _load(self) -> None:
        if not self.index_path.exists():
            return
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        images = data.get("images") if isinstance(data, dict) else None
        if not isinstance(images, list):
            return
        for item in images:
            if not isinstance(item, dict):
                continue
            image_id = item.get("id")
            texts = item.get("texts")
            if not isinstance(image_id, str) or not valid_image_id(image_id):
                continue
            if not isinstance(texts, list):
                continue
            if not (self.images_dir / f"{image_id}.jpg").is_file():
                continue
            cleaned: list[str] = []
            known: set[str] = set()
            for text in texts:
                if not isinstance(text, str):
                    continue
                value = " ".join(text.split()).strip()
                key = text_key(value)
                if not key or key in known:
                    continue
                known.add(key)
                cleaned.append(value)
            self._images[image_id] = cleaned
            self._order.append(image_id)
        self._rebuild_text_index()

    def _rebuild_text_index(self) -> None:
        self._text_to_id = {}
        for image_id in self._order:
            for text in self._images[image_id]:
                self._text_to_id.setdefault(text_key(text), image_id)

    def _dump(self) -> None:
        payload = {
            "images": [
                {"id": image_id, "texts": self._images[image_id]} for image_id in self._order
            ]
        }
        tmp = self.index_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.index_path)

    def list_captures(self) -> list[dict]:
        with self._lock:
            return [
                {"id": image_id, "texts": list(self._images[image_id])}
                for image_id in self._order
            ]

    def jpeg_path(self, image_id: str) -> Path | None:
        if not valid_image_id(image_id):
            return None
        path = self.images_dir / f"{image_id}.jpg"
        return path if path.is_file() else None

    def delete(self, image_ids: list[str]) -> list[str]:
        """Supprime les captures demandées. Renvoie les identifiants réellement supprimés."""
        with self._lock:
            removed = [
                image_id
                for image_id in dict.fromkeys(image_ids)
                if isinstance(image_id, str) and image_id in self._images
            ]
            if not removed:
                return []
            for image_id in removed:
                self._drop_image(image_id)
            self._rebuild_text_index()
            self._dump()
            return removed

    def _known_image(self, text: str) -> str | None:
        key = text_key(text)
        if not key:
            return None
        hit = self._text_to_id.get(key)
        if hit:
            return hit
        for existing, image_id in self._text_to_id.items():
            if similar_text(key, existing):
                self._text_to_id[key] = image_id
                return image_id
        return None

    def _merge_texts(self, image_id: str, texts: list[str]) -> dict | None:
        existing = self._images[image_id]
        added = False
        for text in texts:
            key = text_key(text)
            self._text_to_id.setdefault(key, image_id)
            if any(similar_text(text, item) for item in existing):
                continue
            existing.append(text)
            self._text_to_id[key] = image_id
            added = True
        if not added:
            return None
        self._dump()
        return {"id": image_id, "texts": list(existing)}

    def _drop_image(self, image_id: str) -> None:
        self._images.pop(image_id, None)
        self._phash.pop(image_id, None)
        self._order = [item for item in self._order if item != image_id]
        path = self.images_dir / f"{image_id}.jpg"
        path.unlink(missing_ok=True)

    def _hash_all(self) -> None:
        for image_id in self._order:
            path = self.images_dir / f"{image_id}.jpg"
            try:
                digest = average_hash(path.read_bytes())
            except OSError:
                digest = None
            if digest is not None:
                self._phash[image_id] = digest

    def _near_image(self, phash: int | None) -> str | None:
        if phash is None:
            return None
        best_id = None
        best_dist = _HAMMING_MAX + 1
        for image_id, other in self._phash.items():
            dist = hamming_distance(phash, other)
            if dist < best_dist:
                best_dist = dist
                best_id = image_id
        return best_id if best_dist <= _HAMMING_MAX else None

    def _same_scene(self, image_id: str, texts: list[str], phash: int | None) -> bool:
        if phash is not None and image_id in self._phash:
            dist = hamming_distance(phash, self._phash[image_id])
            if dist <= _HAMMING_MAX:
                return True
            if dist >= _HAMMING_SPLIT:
                return False
        return scenes_overlap(texts, self._images[image_id])

    def compact(self) -> None:
        with self._lock:
            changed = False
            index = 1
            while index < len(self._order):
                image_id = self._order[index]
                texts = self._images[image_id]
                phash = self._phash.get(image_id)
                target = next(
                    (
                        prev
                        for prev in self._order[:index]
                        if self._same_scene(prev, texts, phash)
                    ),
                    None,
                )
                if target is None:
                    index += 1
                    continue
                existing = self._images[target]
                for text in texts:
                    if any(similar_text(text, item) for item in existing):
                        continue
                    existing.append(text)
                self._drop_image(image_id)
                changed = True
            if changed:
                self._rebuild_text_index()
                self._dump()

    def ingest(self, jpeg: bytes, boxes: list) -> dict | None:
        """Un JPEG par scène. Un texte déjà vu ne crée pas une nouvelle image."""
        if not jpeg:
            return None
        texts = unique_texts(boxes)
        if not texts:
            return None
        image_id = hashlib.sha256(jpeg).hexdigest()
        phash = average_hash(jpeg)
        with self._lock:
            visual = self._near_image(phash)
            if visual:
                return self._merge_texts(visual, texts)
            new_texts = [text for text in texts if self._known_image(text) is None]
            if not new_texts:
                return None
            if image_id in self._images:
                return self._merge_texts(image_id, texts)
            path = self.images_dir / f"{image_id}.jpg"
            path.write_bytes(jpeg)
            self._images[image_id] = list(texts)
            self._order.append(image_id)
            if phash is not None:
                self._phash[image_id] = phash
            for text in texts:
                self._text_to_id.setdefault(text_key(text), image_id)
            self._dump()
            return {"id": image_id, "texts": list(texts)}
