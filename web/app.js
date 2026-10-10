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
const captionSourceEl = document.querySelector("#caption-source");
const captionTargetEl = document.querySelector("#caption-target");
const placeholderEl = document.querySelector("#placeholder");
const stageEl = document.querySelector("#stage");
const sourceEl = document.querySelector("#source");
const targetEl = document.querySelector("#target");
const fpsEl = document.querySelector("#fps");
const fpsValueEl = document.querySelector("#fps-value");
const minWordsEl = document.querySelector("#min-words");

const SETTINGS_KEY = "ocr-live.settings";

let socket = null;
let objectUrl = null;
let browserStream = null;
let boxes = [];
let analyzeTimer = 0;
let analyzeBusy = false;
const grabCanvas = document.createElement("canvas");

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
  syncFpsLabel();
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

function streamQuery() {
  return `source=${encodeURIComponent(sourceEl.value)}&target=${encodeURIComponent(targetEl.value)}&fps=${selectedFps()}&min_words=${selectedMinWords()}`;
}

function syncFpsLabel() {
  fpsValueEl.value = String(selectedFps());
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
  if (browserStream) {
    restartAnalyzeSocket();
    return;
  }
  if (socket && windowsEl.value) startNativeStream();
}

function showNativeFrame() {
  placeholderEl.hidden = true;
  videoEl.hidden = true;
  frameEl.hidden = false;
}

function showBrowserVideo() {
  placeholderEl.hidden = true;
  frameEl.hidden = true;
  videoEl.hidden = false;
}

function revokeFrame() {
  if (objectUrl) {
    URL.revokeObjectURL(objectUrl);
    objectUrl = null;
  }
}

function clearOverlay() {
  boxes = [];
  const ctx = overlayEl.getContext("2d");
  ctx.clearRect(0, 0, overlayEl.width, overlayEl.height);
  captionsEl.hidden = true;
  captionSourceEl.textContent = "";
  captionTargetEl.textContent = "";
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
  frameEl.hidden = true;
  videoEl.hidden = true;
  placeholderEl.hidden = false;
  setStatus("Arrêté");
}

function handleSocketMessage(event) {
  if (typeof event.data === "string") {
    const payload = JSON.parse(event.data);
    if (payload.type === "error") setStatus(payload.message, true);
    if (payload.type === "ocr") {
      boxes = payload.boxes || [];
      setStatus(`${boxes.length} texte${boxes.length > 1 ? "s" : ""}`);
      drawOverlay();
    }
    return;
  }
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

function mediaRect() {
  const media = frameEl.hidden ? videoEl : frameEl;
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

function drawOverlay() {
  const dpr = window.devicePixelRatio || 1;
  const width = stageEl.clientWidth;
  const height = stageEl.clientHeight;
  overlayEl.width = Math.max(1, Math.round(width * dpr));
  overlayEl.height = Math.max(1, Math.round(height * dpr));
  overlayEl.style.width = `${width}px`;
  overlayEl.style.height = `${height}px`;
  overlayEl.getContext("2d").clearRect(0, 0, overlayEl.width, overlayEl.height);

  const media = mediaRect();
  if (!media || !boxes.length) {
    captionsEl.hidden = true;
    return;
  }

  const lowest = [...boxes].sort((a, b) => a.y + a.h - (b.y + b.h)).at(-1);
  captionSourceEl.textContent = lowest.text;
  captionTargetEl.textContent = lowest.translated || lowest.text;
  captionsEl.hidden = false;
  captionsEl.style.left = `${media.x + 8}px`;
  captionsEl.style.width = `${Math.max(0, media.w - 16)}px`;
  captionsEl.style.bottom = `${Math.max(8, height - media.y - media.h + 8)}px`;
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
windowsEl.addEventListener("dblclick", startNativeStream);
frameEl.addEventListener("load", drawOverlay);
window.addEventListener("resize", drawOverlay);

applySettings();
loadWindows().catch((error) => setStatus(error.message, true));
