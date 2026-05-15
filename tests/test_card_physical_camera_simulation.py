from __future__ import annotations

from pathlib import Path

from tools import card_physical_camera_simulation


REPO_ROOT = Path(__file__).resolve().parents[1]
IMAGES_DIR = REPO_ROOT / "src" / "AtlasImage"
FINGERPRINTS = REPO_ROOT / "site" / "data" / "card_fingerprints.json"


def test_physical_camera_subset_handles_lighting_and_glare() -> None:
    summary = card_physical_camera_simulation.evaluate_physical_camera_simulation(
        images_dir=IMAGES_DIR,
        fingerprints_path=FINGERPRINTS,
        report_csv=None,
        scenario_names={"desk_normal", "bright_overhead_glare", "low_light_soft_focus"},
        max_cards=8,
    )

    assert summary["evaluated"] == 24
    assert summary["valid_evaluated"] == 24
    assert summary["valid_top1_correct"] == 24
    assert summary["valid_top1_accuracy"] == 1.0
