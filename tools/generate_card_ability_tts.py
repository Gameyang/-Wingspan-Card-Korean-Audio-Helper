from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from tools.generate_card_intro_tts import (
    DEFAULT_API_BASE,
    DEFAULT_LANGUAGE,
    DEFAULT_VOICE_TAG,
    DEFAULT_VOICES_JSON,
    VoiceRef,
    convert_wav_to_m4a,
    load_voice_refs,
    parse_card_range,
    ping_qwen3,
    qwen3_tts_to_wav,
    selected_voice_for_row,
)
from tools.build_card_ability_tts_ko import ability_id_for_text, tts_text_for_ability


DEFAULT_INPUT = Path("src/Data/card_ability_tts_ko.csv")
DEFAULT_CARD_MAP = Path("src/Data/card_ability_ocr.csv")
DEFAULT_OUTPUT_DIR = Path("site/tts/card_ability")
DEFAULT_MANIFEST = Path("site/data/card_ability_tts.json")


@dataclass(frozen=True)
class AbilityTtsJob:
    ability_id: str
    text: str
    voice_tag: str
    voice_id: str
    wav_path: Path
    m4a_path: Path


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    return slug or "ability"


def audio_stem(ability_id: str) -> str:
    return slugify(ability_id)


def selected_ability_ids(
    *,
    rows: list[dict[str, str]],
    mapping_rows: list[dict[str, str]],
    requested_ability_ids: set[str],
    requested_card_numbers: set[str],
) -> set[str]:
    selected = {ability_id for ability_id in requested_ability_ids if ability_id}
    if requested_card_numbers:
        for row in mapping_rows:
            card_no = normalize_spaces(row.get("card_no", ""))
            if card_no in requested_card_numbers:
                ability_id = ability_id_from_mapping_row(row)
                if ability_id:
                    selected.add(ability_id)
    if selected:
        return selected
    return {normalize_spaces(row.get("ability_id", "")) for row in rows if normalize_spaces(row.get("ability_id", ""))}


def selected_rows(
    rows: list[dict[str, str]],
    *,
    ability_ids: set[str],
    limit: int | None,
    approved_only: bool,
) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    for row in rows:
        ability_id = normalize_spaces(row.get("ability_id", ""))
        if not ability_id or ability_id not in ability_ids:
            continue
        if approved_only and normalize_spaces(row.get("review_status", "")).casefold() != "approved":
            continue
        if not normalize_spaces(row.get("tts_text", "")):
            continue
        selected.append(row)
        if limit is not None and len(selected) >= limit:
            break
    return selected


def build_jobs(
    rows: list[dict[str, str]],
    *,
    output_dir: Path,
    default_voice_tag: str,
    override_voice_tag: str = "",
    voice_refs: list[VoiceRef] | None = None,
    rng: random.Random | None = None,
) -> list[AbilityTtsJob]:
    jobs: list[AbilityTtsJob] = []
    voice_refs = voice_refs or []
    rng = rng or random.Random()
    for row in rows:
        ability_id = normalize_spaces(row["ability_id"])
        stem = audio_stem(ability_id)
        voice = selected_voice_for_row(
            row,
            default_voice_tag=default_voice_tag,
            override_voice_tag=override_voice_tag,
            voice_refs=voice_refs,
            rng=rng,
        )
        jobs.append(
            AbilityTtsJob(
                ability_id=ability_id,
                text=normalize_spaces(row.get("tts_text", "")),
                voice_tag=voice.tag,
                voice_id=voice.voice_id,
                wav_path=output_dir / f"{stem}.wav",
                m4a_path=output_dir / f"{stem}.m4a",
            )
        )
    return jobs


def mime_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "audio/mp4"


def site_relative_src(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path("site").resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def build_manifest(
    *,
    tts_rows: list[dict[str, str]],
    mapping_rows: list[dict[str, str]],
    source_path: Path,
    card_map_path: Path,
    output_dir: Path,
    manifest_path: Path,
    voice_tags_by_ability_id: dict[str, str] | None = None,
) -> tuple[int, int, int]:
    tts_by_id = {
        normalize_spaces(row.get("ability_id", "")): row
        for row in tts_rows
        if normalize_spaces(row.get("ability_id", ""))
    }
    by_ability_id: dict[str, dict[str, object]] = {}
    for ability_id, row in tts_by_id.items():
        path = output_dir / f"{audio_stem(ability_id)}.m4a"
        if not path.is_file():
            continue
        by_ability_id[ability_id] = {
            "abilityId": ability_id,
            "abilityTextKo": normalize_spaces(row.get("ability_text_ko", "")),
            "src": site_relative_src(path),
            "mimeType": mime_type(path),
            "reviewStatus": normalize_spaces(row.get("review_status", "")),
            "voiceTag": (voice_tags_by_ability_id or {}).get(ability_id, normalize_spaces(row.get("voice_tag", ""))),
            "sourceCardNos": split_pipe(row.get("source_card_nos", "")),
            "sourceCardIds": split_pipe(row.get("source_card_ids", "")),
        }

    by_card_no: dict[str, dict[str, object]] = {}
    by_card_id: dict[str, dict[str, object]] = {}
    for row in mapping_rows:
        ability_id = ability_id_from_mapping_row(row)
        entry = by_ability_id.get(ability_id)
        if not entry:
            continue
        card_no = normalize_spaces(row.get("card_no", ""))
        card_id = normalize_spaces(row.get("card_id", ""))
        card_entry = {
            **entry,
            "cardNo": card_no,
            "cardId": card_id,
            "birdName": normalize_spaces(row.get("bird_name_ko", "")) or normalize_spaces(row.get("bird_name", "")),
            "birdNameEn": normalize_spaces(row.get("bird_name", "")),
        }
        if card_no:
            by_card_no[card_no] = card_entry
        if card_id:
            by_card_id[card_id] = card_entry

    payload = {
        "version": 1,
        "source": source_path.as_posix(),
        "cardMapSource": card_map_path.as_posix(),
        "audioRoot": "tts/card_ability",
        "byAbilityId": by_ability_id,
        "byCardNo": by_card_no,
        "byCardId": by_card_id,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(by_ability_id), len(by_card_no), len(by_card_id)


def split_pipe(value: str) -> list[str]:
    return [part for part in (normalize_spaces(item) for item in str(value or "").split("|")) if part]


def ability_id_from_mapping_row(row: dict[str, str]) -> str:
    tts_text = tts_text_for_ability(normalize_spaces(row.get("ability_text_ko", "")) or normalize_spaces(row.get("ability_ocr_text", "")))
    return ability_id_for_text(tts_text) if tts_text else ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate deduplicated Korean Wingspan ability audio with Qwen3-TTS.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--card-map", type=Path, default=DEFAULT_CARD_MAP)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--language", default=DEFAULT_LANGUAGE)
    parser.add_argument("--voice-tag", default=DEFAULT_VOICE_TAG)
    parser.add_argument("--override-voice-tag", default="")
    parser.add_argument("--voices-json", type=Path, default=DEFAULT_VOICES_JSON, help="Qwen3 reference voices JSON used for per-clip random voice selection.")
    parser.add_argument("--random-voice", action=argparse.BooleanOptionalAction, default=True, help="Randomly choose one voice per generated clip from --voices-json.")
    parser.add_argument("--voice-seed", type=int, default=None, help="Optional seed for reproducible random voice selection.")
    parser.add_argument("--include-xvec-only-voices", action="store_true")
    parser.add_argument("--ability-id", action="append", default=[])
    parser.add_argument("--card-no", action="append", default=[])
    parser.add_argument("--card-range", action="append", default=[])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--approved-only", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--manifest-only", action="store_true")
    parser.add_argument("--ping-only", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--keep-wav", action="store_true")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--timeout-s", type=int, default=180)
    parser.add_argument("--retries", type=int, default=2)
    args = parser.parse_args()

    if args.ping_only:
        try:
            status = ping_qwen3(args.api_base, timeout_s=args.timeout_s)
            print(f"Qwen3 server OK: {args.api_base} status={status}")
            return 0
        except Exception as error:
            print(f"Qwen3 server unavailable: {args.api_base} ({type(error).__name__}: {error})")
            return 1

    rows = read_csv(args.input)
    mapping_rows = read_csv(args.card_map)
    requested_card_numbers = {str(value).strip() for value in args.card_no if str(value).strip()}
    for card_range in args.card_range:
        requested_card_numbers.update(parse_card_range(card_range))
    requested_ability_ids = {normalize_spaces(value) for value in args.ability_id if normalize_spaces(value)}
    ability_ids = selected_ability_ids(
        rows=rows,
        mapping_rows=mapping_rows,
        requested_ability_ids=requested_ability_ids,
        requested_card_numbers=requested_card_numbers,
    )
    selected = selected_rows(
        rows,
        ability_ids=ability_ids,
        limit=args.limit,
        approved_only=args.approved_only,
    )
    voice_refs = []
    if args.random_voice and not normalize_spaces(args.override_voice_tag):
        voice_refs = load_voice_refs(
            args.voices_json,
            prompt_lang=args.language,
            include_xvec_only=args.include_xvec_only_voices,
        )
        if not voice_refs:
            print(f"[warn] No random voices loaded from {args.voices_json}; falling back to row/default voice tags.")
    rng = random.Random(args.voice_seed)
    jobs = build_jobs(
        selected,
        output_dir=args.output_dir,
        default_voice_tag=args.voice_tag,
        override_voice_tag=normalize_spaces(args.override_voice_tag),
        voice_refs=voice_refs,
        rng=rng,
    )

    if args.dry_run:
        print(f"Input rows: {len(rows)}")
        print(f"Selected unique ability jobs: {len(jobs)}")
        for job in jobs[:10]:
            print(f"{job.ability_id} voice={job.voice_tag} -> {job.m4a_path}")
        return 0

    voice_tags_by_ability_id = {} if args.manifest_only else {job.ability_id: job.voice_tag for job in jobs}
    failures: list[tuple[AbilityTtsJob, Exception]] = []
    if not args.manifest_only:
        for index, job in enumerate(jobs, start=1):
            if args.skip_existing and job.m4a_path.is_file():
                print(f"[{index}/{len(jobs)}] skip existing {job.m4a_path} voice={job.voice_tag}")
                continue
            print(f"[{index}/{len(jobs)}] {job.ability_id} voice={job.voice_tag}")
            try:
                qwen3_tts_to_wav(
                    api_base=args.api_base,
                    text=job.text,
                    voice_tag=job.voice_tag,
                    out_path=job.wav_path,
                    language=args.language,
                    max_tokens=args.max_tokens,
                    temperature=args.temperature,
                    top_p=args.top_p,
                    top_k=args.top_k,
                    timeout_s=args.timeout_s,
                    retries=args.retries,
                )
                convert_wav_to_m4a(job.wav_path, job.m4a_path, ffmpeg=args.ffmpeg, keep_wav=args.keep_wav)
            except Exception as error:
                failures.append((job, error))
                print(f"[error] {job.ability_id}: {type(error).__name__}: {error}")
                if not args.continue_on_error:
                    break

    ability_count, card_no_count, card_id_count = build_manifest(
        tts_rows=rows,
        mapping_rows=mapping_rows,
        source_path=args.input,
        card_map_path=args.card_map,
        output_dir=args.output_dir,
        manifest_path=args.manifest,
        voice_tags_by_ability_id=voice_tags_by_ability_id,
    )
    print(f"Wrote manifest: {args.manifest} ({ability_count} ability, {card_no_count} card_no, {card_id_count} card_id)")
    if not args.manifest_only and failures:
        print(f"Failed jobs: {len(failures)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
