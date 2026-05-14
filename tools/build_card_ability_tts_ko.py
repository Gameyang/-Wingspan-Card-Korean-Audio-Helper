from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageEnhance, ImageOps


EXPECTED_ATLAS_SIZE = (6300, 6790)
GRID_COLUMNS = 10
GRID_ROWS = 7
CARD_SIZE = (
    EXPECTED_ATLAS_SIZE[0] // GRID_COLUMNS,
    EXPECTED_ATLAS_SIZE[1] // GRID_ROWS,
)

DEFAULT_IMAGES_DIR = Path("src/AtlasImage")
DEFAULT_CARD_ALIASES = Path("site/data/card_ocr_aliases.json")
DEFAULT_INTRO_TTS = Path("src/Data/card_intro_tts_ko.csv")
DEFAULT_OCR_OUTPUT = Path("src/Data/card_ability_ocr.csv")
DEFAULT_TTS_OUTPUT = Path("src/Data/card_ability_tts_ko.csv")
DEFAULT_VOICE_TAG = "Jean"
DEFAULT_SEQUENCE_START_CARD_NO = 53
DEFAULT_WINDOWS_OCR_SCRIPT = Path("tools/windows_ocr_image.ps1")

# Korean Wingspan cards place the power strip in the lower third of a 630x970 cell.
ABILITY_REGION = {
    "x": 20,
    "y": 700,
    "width": 590,
    "height": 130,
}

OCR_FIELDS = [
    "card_no",
    "card_id",
    "bird_name",
    "bird_name_ko",
    "atlas",
    "row",
    "col",
    "ability_ocr_text",
    "ability_text_ko",
    "ability_tts_text",
    "ability_id",
    "ocr_engine",
    "ocr_confidence",
    "review_status",
]

TTS_FIELDS = [
    "ability_id",
    "ability_text_ko",
    "tts_text",
    "voice_tag",
    "review_status",
    "source_card_nos",
    "source_card_ids",
    "source_bird_names",
    "source_ocr_texts",
]


@dataclass(frozen=True)
class CardSlot:
    card_id: str
    card_no: str
    bird_name: str
    bird_name_ko: str
    atlas: int
    row: int
    col: int


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_card_range(value: str) -> list[str]:
    match = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", value or "")
    if not match:
        raise argparse.ArgumentTypeError("Expected range like 53-57")
    start = int(match.group(1))
    end = int(match.group(2))
    if end < start:
        raise argparse.ArgumentTypeError("Range end must be greater than or equal to start")
    return [str(card_no) for card_no in range(start, end + 1)]


def selected_card_numbers(card_no: list[str], card_range: list[str]) -> set[str]:
    numbers = {str(value).strip() for value in card_no if str(value).strip()}
    for value in card_range:
        numbers.update(parse_card_range(value))
    return numbers


def ability_id_for_text(value: str) -> str:
    normalized = normalize_for_dedupe(value)
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
    return f"ability_{digest}"


def normalize_for_dedupe(value: str) -> str:
    text = normalize_spaces(value).casefold()
    text = re.sub(r"[^\w가-힣]+", "", text)
    return text


def clean_ability_text(value: str) -> str:
    text = normalize_spaces(value)
    text = re.sub(r"\[[^\]]+\]", " ", text)
    text = re.sub(r"[\[\]{}<>|*_#~`^]", " ", text)
    text = re.sub(r"[A-Za-z]+", " ", text)
    text = text.replace("•", " ")
    text = text.replace("卜", " ")
    text = text.replace("鬱", " ")
    text = normalize_spaces(text)
    return text.strip(" ,:;·")


def tts_text_for_ability(ability_text_ko: str) -> str:
    text = clean_ability_text(ability_text_ko)
    if not text:
        return ""
    return text


def find_atlas_files(images_dir: Path) -> list[Path]:
    if not images_dir.exists():
        raise FileNotFoundError(f"Images directory does not exist: {images_dir}")
    return sorted(
        [
            path
            for path in images_dir.iterdir()
            if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png"}
        ],
        key=lambda item: item.name.lower(),
    )


def card_bbox(row: int, col: int) -> tuple[int, int, int, int]:
    left = col * CARD_SIZE[0]
    top = row * CARD_SIZE[1]
    return left, top, left + CARD_SIZE[0], top + CARD_SIZE[1]


def crop_ability(card_image: Image.Image) -> Image.Image:
    x = ABILITY_REGION["x"]
    y = ABILITY_REGION["y"]
    return card_image.crop((x, y, x + ABILITY_REGION["width"], y + ABILITY_REGION["height"]))


def preprocess_ability_region(image: Image.Image) -> Image.Image:
    gray = ImageOps.grayscale(image)
    gray = ImageOps.autocontrast(gray)
    gray = ImageEnhance.Contrast(gray).enhance(2.2)
    return gray.resize((gray.width * 4, gray.height * 4), Image.Resampling.LANCZOS)


def intro_names_by_card_no(path: Path) -> dict[str, str]:
    names: dict[str, str] = {}
    for row in read_csv(path):
        card_no = normalize_spaces(row.get("card_no", ""))
        bird_name_ko = normalize_spaces(row.get("bird_name_ko", ""))
        if card_no and bird_name_ko:
            names[card_no] = bird_name_ko
    return names


def load_card_slots(
    *,
    card_aliases_path: Path,
    intro_tts_path: Path,
    sequence_start_card_no: int,
) -> list[CardSlot]:
    aliases = json.loads(card_aliases_path.read_text(encoding="utf-8"))
    korean_names = intro_names_by_card_no(intro_tts_path)
    slots: list[CardSlot] = []
    for card in aliases.get("cards", []):
        card_no = normalize_spaces(card.get("cardNo", ""))
        card_id = normalize_spaces(card.get("id", ""))
        if not card_no or not card_id:
            continue
        sequence_index = int(card_no) - sequence_start_card_no
        atlas = sequence_index // (GRID_ROWS * GRID_COLUMNS) + 1
        remainder = sequence_index % (GRID_ROWS * GRID_COLUMNS)
        row = remainder // GRID_COLUMNS + 1
        col = remainder % GRID_COLUMNS + 1
        slots.append(
            CardSlot(
                card_id=card_id,
                card_no=card_no,
                bird_name=normalize_spaces(card.get("birdName", "")),
                bird_name_ko=korean_names.get(card_no, normalize_spaces(card.get("birdName", ""))),
                atlas=atlas,
                row=row,
                col=col,
            )
        )
    return slots


def windows_powershell_path() -> str:
    candidates = [
        shutil.which("powershell.exe"),
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise RuntimeError("Windows PowerShell was not found for Windows OCR fallback.")


def run_windows_ocr(image_path: Path, *, language: str, script_path: Path) -> tuple[str, float]:
    command = [
        windows_powershell_path(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
        "-ImagePath",
        str(image_path),
        "-Language",
        language,
    ]
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    payload = json.loads(completed.stdout)
    return normalize_spaces(payload.get("text", "")), 0.0


def run_tesseract_ocr(image: Image.Image, *, language: str) -> tuple[str, float]:
    if not shutil.which("tesseract"):
        raise RuntimeError("tesseract executable is not available.")
    try:
        import pytesseract
    except ImportError as error:
        raise RuntimeError("pytesseract is not installed.") from error

    data = pytesseract.image_to_data(
        image,
        lang=language,
        config="--oem 3 --psm 6",
        output_type=pytesseract.Output.DICT,
    )
    words: list[str] = []
    confidences: list[float] = []
    for text, confidence in zip(data.get("text", []), data.get("conf", []), strict=False):
        text = normalize_spaces(text)
        if not text:
            continue
        words.append(text)
        try:
            parsed = float(confidence)
        except ValueError:
            continue
        if parsed >= 0:
            confidences.append(parsed)
    if not words:
        return normalize_spaces(pytesseract.image_to_string(image, lang=language, config="--oem 3 --psm 6")), 0.0
    confidence = sum(confidences) / len(confidences) if confidences else 0.0
    return normalize_spaces(" ".join(words)), confidence


def ocr_engine_name(requested: str) -> str:
    if requested != "auto":
        return requested
    if shutil.which("tesseract"):
        return "tesseract"
    return "windows"


def build_ocr_rows(
    *,
    images_dir: Path,
    card_aliases_path: Path,
    intro_tts_path: Path,
    card_numbers: set[str],
    sequence_start_card_no: int,
    engine: str,
    language: str,
    crops_dir: Path | None,
    windows_ocr_script: Path,
) -> list[dict[str, str]]:
    atlas_files = find_atlas_files(images_dir)
    for atlas_path in atlas_files:
        with Image.open(atlas_path) as image:
            if image.size != EXPECTED_ATLAS_SIZE:
                raise ValueError(f"Unexpected atlas size for {atlas_path}: {image.size}")

    slots = load_card_slots(
        card_aliases_path=card_aliases_path,
        intro_tts_path=intro_tts_path,
        sequence_start_card_no=sequence_start_card_no,
    )
    selected = [slot for slot in slots if not card_numbers or slot.card_no in card_numbers]
    actual_engine = ocr_engine_name(engine)
    rows: list[dict[str, str]] = []

    if crops_dir:
        crops_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        for slot in selected:
            atlas_path = atlas_files[slot.atlas - 1]
            with Image.open(atlas_path) as atlas:
                card = atlas.crop(card_bbox(slot.row - 1, slot.col - 1))
            ability_image = preprocess_ability_region(crop_ability(card))
            crop_path = (crops_dir or temp_path) / f"{slot.card_no}_{slot.card_id}_ability.png"
            ability_image.save(crop_path)

            if actual_engine == "tesseract":
                ocr_text, confidence = run_tesseract_ocr(ability_image, language=language)
            elif actual_engine == "windows":
                ocr_text, confidence = run_windows_ocr(crop_path, language=language, script_path=windows_ocr_script)
            elif actual_engine == "none":
                ocr_text, confidence = "", 0.0
            else:
                raise ValueError(f"Unsupported OCR engine: {engine}")

            ability_text_ko = clean_ability_text(ocr_text)
            tts_text = tts_text_for_ability(ability_text_ko)
            ability_id = ability_id_for_text(tts_text) if tts_text else ""
            rows.append(
                {
                    "card_no": slot.card_no,
                    "card_id": slot.card_id,
                    "bird_name": slot.bird_name,
                    "bird_name_ko": slot.bird_name_ko,
                    "atlas": str(slot.atlas),
                    "row": str(slot.row),
                    "col": str(slot.col),
                    "ability_ocr_text": ocr_text,
                    "ability_text_ko": ability_text_ko,
                    "ability_tts_text": tts_text,
                    "ability_id": ability_id,
                    "ocr_engine": actual_engine,
                    "ocr_confidence": f"{confidence:.3f}",
                    "review_status": "ocr_draft",
                }
            )
    return rows


def build_tts_rows(ocr_rows: list[dict[str, str]], *, default_voice_tag: str) -> list[dict[str, str]]:
    grouped: dict[str, dict[str, object]] = {}
    for row in ocr_rows:
        ability_text_ko = normalize_spaces(row.get("ability_text_ko", "")) or clean_ability_text(row.get("ability_ocr_text", ""))
        tts_text = tts_text_for_ability(ability_text_ko)
        if not tts_text:
            continue
        ability_id = ability_id_for_text(tts_text)
        current = grouped.setdefault(
            ability_id,
            {
                "ability_text_ko": ability_text_ko,
                "tts_text": tts_text,
                "review_status": normalize_spaces(row.get("review_status", "")) or "draft",
                "card_nos": [],
                "card_ids": [],
                "bird_names": [],
                "ocr_texts": [],
            },
        )
        current["card_nos"].append(normalize_spaces(row.get("card_no", "")))
        current["card_ids"].append(normalize_spaces(row.get("card_id", "")))
        current["bird_names"].append(normalize_spaces(row.get("bird_name_ko", "")) or normalize_spaces(row.get("bird_name", "")))
        current["ocr_texts"].append(normalize_spaces(row.get("ability_ocr_text", "")))

    rows: list[dict[str, str]] = []
    for ability_id, item in sorted(grouped.items(), key=lambda pair: pair[0]):
        rows.append(
            {
                "ability_id": ability_id,
                "ability_text_ko": str(item["ability_text_ko"]),
                "tts_text": str(item["tts_text"]),
                "voice_tag": default_voice_tag,
                "review_status": str(item["review_status"]),
                "source_card_nos": "|".join(unique_nonempty(item["card_nos"])),
                "source_card_ids": "|".join(unique_nonempty(item["card_ids"])),
                "source_bird_names": "|".join(unique_nonempty(item["bird_names"])),
                "source_ocr_texts": " || ".join(unique_nonempty(item["ocr_texts"])),
            }
        )
    return rows


def unique_nonempty(values: object) -> list[str]:
    result: list[str] = []
    for value in values if isinstance(values, list) else []:
        text = normalize_spaces(value)
        if text and text not in result:
            result.append(text)
    return result


def preserved_ability_rows_by_card_no(path: Path) -> dict[str, dict[str, str]]:
    preserved: dict[str, dict[str, str]] = {}
    for row in read_csv(path):
        card_no = normalize_spaces(row.get("card_no", ""))
        review_status = normalize_spaces(row.get("review_status", "")).casefold()
        ability_text = normalize_spaces(row.get("ability_text_ko", ""))
        if card_no and ability_text and review_status and review_status != "ocr_draft":
            preserved[card_no] = row
    return preserved


def apply_preserved_ability_rows(
    ocr_rows: list[dict[str, str]],
    preserved_rows: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    if not preserved_rows:
        return ocr_rows

    ability_fields = [
        "ability_ocr_text",
        "ability_text_ko",
        "ability_tts_text",
        "ability_id",
        "ocr_engine",
        "ocr_confidence",
        "review_status",
    ]
    merged: list[dict[str, str]] = []
    for row in ocr_rows:
        preserved = preserved_rows.get(normalize_spaces(row.get("card_no", "")))
        if not preserved:
            merged.append(row)
            continue
        updated = dict(row)
        for field in ability_fields:
            updated[field] = preserved.get(field, "")
        merged.append(updated)
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description="OCR Korean Wingspan card powers and build a deduplicated ability TTS list.")
    parser.add_argument("--images-dir", type=Path, default=DEFAULT_IMAGES_DIR)
    parser.add_argument("--card-aliases", type=Path, default=DEFAULT_CARD_ALIASES)
    parser.add_argument("--intro-tts", type=Path, default=DEFAULT_INTRO_TTS)
    parser.add_argument("--ocr-output", type=Path, default=DEFAULT_OCR_OUTPUT)
    parser.add_argument("--tts-output", type=Path, default=DEFAULT_TTS_OUTPUT)
    parser.add_argument("--sequence-start-card-no", type=int, default=DEFAULT_SEQUENCE_START_CARD_NO)
    parser.add_argument("--voice-tag", default=DEFAULT_VOICE_TAG)
    parser.add_argument("--card-no", action="append", default=[])
    parser.add_argument("--card-range", action="append", default=[])
    parser.add_argument("--ocr-engine", choices=["auto", "tesseract", "windows", "none"], default="auto")
    parser.add_argument("--ocr-language", default="kor")
    parser.add_argument("--windows-ocr-language", default="ko")
    parser.add_argument("--windows-ocr-script", type=Path, default=DEFAULT_WINDOWS_OCR_SCRIPT)
    parser.add_argument("--crops-dir", type=Path)
    parser.add_argument("--skip-ocr", action="store_true", help="Read existing OCR CSV and rebuild only the deduplicated TTS table.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    card_numbers = selected_card_numbers(args.card_no, args.card_range)
    if args.skip_ocr:
        ocr_rows = read_csv(args.ocr_output)
    else:
        preserved_rows = preserved_ability_rows_by_card_no(args.ocr_output)
        language = args.windows_ocr_language if ocr_engine_name(args.ocr_engine) == "windows" else args.ocr_language
        ocr_rows = build_ocr_rows(
            images_dir=args.images_dir,
            card_aliases_path=args.card_aliases,
            intro_tts_path=args.intro_tts,
            card_numbers=card_numbers,
            sequence_start_card_no=args.sequence_start_card_no,
            engine=args.ocr_engine,
            language=language,
            crops_dir=args.crops_dir,
            windows_ocr_script=args.windows_ocr_script,
        )
        ocr_rows = apply_preserved_ability_rows(ocr_rows, preserved_rows)

    if card_numbers and args.skip_ocr:
        ocr_rows = [row for row in ocr_rows if normalize_spaces(row.get("card_no", "")) in card_numbers]

    tts_rows = build_tts_rows(ocr_rows, default_voice_tag=args.voice_tag)

    if args.dry_run:
        print(f"OCR rows: {len(ocr_rows)}")
        print(f"Unique ability TTS rows: {len(tts_rows)}")
        for row in tts_rows[:10]:
            print(f"{row['ability_id']}: {row['tts_text']}")
        return 0

    if not args.skip_ocr:
        write_csv(args.ocr_output, OCR_FIELDS, ocr_rows)
    write_csv(args.tts_output, TTS_FIELDS, tts_rows)
    if args.skip_ocr:
        print(f"Read OCR rows: {args.ocr_output} ({len(ocr_rows)})")
    else:
        print(f"Wrote OCR rows: {args.ocr_output} ({len(ocr_rows)})")
    print(f"Wrote ability TTS rows: {args.tts_output} ({len(tts_rows)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
