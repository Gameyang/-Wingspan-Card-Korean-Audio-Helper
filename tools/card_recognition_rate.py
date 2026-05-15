from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Iterable

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import build_card_fingerprints as fingerprints


DEFAULT_IMAGES_DIR = Path("src/AtlasImage")
DEFAULT_FINGERPRINTS = Path("site/data/card_fingerprints.json")
DEFAULT_REPORT_CSV = Path("src/TestImages/card_recognition_report.csv")
VISUAL_SCORE_DIVISOR = 96

REPORT_FIELDS = [
    "card_id",
    "visual_reference_valid",
    "atlas_file",
    "row",
    "col",
    "matched_card_id",
    "expected_rank",
    "matched_distance",
    "expected_distance",
    "visual_score",
    "top_candidates",
    "top1_correct",
    "top3_correct",
]


def hamming_distance_hex(left: str, right: str) -> int:
    if not left or not right or len(left) != len(right):
        return fingerprints.HASH_HEIGHT * (fingerprints.HASH_WIDTH - 1)

    total = 0
    for index in range(0, len(left), 2):
        try:
            total += (int(left[index : index + 2], 16) ^ int(right[index : index + 2], 16)).bit_count()
        except ValueError:
            total += 8
    return total


def visual_score_from_hamming(distance: int) -> int:
    return max(0, round(100 - (distance * 100) / VISUAL_SCORE_DIVISOR))


def expected_card_id(atlas_index: int, row: int, col: int) -> str:
    return f"atlas{atlas_index:02d}_r{row + 1:02d}_c{col + 1:02d}"


def load_fingerprint_cards(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cards = payload.get("cards", [])
    if not isinstance(cards, list) or not cards:
        raise ValueError(f"No fingerprint cards found in {path}")
    return [card for card in cards if isinstance(card, dict) and card.get("id") and card.get("hash")]


def duplicate_hash_diagnostics(cards: Iterable[dict[str, object]]) -> dict[str, int]:
    by_hash: dict[str, list[str]] = {}
    total = 0
    for card in cards:
        total += 1
        by_hash.setdefault(str(card["hash"]), []).append(str(card["id"]))

    duplicate_groups = [ids for ids in by_hash.values() if len(ids) > 1]
    return {
        "fingerprint_cards": total,
        "unique_hashes": len(by_hash),
        "duplicate_hash_groups": len(duplicate_groups),
        "duplicate_hash_cards": sum(len(ids) for ids in duplicate_groups),
    }


def card_hashes(card: dict[str, object]) -> list[str]:
    hashes = card.get("hashes")
    if isinstance(hashes, list):
        return [str(value) for value in hashes if value]
    value = card.get("hash")
    return [str(value)] if value else []


def best_distance_to_card(captured_hash: str, card: dict[str, object]) -> int:
    distances = [
        hamming_distance_hex(captured_hash, candidate_hash)
        for candidate_hash in card_hashes(card)
    ]
    return min(distances) if distances else fingerprints.HASH_HEIGHT * (fingerprints.HASH_WIDTH - 1)


def rank_fingerprint_matches(
    captured_hash: str,
    cards: Iterable[dict[str, object]],
    *,
    require_visual_reference_valid: bool = True,
) -> list[dict[str, object]]:
    ranked: list[dict[str, object]] = []
    for card in cards:
        if require_visual_reference_valid and card.get("visualReferenceValid") is False:
            continue
        distance = best_distance_to_card(captured_hash, card)
        ranked.append(
            {
                "id": str(card["id"]),
                "distance": distance,
                "score": visual_score_from_hamming(distance),
            }
        )
    ranked.sort(key=lambda item: (int(item["distance"]), str(item["id"])))
    return ranked


def write_csv(path: Path, rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def evaluate_recognition(
    images_dir: Path = DEFAULT_IMAGES_DIR,
    fingerprints_path: Path = DEFAULT_FINGERPRINTS,
    report_csv: Path | None = None,
) -> dict[str, float | int | str]:
    atlas_files = fingerprints.find_atlas_files(images_dir)
    if not atlas_files:
        raise FileNotFoundError(f"No atlas images found in {images_dir}")

    cards = load_fingerprint_cards(fingerprints_path)
    duplicate_diagnostics = duplicate_hash_diagnostics(cards)
    rows: list[dict[str, object]] = []
    evaluated = 0
    valid_evaluated = 0
    top1_correct = 0
    top3_correct = 0
    valid_top1_correct = 0
    valid_top3_correct = 0
    worst_expected_distance = 0
    cards_by_id = {str(card["id"]): card for card in cards}

    for atlas_index, atlas_path in enumerate(atlas_files, start=1):
        fingerprints.validate_atlas(atlas_path)
        with Image.open(atlas_path) as atlas_image:
            for row in range(fingerprints.GRID_ROWS):
                for col in range(fingerprints.GRID_COLUMNS):
                    card = atlas_image.crop(fingerprints.card_bbox(row, col))
                    captured_hash = fingerprints.dhash_hex(fingerprints.crop_art(card))
                    ranked = rank_fingerprint_matches(captured_hash, cards)
                    expected_id = expected_card_id(atlas_index, row, col)
                    expected_card = cards_by_id.get(expected_id, {})
                    visual_reference_valid = expected_card.get("visualReferenceValid") is not False
                    expected_rank = next(
                        (index + 1 for index, item in enumerate(ranked) if item["id"] == expected_id),
                        0,
                    )
                    top3 = ranked[:3]
                    best = ranked[0] if ranked else {"id": "", "distance": -1, "score": 0}
                    expected_match = ranked[expected_rank - 1] if expected_rank else None
                    expected_distance = int(expected_match["distance"]) if expected_match else -1
                    worst_expected_distance = max(worst_expected_distance, expected_distance)

                    row_top1 = best["id"] == expected_id
                    row_top3 = any(item["id"] == expected_id for item in top3)
                    evaluated += 1
                    top1_correct += int(row_top1)
                    top3_correct += int(row_top3)
                    if visual_reference_valid:
                        valid_evaluated += 1
                        valid_top1_correct += int(row_top1)
                        valid_top3_correct += int(row_top3)

                    rows.append(
                        {
                            "card_id": expected_id,
                            "visual_reference_valid": str(visual_reference_valid).lower(),
                            "atlas_file": atlas_path.name,
                            "row": row + 1,
                            "col": col + 1,
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
        "worst_expected_distance": worst_expected_distance,
        "report_csv": str(report_csv) if report_csv else "",
        **duplicate_diagnostics,
    }


def print_summary(summary: dict[str, float | int | str]) -> None:
    print(f"Evaluated cards: {summary['evaluated']}")
    print(f"Top-1: {summary['top1_correct']} ({summary['top1_accuracy']:.2%})")
    print(f"Top-3: {summary['top3_correct']} ({summary['top3_accuracy']:.2%})")
    print(f"Valid visual references: {summary['valid_evaluated']}")
    print(f"Valid Top-1: {summary['valid_top1_correct']} ({summary['valid_top1_accuracy']:.2%})")
    print(f"Valid Top-3: {summary['valid_top3_correct']} ({summary['valid_top3_accuracy']:.2%})")
    print(f"Worst expected hamming distance: {summary['worst_expected_distance']}")
    print(f"Unique hashes: {summary['unique_hashes']} / {summary['fingerprint_cards']}")
    print(
        "Duplicate hash groups: "
        f"{summary['duplicate_hash_groups']} ({summary['duplicate_hash_cards']} cards)"
    )
    if summary.get("report_csv"):
        print(f"Report CSV: {summary['report_csv']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate Wingspan card visual recognition against atlas image crops."
    )
    parser.add_argument("--images-dir", type=Path, default=DEFAULT_IMAGES_DIR)
    parser.add_argument("--fingerprints", type=Path, default=DEFAULT_FINGERPRINTS)
    parser.add_argument("--report-csv", type=Path, default=DEFAULT_REPORT_CSV)
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Print only the summary and do not write a CSV report.",
    )
    parser.add_argument(
        "--fail-under-top1",
        type=float,
        default=None,
        help="Exit with status 1 if Top-1 accuracy is below this percent value.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        summary = evaluate_recognition(
            images_dir=args.images_dir,
            fingerprints_path=args.fingerprints,
            report_csv=None if args.no_report else args.report_csv,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    print_summary(summary)
    if args.fail_under_top1 is not None and summary["top1_accuracy"] * 100 < args.fail_under_top1:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
