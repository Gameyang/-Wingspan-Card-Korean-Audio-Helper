from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageOps


EXPECTED_ATLAS_SIZE = (6300, 6790)
GRID_COLUMNS = 10
GRID_ROWS = 7
CARD_SIZE = (
    EXPECTED_ATLAS_SIZE[0] // GRID_COLUMNS,
    EXPECTED_ATLAS_SIZE[1] // GRID_ROWS,
)

ART_REGION = {
    "x": 45,
    "y": 145,
    "width": 565,
    "height": 515,
}
HASH_WIDTH = 17
HASH_HEIGHT = 16

DEFAULT_IMAGES_DIR = Path("src/Images")
DEFAULT_OUTPUT = Path("site/data/card_fingerprints.json")


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


def validate_atlas(path: Path) -> None:
    with Image.open(path) as image:
        if image.size != EXPECTED_ATLAS_SIZE:
            raise ValueError(f"Unexpected atlas size for {path}: {image.size}")


def card_bbox(row: int, col: int) -> tuple[int, int, int, int]:
    left = col * CARD_SIZE[0]
    top = row * CARD_SIZE[1]
    return left, top, left + CARD_SIZE[0], top + CARD_SIZE[1]


def crop_art(card_image: Image.Image) -> Image.Image:
    x = ART_REGION["x"]
    y = ART_REGION["y"]
    return card_image.crop((x, y, x + ART_REGION["width"], y + ART_REGION["height"]))


def dhash_hex(image: Image.Image) -> str:
    gray = ImageOps.grayscale(image)
    gray = ImageOps.autocontrast(gray)
    resized = gray.resize((HASH_WIDTH, HASH_HEIGHT), Image.Resampling.LANCZOS)
    pixels = list(resized.tobytes())

    bits: list[str] = []
    for y in range(HASH_HEIGHT):
        row_offset = y * HASH_WIDTH
        for x in range(HASH_WIDTH - 1):
            left = pixels[row_offset + x]
            right = pixels[row_offset + x + 1]
            bits.append("1" if left > right else "0")

    return "".join(
        f"{int(''.join(bits[index:index + 4]), 2):x}"
        for index in range(0, len(bits), 4)
    )


def build_fingerprint_rows(images_dir: Path) -> list[dict[str, object]]:
    atlas_files = find_atlas_files(images_dir)
    if not atlas_files:
        raise FileNotFoundError(f"No atlas images found in {images_dir}")

    rows: list[dict[str, object]] = []
    for atlas_index, atlas_path in enumerate(atlas_files, start=1):
        validate_atlas(atlas_path)
        with Image.open(atlas_path) as atlas_image:
            for row in range(GRID_ROWS):
                for col in range(GRID_COLUMNS):
                    card = atlas_image.crop(card_bbox(row, col))
                    fingerprint = dhash_hex(crop_art(card))
                    card_id = f"atlas{atlas_index:02d}_r{row + 1:02d}_c{col + 1:02d}"
                    display_name = f"Atlas {atlas_index} R{row + 1} C{col + 1}"
                    if atlas_index == 1 and row == 0 and col == 0:
                        display_name = "Podilymbus podiceps"

                    rows.append(
                        {
                            "id": card_id,
                            "atlas": atlas_index,
                            "row": row + 1,
                            "col": col + 1,
                            "displayName": display_name,
                            "hash": fingerprint,
                        }
                    )

    return rows


def build_database(images_dir: Path, output_path: Path) -> tuple[int, Path]:
    rows = build_fingerprint_rows(images_dir)
    payload = {
        "version": 1,
        "algorithm": "dhash-17x16-grayscale-art-region",
        "cardSize": {"width": CARD_SIZE[0], "height": CARD_SIZE[1]},
        "artRegion": ART_REGION,
        "hash": {"width": HASH_WIDTH, "height": HASH_HEIGHT, "bits": (HASH_WIDTH - 1) * HASH_HEIGHT},
        "cards": rows,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return len(rows), output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build QR-like visual fingerprints from card atlas art.")
    parser.add_argument("--images-dir", type=Path, default=DEFAULT_IMAGES_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    count, output = build_database(args.images_dir, args.output)
    print(f"Wrote {count} card fingerprints: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
