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


def test_ocr_alias_manifest_maps_scientific_names() -> None:
    data_path = REPO_ROOT / "site" / "data" / "card_ocr_aliases.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))

    first = data["byCardId"]["atlas01_r01_c01"]
    last = data["byCardId"]["atlas03_r07_c10"]
    black_woodpecker = data["byCardId"]["atlas03_r03_c07"]

    assert data["version"] == 2
    assert data["matchMethod"] == "multi-signal-kor-eng-ocr"
    assert len(data["cards"]) == 210
    assert first["birdName"] == "Pied Billed Grebe"
    assert first["birdNameKo"] == "\uc5bc\ub8e9\ubd80\ub9ac\ub17c\ubcd1\uc544\ub9ac"
    assert "\uc5bc\ub8e9\ubd80\ub9ac\ub17c\ubcd1\uc544\ub9ac" in first["koreanAliases"]
    assert first["numericSignals"] == {"pointValue": "", "wingspanCm": ""}
    assert "Podilymbus podiceps" in first["aliases"]
    assert "podilymbuspodiceps" in first["normalizedAliases"]
    assert last["birdName"] == "Abbotts Booby"
    assert "Papasula abbotti" in last["aliases"]
    assert "Dryocopus martius" in black_woodpecker["aliases"]
    assert all("Bonelli" not in alias for alias in black_woodpecker["aliases"])


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


def test_card_ability_tts_manifest_deduplicates_shared_power() -> None:
    data_path = REPO_ROOT / "site" / "data" / "card_ability_tts.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))

    grasshopper = data["byCardId"]["atlas01_r01_c04"]
    chipping = data["byCardId"]["atlas01_r01_c05"]

    assert len(data["byAbilityId"]) == 4
    assert len(data["byCardNo"]) == 5
    assert grasshopper["abilityId"] == chipping["abilityId"]
    assert grasshopper["src"] == chipping["src"]
    assert grasshopper["birdName"] == "메뚜기참새"
    assert chipping["birdName"] == "칩핑참새"
    assert (REPO_ROOT / "site" / grasshopper["src"]).is_file()
