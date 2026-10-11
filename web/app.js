const windowsEl = document.querySelector("#windows");
const refreshBtn = document.querySelector("#refresh");
const startBtn = document.querySelector("#start");
const stopBtn = document.querySelector("#stop");
const browserBtn = document.querySelector("#browser-capture");
const statusEl = document.querySelector("#status");
const frameEl = document.querySelector("#frame");
const videoEl = document.querySelector("#browser-video");
const overlayEl = document.querySelector("#overlay");
const captionsEl = document.querySelector("#captions");
const captionListEl = document.querySelector("#caption-list");
const placeholderEl = document.querySelector("#placeholder");
const stageEl = document.querySelector("#stage");
const sourceEl = document.querySelector("#source");
const targetEl = document.querySelector("#target");
const fpsEl = document.querySelector("#fps");
const fpsValueEl = document.querySelector("#fps-value");
const minWordsEl = document.querySelector("#min-words");
const cropTopEl = document.querySelector("#crop-top");
const cropBottomEl = document.querySelector("#crop-bottom");
const cropLeftEl = document.querySelector("#crop-left");
const cropRightEl = document.querySelector("#crop-right");
const cropTopValueEl = document.querySelector("#crop-top-value");
const cropBottomValueEl = document.querySelector("#crop-bottom-value");
const cropLeftValueEl = document.querySelector("#crop-left-value");
const cropRightValueEl = document.querySelector("#crop-right-value");
const showBubblesEl = document.querySelector("#show-bubbles");

const SETTINGS_KEY = "ocr-live.settings";

let socket = null;
let objectUrl = null;
let browserStream = null;
let captureMode = null;
let boxes = [];
let captionSignature = "";
let analyzeTimer = 0;
let analyzeBusy = false;
const grabCanvas = document.createElement("canvas");
const sampleCanvas = document.createElement("canvas");
const sampleCtx = sampleCanvas.getContext("2d", { willReadFrequently: true });
const DEFAULT_BUBBLE_BG = "rgba(12, 14, 20, 0.86)";
const DEFAULT_BUBBLE_FG = "#f4f6fb";
const PLACEHOLDER_IDLE = "Choisis une fenêtre à gauche";

function loadSettings() {
  try {
    const stored = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}");
    return stored && typeof stored === "object" ? stored : {};
  } catch {
    return {};
  }
}

function saveSettings() {
  const settings = {
    source: sourceEl.value,
    target: targetEl.value,
    fps: selectedFps(),
    minWords: selectedMinWords(),
    cropTop: selectedCropPct(cropTopEl, 8),
    cropBottom: selectedCropPct(cropBottomEl),
    cropLeft: selectedCropPct(cropLeftEl),
    cropRight: selectedCropPct(cropRightEl),
    showBubbles: showBubblesEl.checked,
    windowId: windowsEl.value,
  };
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

function applySettings() {
  const settings = loadSettings();
  const sourceOk = [...sourceEl.options].some((option) => option.value === settings.source);
  if (sourceOk) sourceEl.value = settings.source;
  const targetOk = [...targetEl.options].some((option) => option.value === settings.target);
  if (targetOk) targetEl.value = settings.target;
  if (Number.isFinite(settings.fps)) {
    fpsEl.value = String(Math.min(30, Math.max(1, Math.round(settings.fps))));
  }
  if (Number.isFinite(settings.minWords)) {
    minWordsEl.value = String(Math.min(99, Math.max(3, Math.round(settings.minWords))));
  }
  applyCropValue(cropTopEl, settings.cropTop, 8);
  applyCropValue(cropBottomEl, settings.cropBottom, 0);
  applyCropValue(cropLeftEl, settings.cropLeft, 0);
  applyCropValue(cropRightEl, settings.cropRight, 0);
  if (typeof settings.showBubbles === "boolean") {
    showBubblesEl.checked = settings.showBubbles;
  }
  syncFpsLabel();
  syncCropLabels();
}

function restoreWindow(windowId) {
  if (!windowId) return;
  const match = [...windowsEl.options].find((option) => option.value === String(windowId));
  if (match) windowsEl.value = match.value;
}

function setStatus(text, isError = false) {
  statusEl.textContent = text;
  statusEl.classList.toggle("error", isError);
}

function selectedFps() {
  const value = Number(fpsEl.value);
  if (!Number.isFinite(value)) return 10;
  return Math.min(30, Math.max(1, Math.round(value)));
}

function selectedMinWords() {
  const value = Number(minWordsEl.value);
  if (!Number.isFinite(value)) return 3;
  return Math.min(99, Math.max(3, Math.round(value)));
}

function selectedCropPct(el, fallback = 0) {
  const value = Number(el.value);
  if (!Number.isFinite(value)) return fallback;
  return Math.min(40, Math.max(0, Math.round(value)));
}

function applyCropValue(el, value, fallback) {
  if (!Number.isFinite(value)) {
    el.value = String(fallback);
    return;
  }
  el.value = String(Math.min(40, Math.max(0, Math.round(value))));
}

function selectedCrop() {
  return {
    top: selectedCropPct(cropTopEl, 8) / 100,
    bottom: selectedCropPct(cropBottomEl) / 100,
    left: selectedCropPct(cropLeftEl) / 100,
    right: selectedCropPct(cropRightEl) / 100,
  };
}

function streamQuery() {
  return (
    `source=${encodeURIComponent(sourceEl.value)}&target=${encodeURIComponent(targetEl.value)}` +
    `&fps=${selectedFps()}&min_words=${selectedMinWords()}` +
    `&crop_top=${selectedCropPct(cropTopEl, 8)}&crop_bottom=${selectedCropPct(cropBottomEl)}` +
    `&crop_left=${selectedCropPct(cropLeftEl)}&crop_right=${selectedCropPct(cropRightEl)}`
  );
}

function syncFpsLabel() {
  fpsValueEl.value = String(selectedFps());
}

function syncCropLabels() {
  cropTopValueEl.value = `${selectedCropPct(cropTopEl, 8)}%`;
  cropBottomValueEl.value = `${selectedCropPct(cropBottomEl)}%`;
  cropLeftValueEl.value = `${selectedCropPct(cropLeftEl)}%`;
  cropRightValueEl.value = `${selectedCropPct(cropRightEl)}%`;
}

function analyzeIntervalMs() {
  return Math.max(33, Math.round(1000 / selectedFps()));
}

function startAnalyzeTimer() {
  window.clearInterval(analyzeTimer);
  analyzeTimer = window.setInterval(() => {
    sendVideoFrame().catch(() => {});
  }, analyzeIntervalMs());
}

function connectAnalyzeSocket() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const current = new WebSocket(`${protocol}://${location.host}/ws/analyze?${streamQuery()}`);
  socket = current;
  socket.binaryType = "blob";
  socket.addEventListener("message", handleSocketMessage);
  socket.addEventListener("open", startAnalyzeTimer);
  socket.addEventListener("close", () => {
    if (socket !== current) return;
    window.clearInterval(analyzeTimer);
    analyzeTimer = 0;
  });
}

function restartAnalyzeSocket() {
  if (socket) {
    const old = socket;
    socket = null;
    old.close();
  }
  connectAnalyzeSocket();
}

function applyMinWords() {
  minWordsEl.value = String(selectedMinWords());
  restartActiveStream();
}

function restartActiveStream() {
  if (browserStream) {
    restartAnalyzeSocket();
    return;
  }
  if (socket && windowsEl.value) startNativeStream();
}

function applyCrop() {
  syncCropLabels();
  restartActiveStream();
}

function showNativeFrame() {
  captureMode = "native";
  placeholderEl.textContent = PLACEHOLDER_IDLE;
  placeholderEl.hidden = true;
  videoEl.hidden = true;
  videoEl.srcObject = null;
  frameEl.hidden = false;
  captionsEl.hidden = false;
  requestAnimationFrame(drawOverlay);
}

function showBrowserVideo() {
  captureMode = "browser";
  placeholderEl.textContent = PLACEHOLDER_IDLE;
  placeholderEl.hidden = true;
  frameEl.hidden = true;
  frameEl.removeAttribute("src");
  videoEl.hidden = false;
  captionsEl.hidden = false;
  requestAnimationFrame(drawOverlay);
}

function revokeFrame() {
  if (objectUrl) {
    URL.revokeObjectURL(objectUrl);
    objectUrl = null;
  }
}

function clearOverlay() {
  boxes = [];
  captionSignature = "";
  const ctx = overlayEl.getContext("2d");
  ctx.clearRect(0, 0, overlayEl.width, overlayEl.height);
  captionsEl.hidden = true;
  captionListEl.replaceChildren();
}

function stopNativeStream() {
  if (socket) {
    socket.close();
    socket = null;
  }
  stopBtn.disabled = true;
}

function stopBrowserStream() {
  window.clearInterval(analyzeTimer);
  analyzeTimer = 0;
  if (browserStream) {
    for (const track of browserStream.getTracks()) track.stop();
    browserStream = null;
    videoEl.srcObject = null;
  }
}

function stopAll() {
  stopNativeStream();
  stopBrowserStream();
  revokeFrame();
  clearOverlay();
  captureMode = null;
  placeholderEl.textContent = PLACEHOLDER_IDLE;
  frameEl.hidden = true;
  frameEl.removeAttribute("src");
  videoEl.hidden = true;
  videoEl.srcObject = null;
  placeholderEl.hidden = false;
  setStatus("Arrêté");
}

function handleSocketMessage(event) {
  if (typeof event.data === "string") {
    const payload = JSON.parse(event.data);
    if (payload.type === "error") setStatus(payload.message, true);
    if (payload.type === "ocr") {
      applyOcrBoxes(payload.boxes || []);
      setStatus(`${boxes.length} texte${boxes.length > 1 ? "s" : ""}`);
      drawOverlay();
    }
    return;
  }
  if (captureMode !== "native") return;
  revokeFrame();
  objectUrl = URL.createObjectURL(event.data);
  frameEl.src = objectUrl;
  showNativeFrame();
}

async function loadWindows() {
  const response = await fetch("/api/windows");
  const data = await response.json();
  windowsEl.innerHTML = "";
  for (const win of data.windows) {
    const option = document.createElement("option");
    option.value = String(win.id);
    option.textContent = `${win.label} (${win.width}×${win.height})`;
    windowsEl.append(option);
  }
  restoreWindow(loadSettings().windowId);
  setStatus(`${data.windows.length} fenêtres`);
}

function startNativeStream() {
  const windowId = windowsEl.value;
  if (!windowId) {
    setStatus("Sélectionne une fenêtre", true);
    return;
  }

  saveSettings();
  stopAll();
  captureMode = "native";
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(
    `${protocol}://${location.host}/ws/stream?window_id=${windowId}&${streamQuery()}`,
  );
  socket.binaryType = "blob";
  stopBtn.disabled = false;
  setStatus(`Traduction fenêtre ${windowId}…`);

  const current = socket;
  socket.addEventListener("message", handleSocketMessage);
  socket.addEventListener("close", () => {
    if (socket !== current) return;
    socket = null;
    stopBtn.disabled = true;
    setStatus("Connexion fermée");
  });
}

function drawCropMask(ctx, media) {
  const crop = selectedCrop();
  const x = media.x + crop.left * media.w;
  const y = media.y + crop.top * media.h;
  const w = Math.max(0, media.w * (1 - crop.left - crop.right));
  const h = Math.max(0, media.h * (1 - crop.top - crop.bottom));
  if (crop.top + crop.bottom + crop.left + crop.right <= 0) return;
  ctx.save();
  ctx.beginPath();
  ctx.rect(media.x, media.y, media.w, media.h);
  ctx.rect(x, y, w, h);
  ctx.fillStyle = "rgba(8, 10, 16, 0.55)";
  ctx.fill("evenodd");
  ctx.strokeStyle = "rgba(110, 168, 254, 0.75)";
  ctx.lineWidth = 1.5;
  ctx.strokeRect(x + 0.75, y + 0.75, Math.max(0, w - 1.5), Math.max(0, h - 1.5));
  ctx.restore();
}

function splitToken(ctx, token, maxWidth) {
  if (ctx.measureText(token).width <= maxWidth) return [token];
  const parts = [];
  let chunk = "";
  for (const char of token) {
    const trial = chunk + char;
    if (chunk && ctx.measureText(trial).width > maxWidth) {
      parts.push(chunk);
      chunk = char;
    } else {
      chunk = trial;
    }
  }
  if (chunk) parts.push(chunk);
  return parts;
}

function wrapText(ctx, text, maxWidth) {
  const words = text.split(/\s+/).flatMap((word) => splitToken(ctx, word, maxWidth));
  const lines = [];
  let line = "";
  for (const word of words) {
    const trial = line ? `${line} ${word}` : word;
    if (!line || ctx.measureText(trial).width <= maxWidth) line = trial;
    else {
      lines.push(line);
      line = word;
    }
  }
  if (line) lines.push(line);
  return lines;
}

function fitBubbleText(ctx, text, maxWidth, maxHeight) {
  const family = "ui-sans-serif, system-ui, sans-serif";
  const minFont = 6;
  const maxFont = Math.max(minFont, Math.floor(Math.min(42, maxHeight)));
  let bestFont = minFont;
  ctx.font = `600 ${minFont}px ${family}`;
  let bestLines = wrapText(ctx, text, maxWidth);
  let low = minFont;
  let high = maxFont;
  while (low <= high) {
    const font = Math.floor((low + high) / 2);
    ctx.font = `600 ${font}px ${family}`;
    const lines = wrapText(ctx, text, maxWidth);
    const fits =
      lines.length * font * 1.2 <= maxHeight &&
      lines.every((line) => ctx.measureText(line).width <= maxWidth);
    if (fits) {
      bestFont = font;
      bestLines = lines;
      low = font + 1;
    } else {
      high = font - 1;
    }
  }
  ctx.font = `600 ${bestFont}px ${family}`;
  return { font: bestFont, lines: bestLines };
}

function sourceMediaElement() {
  if (captureMode === "browser" || (browserStream && frameEl.hidden)) return videoEl;
  return frameEl;
}

function mediaPixelSize(media) {
  if (media === videoEl) return { w: media.videoWidth, h: media.videoHeight };
  return { w: media.naturalWidth, h: media.naturalHeight };
}

function rgbCss(color) {
  return `rgb(${color.r}, ${color.g}, ${color.b})`;
}

function luma(r, g, b) {
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function colorDist2(a, b) {
  const dr = a.r - b.r;
  const dg = a.g - b.g;
  const db = a.b - b.b;
  return dr * dr + dg * dg + db * db;
}

function meanColor(pixels) {
  let r = 0;
  let g = 0;
  let b = 0;
  for (const pixel of pixels) {
    r += pixel.r;
    g += pixel.g;
    b += pixel.b;
  }
  const n = pixels.length || 1;
  return { r: Math.round(r / n), g: Math.round(g / n), b: Math.round(b / n) };
}

function contrastInk(bg) {
  return luma(bg.r, bg.g, bg.b) > 140
    ? { r: 28, g: 22, b: 16 }
    : { r: 244, g: 246, b: 251 };
}

function darkestColor(pixels) {
  if (!pixels.length) return null;
  const ranked = pixels
    .map((pixel) => ({ pixel, l: luma(pixel.r, pixel.g, pixel.b) }))
    .sort((a, b) => a.l - b.l);
  const take = Math.max(1, Math.ceil(ranked.length * 0.2));
  return meanColor(ranked.slice(0, take).map((item) => item.pixel));
}

function splitPalette(data, width, height) {
  const pixels = [];
  const border = [];
  const margin = Math.max(1, Math.round(Math.min(width, height) * 0.18));
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const i = (y * width + x) * 4;
      const pixel = { r: data[i], g: data[i + 1], b: data[i + 2] };
      pixels.push(pixel);
      if (x < margin || y < margin || x >= width - margin || y >= height - margin) {
        border.push(pixel);
      }
    }
  }
  if (!pixels.length) return null;

  let dark = pixels[0];
  let light = pixels[0];
  let darkL = 256;
  let lightL = -1;
  for (const pixel of pixels) {
    const value = luma(pixel.r, pixel.g, pixel.b);
    if (value < darkL) {
      darkL = value;
      dark = pixel;
    }
    if (value > lightL) {
      lightL = value;
      light = pixel;
    }
  }

  let c0 = { r: dark.r, g: dark.g, b: dark.b };
  let c1 = { r: light.r, g: light.g, b: light.b };
  let group0 = [];
  let group1 = [];
  for (let iter = 0; iter < 6; iter += 1) {
    group0 = [];
    group1 = [];
    for (const pixel of pixels) {
      (colorDist2(pixel, c0) <= colorDist2(pixel, c1) ? group0 : group1).push(pixel);
    }
    if (!group0.length || !group1.length) break;
    c0 = meanColor(group0);
    c1 = meanColor(group1);
  }

  if (!group0.length || !group1.length) {
    const bg = meanColor(border.length ? border : pixels);
    return { bg, fg: contrastInk(bg) };
  }

  let border0 = 0;
  for (const pixel of border) {
    if (colorDist2(pixel, c0) <= colorDist2(pixel, c1)) border0 += 1;
  }
  const c0IsBg = border.length ? border0 >= border.length / 2 : group0.length >= group1.length;
  const ink = c0IsBg ? group1 : group0;
  const bg = c0IsBg ? c0 : c1;
  let fg = c0IsBg ? c1 : c0;
  if (luma(fg.r, fg.g, fg.b) < luma(bg.r, bg.g, bg.b)) {
    fg = darkestColor(ink) || fg;
  }
  if (Math.abs(luma(fg.r, fg.g, fg.b) - luma(bg.r, bg.g, bg.b)) < 36) {
    fg = contrastInk(bg);
  }
  return { bg, fg };
}

function sampleBoxColors(box) {
  const media = sourceMediaElement();
  if (!media || media.hidden) return null;
  const size = mediaPixelSize(media);
  if (!size.w || !size.h) return null;

  const padX = box.w * 0.08;
  const padY = box.h * 0.14;
  const x0 = Math.max(0, Math.floor((box.x - padX) * size.w));
  const y0 = Math.max(0, Math.floor((box.y - padY) * size.h));
  const x1 = Math.min(size.w, Math.ceil((box.x + box.w + padX) * size.w));
  const y1 = Math.min(size.h, Math.ceil((box.y + box.h + padY) * size.h));
  const sw = Math.max(1, x1 - x0);
  const sh = Math.max(1, y1 - y0);
  const scale = Math.min(1, 40 / Math.max(sw, sh));
  const dw = Math.max(6, Math.round(sw * scale));
  const dh = Math.max(6, Math.round(sh * scale));
  sampleCanvas.width = dw;
  sampleCanvas.height = dh;
  try {
    sampleCtx.drawImage(media, x0, y0, sw, sh, 0, 0, dw, dh);
    const { data } = sampleCtx.getImageData(0, 0, dw, dh);
    return splitPalette(data, dw, dh);
  } catch {
    return null;
  }
}

function paletteFor(box) {
  if (box._palette) return box._palette;
  const palette = sampleBoxColors(box);
  if (palette) box._palette = palette;
  return palette;
}

function sameWording(left, right) {
  const norm = (value) => String(value || "").replace(/\s+/g, " ").trim().toLowerCase();
  return norm(left) === norm(right);
}

function findPreviousBox(incoming) {
  return boxes.find(
    (item) =>
      sameWording(item.text, incoming.text) &&
      Math.abs(item.x - incoming.x) <= 0.05 &&
      Math.abs(item.y - incoming.y) <= 0.05,
  );
}

function applyOcrBoxes(incoming) {
  boxes = incoming.map((box) => {
    const prev = findPreviousBox(box);
    if (!prev) return box;
    const next = { ...box };
    if (next.pending && (prev.translated || "").trim()) {
      next.translated = prev.translated;
      next.pending = false;
      next.native = prev.native;
    }
    if (prev._palette) next._palette = prev._palette;
    if (!next.align && prev.align) next.align = prev.align;
    return next;
  });
}

function needsBubble(box) {
  if (box.pending || !(box.translated || "").trim()) return false;
  if (sourceEl.value === "tunic") return Boolean(box.translated || box.text);
  if (box.native) return false;
  return !sameWording(box.text, box.translated);
}

function mediaRect() {
  const media = sourceMediaElement();
  if (!media || media.hidden) return null;
  const stage = stageEl.getBoundingClientRect();
  const rect = media.getBoundingClientRect();
  return {
    x: rect.left - stage.left,
    y: rect.top - stage.top,
    w: rect.width,
    h: rect.height,
  };
}

function updateCaptions() {
  const signature = boxes
    .map((box) => `${box.text}\0${box.translated || ""}\0${box.pending ? "1" : "0"}`)
    .join("\n");
  if (signature === captionSignature) return;
  captionSignature = signature;
  captionListEl.replaceChildren();
  if (!boxes.length) return;
  for (const box of boxes) {
    const row = document.createElement("article");
    row.className = "caption-row";
    const source = document.createElement("p");
    source.className = "caption-source";
    source.textContent = box.text;
    const target = document.createElement("p");
    target.className = "caption-target";
    const translated = (box.translated || "").trim();
    if (translated) {
      target.textContent = translated;
    } else {
      target.classList.add("pending");
      target.textContent = "…";
    }
    row.append(source, target);
    captionListEl.append(row);
  }
  captionsEl.hidden = false;
}

function drawOverlay() {
  updateCaptions();
  void captionsEl.offsetHeight;

  const dpr = window.devicePixelRatio || 1;
  const width = stageEl.clientWidth;
  const height = stageEl.clientHeight;
  overlayEl.width = Math.max(1, Math.round(width * dpr));
  overlayEl.height = Math.max(1, Math.round(height * dpr));
  overlayEl.style.width = `${width}px`;
  overlayEl.style.height = `${height}px`;

  const ctx = overlayEl.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const media = mediaRect();
  if (!media) return;
  drawCropMask(ctx, media);
  if (!showBubblesEl.checked || !boxes.length) return;

  for (const box of boxes) {
    if (!needsBubble(box)) continue;
    const x = media.x + box.x * media.w;
    const y = media.y + box.y * media.h;
    const w = Math.max(8, box.w * media.w);
    const h = Math.max(8, box.h * media.h);
    const pad = Math.min(6, w * 0.06, h * 0.12);
    const innerW = Math.max(4, w - pad * 2);
    const innerH = Math.max(4, h - pad * 2);
    const { font, lines } = fitBubbleText(ctx, box.translated || box.text, innerW, innerH);
    const textH = lines.length * font * 1.2;
    const textY = y + pad + Math.max(0, (innerH - textH) / 2);
    const palette = paletteFor(box);
    const align = box.align === "center" || box.align === "right" ? box.align : "left";
    const textX = align === "right" ? x + w - pad : align === "center" ? x + w / 2 : x + pad;

    ctx.fillStyle = palette ? rgbCss(palette.bg) : DEFAULT_BUBBLE_BG;
    ctx.beginPath();
    ctx.roundRect(x - 1, y - 1, w + 2, h + 2, 4);
    ctx.fill();
    ctx.fillStyle = palette ? rgbCss(palette.fg) : DEFAULT_BUBBLE_FG;
    ctx.textAlign = align;
    ctx.font = `600 ${font}px ui-sans-serif, system-ui, sans-serif`;
    lines.forEach((line, index) => {
      ctx.fillText(line, textX, textY + font + index * font * 1.2);
    });
    ctx.textAlign = "left";
  }
}

async function sendVideoFrame() {
  if (analyzeBusy || !socket || socket.readyState !== WebSocket.OPEN) return;
  if (!videoEl.videoWidth) return;
  const scale = Math.min(1, 1600 / videoEl.videoWidth);
  grabCanvas.width = Math.round(videoEl.videoWidth * scale);
  grabCanvas.height = Math.round(videoEl.videoHeight * scale);
  grabCanvas.getContext("2d").drawImage(videoEl, 0, 0, grabCanvas.width, grabCanvas.height);
  analyzeBusy = true;
  try {
    const blob = await new Promise((resolve) => grabCanvas.toBlob(resolve, "image/jpeg", 0.55));
    if (blob && socket && socket.readyState === WebSocket.OPEN) socket.send(blob);
  } finally {
    analyzeBusy = false;
  }
}

async function startBrowserCapture() {
  stopAll();
  try {
    const fps = selectedFps();
    browserStream = await navigator.mediaDevices.getDisplayMedia({
      video: {
        displaySurface: "window",
        frameRate: { ideal: fps },
      },
      audio: false,
    });
  } catch (error) {
    setStatus(error.message || "Capture navigateur annulée", true);
    return;
  }

  videoEl.srcObject = browserStream;
  showBrowserVideo();
  stopBtn.disabled = false;
  setStatus("Capture navigateur + OCR…");
  browserStream.getVideoTracks()[0].addEventListener("ended", stopAll);

  connectAnalyzeSocket();
}

refreshBtn.addEventListener("click", () => {
  loadWindows().catch((error) => setStatus(error.message, true));
});
startBtn.addEventListener("click", startNativeStream);
stopBtn.addEventListener("click", stopAll);
browserBtn.addEventListener("click", () => {
  startBrowserCapture().catch((error) => setStatus(error.message, true));
});
sourceEl.addEventListener("change", saveSettings);
targetEl.addEventListener("change", saveSettings);
showBubblesEl.addEventListener("change", () => {
  saveSettings();
  drawOverlay();
});
windowsEl.addEventListener("change", saveSettings);
fpsEl.addEventListener("input", () => {
  syncFpsLabel();
  saveSettings();
});
fpsEl.addEventListener("change", () => {
  syncFpsLabel();
  saveSettings();
  if (browserStream) {
    startAnalyzeTimer();
    return;
  }
  if (socket && windowsEl.value) startNativeStream();
});
minWordsEl.addEventListener("change", () => {
  applyMinWords();
  saveSettings();
});
for (const el of [cropTopEl, cropBottomEl, cropLeftEl, cropRightEl]) {
  el.addEventListener("input", () => {
    syncCropLabels();
    saveSettings();
    drawOverlay();
  });
  el.addEventListener("change", () => {
    applyCrop();
    saveSettings();
  });
}
windowsEl.addEventListener("dblclick", startNativeStream);
frameEl.addEventListener("load", drawOverlay);
window.addEventListener("resize", drawOverlay);

applySettings();
loadWindows().catch((error) => setStatus(error.message, true));
