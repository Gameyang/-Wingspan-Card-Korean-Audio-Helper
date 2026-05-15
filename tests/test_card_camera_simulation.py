from __future__ import annotations

from pathlib import Path

from tools import card_camera_simulation


REPO_ROOT = Path(__file__).resolve().parents[1]
IMAGES_DIR = REPO_ROOT / "src" / "AtlasImage"
FINGERPRINTS = REPO_ROOT / "site" / "data" / "card_fingerprints.json"


def test_camera_simulation_subset_handles_core_phone_offsets() -> None:
    summary = card_camera_simulation.evaluate_camera_simulation(
        images_dir=IMAGES_DIR,
        fingerprints_path=FINGERPRINTS,
        report_csv=None,
        scenario_names={"front", "guide_up", "guide_down", "rotate_left_10"},
        max_cards=8,
    )

    assert summary["evaluated"] == 32
    assert summary["valid_evaluated"] == 32
    assert summary["valid_top1_correct"] >= 29
    assert summary["valid_top3_correct"] >= 31
    assert summary["valid_top1_accuracy"] >= 0.90
