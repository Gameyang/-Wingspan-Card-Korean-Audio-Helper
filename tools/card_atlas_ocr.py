from __future__ import annotations

import argparse
import csv
import re
import shutil
import subprocess
import sys
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
DEFAULT_OUTPUT_DIR = Path("src/TestImages")
DEFAULT_SAMPLE_PATH = DEFAULT_OUTPUT_DIR / "new_card_sample.jpg"
DEFAULT_CROPS_DIR = DEFAULT_OUTPUT_DIR / "cards"
DEFAULT_REVIEW_CSV = DEFAULT_OUTPUT_DIR / "atlas_ocr_review.csv"

# Latin/scientific name line inside a single 630x970 card cell.
NAME_REGION = (105, 45, 615, 105)

REVIEW_FIELDS = [
    "atlas_file",
    "row",
    "col",
    "card_crop_path",
    "ocr_text",
    "ocr_confidence",
    "expected_name_latin",
    "display_name_ko",
]

REPORT_FIELDS = [
    "atlas_file",
    "row",
    "col",
    "ocr_text",
    "expected_name_latin",
    "matched_name_latin",
    "matched_score",
    "top_candidates",
    "top1_correct",
    "top3_correct",
]


@dataclass(frozen=True)
class CardCell:
    atlas_file: Path
    atlas_index: int
    row: int
    col: int

    @property
    def crop_name(self) -> str:
        return f"atlas{self.atlas_index + 1:02d}_r{self.row + 1:02d}_c{self.col + 1:02d}.jpg"


def find_atlas_files(images_dir: Path) -> list[Path]:
    if not images_dir.exists():
        raise FileNotFoundError(f"Images directory does not exist: {images_dir}")

    suffixes = {".jpg", ".jpeg", ".png"}
    files = [
        path
        for path in images_dir.iterdir()
        if path.is_file() and path.suffix.lower() in suffixes
    ]
    return sorted(files, key=lambda item: item.name.lower())


def validate_atlas_file(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        size = image.size

    if size != EXPECTED_ATLAS_SIZE:
        raise ValueError(
            f"Unexpected atlas size for {path}: {size}; expected {EXPECTED_ATLAS_SIZE}"
        )

    return size


def iter_cells(atlas_files: Iterable[Path]) -> Iterable[CardCell]:
    for atlas_index, atlas_file in enumerate(atlas_files):
        for row in range(GRID_ROWS):
            for col in range(GRID_COLUMNS):
                yield CardCell(atlas_file=atlas_file, atlas_index=atlas_index, row=row, col=col)


def card_bbox(row: int, col: int) -> tuple[int, int, int, int]:
    if row < 0 or row >= GRID_ROWS:
        raise ValueError(f"row must be between 0 and {GRID_ROWS - 1}: {row}")
    if col < 0 or col >= GRID_COLUMNS:
        raise ValueError(f"col must be between 0 and {GRID_COLUMNS - 1}: {col}")

    left = col * CARD_SIZE[0]
    top = row * CARD_SIZE[1]
    return left, top, left + CARD_SIZE[0], top + CARD_SIZE[1]


def crop_card(atlas_path: Path, row: int, col: int) -> Image.Image:
    validate_atlas_file(atlas_path)
    with Image.open(atlas_path) as image:
        return image.crop(card_bbox(row, col)).copy()


def crop_name_region(card_image: Image.Image) -> Image.Image:
    return card_image.crop(NAME_REGION)


def preprocess_name_region(name_image: Image.Image) -> Image.Image:
    gray = ImageOps.grayscale(name_image)
    gray = ImageOps.autocontrast(gray)
    gray = ImageEnhance.Contrast(gray).enhance(2.0)
    gray = gray.resize((gray.width * 4, gray.height * 4), Image.Resampling.LANCZOS)

    try:
        import cv2
        import numpy as np
    except ImportError:
        return gray

    array = np.array(gray)
    array = cv2.GaussianBlur(array, (3, 3), 0)
    _, array = cv2.threshold(array, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return Image.fromarray(array)


def extract_sample_card(
    images_dir: Path = DEFAULT_IMAGES_DIR,
    output_path: Path = DEFAULT_SAMPLE_PATH,
    atlas_index: int = 0,
    row: int = 0,
    col: int = 0,
) -> Path:
    atlas_files = find_atlas_files(images_dir)
    if not atlas_files:
        raise FileNotFoundError(f"No atlas images found in {images_dir}")
    if atlas_index < 0 or atlas_index >= len(atlas_files):
        raise ValueError(f"atlas_index must be between 0 and {len(atlas_files) - 1}")

    card = crop_card(atlas_files[atlas_index], row=row, col=col)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    card.save(output_path, quality=95)
    return output_path


def ensure_tesseract_ready(language: str = "eng") -> None:
    executable = shutil.which("tesseract")
    if not executable:
        raise RuntimeError(
            "Tesseract executable was not found. Install Tesseract OCR and add it "
            "to PATH, then install English language data."
        )

    languages = {part.strip().lower() for part in language.split("+") if part.strip()}
    result = subprocess.run(
        [executable, "--list-langs"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    available = {
        line.strip().lower()
        for line in (result.stdout + "\n" + result.stderr).splitlines()
        if line.strip() and not line.lower().startswith("list of available languages")
    }
    missing = sorted(languages - available)
    if result.returncode != 0 or missing:
        raise RuntimeError(
            "Tesseract language data is not ready. Missing languages: "
            f"{', '.join(missing) if missing else language}. Install eng traineddata."
        )


def ensure_pytesseract_available():
    try:
        import pytesseract
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency: pytesseract. Install requirements with "
            "`python -m pip install -r requirements.txt`."
        ) from exc

    return pytesseract


def run_ocr(
    card_image: Image.Image,
    language: str = "eng",
    check_tesseract: bool = True,
) -> tuple[str, float]:
    if check_tesseract:
        ensure_tesseract_ready(language=language)
    pytesseract = ensure_pytesseract_available()

    image = preprocess_name_region(crop_name_region(card_image))
    data = pytesseract.image_to_data(
        image,
        lang=language,
        config="--oem 3 --psm 6",
        output_type=pytesseract.Output.DICT,
    )

    words: list[str] = []
    confidences: list[float] = []
    for text, confidence in zip(data.get("text", []), data.get("conf", []), strict=False):
        text = text.strip()
        if not text:
            continue
        words.append(text)
        try:
            parsed_confidence = float(confidence)
        except ValueError:
            continue
        if parsed_confidence >= 0:
            confidences.append(parsed_confidence)

    if not words:
        fallback_text = pytesseract.image_to_string(
            image,
            lang=language,
            config="--oem 3 --psm 6",
        )
        return normalize_spaces(fallback_text), 0.0

    average_confidence = (
        sum(confidences) / len(confidences) if confidences else 0.0
    )
    return normalize_spaces(" ".join(words)), average_confidence


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_for_match(value: str) -> str:
    value = normalize_spaces(value).casefold()
    return re.sub(r"[^0-9a-z]+", "", value)


def _score_with_difflib(query: str, candidate: str) -> float:
    from difflib import SequenceMatcher

    return SequenceMatcher(None, query, candidate).ratio() * 100.0


def score_candidate(query: str, candidate: str) -> float:
    query_norm = normalize_for_match(query)
    candidate_norm = normalize_for_match(candidate)
    if not query_norm or not candidate_norm:
        return 0.0
    if candidate_norm in query_norm or query_norm in candidate_norm:
        return 100.0

    try:
        from rapidfuzz import fuzz
    except ImportError:
        return _score_with_difflib(query_norm, candidate_norm)

    return float(fuzz.WRatio(query_norm, candidate_norm))


def rank_candidates(query: str, expected_names: Iterable[str], limit: int = 3) -> list[tuple[str, float]]:
    ranked = [
        (name, score_candidate(query, name))
        for name in expected_names
        if name and name.strip()
    ]
    ranked.sort(key=lambda item: (-item[1], item[0]))
    return ranked[:limit]


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_review_csv(
    images_dir: Path = DEFAULT_IMAGES_DIR,
    output_csv: Path = DEFAULT_REVIEW_CSV,
    crops_dir: Path = DEFAULT_CROPS_DIR,
    language: str = "eng",
    skip_ocr: bool = False,
    force: bool = False,
) -> tuple[int, Path]:
    if output_csv.exists() and not force:
        raise FileExistsError(f"Review CSV already exists. Use --force to overwrite: {output_csv}")

    atlas_files = find_atlas_files(images_dir)
    if not atlas_files:
        raise FileNotFoundError(f"No atlas images found in {images_dir}")

    if not skip_ocr:
        ensure_tesseract_ready(language=language)
        ensure_pytesseract_available()

    rows: list[dict[str, str]] = []
    crops_dir.mkdir(parents=True, exist_ok=True)

    for atlas_file in atlas_files:
        validate_atlas_file(atlas_file)

    for cell in iter_cells(atlas_files):
        crop_path = crops_dir / cell.crop_name
        card_image = crop_card(cell.atlas_file, cell.row, cell.col)
        card_image.save(crop_path, quality=95)

        ocr_text = ""
        ocr_confidence = ""
        if not skip_ocr:
            ocr_text, confidence = run_ocr(
                card_image,
                language=language,
                check_tesseract=False,
            )
            ocr_confidence = f"{confidence:.3f}"

        rows.append(
            {
                "atlas_file": cell.atlas_file.name,
                "row": str(cell.row),
                "col": str(cell.col),
                "card_crop_path": str(crop_path.as_posix()),
                "ocr_text": ocr_text,
                "ocr_confidence": ocr_confidence,
                "expected_name_latin": "",
                "display_name_ko": "",
            }
        )

    write_csv(output_csv, REVIEW_FIELDS, rows)
    return len(rows), output_csv


def read_review_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def expected_latin_name(row: dict[str, str]) -> str:
    return normalize_spaces(row.get("expected_name_latin", ""))


def validate_identification(
    csv_path: Path = DEFAULT_REVIEW_CSV,
    report_csv: Path | None = None,
) -> dict[str, float | int]:
    rows = read_review_rows(csv_path)
    expected_names = sorted(
        {
            expected_latin_name(row)
            for row in rows
            if expected_latin_name(row)
        }
    )
    if not expected_names:
        raise ValueError(
            f"No expected_name_latin values found in {csv_path}. Fill the review CSV first."
        )

    evaluated = 0
    top1_correct = 0
    top3_correct = 0
    report_rows: list[dict[str, str]] = []

    for row in rows:
        expected = expected_latin_name(row)
        if not expected:
            continue

        evaluated += 1
        ocr_text = normalize_spaces(row.get("ocr_text", ""))
        ranked = rank_candidates(ocr_text, expected_names, limit=3)
        matched_name = ranked[0][0] if ranked else ""
        matched_score = ranked[0][1] if ranked else 0.0
        top_names = [name for name, _score in ranked]
        row_top1 = bool(top_names and top_names[0] == expected)
        row_top3 = expected in top_names

        top1_correct += int(row_top1)
        top3_correct += int(row_top3)

        report_rows.append(
            {
                "atlas_file": row.get("atlas_file", ""),
                "row": row.get("row", ""),
                "col": row.get("col", ""),
                "ocr_text": ocr_text,
                "expected_name_latin": expected,
                "matched_name_latin": matched_name,
                "matched_score": f"{matched_score:.3f}",
                "top_candidates": " | ".join(top_names),
                "top1_correct": str(row_top1).lower(),
                "top3_correct": str(row_top3).lower(),
            }
        )

    if report_csv:
        write_csv(report_csv, REPORT_FIELDS, report_rows)

    return {
        "evaluated": evaluated,
        "top1_correct": top1_correct,
        "top3_correct": top3_correct,
        "top1_accuracy": top1_correct / evaluated if evaluated else 0.0,
        "top3_accuracy": top3_correct / evaluated if evaluated else 0.0,
    }


def print_accuracy(summary: dict[str, float | int]) -> None:
    print(f"Evaluated rows: {summary['evaluated']}")
    print(f"Top-1: {summary['top1_correct']} ({summary['top1_accuracy']:.2%})")
    print(f"Top-3: {summary['top3_correct']} ({summary['top3_accuracy']:.2%})")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Crop Wingspan card atlases, OCR Latin names, and validate matches."
    )
    parser.add_argument("--images-dir", type=Path, default=DEFAULT_IMAGES_DIR)

    subparsers = parser.add_subparsers(dest="command", required=True)

    sample_parser = subparsers.add_parser("extract-sample")
    sample_parser.add_argument("--output", type=Path, default=DEFAULT_SAMPLE_PATH)
    sample_parser.add_argument("--atlas-index", type=int, default=0)
    sample_parser.add_argument("--row", type=int, default=0)
    sample_parser.add_argument("--col", type=int, default=0)

    review_parser = subparsers.add_parser("build-review-csv")
    review_parser.add_argument("--output-csv", type=Path, default=DEFAULT_REVIEW_CSV)
    review_parser.add_argument("--crops-dir", type=Path, default=DEFAULT_CROPS_DIR)
    review_parser.add_argument("--language", default="eng")
    review_parser.add_argument("--skip-ocr", action="store_true")
    review_parser.add_argument("--force", action="store_true")

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--csv", type=Path, default=DEFAULT_REVIEW_CSV)
    validate_parser.add_argument("--report-csv", type=Path)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "extract-sample":
            output = extract_sample_card(
                images_dir=args.images_dir,
                output_path=args.output,
                atlas_index=args.atlas_index,
                row=args.row,
                col=args.col,
            )
            print(f"Saved sample card: {output}")
            return 0

        if args.command == "build-review-csv":
            count, output_csv = build_review_csv(
                images_dir=args.images_dir,
                output_csv=args.output_csv,
                crops_dir=args.crops_dir,
                language=args.language,
                skip_ocr=args.skip_ocr,
                force=args.force,
            )
            print(f"Wrote {count} review rows: {output_csv}")
            return 0

        if args.command == "validate":
            summary = validate_identification(
                csv_path=args.csv,
                report_csv=args.report_csv,
            )
            print_accuracy(summary)
            return 0

    except (FileNotFoundError, FileExistsError, RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
