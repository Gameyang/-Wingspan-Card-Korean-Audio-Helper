const ART_REGION = {
  x: 45,
  y: 145,
  width: 565,
  height: 515,
};
const CARD_SIZE = {
  width: 630,
  height: 970,
};
const HASH_WIDTH = 17;
const HASH_HEIGHT = 16;
const HASH_BITS = (HASH_WIDTH - 1) * HASH_HEIGHT;
const FRAME_SAMPLE_WIDTH = 126;
const FRAME_SAMPLE_HEIGHT = 194;
const FRAME_SEARCH_OFFSETS = [-0.045, 0, 0.045];
const FRAME_SEARCH_SCALES = [0.94, 1, 1.06];
const FRAME_MIN_LAYOUT_SCORE = 36;
const FRAME_MIN_LUMA_RANGE = 28;
const MATCH_SCORE_THRESHOLD = 64;
const MATCH_MIN_GAP_BITS = 6;
const STABLE_MATCH_FRAMES = 2;
const MISS_FRAMES_TO_RESET = 3;

const elements = {
  status: document.querySelector("#status"),
  video: document.querySelector("#camera"),
  cameraBox: document.querySelector("#cameraBox"),
  cardGuide: document.querySelector("#cardGuide"),
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
let ttsManifest = { byCardId: {}, byCardNo: {} };
let scanTimer;
let isScanning = false;
let activeAudioCardId = "";
let pendingAudioCardId = "";
let lastAudioMessage = "";
let missedFrameCount = 0;
let candidateCardId = "";
let candidateFrameCount = 0;

const TTS_GAIN = 1;
const BIRD_BGM_GAIN = 0.22;

const audioMixer = {
  context: null,
  ttsEl: new Audio(),
  birdEl: new Audio(),
  ttsSource: null,
  birdSource: null,
  ttsGain: null,
  birdGain: null,
};

audioMixer.ttsEl.preload = "auto";
audioMixer.birdEl.preload = "auto";
audioMixer.birdEl.loop = true;
audioMixer.ttsEl.volume = TTS_GAIN;
audioMixer.birdEl.volume = BIRD_BGM_GAIN;

const frameProbe = document.createElement("canvas");
frameProbe.width = FRAME_SAMPLE_WIDTH;
frameProbe.height = FRAME_SAMPLE_HEIGHT;

const nibbleBits = Array.from({ length: 16 }, (_, value) =>
  value.toString(2).replaceAll("0", "").length,
);

function setStatus(message, type = "") {
  elements.status.textContent = message;
  elements.status.className = `status ${type}`.trim();
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

async function loadFingerprintDb() {
  setStatus("Loading", "ready");
  const response = await fetch("./data/card_fingerprints.json", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`fingerprint data ${response.status}`);
  }
  fingerprintDb = prepareFingerprintDb(await response.json());
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

async function loadTtsManifest() {
  try {
    const response = await fetch("./data/card_intro_tts.json", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`tts data ${response.status}`);
    }
    ttsManifest = await response.json();
  } catch (error) {
    ttsManifest = { byCardId: {}, byCardNo: {} };
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

function prepareFingerprintDb(rawDb) {
  const hashCounts = new Map();
  for (const card of rawDb.cards) {
    hashCounts.set(card.hash, (hashCounts.get(card.hash) ?? 0) + 1);
  }

  return {
    ...rawDb,
    cards: rawDb.cards.map((card) => {
      const duplicateCount = hashCounts.get(card.hash) ?? 1;
      return {
        ...card,
        duplicateCount,
        ambiguousFingerprint: duplicateCount > 1 || /^0+$/.test(card.hash),
      };
    }),
  };
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

function matchConfidence(best, second) {
  if (!best) {
    return { ok: false, gap: 0, reason: "no candidate" };
  }

  const gap = second ? second.distance - best.distance : HASH_BITS;
  if (best.ambiguousFingerprint) {
    return { ok: false, gap, reason: `ambiguous hash x${best.duplicateCount}` };
  }
  if (best.score < MATCH_SCORE_THRESHOLD) {
    return { ok: false, gap, reason: `weak < ${MATCH_SCORE_THRESHOLD}%` };
  }
  if (gap < MATCH_MIN_GAP_BITS) {
    return { ok: false, gap, reason: `close next gap ${gap}` };
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

function audioClipsForCard(cardId) {
  return audioManifest?.byCardId?.[cardId] ?? [];
}

function ttsIntroForCard(cardId) {
  return ttsManifest?.byCardId?.[cardId] ?? null;
}

function displayNameForCard(card) {
  const intro = ttsIntroForCard(card.id);
  if (intro && /^Atlas \d+ R\d+ C\d+$/.test(card.displayName)) {
    return intro.birdName;
  }
  const clips = audioClipsForCard(card.id);
  if (clips.length && /^Atlas \d+ R\d+ C\d+$/.test(card.displayName)) {
    return clips[0].birdName;
  }
  return card.displayName;
}

function formatFrameSummary(frame) {
  if (!frame) {
    return "";
  }
  return `frame ${Math.round(frame.layoutScore)} r${Math.round(frame.range)}`;
}

function frameRejectReason(frame) {
  if (!frame) {
    return "frame not found";
  }
  if (frame.range < FRAME_MIN_LUMA_RANGE) {
    return `low contrast ${Math.round(frame.range)}`;
  }
  return `layout ${Math.round(frame.layoutScore)} < ${FRAME_MIN_LAYOUT_SCORE}`;
}

function formatMatchMeta(best, second, audioMessage = "", confidence = null, frame = null) {
  if (!best) {
    return frame ? `${formatFrameSummary(frame)} / ${frameRejectReason(frame)}` : "-";
  }

  const parts = [best.id];
  if (frame) {
    parts.push(formatFrameSummary(frame));
  }
  if (second) {
    parts.push(`next ${second.id} (${second.score}% d${second.distance})`);
  }
  if (confidence) {
    parts.push(`gap ${confidence.gap}`);
    if (confidence.reason) {
      parts.push(confidence.reason);
    }
  }
  if (audioMessage) {
    parts.push(audioMessage);
  }
  return parts.join(" / ");
}

function setupAudioMixer() {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) {
    return null;
  }
  if (!audioMixer.context) {
    audioMixer.context = new AudioContextClass();
  }
  if (!audioMixer.ttsSource) {
    audioMixer.ttsSource = audioMixer.context.createMediaElementSource(audioMixer.ttsEl);
    audioMixer.ttsGain = audioMixer.context.createGain();
    audioMixer.ttsGain.gain.value = TTS_GAIN;
    audioMixer.ttsSource.connect(audioMixer.ttsGain);
    audioMixer.ttsGain.connect(audioMixer.context.destination);
  }
  if (!audioMixer.birdSource) {
    audioMixer.birdSource = audioMixer.context.createMediaElementSource(audioMixer.birdEl);
    audioMixer.birdGain = audioMixer.context.createGain();
    audioMixer.birdGain.gain.value = BIRD_BGM_GAIN;
    audioMixer.birdSource.connect(audioMixer.birdGain);
    audioMixer.birdGain.connect(audioMixer.context.destination);
  }
  return audioMixer.context;
}

async function unlockAudioMixer() {
  const context = setupAudioMixer();
  if (context?.state === "suspended") {
    await context.resume();
  }
}

function stopAudioElement(audioElement) {
  audioElement.pause();
  audioElement.removeAttribute("src");
  audioElement.load();
}

function stopBirdBgm() {
  stopAudioElement(audioMixer.birdEl);
}

function stopAudioMix() {
  stopAudioElement(audioMixer.ttsEl);
  stopAudioElement(audioMixer.birdEl);
}

function randomBirdClipForCard(card) {
  const clips = audioClipsForCard(card.id);
  if (!clips.length) {
    return null;
  }
  return clips[Math.floor(Math.random() * clips.length)];
}

async function playAudioMixForCard(card, force = false) {
  if (!force && activeAudioCardId === card.id) {
    return lastAudioMessage;
  }

  activeAudioCardId = card.id;
  const intro = ttsIntroForCard(card.id);
  const birdClip = randomBirdClipForCard(card);
  if (!intro && !birdClip) {
    stopAudioMix();
    lastAudioMessage = "no audio";
    return lastAudioMessage;
  }

  stopAudioMix();
  await unlockAudioMixer();

  let birdStarted = false;
  if (birdClip) {
    audioMixer.birdEl.src = birdClip.src;
    audioMixer.birdEl.loop = Boolean(intro);
    try {
      await audioMixer.birdEl.play();
      birdStarted = true;
    } catch (error) {
      birdStarted = false;
    }
  }

  if (!intro) {
    lastAudioMessage = birdStarted ? "bird bgm" : "tap button for sound";
    if (birdStarted) {
      pendingAudioCardId = "";
    } else {
      pendingAudioCardId = card.id;
    }
    return lastAudioMessage;
  }

  audioMixer.ttsEl.src = intro.src;
  audioMixer.ttsEl.onended = stopBirdBgm;
  audioMixer.ttsEl.onerror = stopBirdBgm;

  try {
    await audioMixer.ttsEl.play();
    pendingAudioCardId = "";
    lastAudioMessage = birdStarted ? "tts + bird bgm" : "tts";
  } catch (error) {
    stopBirdBgm();
    pendingAudioCardId = card.id;
    lastAudioMessage = "tap button for sound";
  }

  return lastAudioMessage;
}

function resetAudioAfterMiss() {
  missedFrameCount += 1;
  if (missedFrameCount >= MISS_FRAMES_TO_RESET) {
    activeAudioCardId = "";
    pendingAudioCardId = "";
    lastAudioMessage = "";
    stopAudioMix();
  }
}

function resetCandidateMatch() {
  candidateCardId = "";
  candidateFrameCount = 0;
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

function candidateRectFromBase(baseRect, offsetX, offsetY, scale) {
  const sw = baseRect.sw * scale;
  const sh = baseRect.sh * scale;
  const centerX = baseRect.sx + baseRect.sw * (0.5 + offsetX);
  const centerY = baseRect.sy + baseRect.sh * (0.5 + offsetY);
  return clampSourceRect({
    sx: centerX - sw / 2,
    sy: centerY - sh / 2,
    sw,
    sh,
  });
}

function grayAt(grays, width, x, y) {
  return grays[y * width + x];
}

function horizontalEdge(grays, width, height, yRatio, xStartRatio, xEndRatio) {
  const y = clamp(Math.round(yRatio * height), 1, height - 2);
  const xStart = clamp(Math.round(xStartRatio * width), 1, width - 2);
  const xEnd = clamp(Math.round(xEndRatio * width), xStart + 1, width - 2);
  let total = 0;
  let count = 0;
  for (let x = xStart; x <= xEnd; x += 1) {
    total += Math.abs(grayAt(grays, width, x, y - 1) - grayAt(grays, width, x, y + 1));
    count += 1;
  }
  return count ? total / count : 0;
}

function verticalEdge(grays, width, height, xRatio, yStartRatio, yEndRatio) {
  const x = clamp(Math.round(xRatio * width), 1, width - 2);
  const yStart = clamp(Math.round(yStartRatio * height), 1, height - 2);
  const yEnd = clamp(Math.round(yEndRatio * height), yStart + 1, height - 2);
  let total = 0;
  let count = 0;
  for (let y = yStart; y <= yEnd; y += 1) {
    total += Math.abs(grayAt(grays, width, x - 1, y) - grayAt(grays, width, x + 1, y));
    count += 1;
  }
  return count ? total / count : 0;
}

function evaluateCardFrame(rect) {
  const context = frameProbe.getContext("2d", { willReadFrequently: true });
  context.imageSmoothingEnabled = true;
  context.drawImage(
    elements.video,
    rect.sx,
    rect.sy,
    rect.sw,
    rect.sh,
    0,
    0,
    FRAME_SAMPLE_WIDTH,
    FRAME_SAMPLE_HEIGHT,
  );

  const imageData = context.getImageData(0, 0, FRAME_SAMPLE_WIDTH, FRAME_SAMPLE_HEIGHT).data;
  const grays = [];
  let min = 255;
  let max = 0;
  for (let index = 0; index < imageData.length; index += 4) {
    const gray = imageData[index] * 0.299 + imageData[index + 1] * 0.587 + imageData[index + 2] * 0.114;
    grays.push(gray);
    min = Math.min(min, gray);
    max = Math.max(max, gray);
  }

  const range = max - min;
  const layoutScore =
    horizontalEdge(grays, FRAME_SAMPLE_WIDTH, FRAME_SAMPLE_HEIGHT, 0.145, 0.34, 0.96) * 0.95 +
    verticalEdge(grays, FRAME_SAMPLE_WIDTH, FRAME_SAMPLE_HEIGHT, 0.36, 0.03, 0.15) * 0.8 +
    horizontalEdge(grays, FRAME_SAMPLE_WIDTH, FRAME_SAMPLE_HEIGHT, 0.69, 0.03, 0.97) * 1.15 +
    horizontalEdge(grays, FRAME_SAMPLE_WIDTH, FRAME_SAMPLE_HEIGHT, 0.82, 0.03, 0.97) * 1.05 +
    verticalEdge(grays, FRAME_SAMPLE_WIDTH, FRAME_SAMPLE_HEIGHT, 0.07, 0.03, 0.18) * 0.55 +
    verticalEdge(grays, FRAME_SAMPLE_WIDTH, FRAME_SAMPLE_HEIGHT, 0.31, 0.03, 0.18) * 0.55;

  return {
    rect,
    layoutScore,
    range,
    ok: layoutScore >= FRAME_MIN_LAYOUT_SCORE && range >= FRAME_MIN_LUMA_RANGE,
  };
}

function findBestCardFrame() {
  const baseRect = getVideoSourceRect(elements.cardGuide);
  let best = null;
  for (const scale of FRAME_SEARCH_SCALES) {
    for (const offsetY of FRAME_SEARCH_OFFSETS) {
      for (const offsetX of FRAME_SEARCH_OFFSETS) {
        const candidate = candidateRectFromBase(baseRect, offsetX, offsetY, scale);
        const result = evaluateCardFrame(candidate);
        if (
          !best ||
          result.layoutScore > best.layoutScore ||
          (result.layoutScore === best.layoutScore && result.range > best.range)
        ) {
          best = result;
        }
      }
    }
  }

  if (!best) {
    return {
      rect: baseRect,
      layoutScore: 0,
      range: 0,
      ok: false,
    };
  }

  return best;
}

function drawAlignedVideoArtPreview(frame) {
  const rect = frame.rect;
  drawPreviewFromSource(
    elements.video,
    rect.sx + (rect.sw * ART_REGION.x) / CARD_SIZE.width,
    rect.sy + (rect.sh * ART_REGION.y) / CARD_SIZE.height,
    (rect.sw * ART_REGION.width) / CARD_SIZE.width,
    (rect.sh * ART_REGION.height) / CARD_SIZE.height,
  );
}

function drawVideoArtPreview() {
  if (!elements.video.videoWidth || !elements.video.videoHeight) {
    throw new Error("Camera is not ready.");
  }

  const frame = findBestCardFrame();
  if (frame.ok) {
    drawAlignedVideoArtPreview(frame);
  }
  return frame;
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
    const frame = drawVideoArtPreview();
    if (!frame.ok) {
      resetCandidateMatch();
      resetAudioAfterMiss();
      elements.matchName.textContent = "Align card";
      elements.matchScore.textContent = formatFrameSummary(frame);
      elements.matchMeta.textContent = formatMatchMeta(null, null, lastAudioMessage, null, frame);
      setStatus("Align", "error");
      return;
    }

    const hash = computeDHash();
    const [best, second] = rankByFingerprint(hash);
    const confidence = matchConfidence(best, second);
    const stableFrames = stableFramesForCandidate(best, confidence.ok);
    const matched = confidence.ok && stableFrames >= STABLE_MATCH_FRAMES;
    let audioMessage = "";

    if (matched) {
      missedFrameCount = 0;
      audioMessage = await playAudioMixForCard(best);
    } else {
      resetAudioAfterMiss();
      audioMessage = confidence.ok
        ? `hold ${stableFrames}/${STABLE_MATCH_FRAMES}`
        : lastAudioMessage;
    }

    elements.matchName.textContent = confidence.ok || matched ? displayNameForCard(best) : "Check";
    elements.matchScore.textContent = best
      ? `${best.score}% / d${best.distance} / gap ${confidence.gap}`
      : "-";
    elements.matchMeta.textContent = formatMatchMeta(best, second, audioMessage, confidence, frame);
    setStatus(matched ? "Matched" : confidence.ok ? "Hold" : "Check", matched ? "ready" : "error");
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
        await playAudioMixForCard(pendingCard, true);
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
      await playAudioMixForCard(pendingCard, true);
    }
  }
  await startCamera();
}

elements.startCamera.addEventListener("click", handleStartCameraClick);

async function boot() {
  try {
    await Promise.all([loadFingerprintDb(), loadAudioManifest(), loadTtsManifest()]);
    await startCamera();
  } catch (error) {
    elements.matchMeta.textContent = error.message;
    setStatus("Tap camera", "error");
  }
}

boot();
