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
  captureIdentify: document.querySelector("#captureIdentify"),
  photoInput: document.querySelector("#photoInput"),
  sampleIdentify: document.querySelector("#sampleIdentify"),
  artPreview: document.querySelector("#artPreview"),
  sampleImage: document.querySelector("#sampleImage"),
  matchName: document.querySelector("#matchName"),
  matchScore: document.querySelector("#matchScore"),
  matchMeta: document.querySelector("#matchMeta"),
};

let stream;
let fingerprintDb;

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

function drawSampleArtPreview() {
  drawPreviewFromSource(
    elements.sampleImage,
    ART_REGION.x,
    ART_REGION.y,
    ART_REGION.width,
    ART_REGION.height,
  );
}

function drawUploadedPhotoPreview(image) {
  const sourceAspect = image.naturalWidth / image.naturalHeight;
  const targetAspect = ART_REGION.width / ART_REGION.height;
  let sx = 0;
  let sy = 0;
  let sw = image.naturalWidth;
  let sh = image.naturalHeight;

  if (sourceAspect > targetAspect) {
    sw = image.naturalHeight * targetAspect;
    sx = (image.naturalWidth - sw) / 2;
  } else {
    sh = image.naturalWidth / targetAspect;
    sy = (image.naturalHeight - sh) / 2;
  }

  drawPreviewFromSource(image, sx, sy, sw, sh);
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

async function identify(drawSource) {
  try {
    if (!fingerprintDb) {
      await loadFingerprintDb();
    }
    elements.captureIdentify.disabled = true;
    drawSource();
    const hash = computeDHash();
    const [best, second] = rankByFingerprint(hash);
    const matched = best && best.score >= MATCH_THRESHOLD;

    elements.matchName.textContent = matched ? best.displayName : "확인 필요";
    elements.matchScore.textContent = best ? `${best.score}점 / 거리 ${best.distance}` : "-";
    elements.matchMeta.textContent = best
      ? `${best.id}${second ? ` · 다음 후보 ${second.id} (${second.score}점)` : ""}`
      : "-";
    setStatus(matched ? "Matched" : "Check", matched ? "ready" : "error");
  } catch (error) {
    elements.matchName.textContent = "오류";
    elements.matchScore.textContent = "-";
    elements.matchMeta.textContent = error.message;
    setStatus("Error", "error");
  } finally {
    elements.captureIdentify.disabled = !stream;
  }
}

async function identifyPhoto(file) {
  if (!file) {
    return;
  }

  const image = new Image();
  const objectUrl = URL.createObjectURL(file);
  try {
    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = reject;
      image.src = objectUrl;
    });
    await identify(() => drawUploadedPhotoPreview(image));
  } finally {
    URL.revokeObjectURL(objectUrl);
    elements.photoInput.value = "";
  }
}

async function startCamera() {
  try {
    if (!window.isSecureContext) {
      throw new Error("HTTPS에서만 카메라를 사용할 수 있습니다.");
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("Camera API is not supported.");
    }

    setStatus("Permission", "ready");
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
    elements.captureIdentify.disabled = false;
    setStatus("Camera ready", "ready");
  } catch (error) {
    elements.matchMeta.textContent = error.message;
    setStatus("Camera error", "error");
  }
}

elements.startCamera.addEventListener("click", startCamera);
elements.captureIdentify.addEventListener("click", () => identify(drawVideoArtPreview));
elements.photoInput.addEventListener("change", (event) => identifyPhoto(event.target.files?.[0]));
elements.sampleIdentify.addEventListener("click", () => identify(drawSampleArtPreview));
elements.sampleImage.addEventListener("load", drawSampleArtPreview);

loadFingerprintDb().catch((error) => {
  elements.matchMeta.textContent = error.message;
  setStatus("Data error", "error");
});
