from __future__ import annotations

import argparse
import csv
import hashlib
import io
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import build_card_fingerprints as fingerprints
from tools import card_recognition_rate


DEFAULT_IMAGES_DIR = Path("src/AtlasImage")
DEFAULT_FINGERPRINTS = Path("site/data/card_fingerprints.json")
DEFAULT_REPORT_CSV = Path("src/TestImages/card_physical_camera_simulation_report.csv")

GUIDE_SIZE = fingerprints.CARD_SIZE
SOURCE_CORNERS = [
    (0.0, 0.0),
    (float(GUIDE_SIZE[0]), 0.0),
    (float(GUIDE_SIZE[0]), float(GUIDE_SIZE[1])),
    (0.0, float(GUIDE_SIZE[1])),
]

PHYSICAL_SCENARIOS = [
    (
        "desk_normal",
        {
            "background": "matte_table",
            "scale": 0.97,
            "rotate_degrees": 1.5,
            "brightness": 1.02,
        },
    ),
    (
        "handheld_left_perspective",
        {
            "background": "warm_table",
            "scale": 0.96,
            "rotate_degrees": -6.5,
            "corner_offsets": [(-0.03, 0.02), (0.04, -0.04), (0.02, 0.04), (-0.02, -0.01)],
        },
    ),
    (
        "handheld_right_perspective",
        {
            "background": "cool_table",
            "scale": 0.96,
            "rotate_degrees": 6.5,
            "corner_offsets": [(-0.03, -0.04), (0.04, 0.02), (0.02, -0.01), (-0.02, 0.04)],
        },
    ),
    (
        "guide_high_partial",
        {
            "background": "matte_table",
            "scale": 1.03,
            "offset_y_ratio": -0.075,
            "rotate_degrees": -2.5,
        },
    ),
    (
        "guide_low_partial",
        {
            "background": "matte_table",
            "scale": 1.03,
            "offset_y_ratio": 0.075,
            "rotate_degrees": 2.5,
        },
    ),
    (
        "far_small_card",
        {
            "background": "warm_table",
            "scale": 0.86,
            "rotate_degrees": 3.0,
            "shadow": "bottom",
        },
    ),
    (
        "close_clipped_card",
        {
            "background": "cool_table",
            "scale": 1.12,
            "offset_x_ratio": 0.035,
            "rotate_degrees": -3.0,
        },
    ),
    (
        "low_light_soft_focus",
        {
            "background": "dark_table",
            "brightness": 0.56,
            "contrast": 0.82,
            "blur_radius": 1.6,
            "noise_sigma": 5.0,
        },
    ),
    (
        "bright_overhead_glare",
        {
            "background": "matte_table",
            "brightness": 1.24,
            "contrast": 0.95,
            "glare": "diagonal",
            "noise_sigma": 2.0,
        },
    ),
    (
        "side_lamp_shadow",
        {
            "background": "warm_table",
            "brightness": 0.78,
            "contrast": 1.08,
            "shadow": "left",
            "rotate_degrees": -4.0,
        },
    ),
    (
        "motion_blur_handheld",
        {
            "background": "matte_table",
            "rotate_degrees": 5.0,
            "motion_blur": 7,
            "brightness": 0.92,
        },
    ),
    (
        "low_res_jpeg",
        {
            "background": "cool_table",
            "scale": 0.94,
            "downsample": 0.52,
            "jpeg_quality": 42,
            "noise_sigma": 3.0,
        },
    ),
]

REPORT_FIELDS = [
    "card_id",
    "visual_reference_valid",
    "scenario",
    "matched_card_id",
    "expected_rank",
    "matched_distance",
    "expected_distance",
    "visual_score",
    "top_candidates",
    "top1_correct",
    "top3_correct",
]


def perspective_coefficients(
    output_points: list[tuple[float, float]],
    source_points: list[tuple[float, float]],
) -> list[float]:
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("Physical camera simulation requires numpy.") from exc

    matrix = []
    vector = []
    for (x, y), (u, v) in zip(output_points, source_points, strict=True):
        matrix.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        matrix.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        vector.extend([u, v])
    return np.linalg.solve(np.asarray(matrix), np.asarray(vector)).tolist()


def rotated_points(
    points: list[tuple[float, float]],
    degrees: float,
    center: tuple[float, float],
) -> list[tuple[float, float]]:
    if not degrees:
        return points
    radians = math.radians(degrees)
    cos_value = math.cos(radians)
    sin_value = math.sin(radians)
    center_x, center_y = center
    rotated = []
    for x, y in points:
        dx = x - center_x
        dy = y - center_y
        rotated.append(
            (
                center_x + dx * cos_value - dy * sin_value,
                center_y + dx * sin_value + dy * cos_value,
            )
        )
    return rotated


def destination_corners(options: dict[str, object]) -> list[tuple[float, float]]:
    width, height = GUIDE_SIZE
    scale = float(options.get("scale", 1.0))
    offset_x = float(options.get("offset_x_ratio", 0.0)) * width
    offset_y = float(options.get("offset_y_ratio", 0.0)) * height
    card_width = width * scale
    card_height = height * scale
    left = (width - card_width) / 2 + offset_x
    top = (height - card_height) / 2 + offset_y
    points = [
        (left, top),
        (left + card_width, top),
        (left + card_width, top + card_height),
        (left, top + card_height),
    ]
    points = rotated_points(
        points,
        float(options.get("rotate_degrees", 0.0)),
        (width / 2 + offset_x, height / 2 + offset_y),
    )
    corner_offsets = options.get("corner_offsets", [])
    if isinstance(corner_offsets, list):
        adjusted = []
        for point, offset in zip(points, corner_offsets, strict=False):
            dx, dy = offset
            adjusted.append((point[0] + float(dx) * width, point[1] + float(dy) * height))
        adjusted.extend(points[len(adjusted) :])
        points = adjusted
    return points


def table_background(kind: str) -> Image.Image:
    width, height = GUIDE_SIZE
    palettes = {
        "matte_table": ((82, 86, 76), (111, 116, 101)),
        "warm_table": ((112, 82, 54), (151, 115, 75)),
        "cool_table": ((58, 72, 82), (88, 104, 118)),
        "dark_table": ((31, 34, 35), (55, 59, 58)),
    }
    top_color, bottom_color = palettes.get(kind, palettes["matte_table"])
    image = Image.new("RGB", GUIDE_SIZE)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / max(1, height - 1)
        color = tuple(round(top_color[i] * (1 - ratio) + bottom_color[i] * ratio) for i in range(3))
        draw.line((0, y, width, y), fill=color)
    return image


def warp_card_to_guide(card_image: Image.Image, options: dict[str, object]) -> Image.Image:
    background = table_background(str(options.get("background", "matte_table")))
    coeffs = perspective_coefficients(destination_corners(options), SOURCE_CORNERS)
    warped_card = card_image.convert("RGB").transform(
        GUIDE_SIZE,
        Image.Transform.PERSPECTIVE,
        coeffs,
        resample=Image.Resampling.BICUBIC,
        fillcolor=(0, 0, 0),
    )
    card_mask = Image.new("L", GUIDE_SIZE, 255).transform(
        GUIDE_SIZE,
        Image.Transform.PERSPECTIVE,
        coeffs,
        resample=Image.Resampling.BICUBIC,
        fillcolor=0,
    )
    background.paste(warped_card, (0, 0), card_mask)
    return background


def add_shadow(image: Image.Image, side: str) -> Image.Image:
    width, height = image.size
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    if side == "left":
        for x in range(width):
            alpha = max(0, round(110 * (1 - x / max(1, width * 0.72))))
            draw.line((x, 0, x, height), fill=(0, 0, 0, alpha))
    elif side == "bottom":
        for y in range(height):
            alpha = max(0, round(100 * ((y - height * 0.35) / max(1, height * 0.65))))
            draw.line((0, y, width, y), fill=(0, 0, 0, alpha))
    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")


def add_glare(image: Image.Image, kind: str) -> Image.Image:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    if kind == "diagonal":
        draw.line((-80, 180, image.width + 90, 620), fill=(255, 255, 255, 92), width=72)
        draw.ellipse((image.width * 0.58, 90, image.width * 1.05, 420), fill=(255, 255, 255, 54))
    overlay = overlay.filter(ImageFilter.GaussianBlur(18))
    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")


def add_noise(image: Image.Image, sigma: float, seed_text: str) -> Image.Image:
    if sigma <= 0:
        return image
    try:
        import numpy as np
    except ImportError:
        return image

    seed = int.from_bytes(hashlib.sha256(seed_text.encode("utf-8")).digest()[:8], "big")
    rng = np.random.default_rng(seed)
    array = np.asarray(image).astype("int16")
    noise = rng.normal(0, sigma, array.shape)
    array = np.clip(array + noise, 0, 255).astype("uint8")
    return Image.fromarray(array, "RGB")


def apply_motion_blur(image: Image.Image, size: int) -> Image.Image:
    if size <= 1:
        return image
    try:
        import numpy as np
    except ImportError:
        return image.filter(ImageFilter.GaussianBlur(size / 3))

    size = size if size % 2 == 1 else size + 1
    half = size // 2
    arrays = []
    for offset in range(-half, half + 1):
        shifted = Image.new("RGB", image.size, (0, 0, 0))
        if offset < 0:
            shifted.paste(image.crop((-offset, 0, image.width, image.height)), (0, 0))
        elif offset > 0:
            shifted.paste(image.crop((0, 0, image.width - offset, image.height)), (offset, 0))
        else:
            shifted.paste(image, (0, 0))
        arrays.append(np.asarray(shifted, dtype="float32"))
    return Image.fromarray(np.clip(np.mean(arrays, axis=0), 0, 255).astype("uint8"), "RGB")


def apply_jpeg_roundtrip(image: Image.Image, quality: int) -> Image.Image:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)
    return Image.open(buffer).convert("RGB")


def apply_physical_effects(image: Image.Image, scenario_name: str, card_id: str, options: dict[str, object]) -> Image.Image:
    result = image
    if options.get("shadow"):
        result = add_shadow(result, str(options["shadow"]))
    if options.get("glare"):
        result = add_glare(result, str(options["glare"]))
    if float(options.get("brightness", 1.0)) != 1.0:
        result = ImageEnhance.Brightness(result).enhance(float(options["brightness"]))
    if float(options.get("contrast", 1.0)) != 1.0:
        result = ImageEnhance.Contrast(result).enhance(float(options["contrast"]))
    if float(options.get("blur_radius", 0.0)):
        result = result.filter(ImageFilter.GaussianBlur(float(options["blur_radius"])))
    if int(options.get("motion_blur", 0)):
        result = apply_motion_blur(result, int(options["motion_blur"]))
    result = add_noise(result, float(options.get("noise_sigma", 0.0)), f"{scenario_name}:{card_id}")
    if float(options.get("downsample", 1.0)) != 1.0:
        factor = float(options["downsample"])
        small_size = (
            max(1, round(result.width * factor)),
            max(1, round(result.height * factor)),
        )
        result = result.resize(small_size, Image.Resampling.BILINEAR).resize(
            result.size,
            Image.Resampling.BICUBIC,
        )
    if int(options.get("jpeg_quality", 0)):
        result = apply_jpeg_roundtrip(result, int(options["jpeg_quality"]))
    return result


def simulate_guide_crop(card_image: Image.Image, scenario_name: str, options: dict[str, object], card_id: str) -> Image.Image:
    guide_crop = warp_card_to_guide(card_image, options)
    return apply_physical_effects(guide_crop, scenario_name, card_id, options)


def selected_scenarios(scenario_names: set[str] | None) -> list[tuple[str, dict[str, object]]]:
    scenarios = [
        (name, options)
        for name, options in PHYSICAL_SCENARIOS
        if not scenario_names or name in scenario_names
    ]
    if not scenarios:
        raise ValueError("No physical camera simulation scenarios selected.")
    return scenarios


def write_csv(path: Path, rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def evaluate_physical_camera_simulation(
    images_dir: Path = DEFAULT_IMAGES_DIR,
    fingerprints_path: Path = DEFAULT_FINGERPRINTS,
    report_csv: Path | None = DEFAULT_REPORT_CSV,
    scenario_names: set[str] | None = None,
    max_cards: int | None = None,
    failure_images_dir: Path | None = None,
) -> dict[str, object]:
    atlas_files = fingerprints.find_atlas_files(images_dir)
    if not atlas_files:
        raise FileNotFoundError(f"No atlas images found in {images_dir}")

    cards = card_recognition_rate.load_fingerprint_cards(fingerprints_path)
    cards_by_id = {str(card["id"]): card for card in cards}
    scenarios = selected_scenarios(scenario_names)
    rows: list[dict[str, object]] = []
    scenario_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "evaluated": 0,
            "top1": 0,
            "top3": 0,
            "valid_evaluated": 0,
            "valid_top1": 0,
            "valid_top3": 0,
        }
    )

    evaluated = 0
    valid_evaluated = 0
    top1_correct = 0
    top3_correct = 0
    valid_top1_correct = 0
    valid_top3_correct = 0
    processed_cards = 0

    if failure_images_dir:
        failure_images_dir.mkdir(parents=True, exist_ok=True)

    for atlas_index, atlas_path in enumerate(atlas_files, start=1):
        fingerprints.validate_atlas(atlas_path)
        with Image.open(atlas_path) as atlas_image:
            for row in range(fingerprints.GRID_ROWS):
                for col in range(fingerprints.GRID_COLUMNS):
                    if max_cards is not None and processed_cards >= max_cards:
                        break
                    expected_id = card_recognition_rate.expected_card_id(atlas_index, row, col)
                    expected_card = cards_by_id.get(expected_id, {})
                    visual_reference_valid = expected_card.get("visualReferenceValid") is not False
                    card_image = atlas_image.crop(fingerprints.card_bbox(row, col))

                    for scenario_name, options in scenarios:
                        simulated = simulate_guide_crop(card_image, scenario_name, options, expected_id)
                        captured_hash = fingerprints.dhash_hex(fingerprints.crop_art(simulated))
                        ranked = card_recognition_rate.rank_fingerprint_matches(captured_hash, cards)
                        expected_rank = next(
                            (index + 1 for index, item in enumerate(ranked) if item["id"] == expected_id),
                            0,
                        )
                        top3 = ranked[:3]
                        best = ranked[0] if ranked else {"id": "", "distance": -1, "score": 0}
                        expected_match = ranked[expected_rank - 1] if expected_rank else None
                        expected_distance = int(expected_match["distance"]) if expected_match else -1
                        row_top1 = best["id"] == expected_id
                        row_top3 = any(item["id"] == expected_id for item in top3)

                        evaluated += 1
                        top1_correct += int(row_top1)
                        top3_correct += int(row_top3)

                        scenario = scenario_counts[scenario_name]
                        scenario["evaluated"] += 1
                        scenario["top1"] += int(row_top1)
                        scenario["top3"] += int(row_top3)

                        if visual_reference_valid:
                            valid_evaluated += 1
                            valid_top1_correct += int(row_top1)
                            valid_top3_correct += int(row_top3)
                            scenario["valid_evaluated"] += 1
                            scenario["valid_top1"] += int(row_top1)
                            scenario["valid_top3"] += int(row_top3)

                        if failure_images_dir and visual_reference_valid and not row_top1:
                            simulated.save(failure_images_dir / f"{expected_id}_{scenario_name}_{best['id']}.jpg", quality=88)

                        rows.append(
                            {
                                "card_id": expected_id,
                                "visual_reference_valid": str(visual_reference_valid).lower(),
                                "scenario": scenario_name,
                                "matched_card_id": best["id"],
                                "expected_rank": expected_rank,
                                "matched_distance": best["distance"],
                                "expected_distance": expected_distance,
                                "visual_score": best["score"],
                                "top_candidates": " | ".join(
                                    f"{item['id']}:{item['distance']}:{item['score']}" for item in top3
                                ),
                                "top1_correct": str(row_top1).lower(),
                                "top3_correct": str(row_top3).lower(),
                            }
                        )
                    processed_cards += 1
                if max_cards is not None and processed_cards >= max_cards:
                    break
        if max_cards is not None and processed_cards >= max_cards:
            break

    if report_csv:
        write_csv(report_csv, rows)

    return {
        "evaluated": evaluated,
        "valid_evaluated": valid_evaluated,
        "top1_correct": top1_correct,
        "top3_correct": top3_correct,
        "valid_top1_correct": valid_top1_correct,
        "valid_top3_correct": valid_top3_correct,
        "top1_accuracy": top1_correct / evaluated if evaluated else 0.0,
        "top3_accuracy": top3_correct / evaluated if evaluated else 0.0,
        "valid_top1_accuracy": valid_top1_correct / valid_evaluated if valid_evaluated else 0.0,
        "valid_top3_accuracy": valid_top3_correct / valid_evaluated if valid_evaluated else 0.0,
        "scenario_count": len(scenarios),
        "scenario_summary": dict(scenario_counts),
        "report_csv": str(report_csv) if report_csv else "",
    }


def print_summary(summary: dict[str, object]) -> None:
    print(f"Evaluated samples: {summary['evaluated']}")
    print(f"Scenarios: {summary['scenario_count']}")
    print(f"Top-1: {summary['top1_correct']} ({summary['top1_accuracy']:.2%})")
    print(f"Top-3: {summary['top3_correct']} ({summary['top3_accuracy']:.2%})")
    print(f"Valid visual samples: {summary['valid_evaluated']}")
    print(f"Valid Top-1: {summary['valid_top1_correct']} ({summary['valid_top1_accuracy']:.2%})")
    print(f"Valid Top-3: {summary['valid_top3_correct']} ({summary['valid_top3_accuracy']:.2%})")
    if summary.get("report_csv"):
        print(f"Report CSV: {summary['report_csv']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Simulate physical phone-camera captures and evaluate visual card recognition."
    )
    parser.add_argument("--images-dir", type=Path, default=DEFAULT_IMAGES_DIR)
    parser.add_argument("--fingerprints", type=Path, default=DEFAULT_FINGERPRINTS)
    parser.add_argument("--report-csv", type=Path, default=DEFAULT_REPORT_CSV)
    parser.add_argument("--no-report", action="store_true")
    parser.add_argument("--scenario", action="append", default=[])
    parser.add_argument("--max-cards", type=int, default=None)
    parser.add_argument("--failure-images-dir", type=Path)
    parser.add_argument(
        "--fail-under-valid-top1",
        type=float,
        default=None,
        help="Exit with status 1 if valid-reference Top-1 accuracy is below this percent value.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        summary = evaluate_physical_camera_simulation(
            images_dir=args.images_dir,
            fingerprints_path=args.fingerprints,
            report_csv=None if args.no_report else args.report_csv,
            scenario_names=set(args.scenario) if args.scenario else None,
            max_cards=args.max_cards,
            failure_images_dir=args.failure_images_dir,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    print_summary(summary)
    if (
        args.fail_under_valid_top1 is not None
        and summary["valid_top1_accuracy"] * 100 < args.fail_under_valid_top1
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
