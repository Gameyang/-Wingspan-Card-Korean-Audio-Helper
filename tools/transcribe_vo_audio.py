from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
from pathlib import Path


CSV_FIELDS = [
    "file_name",
    "card_no",
    "bird_name",
    "vo_id",
    "transcript",
    "duration_seconds",
    "detected_language",
    "language_probability",
    "error",
]

HASH_VO_RE = re.compile(r"_VO_.*#\d+\.wav$", re.IGNORECASE)
PL_VO_RE = re.compile(r"_VO_.*_PL\.wav$", re.IGNORECASE)
PARSE_RE = re.compile(r"^(?P<card_no>\d+)_(?P<bird>.+?)_+VO_(?P<vo_id>.+?)\.wav$", re.IGNORECASE)


def is_base_vo_file(path: Path) -> bool:
    name = path.name
    return (
        path.is_file()
        and path.suffix.lower() == ".wav"
        and "_VO_" in name
        and not PL_VO_RE.search(name)
        and not HASH_VO_RE.search(name)
    )


def is_vo_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == ".wav" and "_VO_" in path.name


def parse_file_name(path: Path) -> dict[str, str]:
    match = PARSE_RE.match(path.name)
    if not match:
        return {"card_no": "", "bird_name": "", "vo_id": ""}

    bird_name = re.sub(r"_+", " ", match.group("bird")).strip()
    return {
        "card_no": match.group("card_no"),
        "bird_name": bird_name,
        "vo_id": match.group("vo_id").strip(),
    }


def move_vo_files(audio_root: Path, vo_dir: Path, include_all_vo: bool) -> tuple[int, int]:
    vo_dir.mkdir(parents=True, exist_ok=True)
    moved = 0
    already_present = 0

    for source in sorted(audio_root.rglob("*.wav"), key=lambda item: item.name.lower()):
        if vo_dir in source.parents:
            continue

        if include_all_vo:
            should_move = is_vo_file(source)
        else:
            should_move = is_base_vo_file(source)

        if not should_move:
            continue

        destination = vo_dir / source.name
        if destination.exists():
            if destination.stat().st_size == source.stat().st_size:
                already_present += 1
                continue
            raise FileExistsError(f"Destination already exists with different size: {destination}")

        shutil.move(str(source), str(destination))
        moved += 1

    return moved, already_present


def successful_transcript_names(csv_path: Path) -> set[str]:
    if not csv_path.exists():
        return set()

    names = set()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("file_name") and row.get("transcript") and not row.get("error"):
                names.add(row["file_name"])
    return names


def delete_transcribed_wavs(vo_dir: Path, csv_path: Path) -> tuple[int, int]:
    vo_dir = vo_dir.resolve()
    successful = successful_transcript_names(csv_path)
    deleted = 0

    for wav_path in sorted(vo_dir.glob("*.wav"), key=lambda item: item.name.lower()):
        resolved = wav_path.resolve()
        if vo_dir not in resolved.parents:
            raise RuntimeError(f"Refusing to delete outside VO directory: {resolved}")
        if wav_path.name not in successful:
            continue

        wav_path.unlink()
        deleted += 1

    remaining = len(list(vo_dir.glob("*.wav")))
    return deleted, remaining


def existing_transcripts(csv_path: Path) -> set[str]:
    if not csv_path.exists():
        return set()

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return {row["file_name"] for row in reader if row.get("file_name")}


def append_row(csv_path: Path, row: dict[str, str]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not csv_path.exists() or csv_path.stat().st_size == 0

    with csv_path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)
        handle.flush()


def transcribe_files(
    vo_dir: Path,
    csv_path: Path,
    model_name: str,
    language: str,
    device: str,
    compute_type: str,
    beam_size: int,
    force: bool,
    limit: int | None,
) -> tuple[int, int]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: faster-whisper. Install it with "
            "`python -m pip install faster-whisper`."
        ) from exc

    if force and csv_path.exists():
        csv_path.unlink()

    done = existing_transcripts(csv_path)
    files = sorted(vo_dir.glob("*.wav"), key=lambda item: item.name.lower())
    if limit is not None:
        files = files[:limit]

    pending = [path for path in files if force or path.name not in done]
    skipped = len(files) - len(pending)
    if not pending:
        return 0, skipped

    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    processed = 0

    for index, audio_path in enumerate(pending, start=1):
        metadata = parse_file_name(audio_path)
        row = {
            "file_name": audio_path.name,
            "card_no": metadata["card_no"],
            "bird_name": metadata["bird_name"],
            "vo_id": metadata["vo_id"],
            "transcript": "",
            "duration_seconds": "",
            "detected_language": "",
            "language_probability": "",
            "error": "",
        }

        print(f"[{index}/{len(pending)}] {audio_path.name}", flush=True)
        try:
            segments, info = model.transcribe(
                str(audio_path),
                language=language,
                beam_size=beam_size,
                vad_filter=True,
                condition_on_previous_text=False,
                initial_prompt=(
                    f"Wingspan bird card narration about {metadata['bird_name']}."
                    if metadata["bird_name"]
                    else "Wingspan bird card narration."
                ),
            )
            row["transcript"] = " ".join(
                segment.text.strip() for segment in segments if segment.text.strip()
            ).strip()
            row["duration_seconds"] = f"{getattr(info, 'duration', 0.0):.3f}"
            row["detected_language"] = getattr(info, "language", "") or ""
            row["language_probability"] = f"{getattr(info, 'language_probability', 0.0):.6f}"
        except Exception as exc:  # Keep the batch moving and record failed files.
            row["error"] = f"{type(exc).__name__}: {exc}"

        append_row(csv_path, row)
        processed += 1

    return processed, skipped


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Move base Wingspan VO wav files and transcribe them to CSV."
    )
    parser.add_argument("--audio-root", type=Path, default=Path("src/AudioClip"))
    parser.add_argument("--vo-dir", type=Path)
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--model", default="small.en")
    parser.add_argument("--language", default="en")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--include-all-vo", action="store_true")
    parser.add_argument("--delete-transcribed-wavs", action="store_true")
    parser.add_argument("--skip-move", action="store_true")
    parser.add_argument("--skip-transcribe", action="store_true")
    args = parser.parse_args()

    audio_root = args.audio_root.resolve()
    vo_dir = (args.vo_dir or audio_root / "VO").resolve()
    csv_path = (args.csv or vo_dir / "vo_transcripts.csv").resolve()

    if not audio_root.exists():
        raise SystemExit(f"Audio root does not exist: {audio_root}")

    if not args.skip_move:
        moved, already_present = move_vo_files(audio_root, vo_dir, args.include_all_vo)
        file_kind = "VO" if args.include_all_vo else "base VO"
        print(f"Moved {moved} {file_kind} files to {vo_dir}")
        if already_present:
            print(f"Skipped {already_present} files already present in {vo_dir}")

    if not args.skip_transcribe:
        if not vo_dir.exists():
            raise SystemExit(f"VO directory does not exist: {vo_dir}")
        processed, skipped = transcribe_files(
            vo_dir=vo_dir,
            csv_path=csv_path,
            model_name=args.model,
            language=args.language,
            device=args.device,
            compute_type=args.compute_type,
            beam_size=args.beam_size,
            force=args.force,
            limit=args.limit,
        )
        print(f"Transcribed {processed} files into {csv_path}")
        if skipped:
            print(f"Skipped {skipped} files already present in {csv_path}")

    if args.delete_transcribed_wavs:
        deleted, remaining = delete_transcribed_wavs(vo_dir, csv_path)
        print(f"Deleted {deleted} successfully transcribed wav files from {vo_dir}")
        print(f"Remaining wav files in {vo_dir}: {remaining}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
