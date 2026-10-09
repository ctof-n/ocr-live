"""Traduction avec cache. API Chrome dict, puis MyMemory en secours."""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request

from server.ocr import TextBox

logger = logging.getLogger("ocr-live")

GOOGLE_SL = {
    "auto": "auto",
    "ja": "ja",
    "zh": "zh-CN",
    "ko": "ko",
    "en": "en",
}

_CACHE: dict[tuple[str, str, str], str] = {}
_SKIP = re.compile(r"^[\d\s./:%+\-_|#]+$")
_USER_AGENT = "Mozilla/5.0"


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


def translate_text(text: str, source: str, target: str) -> str:
    key = (text, source, target)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    if _SKIP.match(text) or len(text) < 2:
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
        box.translated = rendered.get(box.text, box.text)
    return boxes
