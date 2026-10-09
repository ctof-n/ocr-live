from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from server.capture import capture_window
from server.pipeline import LiveOcr
from server.windows import list_windows

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
MIN_FPS = 1
MAX_FPS = 30
DEFAULT_FPS = 10

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ocr-live")

app = FastAPI(title="ocr-live")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


def _langs(ws: WebSocket) -> tuple[str, str]:
    source = ws.query_params.get("source") or "auto"
    target = ws.query_params.get("target") or "fr"
    return source, target


def _fps(ws: WebSocket) -> int:
    raw = ws.query_params.get("fps")
    try:
        value = int(raw) if raw is not None else DEFAULT_FPS
    except ValueError:
        value = DEFAULT_FPS
    return max(MIN_FPS, min(MAX_FPS, value))


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/windows")
async def api_windows() -> dict:
    return {"windows": list_windows()}


async def _send_ocr(ws: WebSocket, boxes: list[dict]) -> None:
    await ws.send_json({"type": "ocr", "boxes": boxes})


@app.websocket("/ws/stream")
async def stream_window(ws: WebSocket) -> None:
    await ws.accept()
    window_id = ws.query_params.get("window_id")
    if not window_id or not window_id.isdigit():
        await ws.close(code=1008, reason="window_id manquant")
        return

    source, target = _langs(ws)
    fps = _fps(ws)
    frame_interval = 1 / fps
    wid = int(window_id)
    ocr = LiveOcr()
    ocr_task: asyncio.Task | None = None
    logger.info("Stream fenêtre %s (%s → %s, %s fps)", wid, source, target, fps)
    failures = 0

    try:
        while True:
            frame = await asyncio.to_thread(capture_window, wid)
            if frame:
                failures = 0
                await ws.send_bytes(frame.jpeg)
                if ocr.should_run(frame.jpeg) and (ocr_task is None or ocr_task.done()):
                    image = frame.image
                    jpeg = frame.jpeg
                    src, dst = source, target

                    async def run_ocr() -> None:
                        try:
                            boxes = await asyncio.to_thread(
                                ocr.run_image, image, src, dst, jpeg
                            )
                            await _send_ocr(ws, boxes)
                        except Exception:
                            logger.debug("OCR non envoyé", exc_info=True)

                    ocr_task = asyncio.create_task(run_ocr())
            else:
                failures += 1
                if failures == 1:
                    await ws.send_json(
                        {
                            "type": "error",
                            "message": "Image vide. Autorise l'enregistrement d'écran pour Cursor / Terminal, et mets le jeu en fenêtré.",
                        }
                    )
                if failures > 30:
                    await ws.close(code=1011, reason="capture impossible")
                    return
            await asyncio.sleep(frame_interval)
    except WebSocketDisconnect:
        logger.info("Client déconnecté")
    except Exception:
        logger.exception("Erreur de stream")
        await ws.close(code=1011)
    finally:
        if ocr_task and not ocr_task.done():
            ocr_task.cancel()


@app.websocket("/ws/analyze")
async def analyze_frames(ws: WebSocket) -> None:
    await ws.accept()
    source, target = _langs(ws)
    ocr = LiveOcr()
    logger.info("Analyse navigateur (%s → %s)", source, target)

    try:
        while True:
            message = await ws.receive()
            jpeg = message.get("bytes")
            if not jpeg:
                continue
            if not ocr.should_run(jpeg):
                continue
            boxes = await asyncio.to_thread(ocr.run_jpeg, jpeg, source, target)
            await _send_ocr(ws, boxes)
    except WebSocketDisconnect:
        logger.info("Analyse déconnectée")
    except Exception:
        logger.exception("Erreur d'analyse")
        await ws.close(code=1011)
