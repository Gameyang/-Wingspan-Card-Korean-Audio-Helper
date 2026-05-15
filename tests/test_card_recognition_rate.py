from __future__ import annotations

from pathlib import Path

from tools import card_recognition_rate


REPO_ROOT = Path(__file__).resolve().parents[1]
IMAGES_DIR = REPO_ROOT / "src" / "AtlasImage"
FINGERPRINTS = REPO_ROOT / "site" / "data" / "card_fingerprints.json"


def test_current_atlas_images_report_visual_recognition_rate() -> None:
    summary = card_recognition_rate.evaluate_recognition(
        images_dir=IMAGES_DIR,
        fingerprints_path=FINGERPRINTS,
    )

    assert summary["evaluated"] == 210
    assert summary["valid_evaluated"] == 170
    assert summary["top1_correct"] == 170
    assert summary["top3_correct"] == 170
    assert summary["valid_top1_correct"] == 170
    assert summary["valid_top3_correct"] == 170
    assert summary["top1_accuracy"] == 170 / 210
    assert summary["top3_accuracy"] == 170 / 210
    assert summary["valid_top1_accuracy"] == 1.0
    assert summary["valid_top3_accuracy"] == 1.0
    assert summary["worst_expected_distance"] == 0
    assert summary["unique_hashes"] == 172
    assert summary["duplicate_hash_groups"] == 2
    assert summary["duplicate_hash_cards"] == 40


def test_hamming_distance_hex_counts_changed_bits() -> None:
    assert card_recognition_rate.hamming_distance_hex("00", "00") == 0
    assert card_recognition_rate.hamming_distance_hex("00", "ff") == 8
    assert card_recognition_rate.hamming_distance_hex("0f", "f0") == 8
