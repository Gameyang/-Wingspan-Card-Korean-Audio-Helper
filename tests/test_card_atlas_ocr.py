from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from tools import card_atlas_ocr as atlas_ocr


REPO_ROOT = Path(__file__).resolve().parents[1]
IMAGES_DIR = REPO_ROOT / "src" / "Images"


def require_atlas_files() -> list[Path]:
    atlas_files = atlas_ocr.find_atlas_files(IMAGES_DIR)
    if not atlas_files:
        pytest.skip(f"No atlas fixtures found in {IMAGES_DIR}")
    return atlas_files


def test_current_atlases_match_expected_grid_size() -> None:
    atlas_files = require_atlas_files()

    assert len(atlas_files) == 3
    for atlas_file in atlas_files:
        assert atlas_ocr.validate_atlas_file(atlas_file) == atlas_ocr.EXPECTED_ATLAS_SIZE


def test_card_bbox_and_sample_crop_dimensions(tmp_path: Path) -> None:
    require_atlas_files()
    output = tmp_path / "sample.jpg"

    saved_path = atlas_ocr.extract_sample_card(IMAGES_DIR, output)

    assert saved_path == output
    assert atlas_ocr.card_bbox(row=0, col=0) == (0, 0, 630, 970)
    with Image.open(saved_path) as image:
        assert image.size == atlas_ocr.CARD_SIZE


def test_matching_ranks_korean_card_name() -> None:
    candidates = ["붉은물오리", "알락귀뿔논병아리", "원앙"]
    ranked = atlas_ocr.rank_candidates("알락귀뿔 논병아리 Podilymbus podiceps", candidates)

    assert ranked[0][0] == "알락귀뿔논병아리"
    assert ranked[0][1] >= 80


def test_tesseract_missing_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(atlas_ocr.shutil, "which", lambda _name: None)

    with pytest.raises(RuntimeError, match="Tesseract executable was not found"):
        atlas_ocr.ensure_tesseract_ready()


def test_build_review_csv_checks_ocr_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_missing(language: str = "kor+eng") -> None:
        raise RuntimeError(f"missing {language}")

    monkeypatch.setattr(atlas_ocr, "ensure_tesseract_ready", raise_missing)

    with pytest.raises(RuntimeError, match="missing kor\\+eng"):
        atlas_ocr.build_review_csv(
            images_dir=IMAGES_DIR,
            output_csv=tmp_path / "review.csv",
            crops_dir=tmp_path / "cards",
        )

    assert not (tmp_path / "review.csv").exists()
    assert not (tmp_path / "cards").exists()


def test_validate_identification_calculates_accuracy(tmp_path: Path) -> None:
    review_csv = tmp_path / "review.csv"
    atlas_ocr.write_csv(
        review_csv,
        atlas_ocr.REVIEW_FIELDS,
        [
            {
                "atlas_file": "atlas01.jpg",
                "row": "0",
                "col": "0",
                "card_crop_path": "card1.jpg",
                "ocr_text": "알락귀뿔 논병아리 Podilymbus podiceps",
                "ocr_confidence": "92.0",
                "expected_name_ko": "알락귀뿔논병아리",
                "expected_name_latin": "Podilymbus podiceps",
            },
            {
                "atlas_file": "atlas01.jpg",
                "row": "0",
                "col": "1",
                "card_crop_path": "card2.jpg",
                "ocr_text": "붉은물오리 Oxyura jamaicensis",
                "ocr_confidence": "91.0",
                "expected_name_ko": "붉은물오리",
                "expected_name_latin": "Oxyura jamaicensis",
            },
        ],
    )

    summary = atlas_ocr.validate_identification(review_csv)

    assert summary["evaluated"] == 2
    assert summary["top1_correct"] == 2
    assert summary["top3_correct"] == 2
    assert summary["top1_accuracy"] == 1.0
    assert summary["top3_accuracy"] == 1.0
