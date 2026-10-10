"""Traduction avec cache. API Chrome dict, puis MyMemory en secours."""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request

from server.ocr import TextBox, is_numeric_group

logger = logging.getLogger("ocr-live")

GOOGLE_SL = {
    "auto": "auto",
    "ja": "ja",
    "zh": "zh-CN",
    "ko": "ko",
    "en": "en",
    "tunic": "en",
}

_CACHE: dict[tuple[str, str, str], str] = {}
_SKIP = re.compile(r"^[\d０-９\s.,:;/\-–—+%#|_×xX=()[\]~～'’`°*]+$")
_USER_AGENT = "Mozilla/5.0"
_KANA = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff]")
_HANGUL = re.compile(r"[\uac00-\ud7af]")
_HAN = re.compile(r"[\u3400-\u9fff]")
_FR_ORTHO = re.compile(r"[àâäéèêëïîôùûüçœæÀÂÄÉÈÊËÏÎÔÙÛÜÇŒÆ]")
_WORDS = re.compile(r"[A-Za-zÀ-ÿœæŒÆ']+")
_FR_WORDS = frozenset(
    {
        "alors",
        "aussi",
        "avec",
        "au",
        "ce",
        "de",
        "du",
        "et",
        "il",
        "je",
        "la",
        "le",
        "ne",
        "se",
        "tu",
        "un",
        "cette",
        "comme",
        "dans",
        "des",
        "elle",
        "est",
        "être",
        "fait",
        "les",
        "leur",
        "mais",
        "même",
        "nous",
        "pas",
        "plus",
        "pour",
        "que",
        "qui",
        "sans",
        "sont",
        "sur",
        "une",
        "vous",
        "aux",
        "par",
        "ces",
        "tout",
        "très",
        "deux",
        "entre",
        "quand",
        "après",
        "avait",
        "était",
        "avoir",
        "faire",
        "dit",
        "peut",
    }
)
_EN_WORDS = frozenset(
    {
        "the",
        "and",
        "of",
        "to",
        "in",
        "is",
        "that",
        "for",
        "with",
        "on",
        "as",
        "are",
        "this",
        "was",
        "from",
        "by",
        "or",
        "be",
        "at",
        "not",
        "have",
        "it",
        "you",
        "he",
        "she",
        "they",
        "we",
        "his",
        "her",
        "their",
        "but",
        "which",
        "when",
        "if",
        "there",
        "been",
        "has",
        "had",
        "were",
        "will",
        "would",
        "can",
        "into",
        "than",
        "then",
        "them",
        "these",
        "those",
        "about",
        "through",
        "after",
        "before",
        "over",
        "its",
    }
)


def _parse_google(payload: object) -> str:
    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, str):
            return first
        if isinstance(first, list):
            parts = []
            for item in payload:
                if isinstance(item, list) and item and isinstance(item[0], str):
                    parts.append(item[0])
            return "".join(parts)
    return ""


def _google(text: str, source: str, target: str) -> str | None:
    url = "https://clients5.google.com/translate_a/t?" + urllib.parse.urlencode(
        {
            "client": "dict-chrome-ex",
            "sl": GOOGLE_SL.get(source, "auto"),
            "tl": target,
            "q": text,
        }
    )
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=8) as response:
        payload = json.loads(response.read().decode())
    result = _parse_google(payload).strip()
    return result or None


def _mymemory(text: str, source: str, target: str) -> str | None:
    pair_source = "ja" if source == "auto" else GOOGLE_SL.get(source, source)
    url = "https://api.mymemory.translated.net/get?" + urllib.parse.urlencode(
        {"q": text, "langpair": f"{pair_source}|{target}"}
    )
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=8) as response:
        payload = json.loads(response.read().decode())
    result = (payload.get("responseData") or {}).get("translatedText") or ""
    result = str(result).strip()
    return result or None


def _lang_prefix(code: str) -> str:
    return (code or "").split("-")[0].lower()


def _same_lang(a: str, b: str) -> bool:
    left, right = _lang_prefix(a), _lang_prefix(b)
    return bool(left) and left == right


def detect_language(text: str) -> str | None:
    """Langue probable du texte, ou None si le signal est trop faible."""
    if _KANA.search(text):
        return "ja"
    if _HANGUL.search(text):
        return "ko"
    if _HAN.search(text):
        return "zh"
    tokens = [token for token in (match.group(0).lower() for match in _WORDS.finditer(text)) if len(token) >= 2]
    if not tokens:
        return None
    fr_hits = sum(1 for token in tokens if token in _FR_WORDS)
    en_hits = sum(1 for token in tokens if token in _EN_WORDS)
    french_spelling = bool(_FR_ORTHO.search(text))
    if french_spelling and fr_hits >= en_hits and (fr_hits >= 1 or len(tokens) >= 4):
        return "fr"
    if fr_hits >= 2 and fr_hits > en_hits:
        return "fr"
    if en_hits >= 2 and en_hits > fr_hits and not french_spelling:
        return "en"
    return None


def is_target_language(text: str, target: str, source: str = "auto") -> bool:
    if source == "tunic":
        return False
    detected = detect_language(text)
    return detected is not None and _same_lang(detected, target)


def translate_text(text: str, source: str, target: str) -> str:
    key = (text, source, target)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    if (
        is_numeric_group(text)
        or _SKIP.match(text)
        or len(text) < 2
        or (
            source != "tunic"
            and _lang_prefix(source) not in {"", "auto"}
            and _same_lang(source, target)
        )
        or is_target_language(text, target, source)
    ):
        _CACHE[key] = text
        return text

    translated = text
    try:
        translated = _google(text, source, target) or text
    except Exception:
        logger.exception("Google Translate a échoué")
        try:
            translated = _mymemory(text, source, target) or text
        except Exception:
            logger.exception("MyMemory a échoué")

    if len(_CACHE) > 4000:
        _CACHE.clear()
    _CACHE[key] = translated
    return translated


def translate_boxes(boxes: list[TextBox], source: str, target: str) -> list[TextBox]:
    unique: list[str] = []
    seen: set[str] = set()
    for box in boxes:
        if box.text not in seen:
            seen.add(box.text)
            unique.append(box.text)

    rendered = {text: translate_text(text, source, target) for text in unique}
    for box in boxes:
        translated = rendered.get(box.text, box.text)
        box.translated = translated
        box.native = is_target_language(box.text, target, source)
    return boxes
