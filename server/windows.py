"""Liste les fenêtres visibles via Quartz (Core Graphics)."""

from Quartz import (
    CGWindowListCopyWindowInfo,
    kCGNullWindowID,
    kCGWindowListExcludeDesktopElements,
    kCGWindowListOptionOnScreenOnly,
)

MIN_SIZE = 80


def list_windows() -> list[dict]:
    options = kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements
    raw = CGWindowListCopyWindowInfo(options, kCGNullWindowID) or []
    windows: list[dict] = []

    for item in raw:
        window_id = item.get("kCGWindowNumber")
        bounds = item.get("kCGWindowBounds") or {}
        width = int(bounds.get("Width") or 0)
        height = int(bounds.get("Height") or 0)
        name = (item.get("kCGWindowName") or "").strip()
        owner = (item.get("kCGWindowOwnerName") or "").strip()
        layer = int(item.get("kCGWindowLayer") or 0)

        if not window_id or layer != 0:
            continue
        if width < MIN_SIZE or height < MIN_SIZE:
            continue
        if not name and not owner:
            continue

        label = f"{owner} — {name}" if name else owner
        windows.append(
            {
                "id": int(window_id),
                "title": name,
                "owner": owner,
                "label": label,
                "width": width,
                "height": height,
            }
        )

    windows.sort(key=lambda w: (w["owner"].lower(), w["title"].lower()))
    return windows
