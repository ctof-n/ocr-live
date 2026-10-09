"""Géométrie d’un glyphe Trunic (hexagone allongé, trait droit à gauche)."""

from __future__ import annotations

# Nom → bit (None = toujours présent, pas dans le masque)
SEGMENTS: dict[str, int | None] = {
    "TLOuter": 0,
    "TCenter": 1,
    "TROuter": 2,
    "TLInner": 3,
    "TRInner": 4,
    "Left": 5,
    "BLInner": 6,
    "BRInner": 7,
    "BLOuter": 8,
    "BCenter": 9,
    "BROuter": 10,
    "Base": None,
}

# Points normalisés 0–1 dans le glyphe : (x, y) depuis le haut-gauche.
VERTICES = {
    "top": (0.50, 0.06),
    "ul": (0.14, 0.28),
    "ur": (0.86, 0.28),
    "ml": (0.14, 0.50),
    "mr": (0.86, 0.50),
    "ll": (0.14, 0.72),
    "lr": (0.86, 0.72),
    "bot": (0.50, 0.90),
    "center": (0.50, 0.50),
    "swap": (0.50, 0.97),
}

SEGMENT_ENDS = {
    "TLOuter": ("top", "ul"),
    "TROuter": ("top", "ur"),
    "Left": ("ul", "ll"),
    "BLOuter": ("ll", "bot"),
    "BROuter": ("lr", "bot"),
    "TCenter": ("top", "center"),
    "BCenter": ("bot", "center"),
    "TLInner": ("ul", "center"),
    "TRInner": ("ur", "center"),
    "BLInner": ("ll", "center"),
    "BRInner": ("lr", "center"),
    "Base": ("ml", "mr"),
}


def lerp(a: tuple[float, float], b: tuple[float, float], t: float) -> tuple[float, float]:
    return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t


def segment_samples(name: str, count: int = 7) -> list[tuple[float, float]]:
    start_name, end_name = SEGMENT_ENDS[name]
    start, end = VERTICES[start_name], VERTICES[end_name]
    # Évite les extrémités (coins partagés / barre centrale).
    return [lerp(start, end, 0.22 + 0.56 * i / (count - 1)) for i in range(count)]
