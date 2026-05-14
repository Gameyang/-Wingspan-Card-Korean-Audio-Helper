# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Wingspan Korean Audio Card Helper — a mobile-friendly static web app that scans Wingspan board game cards through the device camera, identifies them, and plays pre-generated Korean narration audio. The deployable app lives in [site/](site/) and is published via GitHub Pages by [.github/workflows/pages.yml](.github/workflows/pages.yml). The repo root README describes an aspirational MVP layout (cards.json + audio/); the actual implementation has moved past that and lives entirely under `site/`.

Do not trust the file structure shown in [README.md](README.md) — refer to `site/` and the data pipeline below.

## Two-Layer Architecture

The codebase has two distinct halves that meet at JSON manifests in [site/data/](site/data/):

### 1. Browser app — `site/` (vanilla JS, no build step)

[site/app.js](site/app.js) is a single-file frontend with a **shutter-driven (snapshot) flow**, not continuous live-OCR. The runtime modes are `loading → live → capturing → review`, controlled by `data-mode` on the `.scanner` root. The pipeline:

1. **Live mode** — stream the rear camera into a `<video>` element with overlay guides for four card regions: `title`, `score`, `wing`, `ability` (see `OCR_SIGNAL_REGIONS` and `CARD_SIZE = 630x970`, the canonical card pixel size used everywhere). No OCR runs here — the guides are purely for aiming.
2. **Shutter** — user taps `#shutterButton`. `freezeCaptureFromVideo` snapshots the current frame into an off-screen `captureCanvas` at video native resolution, paints it into `#snapshot` for the review UI, and freezes the card-guide rect in source-video coordinates (`frozenGuideRect`). Mode switches to `review` and CSS hides the live video.
3. **Review mode pipeline** — all signals are computed once on the frozen frame:
   - **Visual fingerprint (dhash)** — `computeArtDhashHex` extracts the art region (`ART_REGION = 45,145,565,515` inside the 630×970 card), grayscale + autocontrast on the full-res crop, downsample to 17×16, compute 256-bit dhash, hex-encode. Compared via Hamming distance against all 210 entries in [site/data/card_fingerprints.json](site/data/card_fingerprints.json). `visualScore = max(0, 100 − hamming × 100 / 96)`.
   - **OCR** — `drawCardSignalsForOcr(captureCanvas, frozenGuideRect)` lays out the four card regions onto `ocrCanvas` (title/score/wing also rendered at ±8° rotations), preprocesses to binary, and runs Tesseract.js (`kor+eng`).
   - **Combined ranking** — `rankCandidates` scores every card on `nameScore`, `numericMatches` (score/cm boosts), `abilityScore`, and `visualScore`; final `rankScore = nameScore + numericBoost + abilityScore + visualScore × VISUAL_RANK_WEIGHT`.
   - **Confidence** — `matchConfidence` accepts on any of: strong name (≥85), name≥70 + 1 numeric, name≥60 + 2 numerics, `visualScore ≥ VISUAL_STRONG_SCORE (75)`, or name≥60 + `visualScore ≥ VISUAL_MEDIUM_SCORE (55)`. Plus a 5-point gap over the second candidate.
4. **Candidate panel is always shown after capture** (top `MAX_CANDIDATE_SUGGESTIONS = 8`). If confidence passes, audio auto-plays after `AUTO_SELECT_DELAY_MS`; otherwise the user picks from the panel.
5. **Audio** — Korean intro TTS in the foreground + a random bird call clip as quiet background (`BIRD_BG_VOLUME = 0.24`). The "능력 설명" toggle appends the ability TTS afterward.
6. **Retake** — `#retakeButton` calls `handleRetake`, which stops audio, clears state, and returns to `live` mode.

Card identity is keyed by `cardId` (e.g. `atlas01_r01_c01`, grid position in the source atlas) and by `cardNo` (in-game card number, starting at 53 for the first atlas card — see `DEFAULT_SEQUENCE_START_CARD_NO`).

**dhash port note** — the JS implementation in `computeArtDhashHex` follows the Python algorithm in [tools/build_card_fingerprints.py](tools/build_card_fingerprints.py): grayscale (ITU-R 601-2) + autocontrast on the full-res art crop *before* downsampling, then dhash bits packed MSB-first into 4-bit nibbles. Canvas downsampling is bilinear (not Lanczos like PIL), so hashes from a real camera shot vs. the atlas screenshot of the same card will have non-zero Hamming distance — typically 20–60 bits for matches, which is why `VISUAL_SCORE_DIVISOR = 96` is tuned for tolerance rather than exact equality.

### 2. Asset pipeline — `tools/` (Python)

Source-of-truth data lives in [src/Data/](src/Data/) CSVs and [src/AtlasImage/](src/AtlasImage/) JPGs (the atlas JPGs are gitignored — three 6300×6790 sheets of 10×7=70 cards each, 210 cards total). The `tools/` scripts transform these into the JSON + audio under `site/`:

| Tool | Reads | Writes |
|---|---|---|
| `build_card_fingerprints.py` | `src/Images/` atlas JPGs | `site/data/card_fingerprints.json` (dhash-17x16 of art region) |
| `card_atlas_ocr.py` | atlas JPGs | crops + OCR review CSV (Tesseract; falls back to Windows OCR via `windows_ocr_image.ps1`) |
| `build_audio_clip_tables.py`, `transcribe_vo_audio.py` | raw bird recordings | `src/Data/bird_audio_clips.csv`, `card_intro_transcripts.csv` |
| `build_card_intro_tts_ko.py` | `card_intro_transcripts.csv` | `src/Data/card_intro_tts_ko.csv` (Korean draft) |
| `generate_card_intro_tts.py` | `card_intro_tts_ko.csv` | `site/tts/card_intro/*.m4a` + `site/data/card_intro_tts.json` |
| `build_card_ability_tts_ko.py` | `card_ability_ocr.csv` | `src/Data/card_ability_tts_ko.csv` (deduped by `ability_id`) |
| `generate_card_ability_tts.py` | `card_ability_tts_ko.csv` | `site/tts/card_ability/*.m4a` + `site/data/card_ability_tts.json` |
| `build_site_audio_manifest.py` | `bird_audio_clips.csv` + fingerprints | `site/data/audio_clips.json` (+ copies M4A clips to `site/audio/`) |
| `build_card_ocr_aliases.py` | audio manifest + intro/ability CSVs | `site/data/card_ocr_aliases.json` |
| `convert_wav_to_m4a.py` | WAVs | M4A (AAC 64 kbps, 32 kHz mono — the canonical format) |

TTS generation hits an external Qwen3 endpoint (default `http://100.66.10.225:3000/tools/qwen3-tts`). Most generators support `--dry-run`, `--limit`, `--card-no`, `--card-range`, `--skip-existing`, and `--manifest-only` (rebuild JSON without regenerating audio). See [docs/qwen3_tts_card_intro_plan.md](docs/qwen3_tts_card_intro_plan.md) for the full pipeline narrative.

## Common Commands

```powershell
# Install Python deps
pip install -r requirements.txt

# Run tests
pytest                                              # all tests
pytest tests/test_visual_fingerprints.py            # single file
pytest tests/test_card_atlas_ocr.py::test_matching_ranks_latin_card_name  # single test

# Serve the site locally (camera works only on localhost or HTTPS)
python -m http.server 8000 --directory site
# → http://localhost:8000

# Rebuild a manifest without regenerating audio (fast)
python tools/generate_card_intro_tts.py --manifest-only
python tools/generate_card_ability_tts.py --manifest-only

# Rebuild OCR alias index after editing src/Data CSVs
python tools/build_card_ocr_aliases.py
```

Atlas-dependent tools and tests (`test_card_atlas_ocr.py`, `build_card_fingerprints.py`) need `src/Images/*.jpg` present locally; they `pytest.skip` or error if missing because the atlases are gitignored for copyright reasons.

## Korean Terminology Rules — Critical

Any change to TTS text (`tts_text`, `ability_text_ko`, `ability_tts_text` columns in `src/Data/*.csv`) **must follow** [AGENTS.md](AGENTS.md). Summary of the non-negotiable rules:

- **Never** leave icon tags like `[egg]`, `[seed]`, `[cavity]`, `[invertebrate]` in TTS text — convert to spoken Korean (`알`, `씨앗 먹이`, `구멍형 둥지`, `무척추동물 먹이`, etc.) before sending to Qwen3.
- Ability narration starts directly with the ability text — **no** `능력 설명입니다.` preface.
- Use the official Korean rulebook terms in [src/RuleBook/](src/RuleBook/) (gitignored screenshots — `먹이종류`, `동지종류`, `새때`, `포식자`) as the canonical glossary. Common OCR fixes: `동지`/`등지` → `둥지`, `구명형` → `구멍형`, `새때` → `새떼`, `카드 일에` → `카드 밑에`.
- `tuck` is `끼워넣기` (the phrase, not a direct borrowing); `birdfeeder` is `공급처`; `cache` is `저장`.

Full term table and example translations are in AGENTS.md — consult it before editing any Korean text field.

## Deployment Note

[.github/workflows/pages.yml](.github/workflows/pages.yml) deploys `site/` to GitHub Pages on push to `main`. The workflow's "Check static test page" step is the de facto smoke test — it asserts the four manifest JSONs and at least one M4A under `site/audio/` are present. If you remove or rename any of those files the deploy will fail before publishing.
