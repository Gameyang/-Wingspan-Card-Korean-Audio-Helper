const CARD_SIZE = {
  width: 630,
  height: 970,
};
const OCR_SIGNAL_REGIONS = [
  { key: "title", x: 100, y: 0, width: 525, height: 132, targetWidth: 1000, minHeight: 160 },
  { key: "score", x: 0, y: 210, width: 95, height: 190, targetWidth: 250, minHeight: 320 },
  { key: "wing", x: 480, y: 420, width: 150, height: 130, targetWidth: 360, minHeight: 210 },
  { key: "ability", x: 0, y: 535, width: 630, height: 128, targetWidth: 1060, minHeight: 190 },
];
const OCR_CANVAS_WIDTH = 1100;
const OCR_CANVAS_PADDING = 18;
const OCR_SECTION_GAP = 18;
const OCR_INTERVAL_MS = 1350;
const OCR_STRONG_NAME_SCORE = 85;
const OCR_MEDIUM_NAME_SCORE = 70;
const OCR_MIN_NAME_SCORE = 60;
const OCR_MIN_GAP = 5;
const OCR_MIN_QUERY_LENGTH = 2;
const STABLE_MATCH_FRAMES = 2;
const MISS_FRAMES_TO_RESET = 4;
const ABILITY_TOGGLE_STORAGE_KEY = "wingspan.includeAbilityTts";
const BIRD_BG_VOLUME = 0.24;

const elements = {
  status: document.querySelector("#status"),
  video: document.querySelector("#camera"),
  cameraBox: document.querySelector("#cameraBox"),
  cardGuide: document.querySelector("#cardGuide"),
  abilityToggle: document.querySelector("#abilityToggle"),
  matchName: document.querySelector("#matchName"),
  matchScore: document.querySelector("#matchScore"),
  matchMeta: document.querySelector("#matchMeta"),
};

let stream;
let ocrDb = { cards: [], byCardId: {} };
let audioManifest = { byCardId: {} };
let introTtsManifest = { byCardId: {}, byCardNo: {} };
let abilityTtsManifest = { byCardId: {}, byCardNo: {} };
let tesseractWorker;
let scanTimer;
let isScanning = false;
let activeAudioCardId = "";
let pendingAudioCard = null;
let lastAudioMessage = "";
let playbackToken = 0;
let missedFrameCount = 0;
let candidateCardId = "";
let candidateFrameCount = 0;

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

function normalizeOcrTextForMatch(value) {
  return String(value)
    .normalize("NFKC")
    .toLocaleLowerCase("ko-KR")
    .replace(/&/g, "and")
    .replace(/[^0-9a-z\u3131-\u318e\uac00-\ud7a3]+/g, "");
}

function extractLatinText(value) {
  const matches = String(value).match(/[A-Za-z][A-Za-z.'-]{1,}/g) ?? [];
  return matches
    .map((part) => part.replace(/^[.'-]+|[.'-]+$/g, ""))
    .filter((part) => part.length > 1)
    .join(" ");
}

function extractKoreanText(value) {
  const matches = String(value).match(/[\u3131-\u318e\uac00-\ud7a3]{2,}/g) ?? [];
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

async function loadData() {
  setStatus("Loading", "ready");
  [ocrDb, audioManifest, introTtsManifest, abilityTtsManifest] = await Promise.all([
    fetchJson("./data/card_ocr_aliases.json", { cards: [], byCardId: {} }),
    fetchJson("./data/audio_clips.json", { byCardId: {} }),
    fetchJson("./data/card_intro_tts.json", { byCardId: {}, byCardNo: {} }),
    fetchJson("./data/card_ability_tts.json", { byCardId: {}, byCardNo: {} }),
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
  tesseractWorker = await window.Tesseract.createWorker("kor+eng");
  await tesseractWorker.setParameters({
    preserve_interword_spaces: "1",
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

function cardRegionSourceRect(region) {
  const cardRect = getVideoSourceRect(elements.cardGuide);
  return clampSourceRect({
    sx: cardRect.sx + (cardRect.sw * region.x) / CARD_SIZE.width,
    sy: cardRect.sy + (cardRect.sh * region.y) / CARD_SIZE.height,
    sw: (cardRect.sw * region.width) / CARD_SIZE.width,
    sh: (cardRect.sh * region.height) / CARD_SIZE.height,
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

function drawCardSignalsForOcr() {
  if (!elements.video.videoWidth || !elements.video.videoHeight) {
    throw new Error("Camera is not ready.");
  }

  const layouts = OCR_SIGNAL_REGIONS.map((region) => {
    const rect = cardRegionSourceRect(region);
    const targetWidth = Math.min(OCR_CANVAS_WIDTH - OCR_CANVAS_PADDING * 2, region.targetWidth);
    const scale = targetWidth / rect.sw;
    const targetHeight = Math.max(region.minHeight, Math.round(rect.sh * scale));
    return {
      region,
      rect,
      targetWidth,
      targetHeight,
      targetX: Math.round((OCR_CANVAS_WIDTH - targetWidth) / 2),
    };
  });

  let y = OCR_CANVAS_PADDING;
  for (const layout of layouts) {
    layout.targetY = y;
    y += layout.targetHeight + OCR_SECTION_GAP;
  }

  ocrCanvas.width = OCR_CANVAS_WIDTH;
  ocrCanvas.height = Math.max(96, y - OCR_SECTION_GAP + OCR_CANVAS_PADDING);
  ocrContext.imageSmoothingEnabled = true;
  ocrContext.fillStyle = "#ffffff";
  ocrContext.fillRect(0, 0, ocrCanvas.width, ocrCanvas.height);

  ocrSections = [];
  for (const layout of layouts) {
    const { region, rect, targetX, targetY, targetWidth, targetHeight } = layout;
    ocrContext.filter =
      region.key === "ability"
        ? "grayscale(1) contrast(2.05) brightness(1.12)"
        : "grayscale(1) contrast(1.85) brightness(1.1)";
    ocrContext.drawImage(
      elements.video,
      rect.sx,
      rect.sy,
      rect.sw,
      rect.sh,
      targetX,
      targetY,
      targetWidth,
      targetHeight,
    );
    ocrSections.push({
      key: region.key,
      top: targetY,
      bottom: targetY + targetHeight,
    });
  }
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
    matches.push("score");
  }
  if (wingspanCm && signals.wingNumbers.includes(wingspanCm)) {
    matches.push("cm");
  }
  return matches;
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

function compositeCandidateScore(nameScore, numericMatches, abilityScore) {
  return Math.min(100, Math.round(nameScore + numericMatches.length * 12 + abilityScore));
}

function rankOcrCandidates(signals) {
  const hasReadableText =
    normalizeForMatch(signals.latinText).length >= OCR_MIN_QUERY_LENGTH ||
    normalizeOcrTextForMatch(signals.koreanText).length >= OCR_MIN_QUERY_LENGTH ||
    signals.scoreNumbers.length > 0 ||
    signals.wingNumbers.length > 0;
  if (!hasReadableText) {
    return { candidates: [] };
  }

  const candidates = ocrDb.cards
    .map((card) => {
      const best = bestNameScore(signals, card);
      const numericMatches = exactNumericMatches(signals, card);
      const abilityScore = abilityKeywordScore(signals, card);
      return {
        ...card,
        matchedAlias: best.alias,
        matchKind: best.kind,
        nameScore: best.score,
        numericMatches,
        abilityScore,
        score: compositeCandidateScore(best.score, numericMatches, abilityScore),
      };
    })
    .sort(
      (a, b) =>
        b.score - a.score ||
        b.nameScore - a.nameScore ||
        b.numericMatches.length - a.numericMatches.length ||
        a.cardNo.localeCompare(b.cardNo),
    );

  return { candidates };
}

function matchConfidence(best, second) {
  if (!best) {
    return { ok: false, gap: 0, reason: "no candidate" };
  }
  const gap = best.score - (second?.score ?? 0);
  const exactCount = best.numericMatches?.length ?? 0;
  if (best.nameScore < OCR_MIN_NAME_SCORE) {
    return { ok: false, gap, reason: `name ${best.nameScore}% < ${OCR_MIN_NAME_SCORE}%` };
  }

  const strongName = best.nameScore >= OCR_STRONG_NAME_SCORE;
  const mediumNameWithNumber = best.nameScore >= OCR_MEDIUM_NAME_SCORE && exactCount >= 1;
  const weakNameWithNumbers = best.nameScore >= OCR_MIN_NAME_SCORE && exactCount >= 2;
  if (!strongName && !mediumNameWithNumber && !weakNameWithNumbers) {
    return {
      ok: false,
      gap,
      reason: exactCount ? `need more signal ${exactCount}/2` : `name ${best.nameScore}%`,
    };
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
      reject(new Error("audio playback failed"));
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
      lastAudioMessage = "tap screen for sound";
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
    lastAudioMessage = "no audio";
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
    lastAudioMessage = includeAbilityTts() && abilityTtsForCard(card) ? "intro + ability" : "intro";
    return lastAudioMessage;
  }

  pendingAudioCard = null;
  lastAudioMessage = `audio ${clip.clipType ?? "clip"}`;
  return lastAudioMessage;
}

function resetAudioAfterMiss() {
  missedFrameCount += 1;
  if (missedFrameCount >= MISS_FRAMES_TO_RESET) {
    activeAudioCardId = "";
    pendingAudioCard = null;
    lastAudioMessage = "";
    stopAudioPlayback();
  }
}

function formatMeta(best, second, signals, audioMessage, confidence) {
  const parts = [];
  const readText = signals.titleText || signals.allText;
  if (readText) {
    parts.push(`read "${readText.replace(/\s+/g, " ").slice(0, 44)}"`);
  }
  if (best) {
    const exact = best.numericMatches?.length ? ` exact ${best.numericMatches.join("+")}` : "";
    parts.push(`${best.cardNo} ${best.matchedAlias || best.birdName} name ${best.nameScore}%${exact}`);
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
    drawCardSignalsForOcr();
    const result = await tesseractWorker.recognize(ocrCanvas);
    const signals = extractOcrSignals(result);
    const { candidates } = rankOcrCandidates(signals);
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

    elements.matchName.textContent = confidence.ok || matched ? displayNameForCard(best) : "Scanning";
    elements.matchScore.textContent = best ? `${best.score}% / gap ${confidence.gap}` : "-";
    elements.matchMeta.textContent = formatMeta(best, second, signals, audioMessage, confidence);
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
    playAudioForCard(pendingAudioCard, true);
  }
}

function initAbilityToggle() {
  if (!elements.abilityToggle) {
    return;
  }
  elements.abilityToggle.checked = localStorage.getItem(ABILITY_TOGGLE_STORAGE_KEY) === "true";
  elements.abilityToggle.addEventListener("change", () => {
    localStorage.setItem(ABILITY_TOGGLE_STORAGE_KEY, String(elements.abilityToggle.checked));
    stopAudioPlayback();
    activeAudioCardId = "";
    if (pendingAudioCard) {
      playAudioForCard(pendingAudioCard, true);
    }
  });
}

async function boot() {
  try {
    initAbilityToggle();
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
    stopAudioPlayback();
  }
});

boot();
