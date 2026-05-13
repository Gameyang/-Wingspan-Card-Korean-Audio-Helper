from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
from pathlib import Path


DEFAULT_AUDIO_MANIFEST = Path("site/data/audio_clips.json")
DEFAULT_INTRO_TTS = Path("src/Data/card_intro_tts_ko.csv")
DEFAULT_ABILITY_OCR = Path("src/Data/card_ability_ocr.csv")
DEFAULT_NUMERIC_SIGNALS = Path("src/Data/card_numeric_signals.csv")
DEFAULT_OUTPUT = Path("site/data/card_ocr_aliases.json")
DEFAULT_MATCH_THRESHOLD = 0.88


MANUAL_ALIASES_BY_CARD_NO = {
    "55": ["Western Meadowlark", "Sturnella neglecta"],
    "91": ["Northern Harrier", "Circus hudsonius"],
    "109": ["Barn Owl", "Western Barn Owl", "Tyto alba"],
    "165": ["House Wren", "Northern House Wren", "Troglodytes aedon"],
    "180": ["Painted Whitestart", "Painted Redstart", "Myioborus pictus"],
    "183": ["Griffon Vulture", "Eurasian Griffon", "Gyps fulvus"],
    "186": ["Eurasian Nutcracker", "Northern Nutcracker", "Nucifraga caryocatactes"],
    "193": ["Black Throated Diver", "Black-throated Diver", "Arctic Loon", "Gavia arctica"],
    "196": ["Common Little Bittern", "Little Bittern", "Ixobrychus minutus", "Botaurus minutus"],
    "200": ["Grey Heron", "Gray Heron", "Ardea cinerea"],
    "201": ["Common Cuckoo", "Cuculus canorus"],
    "214": ["Bullfinch", "Eurasian Bullfinch", "Pyrrhula pyrrhula"],
    "219": ["Black Woodpecker", "Dryocopus martius"],
    "224": ["Common Blackbird", "Eurasian Blackbird", "Turdus merula"],
    "228": ["Corsican Nuthatch", "Sitta whiteheadi"],
    "235": ["Common Moorhen", "Eurasian Moorhen", "Gallinula chloropus"],
    "240": ["Northern Goshawk", "Eurasian Goshawk", "Accipiter gentilis", "Astur gentilis"],
    "241": ["Eastern Imperial Eagle", "Imperial Eagle", "Aquila heliaca"],
    "244": ["Common Buzzard", "Buteo buteo"],
    "251": ["Common Starling", "European Starling", "Sturnus vulgaris"],
    "252": ["Common Swift", "Apus apus"],
    "259": ["Greylag Goose", "Graylag Goose", "Anser anser"],
    "262": ["Abbotts Booby", "Abbott's Booby", "Papasula abbotti"],
}


SOURCE_FRAGMENT_RE = re.compile(r"\b(?:XC|XV)\s*\d*\w*\b|\b\d+\s*(?:XC|XV)\b", re.IGNORECASE)
TERMINAL_SOURCE_RE = re.compile(r"\bTJ\b", re.IGNORECASE)
TOKEN_RE = re.compile(r"[0-9A-Za-z\u3131-\u318e\uac00-\ud7a3]+")
ABILITY_STOPWORDS = {
    "1개",
    "1마리",
    "2장",
    "가능",
    "그렇게",
    "능력",
    "당신",
    "때",
    "모든",
    "버립니다",
    "설명입니다",
    "손에",
    "수",
    "있는",
    "있습니다",
    "장을",
    "추가로",
    "카드",
    "합니다",
}


def normalize(value: str) -> str:
    return "".join(ch for ch in value.casefold().replace("&", "and") if ch.isalnum())


def clean_bird_name(value: str) -> str:
    cleaned = SOURCE_FRAGMENT_RE.sub(" ", value.replace("_", " "))
    cleaned = TERMINAL_SOURCE_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned.endswith("larkr"):
        cleaned = cleaned[:-1]
    return cleaned


def add_alias(aliases: list[str], value: str) -> None:
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        return
    normalized = normalize(value)
    if not normalized:
        return
    if all(normalize(existing) != normalized for existing in aliases):
        aliases.append(value)


def read_csv_rows(path: Path | None) -> list[dict[str, str]]:
    if not path or not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_existing_aliases(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(card["id"]): [str(alias) for alias in card.get("aliases", [])]
        for card in data.get("cards", [])
    }


def korean_names_by_card_no(path: Path | None) -> dict[str, str]:
    names: dict[str, str] = {}
    for row in read_csv_rows(path):
        card_no = str(row.get("card_no", "")).strip()
        bird_name_ko = str(row.get("bird_name_ko", "")).strip()
        if card_no and bird_name_ko and card_no not in names:
            names[card_no] = bird_name_ko
    return names


def ability_keywords(text: str, limit: int = 8) -> list[str]:
    keywords: list[str] = []
    for token in TOKEN_RE.findall(text):
        token = token.strip()
        if len(token) < 2 or token in ABILITY_STOPWORDS:
            continue
        if token.isdigit():
            continue
        if all(normalize(existing) != normalize(token) for existing in keywords):
            keywords.append(token)
        if len(keywords) >= limit:
            break
    return keywords


def ability_keywords_by_card_no(path: Path | None) -> dict[str, list[str]]:
    by_card_no: dict[str, list[str]] = {}
    for row in read_csv_rows(path):
        card_no = str(row.get("card_no", "")).strip()
        text = str(row.get("ability_text_ko") or row.get("ability_ocr_text") or "").strip()
        if card_no and text:
            by_card_no[card_no] = ability_keywords(text)
    return by_card_no


def numeric_signals_by_card_no(path: Path | None) -> dict[str, dict[str, str]]:
    signals: dict[str, dict[str, str]] = {}
    for row in read_csv_rows(path):
        card_no = str(row.get("card_no", "")).strip()
        if not card_no:
            continue
        point_value = str(row.get("point_value") or row.get("score") or "").strip()
        wingspan_cm = str(row.get("wingspan_cm") or row.get("wing_cm") or "").strip()
        signals[card_no] = {
            "pointValue": re.sub(r"\D+", "", point_value),
            "wingspanCm": re.sub(r"\D+", "", wingspan_cm),
        }
    return signals


def read_taxonomy(taxonomy_csv: Path | None) -> list[dict[str, str]]:
    if not taxonomy_csv:
        return []
    with taxonomy_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = []
        for row in csv.DictReader(handle):
            if row.get("CATEGORY") == "species":
                rows.append(
                    {
                        "common": row["PRIMARY_COM_NAME"],
                        "scientific": row["SCI_NAME"],
                        "normalized": normalize(row["PRIMARY_COM_NAME"]),
                    }
                )
        return rows


def taxonomy_aliases_for_name(
    bird_name: str,
    taxonomy: list[dict[str, str]],
    threshold: float,
) -> tuple[list[str], float | None]:
    if not taxonomy:
        return [], None

    normalized = normalize(clean_bird_name(bird_name))
    exact = next((row for row in taxonomy if row["normalized"] == normalized), None)
    if exact:
        return [exact["common"], exact["scientific"]], 1.0

    best = max(
        taxonomy,
        key=lambda row: difflib.SequenceMatcher(None, normalized, row["normalized"]).ratio(),
    )
    score = difflib.SequenceMatcher(None, normalized, best["normalized"]).ratio()
    if score < threshold:
        return [], score
    return [best["common"], best["scientific"]], score


def representative_clip(clips: list[dict[str, object]]) -> dict[str, object]:
    if not clips:
        raise ValueError("card has no audio clips")
    return clips[0]


def build_alias_manifest(
    audio_manifest_path: Path,
    output_path: Path,
    intro_tts_path: Path | None = DEFAULT_INTRO_TTS,
    ability_ocr_path: Path | None = DEFAULT_ABILITY_OCR,
    numeric_signals_path: Path | None = DEFAULT_NUMERIC_SIGNALS,
    taxonomy_csv: Path | None = None,
    match_threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> dict[str, object]:
    audio_manifest = json.loads(audio_manifest_path.read_text(encoding="utf-8"))
    taxonomy = read_taxonomy(taxonomy_csv)
    existing_aliases = read_existing_aliases(output_path)
    korean_names = korean_names_by_card_no(intro_tts_path)
    ability_keywords_by_no = ability_keywords_by_card_no(ability_ocr_path)
    numeric_signals_by_no = numeric_signals_by_card_no(numeric_signals_path)

    cards: list[dict[str, object]] = []
    by_card_id: dict[str, dict[str, object]] = {}
    weak_taxonomy_matches: list[dict[str, object]] = []
    korean_alias_count = 0
    numeric_signal_count = 0
    ability_keyword_card_count = 0

    for card_id, clips in audio_manifest["byCardId"].items():
        clip = representative_clip(clips)
        card_no = str(clip["cardNo"])
        bird_name = str(clip["birdName"])
        cleaned_name = clean_bird_name(bird_name)
        bird_name_ko = korean_names.get(card_no, "")
        aliases: list[str] = []
        add_alias(aliases, bird_name)
        add_alias(aliases, cleaned_name)
        for alias in taxonomy_aliases_for_name(cleaned_name, taxonomy, match_threshold)[0]:
            add_alias(aliases, alias)
        for alias in MANUAL_ALIASES_BY_CARD_NO.get(card_no, []):
            add_alias(aliases, alias)
        for alias in existing_aliases.get(card_id, []):
            add_alias(aliases, alias)

        korean_aliases: list[str] = []
        add_alias(korean_aliases, bird_name_ko)
        if korean_aliases:
            korean_alias_count += 1

        numeric_signals = numeric_signals_by_no.get(card_no, {"pointValue": "", "wingspanCm": ""})
        if numeric_signals.get("pointValue") or numeric_signals.get("wingspanCm"):
            numeric_signal_count += 1

        card_ability_keywords = ability_keywords_by_no.get(card_no, [])
        if card_ability_keywords:
            ability_keyword_card_count += 1

        taxonomy_score = taxonomy_aliases_for_name(cleaned_name, taxonomy, match_threshold)[1]
        if taxonomy_score is not None and taxonomy_score < 1 and card_no not in MANUAL_ALIASES_BY_CARD_NO:
            weak_taxonomy_matches.append(
                {
                    "cardNo": card_no,
                    "birdName": bird_name,
                    "score": round(taxonomy_score, 3),
                }
            )

        entry = {
            "id": card_id,
            "cardNo": card_no,
            "birdName": cleaned_name,
            "birdNameKo": bird_name_ko,
            "aliases": aliases,
            "normalizedAliases": [normalize(alias) for alias in aliases],
            "koreanAliases": korean_aliases,
            "normalizedKoreanAliases": [normalize(alias) for alias in korean_aliases],
            "numericSignals": numeric_signals,
            "abilityKeywords": card_ability_keywords,
        }
        cards.append(entry)
        by_card_id[card_id] = entry

    payload = {
        "version": 2,
        "source": str(audio_manifest_path.as_posix()),
        "koreanNameSource": str(intro_tts_path.as_posix())
        if intro_tts_path and intro_tts_path.exists()
        else None,
        "abilityKeywordSource": str(ability_ocr_path.as_posix())
        if ability_ocr_path and ability_ocr_path.exists()
        else None,
        "numericSignalSource": str(numeric_signals_path.as_posix())
        if numeric_signals_path and numeric_signals_path.exists()
        else None,
        "taxonomySource": taxonomy_csv.name if taxonomy_csv else None,
        "matchMethod": "multi-signal-kor-eng-ocr",
        "cards": cards,
        "byCardId": by_card_id,
        "diagnostics": {
            "cardCount": len(cards),
            "koreanAliasCount": korean_alias_count,
            "numericSignalCount": numeric_signal_count,
            "abilityKeywordCardCount": ability_keyword_card_count,
            "weakTaxonomyMatches": weak_taxonomy_matches,
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Build browser OCR aliases for card identification.")
    parser.add_argument("--audio-manifest", type=Path, default=DEFAULT_AUDIO_MANIFEST)
    parser.add_argument("--intro-tts-csv", type=Path, default=DEFAULT_INTRO_TTS)
    parser.add_argument("--ability-ocr-csv", type=Path, default=DEFAULT_ABILITY_OCR)
    parser.add_argument("--numeric-signals-csv", type=Path, default=DEFAULT_NUMERIC_SIGNALS)
    parser.add_argument("--taxonomy-csv", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--match-threshold", type=float, default=DEFAULT_MATCH_THRESHOLD)
    args = parser.parse_args()

    payload = build_alias_manifest(
        audio_manifest_path=args.audio_manifest,
        output_path=args.output,
        intro_tts_path=args.intro_tts_csv,
        ability_ocr_path=args.ability_ocr_csv,
        numeric_signals_path=args.numeric_signals_csv,
        taxonomy_csv=args.taxonomy_csv,
        match_threshold=args.match_threshold,
    )
    print(f"Wrote {len(payload['cards'])} OCR alias mappings: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
