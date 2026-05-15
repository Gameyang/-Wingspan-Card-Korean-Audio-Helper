from __future__ import annotations

import csv
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_first_visual_fingerprint_entry_is_present() -> None:
    data_path = REPO_ROOT / "site" / "data" / "card_fingerprints.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))

    first = data["cards"][0]
    assert len(data["cards"]) == 210
    assert data["version"] == 2
    assert data["algorithm"] == "dhash-17x16-grayscale-art-region-camera-variants"
    assert data["diagnostics"]["validVisualReferenceCount"] == 170
    assert data["diagnostics"]["invalidVisualReferenceCount"] == 40
    assert first["id"] == "atlas01_r01_c01"
    assert first["displayName"] == "Podilymbus podiceps"
    assert len(first["hash"]) == 64
    assert len(first["hashes"]) >= 10
    assert first["visualReferenceValid"] is True


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
    assert data["diagnostics"]["numericSignalCount"] == 210
    assert first["birdName"] == "Pied Billed Grebe"
    assert first["birdNameKo"] == "\uc5bc\ub8e9\ubd80\ub9ac\ub17c\ubcd1\uc544\ub9ac"
    assert "\uc5bc\ub8e9\ubd80\ub9ac\ub17c\ubcd1\uc544\ub9ac" in first["koreanAliases"]
    assert first["numericSignals"] == {"pointValue": "0", "wingspanCm": "41"}
    assert "Podilymbus podiceps" in first["aliases"]
    assert "podilymbuspodiceps" in first["normalizedAliases"]
    assert last["birdName"] == "Abbotts Booby"
    assert last["numericSignals"] == {"pointValue": "5", "wingspanCm": "190"}
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


def test_card_ability_tts_manifest_maps_ocr_rows() -> None:
    data_path = REPO_ROOT / "site" / "data" / "card_ability_tts.json"
    tts_path = REPO_ROOT / "src" / "Data" / "card_ability_tts_ko.csv"
    ocr_path = REPO_ROOT / "src" / "Data" / "card_ability_ocr.csv"
    data = json.loads(data_path.read_text(encoding="utf-8"))
    tts_rows = list(csv.DictReader(tts_path.open(encoding="utf-8-sig")))
    ocr_rows = list(csv.DictReader(ocr_path.open(encoding="utf-8-sig")))
    mapped_ocr_rows = [row for row in ocr_rows if row["ability_text_ko"].strip()]

    intro = data["byCardId"]["atlas01_r01_c01"]

    assert len(data["byAbilityId"]) == len(tts_rows)
    assert len(data["byCardNo"]) == len(mapped_ocr_rows)
    assert len(data["byCardId"]) == len(mapped_ocr_rows)
    assert set(data["byCardNo"]) == {row["card_no"] for row in mapped_ocr_rows}
    assert set(data["byCardId"]) == {row["card_id"] for row in mapped_ocr_rows}
    assert intro["cardNo"] == "53"
    assert intro["birdName"] == "얼룩부리논병아리"
    assert intro["reviewStatus"] == "translated_draft"
    assert intro["voiceTag"]
    for row in tts_rows:
        assert row["tts_text"]
        assert not row["tts_text"].startswith("능력 설명")
        assert "[" not in row["tts_text"]
        assert "]" not in row["tts_text"]
        assert "卜" not in row["tts_text"]
        assert "鬱" not in row["tts_text"]
    for entry in data["byAbilityId"].values():
        assert entry["voiceTag"]
        assert (REPO_ROOT / "site" / entry["src"]).is_file()
