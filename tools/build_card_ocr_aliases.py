from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
from pathlib import Path


DEFAULT_AUDIO_MANIFEST = Path("site/data/audio_clips.json")
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
    taxonomy_csv: Path | None = None,
    match_threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> dict[str, object]:
    audio_manifest = json.loads(audio_manifest_path.read_text(encoding="utf-8"))
    taxonomy = read_taxonomy(taxonomy_csv)

    cards: list[dict[str, object]] = []
    by_card_id: dict[str, dict[str, object]] = {}
    weak_taxonomy_matches: list[dict[str, object]] = []

    for card_id, clips in audio_manifest["byCardId"].items():
        clip = representative_clip(clips)
        card_no = str(clip["cardNo"])
        bird_name = str(clip["birdName"])
        cleaned_name = clean_bird_name(bird_name)
        aliases: list[str] = []
        add_alias(aliases, bird_name)
        add_alias(aliases, cleaned_name)
        for alias in taxonomy_aliases_for_name(cleaned_name, taxonomy, match_threshold)[0]:
            add_alias(aliases, alias)
        for alias in MANUAL_ALIASES_BY_CARD_NO.get(card_no, []):
            add_alias(aliases, alias)

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
            "aliases": aliases,
            "normalizedAliases": [normalize(alias) for alias in aliases],
        }
        cards.append(entry)
        by_card_id[card_id] = entry

    payload = {
        "version": 1,
        "source": str(audio_manifest_path.as_posix()),
        "taxonomySource": taxonomy_csv.name if taxonomy_csv else None,
        "matchMethod": "latin-ocr-normalized-fuzzy",
        "cards": cards,
        "byCardId": by_card_id,
        "diagnostics": {
            "cardCount": len(cards),
            "weakTaxonomyMatches": weak_taxonomy_matches,
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Build browser OCR aliases for card identification.")
    parser.add_argument("--audio-manifest", type=Path, default=DEFAULT_AUDIO_MANIFEST)
    parser.add_argument("--taxonomy-csv", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--match-threshold", type=float, default=DEFAULT_MATCH_THRESHOLD)
    args = parser.parse_args()

    payload = build_alias_manifest(
        audio_manifest_path=args.audio_manifest,
        output_path=args.output,
        taxonomy_csv=args.taxonomy_csv,
        match_threshold=args.match_threshold,
    )
    print(f"Wrote {len(payload['cards'])} OCR alias mappings: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
