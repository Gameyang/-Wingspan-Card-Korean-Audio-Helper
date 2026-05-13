const CARD_WIDTH = 630;
const CARD_HEIGHT = 970;
const NAME_REGION = {
  x: 105,
  y: 45,
  width: 510,
  height: 60,
};
const OCR_SCALE = 4;
const TARGET_CARDS = [
  {
    nameKo: "알락귀뿔논병아리",
    matchName: "Podilymbus podiceps",
  },
];

const elements = {
  status: document.querySelector("#status"),
  video: document.querySelector("#camera"),
  cameraBox: document.querySelector("#cameraBox"),
  cardGuide: document.querySelector("#cardGuide"),
  startCamera: document.querySelector("#startCamera"),
  captureIdentify: document.querySelector("#captureIdentify"),
  sampleIdentify: document.querySelector("#sampleIdentify"),
  cardCanvas: document.querySelector("#cardCanvas"),
  namePreview: document.querySelector("#namePreview"),
  sampleImage: document.querySelector("#sampleImage"),
  matchName: document.querySelector("#matchName"),
  matchScore: document.querySelector("#matchScore"),
  ocrText: document.querySelector("#ocrText"),
};

let stream;
let workerPromise;

function setStatus(message, type = "") {
  elements.status.textContent = message;
  elements.status.className = `status ${type}`.trim();
}

function normalizeLatin(value) {
  return value.toLowerCase().replace(/[^a-z]/g, "");
}

function levenshtein(a, b) {
  const previous = Array.from({ length: b.length + 1 }, (_, index) => index);
  const current = Array.from({ length: b.length + 1 }, () => 0);

  for (let i = 1; i <= a.length; i += 1) {
    current[0] = i;
    for (let j = 1; j <= b.length; j += 1) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      current[j] = Math.min(
        previous[j] + 1,
        current[j - 1] + 1,
        previous[j - 1] + cost,
      );
    }
    previous.splice(0, previous.length, ...current);
  }

  return previous[b.length];
}

function scoreCandidate(ocrText, candidate) {
  const query = normalizeLatin(ocrText);
  const target = normalizeLatin(candidate.matchName);

  if (!query) {
    return 0;
  }
  if (query.includes(target) || target.includes(query)) {
    return 100;
  }

  const distance = levenshtein(query, target);
  return Math.max(0, 100 * (1 - distance / Math.max(query.length, target.length)));
}

function rankCandidates(ocrText) {
  return TARGET_CARDS.map((card) => ({
    ...card,
    score: scoreCandidate(ocrText, card),
  })).sort((a, b) => b.score - a.score);
}

function getVideoSourceRect() {
  const frameRect = elements.cameraBox.getBoundingClientRect();
  const guideRect = elements.cardGuide.getBoundingClientRect();
  const videoWidth = elements.video.videoWidth;
  const videoHeight = elements.video.videoHeight;
  const scale = Math.max(frameRect.width / videoWidth, frameRect.height / videoHeight);
  const renderedWidth = videoWidth * scale;
  const renderedHeight = videoHeight * scale;
  const offsetX = (frameRect.width - renderedWidth) / 2;
  const offsetY = (frameRect.height - renderedHeight) / 2;
  const guideX = guideRect.left - frameRect.left;
  const guideY = guideRect.top - frameRect.top;

  return {
    sx: Math.max(0, (guideX - offsetX) / scale),
    sy: Math.max(0, (guideY - offsetY) / scale),
    sw: Math.min(videoWidth, guideRect.width / scale),
    sh: Math.min(videoHeight, guideRect.height / scale),
  };
}

function drawVideoCard() {
  if (!elements.video.videoWidth || !elements.video.videoHeight) {
    throw new Error("카메라 영상이 아직 준비되지 않았습니다.");
  }

  const { sx, sy, sw, sh } = getVideoSourceRect();
  const context = elements.cardCanvas.getContext("2d", { willReadFrequently: true });
  context.drawImage(
    elements.video,
    sx,
    sy,
    sw,
    sh,
    0,
    0,
    CARD_WIDTH,
    CARD_HEIGHT,
  );
}

function drawSampleCard() {
  const context = elements.cardCanvas.getContext("2d", { willReadFrequently: true });
  context.drawImage(elements.sampleImage, 0, 0, CARD_WIDTH, CARD_HEIGHT);
}

function drawNamePreview() {
  const context = elements.namePreview.getContext("2d", { willReadFrequently: true });
  const targetWidth = NAME_REGION.width * OCR_SCALE;
  const targetHeight = NAME_REGION.height * OCR_SCALE;
  elements.namePreview.width = targetWidth;
  elements.namePreview.height = targetHeight;

  context.imageSmoothingEnabled = true;
  context.drawImage(
    elements.cardCanvas,
    NAME_REGION.x,
    NAME_REGION.y,
    NAME_REGION.width,
    NAME_REGION.height,
    0,
    0,
    targetWidth,
    targetHeight,
  );

  const image = context.getImageData(0, 0, targetWidth, targetHeight);
  for (let index = 0; index < image.data.length; index += 4) {
    const gray =
      image.data[index] * 0.299 +
      image.data[index + 1] * 0.587 +
      image.data[index + 2] * 0.114;
    const contrasted = gray < 178 ? 0 : 255;
    image.data[index] = contrasted;
    image.data[index + 1] = contrasted;
    image.data[index + 2] = contrasted;
  }
  context.putImageData(image, 0, 0);
}

async function getWorker() {
  if (!window.Tesseract) {
    throw new Error("OCR 라이브러리를 불러오지 못했습니다.");
  }

  if (!workerPromise) {
    workerPromise = window.Tesseract.createWorker(["eng"], 1, {
      logger: (message) => {
        if (message.status === "recognizing text") {
          setStatus(`${Math.round(message.progress * 100)}%`, "ready");
        }
      },
    }).then(async (worker) => {
      const psm = window.Tesseract.PSM?.SINGLE_BLOCK ?? "6";
      await worker.setParameters({
        tessedit_pageseg_mode: psm,
        tessedit_char_whitelist: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz .-",
        preserve_interword_spaces: "1",
      });
      return worker;
    });
  }

  return workerPromise;
}

async function recognizeCurrentPreview() {
  setStatus("OCR 준비", "ready");
  const worker = await getWorker();
  setStatus("OCR 실행", "ready");
  const result = await worker.recognize(elements.namePreview);
  return result.data.text.replace(/\s+/g, " ").trim();
}

async function identify(drawSource) {
  try {
    elements.captureIdentify.disabled = true;
    drawSource();
    drawNamePreview();
    const text = await recognizeCurrentPreview();
    const [best] = rankCandidates(text);
    const matched = best && best.score >= 70;

    elements.ocrText.textContent = text || "인식된 텍스트 없음";
    elements.matchName.textContent = matched ? `${best.nameKo} (${best.matchName})` : "확인 필요";
    elements.matchScore.textContent = best ? `${Math.round(best.score)}점` : "-";
    setStatus(matched ? "식별 완료" : "확인 필요", matched ? "ready" : "error");
  } catch (error) {
    elements.ocrText.textContent = error.message;
    elements.matchName.textContent = "오류";
    elements.matchScore.textContent = "-";
    setStatus("오류", "error");
  } finally {
    elements.captureIdentify.disabled = !stream;
  }
}

async function startCamera() {
  try {
    if (!window.isSecureContext) {
      throw new Error("HTTPS에서만 카메라를 사용할 수 있습니다.");
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("이 브라우저는 카메라 API를 지원하지 않습니다.");
    }

    setStatus("권한 요청", "ready");
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
    setStatus("카메라 준비", "ready");
  } catch (error) {
    elements.ocrText.textContent = error.message;
    setStatus("카메라 오류", "error");
  }
}

elements.startCamera.addEventListener("click", startCamera);
elements.captureIdentify.addEventListener("click", () => identify(drawVideoCard));
elements.sampleIdentify.addEventListener("click", () => identify(drawSampleCard));
elements.sampleImage.addEventListener("load", drawSampleCard);
