"""Tables Trunic : masque 12 bits → phonème.

Bits (LSB = 0), d’après RuinSeeker / le manuel Tunic :

  0 TLOuter   2 TROuter   5 Left   8 BLOuter  10 BROuter     (voyelles)
  1 TCenter   3 TLInner   4 TRInner  6 BLInner  7 BRInner  9 BCenter
"""

from __future__ import annotations

VOWEL_BITS = 0b0101_0010_0101
CONSONANT_BITS = 0b0010_1101_1010

CONSONANTS: dict[int, str] = {
    0b0000_1000_0010: "b",
    0b0000_1100_0010: "d",
    0b0010_0101_0000: "f",
    0b0010_1001_0000: "g",
    0b0010_1000_0010: "h",
    0b0000_0100_0010: "j",
    0b0000_1001_0010: "k",
    0b0010_0000_0010: "l",
    0b0000_1100_0000: "m",
    0b0000_1100_1000: "n",
    0b0010_0001_0000: "p",
    0b0010_0001_0010: "r",
    0b0010_0101_0010: "s",
    0b0010_0001_1000: "t",
    0b0000_1000_1010: "v",
    0b0000_0001_1000: "w",
    0b0010_0000_1010: "y",
    0b0010_1000_1010: "z",
    0b0010_0000_1000: "ch",
    0b0010_1101_1000: "sh",
    0b0010_1101_1010: "ng",
    0b0010_0001_1010: "th",
    0b0010_1100_0010: "th",
    0b0000_1101_1010: "zh",
}

VOWELS: dict[int, str] = {
    0b0000_0000_0001: "ay",
    0b0101_0010_0001: "ee",
    0b0000_0000_0100: "ie",
    0b0101_0010_0101: "oh",
    0b0000_0010_0101: "a",
    0b0101_0010_0000: "e",
    0b0101_0000_0000: "i",
    0b0000_0010_0001: "o",
    0b0000_0000_0101: "uh",
    0b0001_0010_0000: "ou",
    0b0001_0010_0101: "oo",
    0b0100_0000_0000: "ow",
    0b0001_0000_0000: "oi",
    0b0101_0000_0101: "ar",
    0b0100_0010_0000: "air",
    0b0100_0010_0001: "eer",
    0b0100_0010_0101: "or",
    0b0101_0010_0100: "ir",
}

# Lecture phonétique collée → mot anglais probable.
WORDS: dict[str, str] = {
    "uh": "the",
    "thu": "the",
    "thuh": "the",
    "yoo": "you",
    "hoo": "who",
    "too": "to",
    "bee": "be",
    "see": "see",
    "in": "in",
    "iz": "is",
    "it": "it",
    "ov": "of",
    "az": "as",
    "ar": "are",
    "mor": "more",
    "and": "and",
    "kan": "can",
    "did": "did",
    "them": "them",
    "tiem": "time",
    "tunik": "tunic",
    "toonik": "tunic",
    "toonikk": "tunic",
    "fox": "fox",
    "key": "key",
    "kay": "key",
    "door": "door",
    "dor": "door",
    "west": "west",
    "east": "east",
    "save": "save",
    "pray": "pray",
}


def _closest(mask: int, table: dict[int, str]) -> str | None:
    if mask == 0:
        return None
    if mask in table:
        return table[mask]
    best_key = None
    best_dist = 3
    for key in table:
        dist = (key ^ mask).bit_count()
        if dist < best_dist:
            best_dist = dist
            best_key = key
    if best_key is not None and best_dist <= 1:
        return table[best_key]
    return None


def decode_mask(mask: int, swap: bool) -> list[str]:
    consonant = _closest(mask & CONSONANT_BITS, CONSONANTS)
    vowel = _closest(mask & VOWEL_BITS, VOWELS)
    parts = [p for p in (consonant, vowel) if p]
    if swap:
        parts.reverse()
    return parts


def tokens_to_english(tokens: list[str]) -> str:
    if not tokens:
        return ""
    joined = "".join(tokens)
    return WORDS.get(joined, joined)
