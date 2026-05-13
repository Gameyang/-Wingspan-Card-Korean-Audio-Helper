from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from tools import build_card_fingerprints as fingerprints


REPO_ROOT = Path(__file__).resolve().parents[1]


def hamming_hex(left: str, right: str) -> int:
    return sum(
        (int(left_item, 16) ^ int(right_item, 16)).bit_count()
        for left_item, right_item in zip(left, right, strict=True)
    )


def test_sample_card_matches_first_visual_fingerprint() -> None:
    data_path = REPO_ROOT / "site" / "data" / "card_fingerprints.json"
    sample_path = REPO_ROOT / "site" / "assets" / "new_card_sample.jpg"
    data = json.loads(data_path.read_text(encoding="utf-8"))

    with Image.open(sample_path) as image:
        sample_hash = fingerprints.dhash_hex(fingerprints.crop_art(image))

    ranked = sorted(
        (
            (hamming_hex(sample_hash, row["hash"]), row["id"], row["displayName"])
            for row in data["cards"]
        ),
        key=lambda item: item[0],
    )

    assert ranked[0][0] <= 8
    assert ranked[0][1] == "atlas01_r01_c01"
    assert ranked[0][2] == "Podilymbus podiceps"
