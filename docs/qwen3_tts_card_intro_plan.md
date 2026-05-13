# Qwen3 TTS Card Intro Plan

## Summary

Wingspan card scanning should play a Korean spoken card intro while using the existing bird call clips as quiet background audio. The source table remains `src/Data/card_intro_transcripts.csv`, and the generated Korean working table is `src/Data/card_intro_tts_ko.csv`.

The target unit is one Korean intro per `card_no`. The source CSV has multiple VO rows per card, so tooling selects one representative source row for review and TTS generation.

Card power narration is separate from intro narration. Power text is captured per card from the atlas images into `src/Data/card_ability_ocr.csv`, then deduplicated into `src/Data/card_ability_tts_ko.csv` so cards with the same power reuse one generated TTS file.

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
   - The `능력 설명` toggle appends the matched card's power narration after the intro.
   - When the matched card changes, the current TTS and bird background audio stop and the next card starts.

4. Build Korean ability TTS data from OCR/review rows:
   ```powershell
   python tools/build_card_ability_tts_ko.py --card-range 53-57
   python tools/build_card_ability_tts_ko.py --skip-ocr
   ```
   The OCR step supports Tesseract when installed, and falls back to Windows OCR on this machine. OCR rows should be reviewed because small Korean text on the atlas images can need correction.

5. Generate deduplicated ability audio:
   ```powershell
   python tools/generate_card_ability_tts.py --card-range 53-57
   python tools/generate_card_ability_tts.py --manifest-only
   ```
   Output audio is written to `site/tts/card_ability/`, and the browser manifest is written to `site/data/card_ability_tts.json`.

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

- `src/Data/card_ability_ocr.csv`
  - Card-level OCR/review table for the card power area.
  - `ability_ocr_text`: raw OCR result.
  - `ability_text_ko`: reviewed Korean power text used for narration.
  - `ability_id`: stable dedupe key. Matching powers share one `ability_id`.

- `src/Data/card_ability_tts_ko.csv`
  - Unique ability-level Korean TTS list.
  - `source_card_nos` and `source_card_ids` map each shared ability back to the cards that use it.

- `site/data/card_ability_tts.json`
  - `byAbilityId`: all generated ability audio keyed by dedupe id.
  - `byCardNo` and `byCardId`: card-to-ability audio mapping for browser playback.

- `tools/generate_card_ability_tts.py`
  - Uses the same Qwen3 endpoint and audio conversion path as intro generation.
  - Supports `--dry-run`, `--limit`, `--ability-id`, `--card-no`, `--card-range`, `--skip-existing`, and `--manifest-only`.

## Defaults

- Qwen3 API base: `http://100.66.10.225:3000/tools/qwen3-tts`
- Language: `korean`
- Voice selection: random per generated clip from `D:\Weeks\Qwen3-TTS\data\voices\ref\voices.json`
- Fixed voice override: pass `--override-voice-tag Jean` or another tag when a consistent voice is needed.
- Output format: M4A, AAC 64 kbps, 32 kHz mono
- Fingerprint mapping start: card no `53`, matching the current site audio manifest.

## Verification

- Run `python tools/build_card_intro_tts_ko.py --dry-run` to check representative card counts without writing files.
- Run `python tools/generate_card_intro_tts.py --dry-run --limit 3` to confirm Qwen3 jobs without generating audio.
- Run `python tools/generate_card_intro_tts.py --manifest-only` after audio exists to rebuild only `site/data/card_intro_tts.json`.
- Run `python tools/build_card_ability_tts_ko.py --skip-ocr --dry-run` to check deduplicated ability rows.
- Run `python tools/generate_card_ability_tts.py --dry-run --card-range 53-57` to confirm unique ability jobs.
- Run `pytest` to verify existing fingerprint and audio manifest behavior.

## Notes

The generated Korean table is a draft asset. It is intentionally separate from `card_intro_transcripts.csv` so source transcription metadata remains intact. Generated TTS files should only be distributed after the Qwen3 voice and service licensing terms are confirmed.
