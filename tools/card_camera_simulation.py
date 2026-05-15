from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import build_card_fingerprints as fingerprints
from tools import card_recognition_rate


DEFAULT_IMAGES_DIR = Path("src/AtlasImage")
DEFAULT_FINGERPRINTS = Path("site/data/card_fingerprints.json")
DEFAULT_REPORT_CSV = Path("src/TestImages/card_camera_simulation_report.csv")

SIMULATION_SCENARIOS = [
    ("front", {}),
    ("rotate_left_6", {"rotate_degrees": -6}),
    ("rotate_right_6", {"rotate_degrees": 6}),
    ("rotate_left_10", {"rotate_degrees": -10}),
    ("rotate_right_10", {"rotate_degrees": 10}),
    ("tilt_left", {"shear_x": -0.11}),
    ("tilt_right", {"shear_x": 0.11}),
    ("tilt_up", {"shear_y": -0.07}),
    ("tilt_down", {"shear_y": 0.07}),
    ("guide_left", {"offset_x_ratio": -0.07}),
    ("guide_right", {"offset_x_ratio": 0.07}),
    ("guide_up", {"offset_y_ratio": -0.05}),
    ("guide_down", {"offset_y_ratio": 0.05}),
    ("zoom_out", {"scale": 0.92}),
    ("zoom_in", {"scale": 1.08}),
    ("dark", {"brightness": 0.72}),
    ("bright", {"brightness": 1.28}),
    ("soft_blur", {"blur_radius": 1.15}),
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


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def evaluate_camera_simulation(
    images_dir: Path = DEFAULT_IMAGES_DIR,
    fingerprints_path: Path = DEFAULT_FINGERPRINTS,
    report_csv: Path | None = DEFAULT_REPORT_CSV,
    scenario_names: set[str] | None = None,
    max_cards: int | None = None,
) -> dict[str, object]:
    atlas_files = fingerprints.find_atlas_files(images_dir)
    if not atlas_files:
        raise FileNotFoundError(f"No atlas images found in {images_dir}")

    cards = card_recognition_rate.load_fingerprint_cards(fingerprints_path)
    cards_by_id = {str(card["id"]): card for card in cards}
    scenarios = [
        (name, kwargs)
        for name, kwargs in SIMULATION_SCENARIOS
        if not scenario_names or name in scenario_names
    ]
    if not scenarios:
        raise ValueError("No simulation scenarios selected.")
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

    for atlas_index, atlas_path in enumerate(atlas_files, start=1):
        fingerprints.validate_atlas(atlas_path)
        with Image.open(atlas_path) as atlas_image:
            for row in range(fingerprints.GRID_ROWS):
                for col in range(fingerprints.GRID_COLUMNS):
                    if max_cards is not None and processed_cards >= max_cards:
                        break
                    card_image = atlas_image.crop(fingerprints.card_bbox(row, col))
                    expected_id = card_recognition_rate.expected_card_id(atlas_index, row, col)
                    expected_card = cards_by_id.get(expected_id, {})
                    visual_reference_valid = expected_card.get("visualReferenceValid") is not False

                    for scenario_name, transform_kwargs in scenarios:
                        simulated_card = fingerprints.transform_image(card_image, **transform_kwargs)
                        captured_hash = fingerprints.dhash_hex(fingerprints.crop_art(simulated_card))
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
        description="Simulate phone camera card captures and evaluate visual recognition."
    )
    parser.add_argument("--images-dir", type=Path, default=DEFAULT_IMAGES_DIR)
    parser.add_argument("--fingerprints", type=Path, default=DEFAULT_FINGERPRINTS)
    parser.add_argument("--report-csv", type=Path, default=DEFAULT_REPORT_CSV)
    parser.add_argument("--no-report", action="store_true")
    parser.add_argument("--scenario", action="append", default=[])
    parser.add_argument("--max-cards", type=int, default=None)
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
        summary = evaluate_camera_simulation(
            images_dir=args.images_dir,
            fingerprints_path=args.fingerprints,
            report_csv=None if args.no_report else args.report_csv,
            scenario_names=set(args.scenario) if args.scenario else None,
            max_cards=args.max_cards,
        )
    except (FileNotFoundError, ValueError) as exc:
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
