"""Version du front : cache-busting + rechargement auto."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

BOOT_ID = uuid.uuid4().hex[:8]
PLACEHOLDER = "__ASSET_VERSION__"
NO_CACHE = "no-cache, no-store, must-revalidate"


def files_version(paths: list[Path]) -> str:
    parts: list[str] = []
    for path in sorted(paths, key=lambda item: item.as_posix()):
        if not path.is_file():
            continue
        stat = path.stat()
        parts.append(f"{path.name}:{stat.st_mtime_ns}:{stat.st_size}")
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:12]


def web_files(web_dir: Path) -> list[Path]:
    return [path for path in web_dir.iterdir() if path.is_file()]


def client_version(web_dir: Path) -> str:
    return f"{BOOT_ID}-{files_version(web_files(web_dir))}"


def render_index(web_dir: Path) -> str:
    html = (web_dir / "index.html").read_text(encoding="utf-8")
    return html.replace(PLACEHOLDER, client_version(web_dir))
