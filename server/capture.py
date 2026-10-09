"""Capture d'une fenêtre macOS en JPEG.

Utilise CGWindowListCreateImage : simple, suffisant pour de l'OCR (~8–12 fps).
Les jeux Metal en plein écran exclusif peuvent renvoyer une image noire ;
dans ce cas, passer le jeu en fenêtré ou utiliser la capture navigateur.
"""

from dataclasses import dataclass

from Cocoa import NSBitmapImageRep, NSJPEGFileType
from Quartz import (
    CGImageGetHeight,
    CGImageGetWidth,
    CGRectNull,
    CGWindowListCreateImage,
    kCGWindowImageBestResolution,
    kCGWindowImageBoundsIgnoreFraming,
    kCGWindowListOptionIncludingWindow,
)

JPEG_QUALITY = 0.55


@dataclass
class Frame:
    jpeg: bytes
    image: object
    width: int
    height: int


def _encode_jpeg(image) -> bytes | None:
    rep = NSBitmapImageRep.alloc().initWithCGImage_(image)
    if rep is None:
        return None
    data = rep.representationUsingType_properties_(
        NSJPEGFileType,
        {"NSImageCompressionFactor": JPEG_QUALITY},
    )
    if data is None:
        return None
    return bytes(data)


def capture_window(window_id: int) -> Frame | None:
    image = CGWindowListCreateImage(
        CGRectNull,
        kCGWindowListOptionIncludingWindow,
        window_id,
        kCGWindowImageBoundsIgnoreFraming | kCGWindowImageBestResolution,
    )
    if image is None:
        return None

    jpeg = _encode_jpeg(image)
    if not jpeg:
        return None

    return Frame(
        jpeg=jpeg,
        image=image,
        width=int(CGImageGetWidth(image)),
        height=int(CGImageGetHeight(image)),
    )
