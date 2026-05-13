from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


DEFAULT_INPUT = Path("src/Data/card_intro_tts_ko.csv")
DEFAULT_FINGERPRINTS = Path("site/data/card_fingerprints.json")
DEFAULT_OUTPUT_DIR = Path("site/tts/card_intro")
DEFAULT_MANIFEST = Path("site/data/card_intro_tts.json")
DEFAULT_API_BASE = "http://100.66.10.225:3000/tools/qwen3-tts"
DEFAULT_LANGUAGE = "korean"
DEFAULT_VOICE_TAG = "Jean"
DEFAULT_SEQUENCE_START_CARD_NO = 53

DISPLAY_NAME_ALIASES = {
    "Podilymbus podiceps": "Pied Billed Grebe",
}


@dataclass(frozen=True)
class TtsJob:
    card_no: str
    bird_name: str
    text: str
    voice_tag: str
    wav_path: Path
    m4a_path: Path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def normalize_name(value: str) -> str:
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    return slug or "card"


def audio_stem(card_no: str, bird_name: str) -> str:
    return f"{card_no}_{slugify(bird_name)}"


def selected_rows(
    rows: list[dict[str, str]],
    *,
    card_numbers: set[str],
    limit: int | None,
    approved_only: bool,
) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    for row in rows:
        card_no = str(row.get("card_no", "")).strip()
        if not card_no:
            continue
        if card_numbers and card_no not in card_numbers:
            continue
        if approved_only and str(row.get("review_status", "")).casefold() != "approved":
            continue
        if not str(row.get("tts_text", "")).strip():
            continue
        selected.append(row)
        if limit is not None and len(selected) >= limit:
            break
    return selected


def parse_card_range(value: str) -> list[str]:
    match = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", value or "")
    if not match:
        raise argparse.ArgumentTypeError("Expected range like 53-262")
    start = int(match.group(1))
    end = int(match.group(2))
    if end < start:
        raise argparse.ArgumentTypeError("Range end must be greater than or equal to start")
    return [str(card_no) for card_no in range(start, end + 1)]


def build_jobs(
    rows: list[dict[str, str]],
    *,
    output_dir: Path,
    default_voice_tag: str,
    override_voice_tag: str = "",
) -> list[TtsJob]:
    jobs: list[TtsJob] = []
    for row in rows:
        card_no = str(row["card_no"]).strip()
        bird_name = str(row.get("bird_name", "")).strip() or f"card_{card_no}"
        stem = audio_stem(card_no, bird_name)
        jobs.append(
            TtsJob(
                card_no=card_no,
                bird_name=bird_name,
                text=str(row.get("tts_text", "")).strip(),
                voice_tag=override_voice_tag or str(row.get("voice_tag", "")).strip() or default_voice_tag,
                wav_path=output_dir / f"{stem}.wav",
                m4a_path=output_dir / f"{stem}.m4a",
            )
        )
    return jobs


def _gradio_call(api_base: str, endpoint: str, data: list[Any], *, timeout_s: int) -> list[Any]:
    base = api_base.rstrip("/")
    call_url = f"{base}/gradio_api/call/{endpoint}"
    body = json.dumps({"data": data}, ensure_ascii=False).encode("utf-8")
    req = Request(call_url, data=body, method="POST", headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=timeout_s) as resp:
        result = json.loads(resp.read())
    event_id = result.get("event_id")
    if not event_id:
        raise RuntimeError(f"No Qwen3 event_id in response: {result}")

    sse_url = f"{call_url}/{event_id}"
    with urlopen(sse_url, timeout=timeout_s) as resp:
        current_event: str | None = None
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            if line.startswith("event:"):
                current_event = line[6:].strip()
                continue
            if not line.startswith("data:"):
                continue

            data_str = line[5:].strip()
            if current_event == "error":
                raise RuntimeError(f"Qwen3-TTS API error: {data_str}")
            if current_event == "complete":
                parsed = json.loads(data_str)
                if not isinstance(parsed, list):
                    raise RuntimeError(f"Unexpected Qwen3 result: {parsed}")
                return parsed

    raise RuntimeError(f"Qwen3-TTS call did not complete: endpoint={endpoint}")


def _extract_audio_path(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("path", "url", "name"):
            candidate = str(value.get(key) or "").strip()
            if candidate:
                return candidate
    if isinstance(value, list):
        for item in value:
            candidate = _extract_audio_path(item)
            if candidate:
                return candidate
    if isinstance(value, str):
        return value.strip()
    return ""


def _download_qwen_file(api_base: str, server_path: str, out_path: Path, *, timeout_s: int) -> Path:
    if server_path.startswith(("http://", "https://")):
        url = server_path
    elif server_path.startswith("/gradio_api/file="):
        url = f"{api_base.rstrip('/')}{server_path}"
    elif server_path.startswith("file="):
        url = f"{api_base.rstrip('/')}/gradio_api/{server_path}"
    else:
        url = f"{api_base.rstrip('/')}/gradio_api/file={server_path}"

    req = Request(url, method="GET")
    with urlopen(req, timeout=timeout_s) as resp:
        data = resp.read()
    if not data:
        raise RuntimeError(f"Empty Qwen3 audio download: {url}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return out_path


def ping_qwen3(api_base: str, *, timeout_s: int) -> int:
    url = f"{api_base.rstrip('/')}/config"
    req = Request(url, method="GET")
    with urlopen(req, timeout=timeout_s) as resp:
        return int(getattr(resp, "status", 200))


def qwen3_tts_to_wav(
    *,
    api_base: str,
    text: str,
    voice_tag: str,
    out_path: Path,
    language: str,
    max_tokens: int,
    temperature: float,
    top_p: float,
    top_k: int,
    timeout_s: int,
    retries: int,
) -> Path:
    last_error: Exception | None = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            result = _gradio_call(
                api_base,
                "generate_single_segment",
                [voice_tag, text, language, True, max_tokens, True, temperature, top_p, top_k],
                timeout_s=timeout_s,
            )
            if len(result) >= 2 and isinstance(result[1], str) and "error" in result[1].casefold():
                raise RuntimeError(result[1])
            audio_path = _extract_audio_path(result[0] if result else None)
            if not audio_path:
                raise RuntimeError(f"No audio path in Qwen3 response: {result}")
            return _download_qwen_file(api_base, audio_path, out_path, timeout_s=timeout_s)
        except (TimeoutError, URLError, ConnectionError) as error:
            last_error = error
            if attempt >= retries:
                break
            sleep_seconds = 1.5 * attempt
            print(f"[warn] Qwen3 request failed ({type(error).__name__}); retrying in {sleep_seconds:.1f}s")
            time.sleep(sleep_seconds)

    raise RuntimeError(f"Qwen3 generation failed after {retries} attempts: {last_error}") from last_error


def convert_wav_to_m4a(wav_path: Path, m4a_path: Path, *, ffmpeg: str, keep_wav: bool) -> Path:
    if not shutil.which(ffmpeg):
        raise RuntimeError(f"ffmpeg not found: {ffmpeg}")
    m4a_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(wav_path),
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        "-ar",
        "32000",
        "-ac",
        "1",
        str(m4a_path),
        "-loglevel",
        "error",
    ]
    subprocess.run(command, check=True)
    if not keep_wav:
        wav_path.unlink(missing_ok=True)
    return m4a_path


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
    source_path: Path,
    output_dir: Path,
    manifest_path: Path,
    fingerprints_path: Path,
    sequence_start_card_no: int,
) -> tuple[int, int]:
    by_card_no: dict[str, dict[str, object]] = {}
    rows_by_card_no = {str(row.get("card_no", "")).strip(): row for row in tts_rows if row.get("card_no")}
    rows_by_name = {normalize_name(str(row.get("bird_name", ""))): row for row in tts_rows if row.get("bird_name")}

    for card_no, row in rows_by_card_no.items():
        bird_name_en = str(row.get("bird_name", "")).strip() or f"card_{card_no}"
        bird_name_ko = str(row.get("bird_name_ko", "")).strip() or bird_name_en
        path = output_dir / f"{audio_stem(card_no, bird_name_en)}.m4a"
        if not path.is_file():
            continue
        by_card_no[card_no] = {
            "cardNo": card_no,
            "birdName": bird_name_ko,
            "birdNameEn": bird_name_en,
            "src": site_relative_src(path),
            "mimeType": mime_type(path),
            "reviewStatus": str(row.get("review_status", "")),
        }

    by_card_id: dict[str, dict[str, object]] = {}
    if fingerprints_path.is_file():
        fingerprints = json.loads(fingerprints_path.read_text(encoding="utf-8"))
        for index, card in enumerate(fingerprints.get("cards", [])):
            card_no = str(sequence_start_card_no + index)
            entry = by_card_no.get(card_no)
            mapping_source = "atlasSequence"
            if not entry:
                display_name = DISPLAY_NAME_ALIASES.get(str(card.get("displayName", "")).strip(), str(card.get("displayName", "")).strip())
                row = rows_by_name.get(normalize_name(display_name))
                if row:
                    entry = by_card_no.get(str(row.get("card_no", "")).strip())
                    mapping_source = "displayName"
            if entry:
                by_card_id[str(card["id"])] = {**entry, "mappingSource": mapping_source}

    payload = {
        "version": 1,
        "source": source_path.as_posix(),
        "audioRoot": "tts/card_intro",
        "atlasSequenceStartCardNo": sequence_start_card_no,
        "byCardNo": by_card_no,
        "byCardId": by_card_id,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(by_card_no), len(by_card_id)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Korean Wingspan card intro audio with Qwen3-TTS.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--fingerprints", type=Path, default=DEFAULT_FINGERPRINTS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--sequence-start-card-no", type=int, default=DEFAULT_SEQUENCE_START_CARD_NO)
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--language", default=DEFAULT_LANGUAGE)
    parser.add_argument("--voice-tag", default=DEFAULT_VOICE_TAG)
    parser.add_argument("--override-voice-tag", default="", help="Use this voice tag for all selected rows.")
    parser.add_argument("--card-no", action="append", default=[], help="Generate only this card number. Repeatable.")
    parser.add_argument("--card-range", action="append", default=[], help="Generate an inclusive card range, e.g. 53-262.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--approved-only", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--manifest-only", action="store_true")
    parser.add_argument("--ping-only", action="store_true", help="Check Qwen3 server connectivity and exit.")
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
    requested_card_numbers = {str(value).strip() for value in args.card_no if str(value).strip()}
    for card_range in args.card_range:
        requested_card_numbers.update(parse_card_range(card_range))

    selected = selected_rows(
        rows,
        card_numbers=requested_card_numbers,
        limit=args.limit,
        approved_only=args.approved_only,
    )
    jobs = build_jobs(
        selected,
        output_dir=args.output_dir,
        default_voice_tag=args.voice_tag,
        override_voice_tag=str(args.override_voice_tag).strip(),
    )

    if args.dry_run:
        print(f"Input rows: {len(rows)}")
        print(f"Selected jobs: {len(jobs)}")
        for job in jobs[:10]:
            print(f"{job.card_no}: {job.bird_name} -> {job.m4a_path}")
        return 0

    if not args.manifest_only:
        failures: list[tuple[TtsJob, Exception]] = []
        for index, job in enumerate(jobs, start=1):
            if args.skip_existing and job.m4a_path.is_file():
                print(f"[{index}/{len(jobs)}] skip existing {job.m4a_path}")
                continue
            print(f"[{index}/{len(jobs)}] {job.card_no} {job.bird_name}")
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
                print(f"[error] {job.card_no} {job.bird_name}: {type(error).__name__}: {error}")
                if not args.continue_on_error:
                    break

    card_no_count, card_id_count = build_manifest(
        tts_rows=rows,
        source_path=args.input,
        output_dir=args.output_dir,
        manifest_path=args.manifest,
        fingerprints_path=args.fingerprints,
        sequence_start_card_no=args.sequence_start_card_no,
    )
    print(f"Wrote manifest: {args.manifest} ({card_no_count} card_no, {card_id_count} card_id)")
    if not args.manifest_only and failures:
        print(f"Failed jobs: {len(failures)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
