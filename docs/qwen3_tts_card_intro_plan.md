# Qwen3 TTS Card Intro Plan

## Summary

Wingspan card scanning should play a Korean spoken card intro while using the existing bird call clips as quiet background audio. The source table remains `src/Data/card_intro_transcripts.csv`, and the generated Korean working table is `src/Data/card_intro_tts_ko.csv`.

The target unit is one Korean intro per `card_no`. The source CSV has multiple VO rows per card, so tooling selects one representative source row for review and TTS generation.

## Data Flow

1. Build Korean TTS draft data:
   ```powershell
   python tools/build_card_intro_tts_ko.py
   ```
   This reads `src/Data/card_intro_transcripts.csv` and writes `src/Data/card_intro_tts_ko.csv`.

2. Generate Qwen3 audio:
   ```powershell
   python tools/generate_card_intro_tts.py --limit 3
   python tools/generate_card_intro_tts.py --card-range 53-262 --skip-existing
   python tools/generate_card_intro_tts.py --skip-existing
   ```
   Output audio is written to `site/tts/card_intro/`, and the browser manifest is written to `site/data/card_intro_tts.json`.

3. Browser playback:
   - Korean TTS intro plays in the foreground.
   - One random bird clip for the matched card plays quietly as background audio.
   - When the matched card changes, the current TTS and bird background audio stop and the next card starts.

## Files and Interfaces

- `src/Data/card_intro_tts_ko.csv`
  - `card_no`: source card number.
  - `bird_name`: English bird/card name from the source data, kept for traceability and stable filenames.
  - `bird_name_ko`: Korean display/narration name.
  - `tts_text`: Korean narration text sent to Qwen3. Inline bracket tags are not used because this Qwen3 endpoint does not parse them reliably.
  - `voice_tag`: Qwen3 voice library tag.
  - `review_status`: defaults to `draft`; edit to `approved` if a manual review workflow is needed later.
  - `source_file_name`, `source_vo_id`, `source_transcript`: traceability to the selected source row.

- `site/data/card_intro_tts.json`
  - `byCardNo`: all generated card intro audio keyed by `card_no`.
  - `byCardId`: generated intro audio mapped to current visual fingerprint card ids.
  - `audioRoot`: relative browser root for generated intro audio.
  - `birdName`: Korean display name; `birdNameEn`: English source name.

- `tools/generate_card_intro_tts.py`
  - Defaults to Qwen3 tag mode via `generate_single_segment`.
  - Supports `--dry-run`, `--limit`, `--card-no`, `--card-range`, `--skip-existing`, `--manifest-only`, `--api-base`, `--voice-tag`, and generation parameter overrides.

## Defaults

- Qwen3 API base: `http://100.66.10.225:3000/tools/qwen3-tts`
- Language: `korean`
- Voice tag: `Jean`
- Output format: M4A, AAC 64 kbps, 32 kHz mono
- Fingerprint mapping start: card no `53`, matching the current site audio manifest.

## Verification

- Run `python tools/build_card_intro_tts_ko.py --dry-run` to check representative card counts without writing files.
- Run `python tools/generate_card_intro_tts.py --dry-run --limit 3` to confirm Qwen3 jobs without generating audio.
- Run `python tools/generate_card_intro_tts.py --manifest-only` after audio exists to rebuild only `site/data/card_intro_tts.json`.
- Run `pytest` to verify existing fingerprint and audio manifest behavior.

## Notes

The generated Korean table is a draft asset. It is intentionally separate from `card_intro_transcripts.csv` so source transcription metadata remains intact. Generated TTS files should only be distributed after the Qwen3 voice and service licensing terms are confirmed.
