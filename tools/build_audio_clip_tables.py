from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path


INTRO_AUDIO_COLUMNS = [
    "bird_audio_bird_name",
    "bird_audio_clip_count",
    "bird_audio_clip_files",
    "bird_audio_main_files",
]

CLIP_FIELDS = [
    "card_no",
    "bird_name",
    "search_key",
    "audio_file",
    "audio_path",
    "clip_index",
    "clip_type",
    "is_main",
    "source_id",
    "file_size_bytes",
]

TRAILING_PATTERNS = [
    re.compile(
        r"^(?P<prefix>.+)_\s*(?P<clip>\d+)_main_(?P<kind>call|song)\s*_?\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?P<prefix>.+)_\s*(?P<clip>\d+)_(?P<kind>call|song)(?:_(?P<main>main))?\s*_?\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?P<prefix>.+)_(?P<kind>call|song)_\s*(?P<clip>\d+)\s*_?\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?P<prefix>.+)_(?P<kind>call|song)_\s*(?P<clip>\d+)(?:_(?P<main>main))?\s*_?\s*$",
        re.IGNORECASE,
    ),
]


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def normalize_search(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def clean_bird_name(parts: list[str]) -> str:
    value = " ".join(part.strip() for part in parts if part.strip())
    value = re.sub(r"\s+", " ", value).strip()
    return value.title()


def parse_clip(path: Path, audio_root: Path) -> dict[str, str]:
    stem = path.stem.strip()
    card_match = re.match(r"^(?P<card>\d+)_(?P<rest>.+)$", stem)
    if not card_match:
        raise ValueError(f"Cannot parse card number from {path.name}")

    card_no = card_match.group("card")
    rest = card_match.group("rest").strip()
    prefix = rest
    clip_index = ""
    clip_type = ""
    is_main = False

    for pattern in TRAILING_PATTERNS:
        match = pattern.match(rest)
        if match:
            prefix = match.group("prefix").strip(" _")
            clip_index = match.group("clip").strip()
            clip_type = match.group("kind").lower()
            is_main = bool(match.groupdict().get("main")) or "_main_" in rest.lower()
            break

    parts = [part.strip() for part in prefix.split("_") if part.strip()]
    source_id = ""
    if parts:
        last = parts[-1]
        if re.fullmatch(r"\d+", last) or re.fullmatch(r"XC\d+", last, re.IGNORECASE):
            source_id = last
            parts = parts[:-1]
        else:
            attached_source = re.match(r"^(?P<name>.*?[A-Za-z])(?P<source>\d+)$", last)
            if attached_source:
                source_id = attached_source.group("source")
                parts[-1] = attached_source.group("name")

    bird_name = clean_bird_name(parts)
    audio_path = "src/AudioClip/" + path.relative_to(audio_root).as_posix()

    return {
        "card_no": card_no,
        "bird_name": bird_name,
        "search_key": normalize_search(bird_name),
        "audio_file": path.name,
        "audio_path": audio_path,
        "clip_index": clip_index,
        "clip_type": clip_type,
        "is_main": "true" if is_main else "false",
        "source_id": source_id,
        "file_size_bytes": str(path.stat().st_size),
    }


def build_tables(root: Path) -> tuple[int, int, list[str]]:
    intro_path = root / "src" / "Data" / "card_intro_transcripts.csv"
    clip_path = root / "src" / "Data" / "bird_audio_clips.csv"
    audio_root = root / "src" / "AudioClip"

    intro_rows, intro_fields = read_csv(intro_path)
    clips = [parse_clip(path, audio_root) for path in sorted(audio_root.rglob("*.m4a"), key=lambda p: p.name.lower())]

    clips_by_card: dict[str, list[dict[str, str]]] = defaultdict(list)
    for clip in clips:
        clips_by_card[clip["card_no"]].append(clip)

    for row in intro_rows:
        card_clips = clips_by_card.get(row.get("card_no", ""), [])
        main_clips = [clip for clip in card_clips if clip["is_main"] == "true"]
        row["bird_audio_bird_name"] = card_clips[0]["bird_name"] if card_clips else ""
        row["bird_audio_clip_count"] = str(len(card_clips))
        row["bird_audio_clip_files"] = "|".join(clip["audio_path"] for clip in card_clips)
        row["bird_audio_main_files"] = "|".join(clip["audio_path"] for clip in main_clips)

    missing_cards = sorted(
        {row["card_no"] for row in intro_rows if row.get("card_no") and row["bird_audio_clip_count"] == "0"},
        key=lambda value: int(value),
    )

    intro_output_fields = list(intro_fields)
    for field in INTRO_AUDIO_COLUMNS:
        if field not in intro_output_fields:
            intro_output_fields.append(field)

    write_csv(intro_path, intro_rows, intro_output_fields)
    write_csv(clip_path, clips, CLIP_FIELDS)
    return len(intro_rows), len(clips), missing_cards


def main() -> int:
    parser = argparse.ArgumentParser(description="Match converted M4A bird audio clips to card tables.")
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()

    intro_count, clip_count, missing_cards = build_tables(args.root.resolve())
    print(f"Updated intro rows: {intro_count}")
    print(f"Audio clip rows: {clip_count}")
    if missing_cards:
        print("Cards without audio clips: " + ", ".join(missing_cards))
    return 0


if __name__ == "__main__":
    sys.exit(main())
