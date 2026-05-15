from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageStat


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
LOW_VARIANCE_STDDEV = 3.0

REFERENCE_CAMERA_VARIANTS = [
    ("original", {}),
    ("rotate_left_6", {"rotate_degrees": -6}),
    ("rotate_right_6", {"rotate_degrees": 6}),
    ("rotate_left_10", {"rotate_degrees": -10}),
    ("rotate_right_10", {"rotate_degrees": 10}),
    ("zoom_out", {"scale": 0.94}),
    ("zoom_in", {"scale": 1.06}),
    ("offset_left", {"offset_x_ratio": -0.05}),
    ("offset_right", {"offset_x_ratio": 0.05}),
    ("offset_left_7", {"offset_x_ratio": -0.07}),
    ("offset_right_7", {"offset_x_ratio": 0.07}),
    ("offset_up", {"offset_y_ratio": -0.05}),
    ("offset_down", {"offset_y_ratio": 0.05}),
    ("offset_up_8", {"scale": 1.03, "offset_y_ratio": -0.075}),
    ("offset_down_8", {"scale": 1.03, "offset_y_ratio": 0.075}),
    ("tilt_left", {"shear_x": -0.08}),
    ("tilt_right", {"shear_x": 0.08}),
    ("tilt_left_strong", {"rotate_degrees": -6, "shear_x": -0.12}),
    ("tilt_right_strong", {"rotate_degrees": 6, "shear_x": 0.12}),
]

DEFAULT_IMAGES_DIR = Path("src/AtlasImage")
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


def average_rgb(image: Image.Image) -> tuple[int, int, int]:
    pixel = image.convert("RGB").resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))
    return tuple(int(value) for value in pixel)


def transform_image(
    image: Image.Image,
    *,
    scale: float = 1.0,
    offset_x_ratio: float = 0.0,
    offset_y_ratio: float = 0.0,
    rotate_degrees: float = 0.0,
    shear_x: float = 0.0,
    shear_y: float = 0.0,
    brightness: float = 1.0,
    blur_radius: float = 0.0,
) -> Image.Image:
    width, height = image.size
    fill = average_rgb(image)
    result = image.convert("RGB")

    if scale != 1.0 or offset_x_ratio or offset_y_ratio:
        canvas = Image.new("RGB", (width, height), fill)
        scaled_size = (
            max(1, round(width * scale)),
            max(1, round(height * scale)),
        )
        scaled = result.resize(scaled_size, Image.Resampling.BICUBIC)
        left = round((width - scaled_size[0]) / 2 + width * offset_x_ratio)
        top = round((height - scaled_size[1]) / 2 + height * offset_y_ratio)
        canvas.paste(scaled, (left, top))
        result = canvas

    if shear_x or shear_y:
        result = result.transform(
            (width, height),
            Image.Transform.AFFINE,
            (
                1,
                shear_x,
                -shear_x * height / 2,
                shear_y,
                1,
                -shear_y * width / 2,
            ),
            resample=Image.Resampling.BICUBIC,
            fillcolor=fill,
        )

    if rotate_degrees:
        result = result.rotate(
            rotate_degrees,
            resample=Image.Resampling.BICUBIC,
            expand=False,
            fillcolor=fill,
        )

    if brightness != 1.0:
        result = ImageEnhance.Brightness(result).enhance(brightness)

    if blur_radius:
        result = result.filter(ImageFilter.GaussianBlur(blur_radius))

    return result


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


def grayscale_stddev(image: Image.Image) -> float:
    return float(ImageStat.Stat(ImageOps.grayscale(image)).stddev[0])


def hash_variants_for_art(art_image: Image.Image) -> list[dict[str, str]]:
    variants: list[dict[str, str]] = []
    seen: set[str] = set()
    for name, kwargs in REFERENCE_CAMERA_VARIANTS:
        transformed = transform_image(art_image, **kwargs)
        fingerprint = dhash_hex(transformed)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        variants.append({"name": name, "hash": fingerprint})
    return variants


def annotate_visual_reference_quality(rows: list[dict[str, object]]) -> None:
    by_hash: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_hash[str(row["hash"])].append(row)

    for row in rows:
        duplicate_group_size = len(by_hash[str(row["hash"])])
        low_variance = float(row["artStdDev"]) < LOW_VARIANCE_STDDEV
        duplicate_hash = duplicate_group_size > 1
        valid = not low_variance and not duplicate_hash
        reasons = []
        if low_variance:
            reasons.append("low_variance")
        if duplicate_hash:
            reasons.append("duplicate_original_hash")

        row["visualReferenceValid"] = valid
        row["visualReferenceReason"] = "ok" if valid else "|".join(reasons)
        row["visualDuplicateGroupSize"] = duplicate_group_size


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
                    art = crop_art(card)
                    hash_variants = hash_variants_for_art(art)
                    fingerprint = hash_variants[0]["hash"]
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
                            "hashes": [variant["hash"] for variant in hash_variants],
                            "hashVariants": hash_variants,
                            "artStdDev": round(grayscale_stddev(art), 3),
                        }
                    )

    annotate_visual_reference_quality(rows)
    return rows


def build_database(images_dir: Path, output_path: Path) -> tuple[int, Path]:
    rows = build_fingerprint_rows(images_dir)
    duplicate_groups = defaultdict(list)
    for row in rows:
        duplicate_groups[str(row["hash"])].append(str(row["id"]))
    duplicate_hash_groups = [ids for ids in duplicate_groups.values() if len(ids) > 1]
    valid_rows = [row for row in rows if row["visualReferenceValid"]]
    payload = {
        "version": 2,
        "algorithm": "dhash-17x16-grayscale-art-region-camera-variants",
        "cardSize": {"width": CARD_SIZE[0], "height": CARD_SIZE[1]},
        "artRegion": ART_REGION,
        "hash": {"width": HASH_WIDTH, "height": HASH_HEIGHT, "bits": (HASH_WIDTH - 1) * HASH_HEIGHT},
        "referenceVariants": [name for name, _kwargs in REFERENCE_CAMERA_VARIANTS],
        "diagnostics": {
            "cardCount": len(rows),
            "validVisualReferenceCount": len(valid_rows),
            "invalidVisualReferenceCount": len(rows) - len(valid_rows),
            "duplicateOriginalHashGroups": len(duplicate_hash_groups),
            "duplicateOriginalHashCards": sum(len(ids) for ids in duplicate_hash_groups),
            "lowVarianceThreshold": LOW_VARIANCE_STDDEV,
        },
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
