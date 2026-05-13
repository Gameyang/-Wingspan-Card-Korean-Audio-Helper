const CARD_SIZE = {
  width: 630,
  height: 970,
};
const NAME_REGION = {
  x: 165,
  y: 28,
  width: 450,
  height: 112,
};
const OCR_CANVAS_WIDTH = 1000;
const OCR_INTERVAL_MS = 1350;
const OCR_MATCH_THRESHOLD = 78;
const OCR_MIN_GAP = 5;
const OCR_MIN_QUERY_LENGTH = 6;
const STABLE_MATCH_FRAMES = 2;
const MISS_FRAMES_TO_RESET = 4;

const elements = {
  status: document.querySelector("#status"),
  video: document.querySelector("#camera"),
  cameraBox: document.querySelector("#cameraBox"),
  cardGuide: document.querySelector("#cardGuide"),
  matchName: document.querySelector("#matchName"),
  matchScore: document.querySelector("#matchScore"),
  matchMeta: document.querySelector("#matchMeta"),
};

let stream;
let ocrDb = { cards: [], byCardId: {} };
let audioManifest = { byCardId: {} };
let tesseractWorker;
let scanTimer;
let isScanning = false;
let activeAudioCardId = "";
let pendingAudioCard = null;
let lastAudioMessage = "";
let missedFrameCount = 0;
let candidateCardId = "";
let candidateFrameCount = 0;

const soundElement = new Audio();
soundElement.preload = "auto";
soundElement.loop = false;

const ocrCanvas = document.createElement("canvas");
const ocrContext = ocrCanvas.getContext("2d", { willReadFrequently: true });

function setStatus(message, type = "") {
  elements.status.textContent = message;
  elements.status.className = `status ${type}`.trim();
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function cleanBirdName(value) {
  return String(value)
    .replace(/\b(?:XC|XV)\s*\d*\w*\b|\b\d+\s*(?:XC|XV)\b/gi, " ")
    .replace(/\bTJ\b/gi, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/larkr$/i, "lark");
}

function normalizeForMatch(value) {
  return cleanBirdName(value)
    .toLocaleLowerCase("en-US")
    .replace(/&/g, "and")
    .replace(/[^a-z0-9]+/g, "");
}

function extractLatinText(value) {
  const matches = String(value).match(/[A-Za-z][A-Za-z.'-]{1,}/g) ?? [];
  return matches
    .map((part) => part.replace(/^[.'-]+|[.'-]+$/g, ""))
    .filter((part) => part.length > 1)
    .join(" ");
}

async function fetchJson(path, fallback) {
  try {
    const response = await fetch(path, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`${path} ${response.status}`);
    }
    return await response.json();
  } catch (error) {
    return fallback;
  }
}

async function loadData() {
  setStatus("Loading", "ready");
  [ocrDb, audioManifest] = await Promise.all([
    fetchJson("./data/card_ocr_aliases.json", { cards: [], byCardId: {} }),
    fetchJson("./data/audio_clips.json", { byCardId: {} }),
  ]);
  if (!ocrDb.cards.length) {
    throw new Error("OCR data unavailable.");
  }
}

async function initOcrWorker() {
  if (tesseractWorker) {
    return;
  }
  if (!window.Tesseract?.createWorker) {
    throw new Error("OCR engine unavailable.");
  }
  setStatus("OCR", "ready");
  tesseractWorker = await window.Tesseract.createWorker("eng");
  await tesseractWorker.setParameters({
    preserve_interword_spaces: "1",
    tessedit_char_whitelist: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz .'-",
  });
}

function getVideoSourceRect(targetElement) {
  const frameRect = elements.cameraBox.getBoundingClientRect();
  const targetRect = targetElement.getBoundingClientRect();
  const videoWidth = elements.video.videoWidth;
  const videoHeight = elements.video.videoHeight;
  const scale = Math.max(frameRect.width / videoWidth, frameRect.height / videoHeight);
  const renderedWidth = videoWidth * scale;
  const renderedHeight = videoHeight * scale;
  const offsetX = (frameRect.width - renderedWidth) / 2;
  const offsetY = (frameRect.height - renderedHeight) / 2;
  const targetX = targetRect.left - frameRect.left;
  const targetY = targetRect.top - frameRect.top;

  return {
    sx: clamp((targetX - offsetX) / scale, 0, videoWidth),
    sy: clamp((targetY - offsetY) / scale, 0, videoHeight),
    sw: clamp(targetRect.width / scale, 1, videoWidth),
    sh: clamp(targetRect.height / scale, 1, videoHeight),
  };
}

function clampSourceRect(rect) {
  const videoWidth = elements.video.videoWidth;
  const videoHeight = elements.video.videoHeight;
  const width = clamp(rect.sw, 1, videoWidth);
  const height = clamp(rect.sh, 1, videoHeight);
  return {
    sx: clamp(rect.sx, 0, Math.max(0, videoWidth - width)),
    sy: clamp(rect.sy, 0, Math.max(0, videoHeight - height)),
    sw: width,
    sh: height,
  };
}

function nameSourceRect() {
  const cardRect = getVideoSourceRect(elements.cardGuide);
  return clampSourceRect({
    sx: cardRect.sx + (cardRect.sw * NAME_REGION.x) / CARD_SIZE.width,
    sy: cardRect.sy + (cardRect.sh * NAME_REGION.y) / CARD_SIZE.height,
    sw: (cardRect.sw * NAME_REGION.width) / CARD_SIZE.width,
    sh: (cardRect.sh * NAME_REGION.height) / CARD_SIZE.height,
  });
}

function preprocessOcrCanvas() {
  const imageData = ocrContext.getImageData(0, 0, ocrCanvas.width, ocrCanvas.height);
  const data = imageData.data;
  let min = 255;
  let max = 0;
  const grays = new Uint8Array(ocrCanvas.width * ocrCanvas.height);

  for (let index = 0, pixel = 0; index < data.length; index += 4, pixel += 1) {
    const gray = data[index] * 0.299 + data[index + 1] * 0.587 + data[index + 2] * 0.114;
    grays[pixel] = gray;
    min = Math.min(min, gray);
    max = Math.max(max, gray);
  }

  const range = Math.max(1, max - min);
  for (let index = 0, pixel = 0; index < data.length; index += 4, pixel += 1) {
    const normalized = ((grays[pixel] - min) / range) * 255;
    const value = normalized > 128 ? 255 : 0;
    data[index] = value;
    data[index + 1] = value;
    data[index + 2] = value;
    data[index + 3] = 255;
  }
  ocrContext.putImageData(imageData, 0, 0);
}

function drawNameCropForOcr() {
  if (!elements.video.videoWidth || !elements.video.videoHeight) {
    throw new Error("Camera is not ready.");
  }

  const rect = nameSourceRect();
  const scale = OCR_CANVAS_WIDTH / rect.sw;
  ocrCanvas.width = OCR_CANVAS_WIDTH;
  ocrCanvas.height = Math.max(96, Math.round(rect.sh * scale));
  ocrContext.imageSmoothingEnabled = true;
  ocrContext.filter = "grayscale(1) contrast(1.75) brightness(1.08)";
  ocrContext.drawImage(
    elements.video,
    rect.sx,
    rect.sy,
    rect.sw,
    rect.sh,
    0,
    0,
    ocrCanvas.width,
    ocrCanvas.height,
  );
  ocrContext.filter = "none";
  preprocessOcrCanvas();
}

function levenshteinDistance(left, right) {
  if (left === right) {
    return 0;
  }
  if (!left.length) {
    return right.length;
  }
  if (!right.length) {
    return left.length;
  }

  const previous = Array.from({ length: right.length + 1 }, (_, index) => index);
  const current = Array(right.length + 1).fill(0);

  for (let i = 1; i <= left.length; i += 1) {
    current[0] = i;
    for (let j = 1; j <= right.length; j += 1) {
      const cost = left[i - 1] === right[j - 1] ? 0 : 1;
      current[j] = Math.min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost);
    }
    for (let j = 0; j <= right.length; j += 1) {
      previous[j] = current[j];
    }
  }
  return previous[right.length];
}

function bigramCounts(value) {
  const counts = new Map();
  if (value.length < 2) {
    counts.set(value, 1);
    return counts;
  }
  for (let index = 0; index < value.length - 1; index += 1) {
    const bigram = value.slice(index, index + 2);
    counts.set(bigram, (counts.get(bigram) ?? 0) + 1);
  }
  return counts;
}

function diceSimilarity(left, right) {
  const leftCounts = bigramCounts(left);
  const rightCounts = bigramCounts(right);
  let overlap = 0;
  for (const [bigram, count] of leftCounts.entries()) {
    overlap += Math.min(count, rightCounts.get(bigram) ?? 0);
  }
  const total = Math.max(1, left.length - 1) + Math.max(1, right.length - 1);
  return (2 * overlap) / total;
}

function normalizedSimilarity(left, right) {
  if (!left || !right) {
    return 0;
  }
  if (left === right) {
    return 100;
  }
  if (left.length >= 10 && left.includes(right)) {
    return Math.min(99, 92 + Math.round((right.length / left.length) * 7));
  }
  if (right.length >= 10 && right.includes(left)) {
    return left.length >= 8 ? 90 : 68;
  }

  const distance = levenshteinDistance(left, right);
  const editScore = 1 - distance / Math.max(left.length, right.length);
  const diceScore = diceSimilarity(left, right);
  return Math.round(100 * (editScore * 0.68 + diceScore * 0.32));
}

function bestAliasScore(query, card) {
  let best = { alias: "", score: 0 };
  for (const alias of card.aliases ?? []) {
    const normalized = normalizeForMatch(alias);
    const score = normalizedSimilarity(query, normalized);
    if (score > best.score) {
      best = { alias, score };
    }
  }
  return best;
}

function rankOcrCandidates(ocrText) {
  const latinText = extractLatinText(ocrText);
  const query = normalizeForMatch(latinText);
  if (query.length < OCR_MIN_QUERY_LENGTH) {
    return { latinText, query, candidates: [] };
  }

  const candidates = ocrDb.cards
    .map((card) => {
      const best = bestAliasScore(query, card);
      return {
        ...card,
        matchedAlias: best.alias,
        score: best.score,
      };
    })
    .sort((a, b) => b.score - a.score || a.cardNo.localeCompare(b.cardNo));

  return { latinText, query, candidates };
}

function matchConfidence(best, second) {
  if (!best) {
    return { ok: false, gap: 0, reason: "no candidate" };
  }
  const gap = best.score - (second?.score ?? 0);
  if (best.score < OCR_MATCH_THRESHOLD) {
    return { ok: false, gap, reason: `weak < ${OCR_MATCH_THRESHOLD}%` };
  }
  if (gap < OCR_MIN_GAP) {
    return { ok: false, gap, reason: `close next ${gap}%` };
  }
  return { ok: true, gap, reason: "" };
}

function stableFramesForCandidate(best, confident) {
  if (!confident || !best) {
    candidateCardId = "";
    candidateFrameCount = 0;
    return 0;
  }
  if (candidateCardId === best.id) {
    candidateFrameCount += 1;
  } else {
    candidateCardId = best.id;
    candidateFrameCount = 1;
  }
  return candidateFrameCount;
}

function audioClipsForCard(card) {
  const clips = audioManifest?.byCardId?.[card.id] ?? [];
  if (!clips.length) {
    return [];
  }
  const targetName = normalizeForMatch(card.birdName);
  const filtered = clips.filter((clip) => normalizeForMatch(clip.birdName) === targetName);
  return filtered.length ? filtered : clips;
}

function randomBirdClipForCard(card) {
  const clips = audioClipsForCard(card);
  if (!clips.length) {
    return null;
  }
  return clips[Math.floor(Math.random() * clips.length)];
}

async function playAudioForCard(card, force = false) {
  if (!force && activeAudioCardId === card.id) {
    return lastAudioMessage;
  }

  activeAudioCardId = card.id;
  const clip = randomBirdClipForCard(card);
  if (!clip) {
    soundElement.pause();
    soundElement.removeAttribute("src");
    lastAudioMessage = "no audio";
    return lastAudioMessage;
  }

  soundElement.pause();
  soundElement.currentTime = 0;
  soundElement.src = clip.src;
  soundElement.loop = false;

  try {
    await soundElement.play();
    pendingAudioCard = null;
    lastAudioMessage = `audio ${clip.clipType ?? "clip"}`;
  } catch (error) {
    pendingAudioCard = card;
    lastAudioMessage = "tap screen for sound";
  }
  return lastAudioMessage;
}

function resetAudioAfterMiss() {
  missedFrameCount += 1;
  if (missedFrameCount >= MISS_FRAMES_TO_RESET) {
    activeAudioCardId = "";
    pendingAudioCard = null;
    lastAudioMessage = "";
    soundElement.pause();
    soundElement.removeAttribute("src");
  }
}

function formatMeta(best, second, latinText, audioMessage, confidence) {
  const parts = [];
  if (latinText) {
    parts.push(`read "${latinText.slice(0, 44)}"`);
  }
  if (best) {
    parts.push(`${best.cardNo} ${best.matchedAlias}`);
  }
  if (second) {
    parts.push(`next ${second.cardNo} ${second.score}%`);
  }
  if (confidence?.reason) {
    parts.push(confidence.reason);
  }
  if (audioMessage) {
    parts.push(audioMessage);
  }
  return parts.join(" / ") || "-";
}

async function identifyCurrentFrame() {
  if (isScanning || !stream || !tesseractWorker) {
    return;
  }

  isScanning = true;
  try {
    drawNameCropForOcr();
    const result = await tesseractWorker.recognize(ocrCanvas);
    const ocrText = result?.data?.text ?? "";
    const { latinText, candidates } = rankOcrCandidates(ocrText);
    const [best, second] = candidates;
    const confidence = matchConfidence(best, second);
    const stableFrames = stableFramesForCandidate(best, confidence.ok);
    const matched = confidence.ok && stableFrames >= STABLE_MATCH_FRAMES;
    let audioMessage = "";

    if (matched) {
      missedFrameCount = 0;
      audioMessage = await playAudioForCard(best);
    } else {
      resetAudioAfterMiss();
      audioMessage = confidence.ok ? `hold ${stableFrames}/${STABLE_MATCH_FRAMES}` : lastAudioMessage;
    }

    elements.matchName.textContent = confidence.ok || matched ? best.birdName : "Scanning";
    elements.matchScore.textContent = best ? `${best.score}% / gap ${confidence.gap}` : "-";
    elements.matchMeta.textContent = formatMeta(best, second, latinText, audioMessage, confidence);
    setStatus(matched ? "Matched" : confidence.ok ? "Hold" : "Reading", matched ? "ready" : "");
  } catch (error) {
    elements.matchName.textContent = "Error";
    elements.matchScore.textContent = "-";
    elements.matchMeta.textContent = error.message;
    setStatus("Error", "error");
  } finally {
    isScanning = false;
  }
}

function startScanLoop() {
  window.clearInterval(scanTimer);
  scanTimer = window.setInterval(identifyCurrentFrame, OCR_INTERVAL_MS);
  identifyCurrentFrame();
}

async function startCamera() {
  if (!window.isSecureContext) {
    throw new Error("HTTPS is required.");
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error("Camera API is not supported.");
  }

  setStatus("Permission", "ready");
  if (stream) {
    stream.getTracks().forEach((track) => track.stop());
  }
  stream = await navigator.mediaDevices.getUserMedia({
    audio: false,
    video: {
      facingMode: { ideal: "environment" },
      width: { ideal: 1920 },
      height: { ideal: 1080 },
    },
  });
  elements.video.srcObject = stream;
  await elements.video.play();
  setStatus("Scanning", "ready");
  startScanLoop();
}

async function handleUserActivation() {
  if (pendingAudioCard) {
    await playAudioForCard(pendingAudioCard, true);
  }
}

async function boot() {
  try {
    await loadData();
    await initOcrWorker();
    await startCamera();
  } catch (error) {
    elements.matchName.textContent = "Camera";
    elements.matchScore.textContent = "-";
    elements.matchMeta.textContent = error.message;
    setStatus("Tap screen", "error");
  }
}

document.addEventListener("pointerdown", handleUserActivation, { passive: true });
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    soundElement.pause();
  }
});

boot();
