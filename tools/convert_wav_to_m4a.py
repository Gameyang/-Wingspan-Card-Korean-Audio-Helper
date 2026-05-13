from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def find_wavs(audio_root: Path) -> list[Path]:
    return sorted(
        [path for path in audio_root.rglob("*.wav") if path.is_file()],
        key=lambda item: str(item).lower(),
    )


def needs_conversion(source: Path, destination: Path, force: bool) -> bool:
    if force:
        return True
    if not destination.exists() or destination.stat().st_size == 0:
        return True
    return destination.stat().st_mtime < source.stat().st_mtime


def convert_file(source: Path, destination: Path, bitrate: str, sample_rate: int | None) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_destination = destination.with_suffix(".tmp.m4a")
    if tmp_destination.exists():
        tmp_destination.unlink()

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-c:a",
        "aac",
        "-b:a",
        bitrate,
        "-movflags",
        "+faststart",
    ]
    if sample_rate:
        command.extend(["-ar", str(sample_rate)])
    command.append(str(tmp_destination))

    subprocess.run(command, check=True)
    tmp_destination.replace(destination)


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert WAV audio files to mobile-friendly M4A.")
    parser.add_argument("--audio-root", type=Path, default=Path("src/AudioClip"))
    parser.add_argument("--bitrate", default="64k")
    parser.add_argument("--sample-rate", type=int, default=44100)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--delete-source", action="store_true")
    args = parser.parse_args()

    audio_root = args.audio_root.resolve()
    if not audio_root.exists():
        raise SystemExit(f"Audio root does not exist: {audio_root}")

    wavs = find_wavs(audio_root)
    if args.limit is not None:
        wavs = wavs[: args.limit]
    converted = 0
    skipped = 0
    failed = 0

    for index, source in enumerate(wavs, start=1):
        destination = source.with_suffix(".m4a")
        if not needs_conversion(source, destination, args.force):
            skipped += 1
            continue

        print(f"[{index}/{len(wavs)}] {source.relative_to(audio_root)}", flush=True)
        try:
            convert_file(source, destination, args.bitrate, args.sample_rate)
            converted += 1
            if args.delete_source:
                source.unlink()
        except Exception as exc:
            failed += 1
            print(f"ERROR: {source}: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)

    print(f"Converted: {converted}")
    print(f"Skipped: {skipped}")
    print(f"Failed: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
