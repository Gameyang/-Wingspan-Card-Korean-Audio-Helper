from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_first_visual_fingerprint_entry_is_present() -> None:
    data_path = REPO_ROOT / "site" / "data" / "card_fingerprints.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))

    first = data["cards"][0]
    assert len(data["cards"]) == 210
    assert data["algorithm"] == "dhash-17x16-grayscale-art-region"
    assert first["id"] == "atlas01_r01_c01"
    assert first["displayName"] == "Podilymbus podiceps"
    assert len(first["hash"]) == 64


def test_site_audio_manifest_maps_first_card_to_audio_files() -> None:
    data_path = REPO_ROOT / "site" / "data" / "audio_clips.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))

    clips = data["byCardId"]["atlas01_r01_c01"]

    assert len(clips) == 3
    assert {clip["birdName"] for clip in clips} == {"Pied Billed Grebe"}
    assert any(clip["isMain"] for clip in clips)
    for clip in clips:
        assert (REPO_ROOT / "site" / clip["src"]).is_file()
