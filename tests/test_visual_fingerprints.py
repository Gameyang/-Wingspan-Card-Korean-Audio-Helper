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

    assert len(data["byCardId"]) == 210
    assert data["atlasSequenceStartCardNo"] == 53
    assert len(clips) == 3
    assert {clip["birdName"] for clip in clips} == {"Pied Billed Grebe"}
    assert any(clip["isMain"] for clip in clips)
    for clip in clips:
        assert (REPO_ROOT / "site" / clip["src"]).is_file()


def test_site_audio_manifest_maps_last_card_to_audio_files() -> None:
    data_path = REPO_ROOT / "site" / "data" / "audio_clips.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))

    clips = data["byCardId"]["atlas03_r07_c10"]

    assert len(clips) == 5
    assert {clip["cardNo"] for clip in clips} == {"262"}
    assert {clip["birdName"] for clip in clips} == {"Abbotts Booby"}
    assert all(" " not in clip["src"] for clip in clips)
    for clip in clips:
        assert (REPO_ROOT / "site" / clip["src"]).is_file()


def test_card_intro_tts_manifest_maps_generated_sample() -> None:
    data_path = REPO_ROOT / "site" / "data" / "card_intro_tts.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))

    intro = data["byCardId"]["atlas01_r01_c01"]

    assert data["atlasSequenceStartCardNo"] == 53
    assert intro["cardNo"] == "53"
    assert intro["birdName"] == "얼룩부리논병아리"
    assert intro["birdNameEn"] == "Pied Billed Grebe"
    assert intro["src"] == "tts/card_intro/53_pied_billed_grebe.m4a"
    assert (REPO_ROOT / "site" / intro["src"]).is_file()
