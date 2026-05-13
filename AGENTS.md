# Agent Rules

## Wingspan Korean Symbol Terms

Use the Korean official rulebook screenshots in `src/RuleBook/` as the terminology source when cleaning OCR, translating card powers, or preparing TTS strings.

### General TTS Rules

- Do not send icon tags such as `[egg]`, `[card]`, `[seed]`, or `[cavity]` to Qwen3 TTS.
- Convert every icon/tag into spoken Korean before writing `tts_text` or `ability_tts_text`.
- Keep `ability_text_ko` and `tts_text` in natural Korean sentence form. Do not leave English card-rule placeholders in the spoken text.
- For ability audio, start directly with the ability text. Do not add a preface such as `능력 설명입니다.`
- Prefer official Korean board-game terms over literal English translations.
- If OCR text is noisy, correct terms using the rulebook vocabulary below before deduping ability text.

### Core Game Tokens

- `[egg]`: `알`
- `[card]`: `카드`
- `birdfeeder`: `공급처`
- `cache`: `저장`
- `tuck`: `끼워넣기`; in a sentence, use `이 새 아래에 카드 1장을 끼워넣습니다.`
- A tucked card scores as `이 새 아래에 끼워넣은 카드 1장당 1점입니다.`

### Food Icons

Source: `src/RuleBook/먹이종류.png`

- `[invertebrate]`: `무척추동물 먹이`
- `[seed]`: `씨앗 먹이`
- `[fish]`: `물고기 먹이`
- `[fruit]`: `과일 먹이`
- `[rodent]`: `설치류 먹이`
- Wild food icon or slash food choice: `아무 먹이` or `먹이 5종류 중 아무거나`
- No food cost: `먹이 비용 없음`; in a sentence, use `먹이 비용이 없습니다.`

When the Korean sentence already clearly talks about food, the word `먹이` may be omitted after the specific food name if it sounds more natural. For example, `씨앗 먹이 1개` and `씨앗 1개` are both acceptable, but be consistent within one file.

### Nest Icons

Source: `src/RuleBook/동지종류.png`

- `[platform]`: `접시형 둥지`
- `[cavity]`: `구멍형 둥지`
- `[bowl]`: `사발형 둥지`
- `[ground]`: `바닥형 둥지`
- Star/wild nest icon: `별 모양 둥지`

The star/wild nest counts as every nest type for goals, bonus cards, and powers. When explaining it, use: `별 모양 둥지는 모든 종류의 둥지에 해당합니다.`

OCR cleanup notes:

- Correct `동지`, `등지`, or `구명형` to `둥지` and `구멍형` when the context is nest type.
- Prefer `구멍형 둥지 새`, `바닥형 둥지 새`, `접시형 둥지 새`, and `사발형 둥지 새` in card ability narration.

### Predator Symbol

Source: `src/RuleBook/포식자.png`

- Predator symbol: `포식자`
- In explanatory narration, use `이 새는 포식자입니다.`

Do not keep broken OCR text such as `[포식자!` in source or TTS fields.

### Flocking Symbol

Source: `src/RuleBook/새때.png`

- Flocking symbol: `새떼`
- Use `새떼를 형성하는 새` when describing the trait.
- For effects that place cards under a bird, use `끼워넣다`, not a direct English borrowing.

OCR cleanup notes:

- Correct `새때` to `새떼`.
- Correct noisy OCR such as `카드 일에`, `일에 길린`, or `다던 카드` to the intended wording: `카드 밑에`, `밑에 깔린`, `다른 카드`.

### Ability Text Examples

- `Lay 1 [egg] on any bird.` -> `원하는 새 1마리에 알 1개를 낳습니다.`
- `All players lay 1 [egg] on any 1 [cavity] bird.` -> `모든 플레이어는 구멍형 둥지 새 1마리에 알 1개를 낳습니다.`
- `Gain 1 [seed] from the birdfeeder.` -> `공급처에서 씨앗 먹이 1개를 가져옵니다.`
- `Tuck 1 [card] from your hand behind this bird.` -> `손에 있는 카드 1장을 이 새 아래에 끼워넣습니다.`
