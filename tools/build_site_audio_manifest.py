from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import defaultdict
from pathlib import Path


DEFAULT_FINGERPRINTS = Path("site/data/card_fingerprints.json")
DEFAULT_AUDIO_CSV = Path("src/Data/bird_audio_clips.csv")
DEFAULT_SITE_AUDIO_DIR = Path("site/audio")
DEFAULT_OUTPUT = Path("site/data/audio_clips.json")

DISPLAY_NAME_ALIASES = {
    "Podilymbus podiceps": "Pied Billed Grebe",
}


def normalize_name(value: str) -> str:
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def read_audio_rows(csv_path: Path) -> dict[str, list[dict[str, str]]]:
    rows_by_name: dict[str, list[dict[str, str]]] = defaultdict(list)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows_by_name[normalize_name(row["bird_name"])].append(row)
    return rows_by_name


def build_manifest(
    fingerprints_path: Path,
    audio_csv_path: Path,
    site_audio_dir: Path,
    output_path: Path,
) -> tuple[int, int, Path]:
    fingerprints = json.loads(fingerprints_path.read_text(encoding="utf-8"))
    audio_rows = read_audio_rows(audio_csv_path)
    site_audio_dir.mkdir(parents=True, exist_ok=True)

    by_card_id: dict[str, list[dict[str, object]]] = {}
    copied_files: set[Path] = set()

    for card in fingerprints["cards"]:
        display_name = str(card.get("displayName", "")).strip()
        bird_name = DISPLAY_NAME_ALIASES.get(display_name, display_name)
        rows = audio_rows.get(normalize_name(bird_name), [])
        if not rows:
            continue

        clips: list[dict[str, object]] = []
        for row in rows:
            source = Path(row["audio_path"])
            if not source.exists():
                continue
            destination = site_audio_dir / source.name
            if destination not in copied_files:
                shutil.copy2(source, destination)
                copied_files.add(destination)

            clips.append(
                {
                    "birdName": row["bird_name"],
                    "cardNo": row["card_no"],
                    "src": f"audio/{destination.name}",
                    "clipType": row["clip_type"],
                    "isMain": row["is_main"].casefold() == "true",
                    "sourceId": row["source_id"],
                }
            )

        if clips:
            by_card_id[str(card["id"])] = clips

    payload = {
        "version": 1,
        "source": str(audio_csv_path.as_posix()),
        "byCardId": by_card_id,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(by_card_id), len(copied_files), output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build site audio manifest from bird audio CSV.")
    parser.add_argument("--fingerprints", type=Path, default=DEFAULT_FINGERPRINTS)
    parser.add_argument("--audio-csv", type=Path, default=DEFAULT_AUDIO_CSV)
    parser.add_argument("--site-audio-dir", type=Path, default=DEFAULT_SITE_AUDIO_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    mapped, copied, output = build_manifest(
        fingerprints_path=args.fingerprints,
        audio_csv_path=args.audio_csv,
        site_audio_dir=args.site_audio_dir,
        output_path=args.output,
    )
    print(f"Wrote {mapped} card audio mappings and copied {copied} files: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
