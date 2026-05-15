const CARD_SIZE = {
  width: 630,
  height: 970,
};
const ART_REGION = {
  x: 45,
  y: 145,
  width: 565,
  height: 515,
};
const OCR_SIGNAL_REGIONS = [
  { key: "title", x: 205, y: 0, width: 420, height: 155, targetWidth: 1000, minHeight: 300 },
  { key: "score", x: 0, y: 195, width: 125, height: 215, targetWidth: 340, minHeight: 430 },
  { key: "wing", x: 440, y: 500, width: 190, height: 165, targetWidth: 470, minHeight: 360 },
  { key: "ability", x: 0, y: 650, width: 630, height: 190, targetWidth: 1060, minHeight: 300 },
];
const OCR_CANVAS_WIDTH = 1100;
const OCR_CANVAS_PADDING = 18;
const OCR_SECTION_GAP = 18;
const OCR_REGION_MARGIN = 0.14;
const OCR_ROTATED_REGION_MARGIN = 0.22;
const OCR_ROTATION_DEGREES = [-8, 0, 8];
const OCR_ROTATION_REGION_KEYS = new Set(["title", "score", "wing"]);
const OCR_STRONG_NAME_SCORE = 85;
const OCR_MEDIUM_NAME_SCORE = 70;
const OCR_MIN_NAME_SCORE = 60;
const OCR_MIN_GAP = 5;
const OCR_MIN_QUERY_LENGTH = 2;
const OCR_SCORE_SIGNAL_LABEL = "점수";
const OCR_WING_SIGNAL_LABEL = "날개길이";
const OCR_NUMERIC_SINGLE_BOOST = 10;
const OCR_NUMERIC_PAIR_BOOST = 30;
const MAX_CANDIDATE_SUGGESTIONS = 8;
const MIN_CANDIDATE_NAME_SCORE = 20;
const MIN_CANDIDATE_RANK_SCORE = 18;
const ABILITY_TOGGLE_STORAGE_KEY = "wingspan.includeAbilityTts";
const BIRD_BG_VOLUME = 0.24;
const VOICE_RECOGNITION_LANG = "ko-KR";

const DHASH_WIDTH = 17;
const DHASH_HEIGHT = 16;
const DHASH_BITS = (DHASH_WIDTH - 1) * DHASH_HEIGHT; // 256
const VISUAL_SCORE_DIVISOR = 96; // hamming distance that maps to score 0
const VISUAL_RANK_WEIGHT = 0.5;
const VISUAL_STRONG_SCORE = 75;
const VISUAL_MEDIUM_SCORE = 55;
const AUTO_SELECT_DELAY_MS = 220;

const elements = {
  status: document.querySelector("#status"),
  scanner: document.querySelector(".scanner"),
  video: document.querySelector("#camera"),
  snapshot: document.querySelector("#snapshot"),
  cameraBox: document.querySelector("#cameraBox"),
  cardGuide: document.querySelector("#cardGuide"),
  successGlow: document.querySelector("#successGlow"),
  debugSheet: document.querySelector("#debugSheet"),
  debugToggle: document.querySelector("#debugToggle"),
  candidatePanel: document.querySelector("#candidatePanel"),
  candidateList: document.querySelector("#candidateList"),
  abilityToggle: document.querySelector("#abilityToggle"),
  voiceButton: document.querySelector("#voiceButton"),
  shutterButton: document.querySelector("#shutterButton"),
  retakeButton: document.querySelector("#retakeButton"),
  matchName: document.querySelector("#matchName"),
  matchScore: document.querySelector("#matchScore"),
  matchMeta: document.querySelector("#matchMeta"),
};

let stream;
let cameraReady = false;
let ocrDb = { cards: [], byCardId: {} };
let audioManifest = { byCardId: {} };
let introTtsManifest = { byCardId: {}, byCardNo: {} };
let abilityTtsManifest = { byCardId: {}, byCardNo: {} };
let fingerprintDb = { cards: [], byCardId: {} };
let tesseractWorker;
let mode = "loading";
let frozenGuideRect = null;
let activeAudioCardId = "";
let pendingAudioCard = null;
let lastAudioMessage = "";
let playbackToken = 0;
let speechRecognition = null;
let isVoiceListening = false;
let voiceResultHandled = false;
let voiceErrorHandled = false;

const speechElement = new Audio();
speechElement.preload = "auto";
speechElement.loop = false;

const birdBgElement = new Audio();
birdBgElement.preload = "auto";
birdBgElement.loop = false;
birdBgElement.volume = 1;

const ocrCanvas = document.createElement("canvas");
const ocrContext = ocrCanvas.getContext("2d", { willReadFrequently: true });
let ocrSections = [];

const captureCanvas = document.createElement("canvas");
const captureContext = captureCanvas.getContext("2d", { willReadFrequently: true });
const dhashCanvas = document.createElement("canvas");
const dhashContext = dhashCanvas.getContext("2d", { willReadFrequently: true });
dhashCanvas.width = DHASH_WIDTH;
dhashCanvas.height = DHASH_HEIGHT;
const dhashWorkCanvas = document.createElement("canvas");
const dhashWorkContext = dhashWorkCanvas.getContext("2d", { willReadFrequently: true });
const snapshotContext = elements.snapshot?.getContext("2d") ?? null;

function setStatus(message, type = "") {
  elements.status.textContent = message;
  elements.status.className = `status ${type}`.trim();
}

function setMode(next) {
  mode = next;
  if (elements.scanner) {
    elements.scanner.dataset.mode = next;
  }
  if (elements.shutterButton) {
    elements.shutterButton.disabled = next !== "live" || isVoiceListening || !cameraReady;
  }
  if (elements.retakeButton) {
    elements.retakeButton.hidden = next !== "review";
  }
  updateVoiceButtonState();
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

function normalizeOcrTextForMatch(value) {
  return String(value)
    .normalize("NFKC")
    .toLocaleLowerCase("ko-KR")
    .replace(/&/g, "and")
    .replace(/[^0-9a-zㄱ-ㆎ가-힣]+/g, "");
}

function extractLatinText(value) {
  const matches = String(value).match(/[A-Za-z][A-Za-z.'-]{1,}/g) ?? [];
  return matches
    .map((part) => part.replace(/^[.'-]+|[.'-]+$/g, ""))
    .filter((part) => part.length > 1)
    .join(" ");
}

function extractKoreanText(value) {
  const matches = String(value).match(/[ㄱ-ㆎ가-힣]{2,}/g) ?? [];
  return matches.join(" ");
}

function normalizeDigitsForOcr(value) {
  return String(value)
    .normalize("NFKC")
    .replace(/[Oo]/g, "0")
    .replace(/[Il|]/g, "1");
}

function uniqueValues(values) {
  return [...new Set(values.filter(Boolean))];
}

function extractSingleDigitNumbers(value) {
  const normalized = normalizeDigitsForOcr(value);
  const matches = [...normalized.matchAll(/(^|[^\d])([0-9])(?=$|[^\d])/g)];
  return uniqueValues(matches.map((match) => match[2]));
}

function extractCmNumbers(value) {
  const normalized = normalizeDigitsForOcr(value);
  const cmMatches = [...normalized.matchAll(/(^|[^\d])([0-9]{2,3})\s*[cC]\s*[mM]\b/g)];
  if (cmMatches.length) {
    return uniqueValues(cmMatches.map((match) => match[2]));
  }
  const numericMatches = [...normalized.matchAll(/(^|[^\d])([0-9]{2,3})(?=$|[^\d])/g)];
  return uniqueValues(numericMatches.map((match) => match[2]));
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

function indexFingerprints(cards) {
  const byCardId = {};
  for (const card of cards) {
    byCardId[card.id] = card;
  }
  return byCardId;
}

async function loadData() {
  setStatus("불러오는 중", "ready");
  const [ocrDbData, audioManifestData, introData, abilityData, fingerprintData] =
    await Promise.all([
      fetchJson("./data/card_ocr_aliases.json", { cards: [], byCardId: {} }),
      fetchJson("./data/audio_clips.json", { byCardId: {} }),
      fetchJson("./data/card_intro_tts.json", { byCardId: {}, byCardNo: {} }),
      fetchJson("./data/card_ability_tts.json", { byCardId: {}, byCardNo: {} }),
      fetchJson("./data/card_fingerprints.json", { cards: [] }),
    ]);
  ocrDb = ocrDbData;
  audioManifest = audioManifestData;
  introTtsManifest = introData;
  abilityTtsManifest = abilityData;
  fingerprintDb = {
    cards: fingerprintData.cards ?? [],
    byCardId: indexFingerprints(fingerprintData.cards ?? []),
  };
  if (!ocrDb.cards.length) {
    throw new Error("OCR 데이터를 불러오지 못했습니다.");
  }
}

async function initOcrWorker() {
  if (tesseractWorker) {
    return;
  }
  if (!window.Tesseract?.createWorker) {
    throw new Error("OCR 엔진을 사용할 수 없습니다.");
  }
  setStatus("문자 인식", "ready");
  tesseractWorker = await window.Tesseract.createWorker("kor+eng");
  await tesseractWorker.setParameters({
    preserve_interword_spaces: "1",
  });
}

function videoSourceRectFromElement(targetElement) {
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

function clampSourceRect(rect, sourceWidth, sourceHeight) {
  const width = clamp(rect.sw, 1, sourceWidth);
  const height = clamp(rect.sh, 1, sourceHeight);
  return {
    sx: clamp(rect.sx, 0, Math.max(0, sourceWidth - width)),
    sy: clamp(rect.sy, 0, Math.max(0, sourceHeight - height)),
    sw: width,
    sh: height,
  };
}

function cardRegionSourceRect(region, marginRatio, cardRect, sourceWidth, sourceHeight) {
  const marginX = region.width * marginRatio;
  const marginY = region.height * marginRatio;
  const x = Math.max(0, region.x - marginX);
  const y = Math.max(0, region.y - marginY);
  const width = Math.min(CARD_SIZE.width - x, region.width + marginX * 2);
  const height = Math.min(CARD_SIZE.height - y, region.height + marginY * 2);
  return clampSourceRect(
    {
      sx: cardRect.sx + (cardRect.sw * x) / CARD_SIZE.width,
      sy: cardRect.sy + (cardRect.sh * y) / CARD_SIZE.height,
      sw: (cardRect.sw * width) / CARD_SIZE.width,
      sh: (cardRect.sh * height) / CARD_SIZE.height,
    },
    sourceWidth,
    sourceHeight,
  );
}

function rotationAnglesForRegion(region) {
  return OCR_ROTATION_REGION_KEYS.has(region.key) ? OCR_ROTATION_DEGREES : [0];
}

function rotatedBounds(width, height, degrees) {
  const radians = (Math.abs(degrees) * Math.PI) / 180;
  return {
    width: Math.ceil(width * Math.cos(radians) + height * Math.sin(radians)),
    height: Math.ceil(width * Math.sin(radians) + height * Math.cos(radians)),
  };
}

function createOcrLayout(region, degrees, cardRect, sourceWidth, sourceHeight) {
  const marginRatio = degrees === 0 ? OCR_REGION_MARGIN : OCR_ROTATED_REGION_MARGIN;
  const rect = cardRegionSourceRect(region, marginRatio, cardRect, sourceWidth, sourceHeight);
  const maxWidth = OCR_CANVAS_WIDTH - OCR_CANVAS_PADDING * 2;
  let targetWidth = Math.min(maxWidth, region.targetWidth);
  let scale = targetWidth / rect.sw;
  let targetHeight = Math.max(region.minHeight, Math.round(rect.sh * scale));
  let bounds = rotatedBounds(targetWidth, targetHeight, degrees);

  if (bounds.width > maxWidth) {
    const shrink = maxWidth / bounds.width;
    targetWidth = Math.floor(targetWidth * shrink);
    targetHeight = Math.floor(targetHeight * shrink);
    bounds = rotatedBounds(targetWidth, targetHeight, degrees);
  }

  return {
    region,
    rect,
    degrees,
    targetWidth,
    targetHeight,
    layoutWidth: bounds.width,
    layoutHeight: bounds.height,
    targetX: Math.round((OCR_CANVAS_WIDTH - bounds.width) / 2),
  };
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

function drawCardSignalsForOcr(sourceCanvas, cardRect) {
  const sourceWidth = sourceCanvas.width;
  const sourceHeight = sourceCanvas.height;
  if (!sourceWidth || !sourceHeight) {
    throw new Error("캡처 이미지가 비어 있습니다.");
  }

  const layouts = OCR_SIGNAL_REGIONS.flatMap((region) =>
    rotationAnglesForRegion(region).map((degrees) =>
      createOcrLayout(region, degrees, cardRect, sourceWidth, sourceHeight),
    ),
  );

  let y = OCR_CANVAS_PADDING;
  for (const layout of layouts) {
    layout.targetY = y;
    y += layout.layoutHeight + OCR_SECTION_GAP;
  }

  ocrCanvas.width = OCR_CANVAS_WIDTH;
  ocrCanvas.height = Math.max(96, y - OCR_SECTION_GAP + OCR_CANVAS_PADDING);
  ocrContext.imageSmoothingEnabled = true;
  ocrContext.fillStyle = "#ffffff";
  ocrContext.fillRect(0, 0, ocrCanvas.width, ocrCanvas.height);

  ocrSections = [];
  for (const layout of layouts) {
    const {
      region,
      rect,
      degrees,
      targetX,
      targetY,
      targetWidth,
      targetHeight,
      layoutWidth,
      layoutHeight,
    } = layout;
    ocrContext.filter =
      region.key === "ability"
        ? "grayscale(1) contrast(2.05) brightness(1.12)"
        : "grayscale(1) contrast(1.85) brightness(1.1)";
    ocrContext.save();
    ocrContext.translate(targetX + layoutWidth / 2, targetY + layoutHeight / 2);
    ocrContext.rotate((degrees * Math.PI) / 180);
    ocrContext.drawImage(
      sourceCanvas,
      rect.sx,
      rect.sy,
      rect.sw,
      rect.sh,
      -targetWidth / 2,
      -targetHeight / 2,
      targetWidth,
      targetHeight,
    );
    ocrContext.restore();
    ocrSections.push({
      key: region.key,
      top: targetY,
      bottom: targetY + layoutHeight,
    });
  }
  ocrContext.filter = "none";
  preprocessOcrCanvas();
}

function artSourceRect(cardRect, sourceWidth, sourceHeight) {
  return clampSourceRect(
    {
      sx: cardRect.sx + (cardRect.sw * ART_REGION.x) / CARD_SIZE.width,
      sy: cardRect.sy + (cardRect.sh * ART_REGION.y) / CARD_SIZE.height,
      sw: (cardRect.sw * ART_REGION.width) / CARD_SIZE.width,
      sh: (cardRect.sh * ART_REGION.height) / CARD_SIZE.height,
    },
    sourceWidth,
    sourceHeight,
  );
}

function computeArtDhashHex(sourceCanvas, cardRect) {
  const artRect = artSourceRect(cardRect, sourceCanvas.width, sourceCanvas.height);
  const workW = Math.max(64, Math.round(artRect.sw));
  const workH = Math.max(64, Math.round(artRect.sh));
  if (dhashWorkCanvas.width !== workW || dhashWorkCanvas.height !== workH) {
    dhashWorkCanvas.width = workW;
    dhashWorkCanvas.height = workH;
  }
  dhashWorkContext.imageSmoothingEnabled = true;
  dhashWorkContext.imageSmoothingQuality = "high";
  dhashWorkContext.drawImage(
    sourceCanvas,
    artRect.sx,
    artRect.sy,
    artRect.sw,
    artRect.sh,
    0,
    0,
    workW,
    workH,
  );

  const work = dhashWorkContext.getImageData(0, 0, workW, workH);
  const wd = work.data;
  const totalPixels = workW * workH;
  const grayBuf = new Uint8ClampedArray(totalPixels);
  let min = 255;
  let max = 0;
  for (let i = 0, p = 0; i < wd.length; i += 4, p += 1) {
    const g = Math.round(wd[i] * 0.299 + wd[i + 1] * 0.587 + wd[i + 2] * 0.114);
    grayBuf[p] = g;
    if (g < min) min = g;
    if (g > max) max = g;
  }
  const range = Math.max(1, max - min);
  for (let i = 0, p = 0; i < wd.length; i += 4, p += 1) {
    const stretched = Math.round(((grayBuf[p] - min) / range) * 255);
    wd[i] = stretched;
    wd[i + 1] = stretched;
    wd[i + 2] = stretched;
    wd[i + 3] = 255;
  }
  dhashWorkContext.putImageData(work, 0, 0);

  dhashContext.imageSmoothingEnabled = true;
  dhashContext.imageSmoothingQuality = "high";
  dhashContext.fillStyle = "#000000";
  dhashContext.fillRect(0, 0, DHASH_WIDTH, DHASH_HEIGHT);
  dhashContext.drawImage(dhashWorkCanvas, 0, 0, DHASH_WIDTH, DHASH_HEIGHT);

  const { data } = dhashContext.getImageData(0, 0, DHASH_WIDTH, DHASH_HEIGHT);
  const grays = new Uint8Array(DHASH_WIDTH * DHASH_HEIGHT);
  for (let i = 0, p = 0; i < data.length; i += 4, p += 1) {
    grays[p] = data[i];
  }

  let hex = "";
  let nibble = 0;
  let nibbleBits = 0;
  for (let row = 0; row < DHASH_HEIGHT; row += 1) {
    const rowOffset = row * DHASH_WIDTH;
    for (let col = 0; col < DHASH_WIDTH - 1; col += 1) {
      const bit = grays[rowOffset + col] > grays[rowOffset + col + 1] ? 1 : 0;
      nibble = (nibble << 1) | bit;
      nibbleBits += 1;
      if (nibbleBits === 4) {
        hex += nibble.toString(16);
        nibble = 0;
        nibbleBits = 0;
      }
    }
  }
  if (nibbleBits > 0) {
    hex += (nibble << (4 - nibbleBits)).toString(16);
  }
  return hex;
}

const HEX_POPCOUNT = (() => {
  const table = new Uint8Array(256);
  for (let i = 0; i < 256; i += 1) {
    let v = i;
    let count = 0;
    while (v) {
      count += v & 1;
      v >>= 1;
    }
    table[i] = count;
  }
  return table;
})();

function hammingDistanceHex(left, right) {
  if (!left || !right || left.length !== right.length) {
    return DHASH_BITS;
  }
  let total = 0;
  for (let i = 0; i < left.length; i += 2) {
    const a = parseInt(left.slice(i, i + 2), 16);
    const b = parseInt(right.slice(i, i + 2), 16);
    if (Number.isNaN(a) || Number.isNaN(b)) {
      total += 8;
      continue;
    }
    total += HEX_POPCOUNT[a ^ b];
  }
  return total;
}

function visualScoreFromHamming(hamming) {
  return Math.max(0, Math.round(100 - (hamming * 100) / VISUAL_SCORE_DIVISOR));
}

function cardFingerprintHashes(card) {
  if (!card) {
    return [];
  }
  if (Array.isArray(card.hashes) && card.hashes.length) {
    return card.hashes.filter(Boolean);
  }
  return card.hash ? [card.hash] : [];
}

function isVisualReferenceUsable(card) {
  return card?.visualReferenceValid !== false && cardFingerprintHashes(card).length > 0;
}

function computeVisualScores(capturedHash) {
  const scores = {};
  if (!capturedHash) {
    return scores;
  }
  for (const card of fingerprintDb.cards) {
    if (!isVisualReferenceUsable(card)) {
      continue;
    }
    const hashes = cardFingerprintHashes(card);
    const distance = hashes.reduce(
      (best, hash) => Math.min(best, hammingDistanceHex(capturedHash, hash)),
      DHASH_BITS,
    );
    scores[card.id] = {
      distance,
      score: visualScoreFromHamming(distance),
      variantCount: hashes.length,
    };
  }
  return scores;
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

function wordCenterY(word) {
  const box = word?.bbox ?? word;
  const y0 = Number(box?.y0);
  const y1 = Number(box?.y1);
  if (Number.isFinite(y0) && Number.isFinite(y1)) {
    return (y0 + y1) / 2;
  }
  return null;
}

function textItemsFromOcrResult(result) {
  const words = result?.data?.words ?? [];
  if (words.length) {
    return words.map((word) => ({ text: word.text ?? "", centerY: wordCenterY(word) }));
  }
  const lines = result?.data?.lines ?? [];
  return lines.map((line) => ({ text: line.text ?? "", centerY: wordCenterY(line) }));
}

function sectionForY(centerY) {
  if (!Number.isFinite(centerY)) {
    return null;
  }
  return ocrSections.find((section) => centerY >= section.top && centerY <= section.bottom) ?? null;
}

function groupedOcrText(result) {
  const allText = result?.data?.text ?? "";
  const sections = Object.fromEntries(OCR_SIGNAL_REGIONS.map((region) => [region.key, ""]));
  let grouped = false;

  for (const item of textItemsFromOcrResult(result)) {
    const section = sectionForY(item.centerY);
    const text = String(item.text ?? "").trim();
    if (!section || !text) {
      continue;
    }
    sections[section.key] = `${sections[section.key]} ${text}`.trim();
    grouped = true;
  }

  if (!grouped) {
    sections.title = allText;
  }
  return { allText, sections };
}

function extractOcrSignals(result) {
  const { allText, sections } = groupedOcrText(result);
  const titleText = sections.title || allText;
  const scoreText = sections.score || "";
  const wingText = sections.wing || "";
  const abilityText = sections.ability || "";

  return {
    allText,
    titleText,
    latinText: extractLatinText(titleText),
    koreanText: extractKoreanText(titleText),
    scoreNumbers: extractSingleDigitNumbers(scoreText),
    wingNumbers: extractCmNumbers(wingText),
    abilityText,
  };
}

function bestScoreForAliases(query, aliases, normalizer) {
  let best = { alias: "", score: 0 };
  if (query.length < OCR_MIN_QUERY_LENGTH) {
    return best;
  }
  for (const alias of aliases ?? []) {
    const normalized = normalizer(alias);
    const score = normalizedSimilarity(query, normalized);
    if (score > best.score) {
      best = { alias, score };
    }
  }
  return best;
}

function bestNameScore(signals, card) {
  const latinQuery = normalizeForMatch(signals.latinText);
  const koreanQuery = normalizeOcrTextForMatch(signals.koreanText);
  const latinBest = bestScoreForAliases(latinQuery, card.aliases, normalizeForMatch);
  const koreanBest = bestScoreForAliases(
    koreanQuery,
    card.koreanAliases ?? [],
    normalizeOcrTextForMatch,
  );

  if (koreanBest.score > latinBest.score) {
    return { ...koreanBest, kind: "ko" };
  }
  return { ...latinBest, kind: "en" };
}

function exactNumericMatches(signals, card) {
  const numericSignals = card.numericSignals ?? {};
  const matches = [];
  const pointValue = String(numericSignals.pointValue ?? "");
  const wingspanCm = String(numericSignals.wingspanCm ?? "");

  if (pointValue && signals.scoreNumbers.includes(pointValue)) {
    matches.push(OCR_SCORE_SIGNAL_LABEL);
  }
  if (wingspanCm && signals.wingNumbers.includes(wingspanCm)) {
    matches.push(OCR_WING_SIGNAL_LABEL);
  }
  return matches;
}

function hasExactNumericPair(numericMatches) {
  return (
    numericMatches.includes(OCR_SCORE_SIGNAL_LABEL) &&
    numericMatches.includes(OCR_WING_SIGNAL_LABEL)
  );
}

function abilityKeywordScore(signals, card) {
  const abilityText = normalizeOcrTextForMatch(signals.abilityText);
  if (!abilityText) {
    return 0;
  }
  const keywords = card.abilityKeywords ?? [];
  const hits = keywords.filter((keyword) => abilityText.includes(normalizeOcrTextForMatch(keyword)));
  return Math.min(12, hits.length * 4);
}

function compositeCandidateRankScore(nameScore, numericMatches, abilityScore, visualScore) {
  const pairBoost = hasExactNumericPair(numericMatches) ? OCR_NUMERIC_PAIR_BOOST : 0;
  return Math.round(
    nameScore +
      numericMatches.length * OCR_NUMERIC_SINGLE_BOOST +
      pairBoost +
      abilityScore +
      visualScore * VISUAL_RANK_WEIGHT,
  );
}

function rankCandidates(signals, visualScores) {
  const candidates = ocrDb.cards.map((card) => {
    const best = bestNameScore(signals, card);
    const numericMatches = exactNumericMatches(signals, card);
    const abilityScore = abilityKeywordScore(signals, card);
    const fingerprint = fingerprintDb.byCardId?.[card.id] ?? null;
    const visualReferenceValid = isVisualReferenceUsable(fingerprint);
    const visual = visualScores[card.id] ?? null;
    const visualScore = visualReferenceValid ? (visual?.score ?? 0) : 0;
    const visualDistance = visualReferenceValid ? (visual?.distance ?? null) : null;
    const rankScore = compositeCandidateRankScore(
      best.score,
      numericMatches,
      abilityScore,
      visualScore,
    );
    return {
      ...card,
      matchedAlias: best.alias,
      matchKind: best.kind,
      nameScore: best.score,
      numericMatches,
      numericPairMatched: hasExactNumericPair(numericMatches),
      abilityScore,
      visualReferenceValid,
      visualScore,
      visualDistance,
      visualVariantCount: visual?.variantCount ?? 0,
      rankScore,
      score: Math.min(100, rankScore),
    };
  });
  candidates.sort(
    (a, b) =>
      b.rankScore - a.rankScore ||
      b.visualScore - a.visualScore ||
      b.nameScore - a.nameScore ||
      b.numericMatches.length - a.numericMatches.length ||
      a.cardNo.localeCompare(b.cardNo),
  );
  return candidates;
}

function matchConfidence(best, second) {
  if (!best) {
    return { ok: false, gap: 0, reason: "후보 없음" };
  }
  const gap = (best.rankScore ?? best.score) - (second?.rankScore ?? second?.score ?? 0);
  const exactCount = best.numericMatches?.length ?? 0;
  const strongName = best.nameScore >= OCR_STRONG_NAME_SCORE;
  const mediumNameWithNumber = best.nameScore >= OCR_MEDIUM_NAME_SCORE && exactCount >= 1;
  const weakNameWithNumbers = best.nameScore >= OCR_MIN_NAME_SCORE && exactCount >= 2;
  const visualStrong = best.visualReferenceValid && best.visualScore >= VISUAL_STRONG_SCORE;
  const nameAndVisual =
    best.visualReferenceValid &&
    best.nameScore >= OCR_MIN_NAME_SCORE &&
    best.visualScore >= VISUAL_MEDIUM_SCORE;

  if (!strongName && !mediumNameWithNumber && !weakNameWithNumbers && !visualStrong && !nameAndVisual) {
    if (best.nameScore < OCR_MIN_NAME_SCORE) {
      return { ok: false, gap, reason: `이름 ${best.nameScore}% / 이미지 ${best.visualScore}%` };
    }
    return {
      ok: false,
      gap,
      reason: exactCount ? `추가 신호 필요 ${exactCount}/2` : `이름 ${best.nameScore}%`,
    };
  }
  if (gap < OCR_MIN_GAP) {
    return { ok: false, gap, reason: `다음 후보와 차이 ${gap}%` };
  }
  return { ok: true, gap, reason: "" };
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

function introTtsForCard(card) {
  return introTtsManifest?.byCardId?.[card.id] ?? introTtsManifest?.byCardNo?.[card.cardNo] ?? null;
}

function abilityTtsForCard(card) {
  return abilityTtsManifest?.byCardId?.[card.id] ?? abilityTtsManifest?.byCardNo?.[card.cardNo] ?? null;
}

function includeAbilityTts() {
  return Boolean(elements.abilityToggle?.checked);
}

function displayNameForCard(card) {
  return introTtsForCard(card)?.birdName || abilityTtsForCard(card)?.birdName || card.birdName;
}

function cardById(cardId) {
  return ocrDb.byCardId?.[cardId] ?? ocrDb.cards.find((card) => card.id === cardId) ?? null;
}

function candidateMetaText(candidate) {
  const parts = [];
  if (candidate.nameScore > 0) {
    parts.push(`이름 ${candidate.nameScore}%`);
  }
  if (candidate.visualScore > 0) {
    parts.push(`이미지 ${candidate.visualScore}%`);
  }
  if (candidate.numericMatches?.length) {
    parts.push(candidate.numericMatches.join("+"));
  }
  if (candidate.abilityScore > 0) {
    parts.push("능력");
  }
  return parts.join(" · ") || "유사 후보";
}

function hideCandidateSuggestions() {
  if (!elements.candidatePanel || !elements.candidateList) {
    return;
  }
  elements.candidatePanel.hidden = true;
  elements.candidateList.replaceChildren();
}

function candidateButton(candidate, index, leadingCardId) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "candidate-button";
  if (candidate.id === leadingCardId) {
    button.classList.add("is-leading");
  }
  button.dataset.cardId = candidate.id;
  button.setAttribute("aria-label", `${displayNameForCard(candidate)} 선택`);

  const rank = document.createElement("span");
  rank.className = "candidate-rank";
  rank.textContent = String(index + 1);

  const text = document.createElement("span");
  text.className = "candidate-text";

  const name = document.createElement("span");
  name.className = "candidate-name";
  name.textContent = displayNameForCard(candidate);

  const meta = document.createElement("span");
  meta.className = "candidate-meta";
  meta.textContent = `${candidate.cardNo} · ${candidateMetaText(candidate)}`;

  const score = document.createElement("span");
  score.className = "candidate-score";
  score.textContent = `${candidate.score}%`;

  text.append(name, meta);
  button.append(rank, text, score);
  return button;
}

function isUsefulCandidate(candidate) {
  if (!candidate) {
    return false;
  }
  if (candidate.numericPairMatched || candidate.abilityScore > 0) {
    return true;
  }
  if ((candidate.numericMatches?.length ?? 0) >= 2) {
    return true;
  }
  if (candidate.nameScore >= MIN_CANDIDATE_NAME_SCORE) {
    return true;
  }
  if (candidate.visualScore >= VISUAL_MEDIUM_SCORE) {
    return true;
  }
  if ((candidate.numericMatches?.length ?? 0) >= 1) {
    return true;
  }
  return (candidate.rankScore ?? candidate.score ?? 0) >= MIN_CANDIDATE_RANK_SCORE;
}

function renderCandidateSuggestions(candidates, leadingCardId = "") {
  if (!elements.candidatePanel || !elements.candidateList) {
    return;
  }
  const useful = candidates.filter(isUsefulCandidate);
  const top = (useful.length ? useful : candidates).slice(0, MAX_CANDIDATE_SUGGESTIONS);
  if (!top.length) {
    hideCandidateSuggestions();
    return;
  }
  elements.candidateList.replaceChildren(
    ...top.map((candidate, index) => candidateButton(candidate, index, leadingCardId)),
  );
  elements.candidatePanel.hidden = false;
  elements.candidateList.scrollTop = 0;
}

function selectCandidateCard(card) {
  if (!card) {
    return;
  }
  triggerSuccessFeedback(card, true);
  const audioMessage = playAudioForCard(card, true);
  elements.matchName.textContent = displayNameForCard(card);
  elements.matchScore.textContent = "직접 선택";
  elements.matchMeta.textContent = `${card.cardNo} ${displayNameForCard(card)} / 사용자 선택 / ${audioMessage}`;
  setStatus("선택", "ready");
  hideCandidateSuggestions();
}

function updateVoiceButtonState() {
  if (!elements.voiceButton) {
    return;
  }
  const supported = Boolean(speechRecognition);
  const canUseNow = mode === "live" || isVoiceListening;
  elements.voiceButton.disabled = !supported || !canUseNow;
  elements.voiceButton.classList.toggle("is-listening", isVoiceListening);
  elements.voiceButton.setAttribute("aria-pressed", String(isVoiceListening));
  elements.voiceButton.title = supported
    ? isVoiceListening
      ? "듣기 중지"
      : "새 이름 말하기"
    : "이 브라우저에서는 음성 인식을 지원하지 않습니다.";
}

function setVoiceListening(next) {
  isVoiceListening = next;
  if (elements.shutterButton) {
    elements.shutterButton.disabled = mode !== "live" || isVoiceListening || !cameraReady;
  }
  updateVoiceButtonState();
}

function voiceSignalsFromTranscript(transcript) {
  const text = String(transcript).replace(/\s+/g, " ").trim();
  return {
    allText: text,
    titleText: text,
    latinText: extractLatinText(text),
    koreanText: extractKoreanText(text),
    scoreNumbers: [],
    wingNumbers: [],
    abilityText: "",
  };
}

function transcriptsFromSpeechEvent(event) {
  const transcripts = [];
  for (let resultIndex = event.resultIndex; resultIndex < event.results.length; resultIndex += 1) {
    const result = event.results[resultIndex];
    for (let altIndex = 0; altIndex < result.length; altIndex += 1) {
      const transcript = String(result[altIndex]?.transcript ?? "").replace(/\s+/g, " ").trim();
      if (transcript) {
        transcripts.push(transcript);
      }
    }
  }
  return uniqueValues(transcripts);
}

function rankVoiceCandidates(transcripts) {
  const byCardId = new Map();
  for (const transcript of transcripts) {
    const candidates = rankCandidates(voiceSignalsFromTranscript(transcript), {});
    for (const candidate of candidates) {
      if (!candidate.nameScore) {
        continue;
      }
      const current = byCardId.get(candidate.id);
      if (
        !current ||
        candidate.nameScore > current.nameScore ||
        (candidate.nameScore === current.nameScore && candidate.rankScore > current.rankScore)
      ) {
        byCardId.set(candidate.id, {
          ...candidate,
          voiceTranscript: transcript,
          visualScore: 0,
          visualDistance: null,
          abilityScore: 0,
          numericMatches: [],
          numericPairMatched: false,
          rankScore: candidate.nameScore,
          score: candidate.nameScore,
        });
      }
    }
  }
  return [...byCardId.values()].sort(
    (a, b) =>
      b.rankScore - a.rankScore ||
      b.nameScore - a.nameScore ||
      a.cardNo.localeCompare(b.cardNo),
  );
}

function formatVoiceMeta(best, second, transcript, audioMessage, confidence) {
  const parts = [];
  if (transcript) {
    parts.push(`말함 "${transcript.replace(/\s+/g, " ").slice(0, 44)}"`);
  }
  if (best) {
    parts.push(`${best.cardNo} ${best.matchedAlias || best.birdName} 이름 ${best.nameScore}%`);
  }
  if (second) {
    parts.push(`다음 ${second.cardNo} ${second.score}%`);
  }
  if (confidence?.reason) {
    parts.push(confidence.reason);
  }
  if (audioMessage) {
    parts.push(audioMessage);
  }
  return parts.join(" / ") || "-";
}

function showVoiceMessage(message, type = "") {
  hideCandidateSuggestions();
  updateRecognitionRate(null);
  elements.matchName.textContent = "음성 인식";
  elements.matchScore.textContent = "-";
  elements.matchMeta.textContent = message;
  setStatus(type === "error" ? "오류" : "대기", type);
}

function processVoiceTranscripts(transcripts) {
  const candidates = rankVoiceCandidates(transcripts);
  const [best, second] = candidates;
  const transcript = best?.voiceTranscript || transcripts[0] || "";
  const confidence = matchConfidence(best, second);
  let audioMessage = "";

  updateRecognitionRate(best?.score);

  if (!best) {
    showVoiceMessage("일치하는 후보를 찾지 못했습니다.");
    return;
  }

  renderCandidateSuggestions(candidates, best.id);

  if (confidence.ok) {
    triggerSuccessFeedback(best, true);
    audioMessage = playAudioForCard(best, true);
    elements.matchName.textContent = displayNameForCard(best);
    elements.matchScore.textContent = `${best.score}% / 차이 ${confidence.gap}`;
    elements.matchMeta.textContent = formatVoiceMeta(best, second, transcript, audioMessage, confidence);
    setStatus("일치", "ready");
    hideCandidateSuggestions();
    return;
  }

  audioMessage = "후보 중 선택";
  elements.matchName.textContent = displayNameForCard(best);
  elements.matchScore.textContent = `${best.score}% / 차이 ${confidence.gap}`;
  elements.matchMeta.textContent = formatVoiceMeta(best, second, transcript, audioMessage, confidence);
  setStatus("선택", "");
}

function voiceErrorMessage(errorType) {
  switch (errorType) {
    case "not-allowed":
    case "service-not-allowed":
      return "마이크 권한이 필요합니다.";
    case "no-speech":
      return "음성이 감지되지 않았습니다.";
    case "audio-capture":
      return "마이크를 사용할 수 없습니다.";
    case "network":
      return "음성 인식 네트워크 오류입니다.";
    default:
      return "음성 인식에 실패했습니다.";
  }
}

function handleVoiceRecognitionResult(event) {
  voiceResultHandled = true;
  const transcripts = transcriptsFromSpeechEvent(event);
  if (!transcripts.length) {
    showVoiceMessage("일치하는 후보를 찾지 못했습니다.");
    return;
  }
  processVoiceTranscripts(transcripts);
}

function handleVoiceRecognitionError(event) {
  if (event.error === "aborted") {
    return;
  }
  voiceErrorHandled = true;
  showVoiceMessage(voiceErrorMessage(event.error), "error");
}

function handleVoiceRecognitionEnd() {
  const hadResultOrError = voiceResultHandled || voiceErrorHandled;
  setVoiceListening(false);
  if (!hadResultOrError && mode === "live") {
    setStatus("대기", "ready");
  }
}

function stopVoiceRecognition() {
  if (!speechRecognition || !isVoiceListening) {
    return;
  }
  try {
    speechRecognition.abort();
  } catch (error) {
    setVoiceListening(false);
  }
}

function handleVoiceButton() {
  if (!speechRecognition) {
    showVoiceMessage("이 브라우저에서는 음성 인식을 지원하지 않습니다.", "error");
    return;
  }
  if (isVoiceListening) {
    speechRecognition.stop();
    return;
  }
  if (mode !== "live") {
    return;
  }

  try {
    voiceResultHandled = false;
    voiceErrorHandled = false;
    speechRecognition.start();
  } catch (error) {
    showVoiceMessage("음성 인식을 시작하지 못했습니다.", "error");
  }
}

function speechQueueForCard(card) {
  const queue = [];
  const intro = introTtsForCard(card);
  if (intro?.src) {
    queue.push({ kind: "intro", src: intro.src });
  }
  const ability = abilityTtsForCard(card);
  if (includeAbilityTts() && ability?.src) {
    queue.push({ kind: "ability", src: ability.src });
  }
  return queue;
}

function waitForAudioEnd(audio) {
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      audio.removeEventListener("ended", handleEnded);
      audio.removeEventListener("error", handleError);
    };
    const handleEnded = () => {
      cleanup();
      resolve();
    };
    const handleError = () => {
      cleanup();
      reject(new Error("오디오 재생에 실패했습니다."));
    };
    audio.addEventListener("ended", handleEnded, { once: true });
    audio.addEventListener("error", handleError, { once: true });
  });
}

function stopAudioPlayback() {
  playbackToken += 1;
  speechElement.pause();
  speechElement.removeAttribute("src");
  birdBgElement.pause();
  birdBgElement.removeAttribute("src");
}

async function playSpeechQueue(queue, token, card) {
  try {
    for (const item of queue) {
      if (token !== playbackToken) {
        return;
      }
      speechElement.pause();
      speechElement.currentTime = 0;
      speechElement.src = item.src;
      await speechElement.play();
      await waitForAudioEnd(speechElement);
    }
    if (token === playbackToken) {
      birdBgElement.pause();
    }
  } catch (error) {
    if (token === playbackToken) {
      pendingAudioCard = card;
      lastAudioMessage = "소리 재생은 화면을 탭";
      birdBgElement.pause();
    }
  }
}

function playAudioForCard(card, force = false) {
  if (!force && activeAudioCardId === card.id) {
    return lastAudioMessage;
  }

  activeAudioCardId = card.id;
  const clip = randomBirdClipForCard(card);
  const queue = speechQueueForCard(card);
  if (!clip && !queue.length) {
    stopAudioPlayback();
    lastAudioMessage = "오디오 없음";
    return lastAudioMessage;
  }

  stopAudioPlayback();
  const token = playbackToken;

  if (clip) {
    birdBgElement.currentTime = 0;
    birdBgElement.src = clip.src;
    birdBgElement.loop = Boolean(queue.length);
    birdBgElement.volume = queue.length ? BIRD_BG_VOLUME : 1;
    birdBgElement.play().catch(() => {});
  }

  if (queue.length) {
    pendingAudioCard = null;
    playSpeechQueue(queue, token, card);
    lastAudioMessage = includeAbilityTts() && abilityTtsForCard(card) ? "소개 + 능력" : "소개";
    return lastAudioMessage;
  }

  pendingAudioCard = null;
  lastAudioMessage = "새소리";
  return lastAudioMessage;
}

function restartAnimation(element, className) {
  if (!element) {
    return;
  }
  element.classList.remove(className);
  void element.offsetWidth;
  element.classList.add(className);
}

function triggerSuccessFeedback(card) {
  if (!card) {
    return;
  }
  restartAnimation(elements.successGlow, "is-active");
  if (navigator.vibrate) {
    navigator.vibrate(35);
  }
}

function formatMeta(best, second, signals, audioMessage, confidence) {
  const parts = [];
  const readText = signals.titleText || signals.allText;
  if (readText) {
    parts.push(`읽음 "${readText.replace(/\s+/g, " ").slice(0, 44)}"`);
  }
  if (best) {
    const exact = best.numericMatches?.length ? ` 숫자 ${best.numericMatches.join("+")}` : "";
    const numericPair = best.numericPairMatched ? " 점수+cm" : "";
    const visual = best.visualScore > 0 ? ` 이미지 ${best.visualScore}%` : "";
    parts.push(
      `${best.cardNo} ${best.matchedAlias || best.birdName} 이름 ${best.nameScore}%${visual}${exact}${numericPair}`,
    );
  }
  if (second) {
    parts.push(`다음 ${second.cardNo} ${second.score}%`);
  }
  if (confidence?.reason) {
    parts.push(confidence.reason);
  }
  if (audioMessage) {
    parts.push(audioMessage);
  }
  return parts.join(" / ") || "-";
}

function freezeCaptureFromVideo() {
  const video = elements.video;
  const width = video.videoWidth;
  const height = video.videoHeight;
  if (!width || !height) {
    throw new Error("카메라 프레임을 읽을 수 없습니다.");
  }
  if (captureCanvas.width !== width || captureCanvas.height !== height) {
    captureCanvas.width = width;
    captureCanvas.height = height;
  }
  captureContext.drawImage(video, 0, 0, width, height);

  if (elements.snapshot && snapshotContext) {
    elements.snapshot.width = width;
    elements.snapshot.height = height;
    snapshotContext.drawImage(captureCanvas, 0, 0, width, height);
  }
  frozenGuideRect = videoSourceRectFromElement(elements.cardGuide);
}

async function processCapture() {
  if (!tesseractWorker) {
    throw new Error("OCR 엔진이 준비되지 않았습니다.");
  }
  if (!frozenGuideRect) {
    throw new Error("카드 가이드 좌표를 알 수 없습니다.");
  }

  const capturedHash = computeArtDhashHex(captureCanvas, frozenGuideRect);
  const visualScores = computeVisualScores(capturedHash);

  drawCardSignalsForOcr(captureCanvas, frozenGuideRect);
  const result = await tesseractWorker.recognize(ocrCanvas);
  const signals = extractOcrSignals(result);
  const candidates = rankCandidates(signals, visualScores);
  const [best, second] = candidates;
  const confidence = matchConfidence(best, second);
  let audioMessage = "";

  updateRecognitionRate(best?.score);
  renderCandidateSuggestions(candidates, best?.id);

  if (confidence.ok && best) {
    triggerSuccessFeedback(best);
    setTimeout(() => {
      if (mode === "review") {
        audioMessage = playAudioForCard(best);
        elements.matchMeta.textContent = formatMeta(best, second, signals, audioMessage, confidence);
      }
    }, AUTO_SELECT_DELAY_MS);
    audioMessage = "재생 준비";
  } else {
    audioMessage = "후보 중 선택";
  }

  elements.matchName.textContent = best ? displayNameForCard(best) : "후보 없음";
  elements.matchScore.textContent = best
    ? `${best.score}% / 차이 ${confidence.gap}`
    : "-";
  elements.matchMeta.textContent = formatMeta(best, second, signals, audioMessage, confidence);
  setStatus(confidence.ok ? "일치" : "선택", confidence.ok ? "ready" : "");
}

async function handleShutter() {
  if (mode !== "live") {
    return;
  }
  setMode("capturing");
  setStatus("촬영", "ready");
  try {
    freezeCaptureFromVideo();
    setMode("review");
    setStatus("분석 중", "ready");
    await processCapture();
  } catch (error) {
    elements.matchName.textContent = "오류";
    elements.matchScore.textContent = "-";
    elements.matchMeta.textContent = error.message;
    updateRecognitionRate(null);
    hideCandidateSuggestions();
    setStatus("오류", "error");
    setMode("live");
  }
}

function handleRetake() {
  stopVoiceRecognition();
  stopAudioPlayback();
  activeAudioCardId = "";
  pendingAudioCard = null;
  lastAudioMessage = "";
  frozenGuideRect = null;
  hideCandidateSuggestions();
  elements.matchName.textContent = "-";
  elements.matchScore.textContent = "-";
  elements.matchMeta.textContent = "-";
  updateRecognitionRate(null);
  setMode("live");
  setStatus("대기", "ready");
}

async function startCamera() {
  cameraReady = false;
  updateVoiceButtonState();
  if (!window.isSecureContext) {
    throw new Error("HTTPS 환경이 필요합니다.");
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error("카메라 API를 지원하지 않는 브라우저입니다.");
  }

  setStatus("권한 요청", "ready");
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
  cameraReady = true;
  setMode("live");
  setStatus("대기", "ready");
}

async function handleUserActivation() {
  if (pendingAudioCard) {
    playAudioForCard(pendingAudioCard, true);
  }
}

function setDebugSheetCollapsed(collapsed) {
  if (!elements.debugSheet || !elements.debugToggle) {
    return;
  }
  elements.debugSheet.classList.toggle("is-collapsed", collapsed);
  elements.debugToggle.setAttribute("aria-expanded", String(!collapsed));
}

function updateRecognitionRate(score) {
  if (!elements.debugToggle) {
    return;
  }
  const label = Number.isFinite(score) ? `인식률 ${score}%` : "인식률 --";
  elements.debugToggle.textContent = label;
  elements.debugToggle.setAttribute("aria-label", label);
}

function initDebugSheet() {
  if (!elements.debugSheet || !elements.debugToggle) {
    return;
  }
  updateRecognitionRate(null);
  setDebugSheetCollapsed(true);
  elements.debugToggle.addEventListener("click", (event) => {
    event.stopPropagation();
    setDebugSheetCollapsed(!elements.debugSheet.classList.contains("is-collapsed"));
  });
  document.addEventListener(
    "pointerdown",
    (event) => {
      if (!elements.debugSheet.contains(event.target)) {
        setDebugSheetCollapsed(true);
      }
    },
    { passive: true },
  );
}

function initCandidateSuggestions() {
  if (!elements.candidateList) {
    return;
  }
  elements.candidateList.addEventListener("click", (event) => {
    const button = event.target.closest?.(".candidate-button");
    if (!button) {
      return;
    }
    event.stopPropagation();
    selectCandidateCard(cardById(button.dataset.cardId));
  });
}

function initAbilityToggle() {
  if (!elements.abilityToggle) {
    return;
  }
  const savedValue = localStorage.getItem(ABILITY_TOGGLE_STORAGE_KEY);
  elements.abilityToggle.checked = savedValue === null ? true : savedValue === "true";
  elements.abilityToggle.addEventListener("change", () => {
    localStorage.setItem(ABILITY_TOGGLE_STORAGE_KEY, String(elements.abilityToggle.checked));
    stopAudioPlayback();
    activeAudioCardId = "";
    if (pendingAudioCard) {
      playAudioForCard(pendingAudioCard, true);
    }
  });
}

function initShutterControls() {
  elements.shutterButton?.addEventListener("click", (event) => {
    event.stopPropagation();
    handleShutter();
  });
  elements.retakeButton?.addEventListener("click", (event) => {
    event.stopPropagation();
    handleRetake();
  });
}

function initVoiceRecognition() {
  if (!elements.voiceButton) {
    return;
  }
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) {
    updateVoiceButtonState();
    return;
  }

  speechRecognition = new Recognition();
  speechRecognition.lang = VOICE_RECOGNITION_LANG;
  speechRecognition.continuous = false;
  speechRecognition.interimResults = false;
  speechRecognition.maxAlternatives = 5;

  speechRecognition.addEventListener("start", () => {
    voiceResultHandled = false;
    voiceErrorHandled = false;
    setVoiceListening(true);
    hideCandidateSuggestions();
    stopAudioPlayback();
    activeAudioCardId = "";
    pendingAudioCard = null;
    lastAudioMessage = "";
    elements.matchName.textContent = "음성 인식";
    elements.matchScore.textContent = "-";
    elements.matchMeta.textContent = "듣는 중";
    updateRecognitionRate(null);
    setStatus("듣는 중", "ready");
  });
  speechRecognition.addEventListener("result", handleVoiceRecognitionResult);
  speechRecognition.addEventListener("error", handleVoiceRecognitionError);
  speechRecognition.addEventListener("end", handleVoiceRecognitionEnd);

  elements.voiceButton.addEventListener("click", (event) => {
    event.stopPropagation();
    handleVoiceButton();
  });
  updateVoiceButtonState();
}

async function boot() {
  try {
    setMode("loading");
    initDebugSheet();
    initCandidateSuggestions();
    initAbilityToggle();
    initShutterControls();
    initVoiceRecognition();
    await loadData();
    try {
      await initOcrWorker();
      await startCamera();
    } catch (cameraError) {
      cameraReady = false;
      setMode("live");
      elements.matchName.textContent = "카메라";
      elements.matchScore.textContent = "-";
      elements.matchMeta.textContent = `${cameraError.message} / 음성 인식은 계속 사용할 수 있습니다.`;
      updateRecognitionRate(null);
      setStatus(speechRecognition ? "마이크 가능" : "화면 탭", speechRecognition ? "ready" : "error");
    }
  } catch (error) {
    elements.matchName.textContent = "카메라";
    elements.matchScore.textContent = "-";
    elements.matchMeta.textContent = error.message;
    updateRecognitionRate(null);
    setStatus("화면 탭", "error");
  }
}

document.addEventListener("pointerdown", handleUserActivation, { passive: true });
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    stopVoiceRecognition();
    stopAudioPlayback();
  }
});

boot();
