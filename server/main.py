from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketDisconnected, WebSocketState
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from server.archive import CaptureStore
from server.assets import NO_CACHE, client_version, render_index
from server.capture import capture_window
from server.ocr import normalize_crop
from server.pipeline import LiveOcr
from server.windows import list_windows

ROOT_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT_DIR / "web"
CAPTURES_DIR = ROOT_DIR / "captures"
MIN_FPS = 1
MAX_FPS = 30
DEFAULT_FPS = 10
MIN_WORDS_LIMIT = 3
MAX_WORDS_LIMIT = 99
DEFAULT_MIN_WORDS = 3
MAX_CROP_PCT = 40
DEFAULT_CROP_TOP = 8

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ocr-live")

app = FastAPI(title="ocr-live")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
captures = CaptureStore(CAPTURES_DIR)


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


def _min_words(ws: WebSocket) -> int:
    raw = ws.query_params.get("min_words")
    try:
        value = int(raw) if raw is not None else DEFAULT_MIN_WORDS
    except ValueError:
        value = DEFAULT_MIN_WORDS
    return max(MIN_WORDS_LIMIT, min(MAX_WORDS_LIMIT, value))


def _crop_pct(ws: WebSocket, name: str, default: int = 0) -> int:
    raw = ws.query_params.get(name)
    try:
        value = int(raw) if raw is not None else default
    except ValueError:
        value = default
    return max(0, min(MAX_CROP_PCT, value))


def _crop(ws: WebSocket) -> tuple[float, float, float, float]:
    return normalize_crop(
        _crop_pct(ws, "crop_top", DEFAULT_CROP_TOP) / 100,
        _crop_pct(ws, "crop_right") / 100,
        _crop_pct(ws, "crop_bottom") / 100,
        _crop_pct(ws, "crop_left") / 100,
    )


@app.get("/")
async def index() -> HTMLResponse:
    return HTMLResponse(
        render_index(WEB_DIR),
        headers={"Cache-Control": NO_CACHE, "Pragma": "no-cache"},
    )


@app.get("/api/version")
async def api_version() -> JSONResponse:
    return JSONResponse(
        {"version": client_version(WEB_DIR)},
        headers={"Cache-Control": NO_CACHE, "Pragma": "no-cache"},
    )


@app.get("/api/windows")
async def api_windows() -> dict:
    return {"windows": list_windows()}


@app.get("/api/captures")
async def api_captures() -> dict:
    return {"captures": captures.list_captures()}


@app.post("/api/captures/delete")
async def api_delete_captures(payload: dict = Body(...)) -> dict:
    ids = payload.get("ids")
    if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
        raise HTTPException(status_code=422, detail="ids doit être une liste")
    removed = await asyncio.to_thread(captures.delete, ids)
    return {"deleted": removed}


@app.get("/api/captures/{image_id}.jpg")
async def api_capture_jpeg(image_id: str) -> FileResponse:
    path = captures.jpeg_path(image_id)
    if path is None:
        raise HTTPException(status_code=404)
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


async def _send_json(
    ws: WebSocket, payload: dict, lock: asyncio.Lock | None = None
) -> None:
    if lock is None:
        await ws.send_json(payload)
        return
    async with lock:
        await ws.send_json(payload)


async def _send_ocr(
    ws: WebSocket,
    boxes: list[dict],
    frame_id: int | None = None,
    lock: asyncio.Lock | None = None,
) -> None:
    payload: dict = {"type": "ocr", "boxes": boxes}
    if frame_id is not None:
        payload["frame_id"] = frame_id
    await _send_json(ws, payload, lock)


async def _send_archive(
    ws: WebSocket,
    jpeg: bytes | None,
    boxes: list[dict],
    lock: asyncio.Lock | None = None,
) -> None:
    if not jpeg or not boxes:
        return
    record = await asyncio.to_thread(captures.ingest, jpeg, boxes)
    if not record:
        return
    await _send_json(
        ws,
        {"type": "archive", "id": record["id"], "texts": record["texts"]},
        lock,
    )


@app.websocket("/ws/stream")
async def stream_window(ws: WebSocket) -> None:
    await ws.accept()
    window_id = ws.query_params.get("window_id")
    if not window_id or not window_id.isdigit():
        await ws.close(code=1008, reason="window_id manquant")
        return

    source, target = _langs(ws)
    fps = _fps(ws)
    min_words = _min_words(ws)
    crop = _crop(ws)
    frame_interval = 1 / fps
    wid = int(window_id)
    ocr = LiveOcr()
    ocr_task: asyncio.Task | None = None
    frame_id = 0
    send_lock = asyncio.Lock()
    logger.info(
        "Stream fenêtre %s (%s → %s, %s fps, min %s mot(s), crop %s)",
        wid,
        source,
        target,
        fps,
        min_words,
        crop,
    )
    failures = 0

    try:
        while True:
            frame = await asyncio.to_thread(capture_window, wid)
            if frame:
                failures = 0
                frame_id += 1
                fid = frame_id
                async with send_lock:
                    await ws.send_json({"type": "frame", "id": fid})
                    await ws.send_bytes(frame.jpeg)
                action = ocr.next_action(frame.jpeg)
                if action == "confirm":
                    boxes = await asyncio.to_thread(ocr.confirm_static, source, target)
                    if boxes is not None:
                        await _send_ocr(ws, boxes, fid, send_lock)
                elif action == "ocr" and (ocr_task is None or ocr_task.done()):
                    image = frame.image
                    jpeg = frame.jpeg
                    src, dst = source, target
                    required_words = min_words
                    region = crop

                    async def run_ocr(
                        image=image,
                        jpeg=jpeg,
                        src=src,
                        dst=dst,
                        required_words=required_words,
                        region=region,
                        fid=fid,
                    ) -> None:
                        try:
                            identified, stable = await asyncio.to_thread(
                                ocr.collect,
                                src,
                                jpeg,
                                image,
                                required_words,
                                region,
                            )
                            await _send_ocr(ws, identified, fid, send_lock)
                            await _send_archive(ws, jpeg, identified, send_lock)
                            if stable:
                                boxes = await asyncio.to_thread(
                                    ocr.translate_stable, stable, src, dst
                                )
                                await _send_ocr(ws, boxes, fid, send_lock)
                        except Exception:
                            logger.debug("OCR non envoyé", exc_info=True)

                    ocr_task = asyncio.create_task(run_ocr())
            else:
                failures += 1
                if failures == 1:
                    async with send_lock:
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
    except (WebSocketDisconnect, WebSocketDisconnected):
        logger.info("Client déconnecté")
    except Exception:
        logger.exception("Erreur de stream")
        if ws.client_state == WebSocketState.CONNECTED:
            await ws.close(code=1011)
    finally:
        if ocr_task and not ocr_task.done():
            ocr_task.cancel()


@app.websocket("/ws/analyze")
async def analyze_frames(ws: WebSocket) -> None:
    await ws.accept()
    source, target = _langs(ws)
    min_words = _min_words(ws)
    crop = _crop(ws)
    ocr = LiveOcr()
    frame_id: int | None = None
    logger.info(
        "Analyse navigateur (%s → %s, min %s mot(s), crop %s)",
        source,
        target,
        min_words,
        crop,
    )

    try:
        while True:
            message = await ws.receive()
            text = message.get("text")
            if text:
                try:
                    meta = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if not isinstance(meta, dict):
                    continue
                raw_id = meta.get("id")
                if meta.get("type") == "frame" and isinstance(raw_id, int):
                    frame_id = raw_id
                continue
            jpeg = message.get("bytes")
            if not jpeg:
                continue
            fid = frame_id
            action = ocr.next_action(jpeg)
            if action == "confirm":
                boxes = await asyncio.to_thread(ocr.confirm_static, source, target)
                if boxes is not None:
                    await _send_ocr(ws, boxes, fid)
                continue
            if action != "ocr":
                continue
            identified, stable = await asyncio.to_thread(
                ocr.collect, source, jpeg, None, min_words, crop
            )
            await _send_ocr(ws, identified, fid)
            await _send_archive(ws, jpeg, identified)
            if stable:
                boxes = await asyncio.to_thread(
                    ocr.translate_stable, stable, source, target
                )
                await _send_ocr(ws, boxes, fid)
    except (WebSocketDisconnect, WebSocketDisconnected):
        logger.info("Analyse déconnectée")
    except Exception:
        logger.exception("Erreur d'analyse")
        if ws.client_state == WebSocketState.CONNECTED:
            await ws.close(code=1011)
