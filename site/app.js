const ART_REGION = {
  x: 45,
  y: 145,
  width: 565,
  height: 515,
};
const HASH_WIDTH = 17;
const HASH_HEIGHT = 16;
const HASH_BITS = (HASH_WIDTH - 1) * HASH_HEIGHT;
const MATCH_THRESHOLD = 58;

const elements = {
  status: document.querySelector("#status"),
  video: document.querySelector("#camera"),
  cameraBox: document.querySelector("#cameraBox"),
  artGuide: document.querySelector(".art-guide"),
  startCamera: document.querySelector("#startCamera"),
  artPreview: document.querySelector("#artPreview"),
  matchName: document.querySelector("#matchName"),
  matchScore: document.querySelector("#matchScore"),
  matchMeta: document.querySelector("#matchMeta"),
};

let stream;
let fingerprintDb;
let audioManifest = { byCardId: {} };
let scanTimer;
let isScanning = false;
let activeAudioCardId = "";
let pendingAudioCardId = "";
let lastAudioMessage = "";
let missedFrameCount = 0;

const audioPlayer = new Audio();
audioPlayer.preload = "auto";

const nibbleBits = Array.from({ length: 16 }, (_, value) =>
  value.toString(2).replaceAll("0", "").length,
);

function setStatus(message, type = "") {
  elements.status.textContent = message;
  elements.status.className = `status ${type}`.trim();
}

async function loadFingerprintDb() {
  setStatus("Loading", "ready");
  const response = await fetch("./data/card_fingerprints.json", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`fingerprint data ${response.status}`);
  }
  fingerprintDb = await response.json();
  setStatus(`${fingerprintDb.cards.length} ready`, "ready");
}

async function loadAudioManifest() {
  try {
    const response = await fetch("./data/audio_clips.json", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`audio data ${response.status}`);
    }
    audioManifest = await response.json();
  } catch (error) {
    audioManifest = { byCardId: {} };
    lastAudioMessage = "audio unavailable";
  }
}

function hammingDistanceHex(left, right) {
  const length = Math.min(left.length, right.length);
  let distance = Math.abs(left.length - right.length) * 4;
  for (let index = 0; index < length; index += 1) {
    const xor = Number.parseInt(left[index], 16) ^ Number.parseInt(right[index], 16);
    distance += nibbleBits[xor];
  }
  return distance;
}

function rankByFingerprint(hash) {
  return fingerprintDb.cards
    .map((card) => {
      const distance = hammingDistanceHex(hash, card.hash);
      const score = Math.max(0, Math.round(100 * (1 - distance / HASH_BITS)));
      return { ...card, distance, score };
    })
    .sort((a, b) => a.distance - b.distance || a.id.localeCompare(b.id));
}

function audioClipsForCard(cardId) {
  return audioManifest?.byCardId?.[cardId] ?? [];
}

function displayNameForCard(card) {
  const clips = audioClipsForCard(card.id);
  if (clips.length && /^Atlas \d+ R\d+ C\d+$/.test(card.displayName)) {
    return clips[0].birdName;
  }
  return card.displayName;
}

function formatMatchMeta(best, second, audioMessage = "") {
  if (!best) {
    return "-";
  }

  const parts = [best.id];
  if (second) {
    parts.push(`next ${second.id} (${second.score}%)`);
  }
  if (audioMessage) {
    parts.push(audioMessage);
  }
  return parts.join(" / ");
}

async function playRandomClipForCard(card, force = false) {
  if (!force && activeAudioCardId === card.id) {
    return lastAudioMessage;
  }

  activeAudioCardId = card.id;
  const clips = audioClipsForCard(card.id);
  if (!clips.length) {
    lastAudioMessage = "no audio";
    return lastAudioMessage;
  }

  const clip = clips[Math.floor(Math.random() * clips.length)];
  audioPlayer.pause();
  audioPlayer.src = clip.src;

  try {
    await audioPlayer.play();
    pendingAudioCardId = "";
    lastAudioMessage = clip.isMain ? "main audio" : "audio";
  } catch (error) {
    pendingAudioCardId = card.id;
    lastAudioMessage = "tap button for sound";
  }

  return lastAudioMessage;
}

function resetAudioAfterMiss() {
  missedFrameCount += 1;
  if (missedFrameCount >= 3) {
    activeAudioCardId = "";
    pendingAudioCardId = "";
    lastAudioMessage = "";
  }
}

function drawPreviewFromSource(source, sx, sy, sw, sh) {
  const context = elements.artPreview.getContext("2d", { willReadFrequently: true });
  elements.artPreview.width = ART_REGION.width;
  elements.artPreview.height = ART_REGION.height;
  context.imageSmoothingEnabled = true;
  context.drawImage(source, sx, sy, sw, sh, 0, 0, ART_REGION.width, ART_REGION.height);
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
    sx: Math.max(0, (targetX - offsetX) / scale),
    sy: Math.max(0, (targetY - offsetY) / scale),
    sw: Math.min(videoWidth, targetRect.width / scale),
    sh: Math.min(videoHeight, targetRect.height / scale),
  };
}

function drawVideoArtPreview() {
  if (!elements.video.videoWidth || !elements.video.videoHeight) {
    throw new Error("Camera is not ready.");
  }

  const rect = getVideoSourceRect(elements.artGuide);
  drawPreviewFromSource(elements.video, rect.sx, rect.sy, rect.sw, rect.sh);
}

function computeDHash() {
  const canvas = document.createElement("canvas");
  canvas.width = HASH_WIDTH;
  canvas.height = HASH_HEIGHT;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  context.imageSmoothingEnabled = true;
  context.drawImage(elements.artPreview, 0, 0, HASH_WIDTH, HASH_HEIGHT);

  const data = context.getImageData(0, 0, HASH_WIDTH, HASH_HEIGHT).data;
  const grays = [];
  let min = 255;
  let max = 0;
  for (let index = 0; index < data.length; index += 4) {
    const gray = data[index] * 0.299 + data[index + 1] * 0.587 + data[index + 2] * 0.114;
    grays.push(gray);
    min = Math.min(min, gray);
    max = Math.max(max, gray);
  }

  const range = Math.max(1, max - min);
  const bits = [];
  for (let y = 0; y < HASH_HEIGHT; y += 1) {
    const rowOffset = y * HASH_WIDTH;
    for (let x = 0; x < HASH_WIDTH - 1; x += 1) {
      const left = (grays[rowOffset + x] - min) / range;
      const right = (grays[rowOffset + x + 1] - min) / range;
      bits.push(left > right ? "1" : "0");
    }
  }

  let hash = "";
  for (let index = 0; index < bits.length; index += 4) {
    hash += Number.parseInt(bits.slice(index, index + 4).join(""), 2).toString(16);
  }
  return hash;
}

async function identifyCurrentFrame() {
  if (isScanning || !stream) {
    return;
  }

  isScanning = true;
  try {
    if (!fingerprintDb) {
      await loadFingerprintDb();
    }
    drawVideoArtPreview();
    const hash = computeDHash();
    const [best, second] = rankByFingerprint(hash);
    const matched = best && best.score >= MATCH_THRESHOLD;
    let audioMessage = "";

    if (matched) {
      missedFrameCount = 0;
      audioMessage = await playRandomClipForCard(best);
    } else {
      resetAudioAfterMiss();
      audioMessage = lastAudioMessage;
    }

    elements.matchName.textContent = matched ? displayNameForCard(best) : "Check";
    elements.matchScore.textContent = best ? `${best.score}% / d${best.distance}` : "-";
    elements.matchMeta.textContent = formatMatchMeta(best, second, audioMessage);
    setStatus(matched ? "Matched" : "Check", matched ? "ready" : "error");
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
  scanTimer = window.setInterval(identifyCurrentFrame, 850);
  identifyCurrentFrame();
}

async function startCamera() {
  try {
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
    if (pendingAudioCardId && fingerprintDb) {
      const pendingCard = fingerprintDb.cards.find((card) => card.id === pendingAudioCardId);
      if (pendingCard) {
        await playRandomClipForCard(pendingCard, true);
      }
    }
    elements.startCamera.textContent = "Restart camera";
    setStatus("Scanning", "ready");
    startScanLoop();
  } catch (error) {
    elements.matchMeta.textContent = error.message;
    setStatus("Camera error", "error");
  }
}

async function handleStartCameraClick() {
  if (pendingAudioCardId && fingerprintDb) {
    const pendingCard = fingerprintDb.cards.find((card) => card.id === pendingAudioCardId);
    if (pendingCard) {
      await playRandomClipForCard(pendingCard, true);
    }
  }
  await startCamera();
}

elements.startCamera.addEventListener("click", handleStartCameraClick);

async function boot() {
  try {
    await Promise.all([loadFingerprintDb(), loadAudioManifest()]);
    await startCamera();
  } catch (error) {
    elements.matchMeta.textContent = error.message;
    setStatus("Tap camera", "error");
  }
}

boot();
