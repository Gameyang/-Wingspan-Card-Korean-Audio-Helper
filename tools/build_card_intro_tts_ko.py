from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path


DEFAULT_INPUT = Path("src/Data/card_intro_transcripts.csv")
DEFAULT_OUTPUT = Path("src/Data/card_intro_tts_ko.csv")
DEFAULT_VOICE_TAG = "Jean"

OUTPUT_FIELDS = [
    "card_no",
    "bird_name",
    "bird_name_ko",
    "tts_text",
    "voice_tag",
    "review_status",
    "source_file_name",
    "source_vo_id",
    "source_transcript",
    "source_score",
]

SPAM_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"like,\s*share,\s*and\s*subscribe",
        r"comments?\s+below",
        r"great\s+day",
        r"who\s+are\s+you",
        r"do\s+you\s+have\s+a\s+question",
        r"first\s+time\s+i'?ve\s+ever\s+seen",
    ]
]

CATEGORY_RULES: list[tuple[tuple[str, ...], str]] = [
    (
        ("owl",),
        "밤에 활동하는 맹금류로, 조용히 날아 먹이를 찾는 습성이 두드러집니다.",
    ),
    (
        ("hawk", "eagle", "falcon", "kite", "harrier", "osprey", "vulture", "condor"),
        "날카로운 시야와 강한 날개로 하늘을 누비는 맹금류입니다.",
    ),
    (
        (
            "duck",
            "goose",
            "swan",
            "merganser",
            "goldeneye",
            "scaup",
            "mallard",
            "canvasback",
            "teal",
            "wigeon",
            "pintail",
            "shoveler",
        ),
        "물가에서 생활하며 헤엄과 잠수를 활용해 먹이를 찾습니다.",
    ),
    (
        ("heron", "egret", "ibis", "stork", "bittern", "crane", "rail", "coot", "gallinule"),
        "습지와 얕은 물가에서 긴 다리와 부리를 활용해 먹이를 찾습니다.",
    ),
    (
        ("woodpecker", "sapsucker", "flicker"),
        "나무줄기를 타고 오르며 부리로 두드려 곤충이나 수액을 찾습니다.",
    ),
    (
        ("hummingbird",),
        "공중에 정지하듯 날며 꽃의 꿀을 빠는 작은 새입니다.",
    ),
    (
        ("swallow", "swift", "martin", "nighthawk"),
        "하늘을 빠르게 날며 날아다니는 곤충을 잡아먹습니다.",
    ),
    (
        ("gull", "tern", "skimmer", "puffin", "auklet", "pelican", "cormorant", "booby", "frigatebird", "albatross"),
        "바다와 호수 주변에서 생활하며 물고기와 작은 수생 동물을 노립니다.",
    ),
    (
        ("kingfisher",),
        "물가에서 기다리다가 빠르게 뛰어들어 물고기를 잡는 새입니다.",
    ),
    (
        ("flycatcher", "phoebe", "kingbird"),
        "나뭇가지에서 기다리다가 날아오르는 곤충을 재빠르게 낚아챕니다.",
    ),
    (
        ("crow", "raven", "jay", "magpie", "nutcracker"),
        "영리하고 적응력이 뛰어나며 다양한 먹이를 활용하는 새입니다.",
    ),
    (
        ("pigeon", "dove"),
        "부드러운 울음소리와 씨앗을 먹는 습성이 잘 알려진 새입니다.",
    ),
    (
        ("quail", "pheasant", "grouse", "turkey", "chicken", "partridge", "ptarmigan", "junglefowl"),
        "주로 땅 위에서 생활하며 풀숲과 덤불 사이를 빠르게 오갑니다.",
    ),
    (
        ("plover", "sandpiper", "curlew", "turnstone", "willet", "snipe", "dowitcher", "godwit", "yellowlegs", "woodcock", "avocet", "stilt", "oystercatcher"),
        "해안과 습지 가장자리에서 긴 부리로 작은 먹이를 찾아냅니다.",
    ),
    (
        ("parrot", "parakeet", "macaw", "cockatoo"),
        "강한 부리와 사회적인 행동이 특징인 지능적인 새입니다.",
    ),
    (
        (
            "sparrow",
            "warbler",
            "vireo",
            "wren",
            "finch",
            "bunting",
            "grosbeak",
            "tanager",
            "cardinal",
            "oriole",
            "blackbird",
            "thrush",
            "robin",
            "bluebird",
            "meadowlark",
            "cowbird",
            "starling",
            "mockingbird",
            "catbird",
            "pipit",
            "lark",
            "chat",
        ),
        "작은 몸집과 뚜렷한 울음소리로 숲과 초원에서 존재감을 드러냅니다.",
    ),
]

NAME_FIXES = {
    "Western Meadowlarkr": "Western Meadowlark",
}

KOREAN_NAME_OVERRIDES = {
    "Wild Turkey": "들칠면조",
    "Pied Billed Grebe": "얼룩부리논병아리",
    "Pileated Woodpecker": "도가머리딱따구리",
    "Great Crested Grebe": "뿔논병아리",
    "Little Grebe": "논병아리",
    "Great Egret": "대백로",
    "Little Egret": "쇠백로",
    "Snowy Egret": "눈백로",
    "Cattle Egret": "황로",
    "Great Blue Heron": "큰푸른왜가리",
    "Grey Heron": "왜가리",
    "Purple Heron": "붉은왜가리",
    "Black Stork": "먹황새",
    "White Stork": "황새",
    "Mandarin Duck": "원앙",
    "Mallard": "청둥오리",
    "Common Teal": "쇠오리",
    "Smew": "흰비오리",
    "Canada Goose": "캐나다기러기",
    "Trumpeter Swan": "나팔고니",
    "Whooping Crane": "아메리카흰두루미",
    "Sandhill Crane": "캐나다두루미",
    "Common Raven": "큰까마귀",
    "American Crow": "아메리카까마귀",
    "Blue Jay": "푸른어치",
    "Eurasian Jay": "어치",
    "Common Myna": "구관조",
    "Rock Pigeon": "바위비둘기",
    "Spotted Dove": "점박이비둘기",
    "Zebra Dove": "얼룩말비둘기",
    "Bald Eagle": "흰머리수리",
    "Golden Eagle": "검독수리",
    "Philippine Eagle": "필리핀수리",
    "Brahminy Kite": "흰머리솔개",
    "Turkey Vulture": "칠면조독수리",
    "California Condor": "캘리포니아콘도르",
    "Barn Owl": "가면올빼미",
    "Snowy Owl": "흰올빼미",
    "Little Owl": "금눈쇠올빼미",
    "Oriental Bay Owl": "밤색가면올빼미",
    "Eurasian Eagle Owl": "수리부엉이",
    "Forest Owlet": "숲올빼미",
    "Barred Owl": "줄무늬올빼미",
    "Great Horned Owl": "아메리카수리부엉이",
    "Common Kingfisher": "물총새",
    "White Throated Kingfisher": "흰목물총새",
    "Stork Billed Kingfisher": "황새부리물총새",
    "Rose Ringed Parakeet": "목도리앵무",
    "Asian Koel": "검은뻐꾸기",
    "Green Pheasant": "꿩",
    "Golden Pheasant": "황금꿩",
    "Red Junglefowl": "적색야계",
}

WORD_KO = {
    "acorn": "도토리",
    "american": "아메리카",
    "anna": "안나",
    "annas": "안나",
    "asian": "아시아",
    "atlantic": "대서양",
    "baird": "베어드",
    "bairds": "베어드",
    "bald": "흰머리",
    "barrow": "배로",
    "barrows": "배로",
    "bearded": "수염",
    "bell": "벨",
    "bells": "벨",
    "belted": "띠",
    "bewick": "뷰익",
    "bewicks": "뷰익",
    "black": "검은",
    "blue": "푸른",
    "breasted": "가슴",
    "brewer": "브루어",
    "brewers": "브루어",
    "broad": "넓은",
    "bronzed": "청동",
    "brown": "갈색",
    "burrowing": "굴파는",
    "california": "캘리포니아",
    "canada": "캐나다",
    "carolina": "캐롤라이나",
    "cassin": "캐신",
    "cassins": "캐신",
    "cerulean": "하늘빛",
    "chestnut": "밤색",
    "chihuahuan": "치와와",
    "chipping": "칩핑",
    "clark": "클라크",
    "clarks": "클라크",
    "common": "일반",
    "cooper": "쿠퍼",
    "coopers": "쿠퍼",
    "crested": "볏",
    "dark": "검은",
    "desert": "사막",
    "double": "두겹",
    "downy": "솜털",
    "eastern": "동부",
    "eurasian": "유라시아",
    "fire": "불꽃",
    "forster": "포스터",
    "forsters": "포스터",
    "franklin": "프랭클린",
    "franklins": "프랭클린",
    "golden": "금빛",
    "grasshopper": "메뚜기",
    "gray": "회색",
    "great": "큰",
    "greater": "큰",
    "green": "초록",
    "headed": "머리",
    "hermit": "은둔",
    "hooded": "두건",
    "horned": "뿔",
    "house": "집",
    "inca": "잉카",
    "indigo": "남색",
    "juniper": "향나무",
    "killdeer": "킬디어",
    "lazuli": "라줄리",
    "lesser": "작은",
    "lincoln": "링컨",
    "lincolns": "링컨",
    "little": "작은",
    "loggerhead": "큰머리",
    "mountain": "산",
    "mourning": "애도",
    "northern": "북부",
    "orange": "주황",
    "painted": "채색",
    "philippine": "필리핀",
    "pileated": "도가머리",
    "pine": "소나무",
    "prothonotary": "프로토노터리",
    "purple": "보라",
    "pygmy": "꼬마",
    "red": "붉은",
    "ring": "고리",
    "ringed": "고리",
    "rock": "바위",
    "rose": "장밋빛",
    "ruby": "루비",
    "ruddy": "붉은빛",
    "rufous": "적갈색",
    "sandhill": "모래언덕",
    "savannah": "사바나",
    "scissor": "가위",
    "scissor tailed": "가위꼬리",
    "small": "작은",
    "snowy": "흰",
    "song": "노래",
    "spotted": "점박이",
    "steller": "스텔러",
    "stellers": "스텔러",
    "swainson": "스웨인슨",
    "swainsons": "스웨인슨",
    "tufted": "볏",
    "violet": "보라",
    "western": "서부",
    "white": "흰",
    "wild": "들",
    "wilson": "윌슨",
    "wilsons": "윌슨",
    "winged": "날개",
    "yellow": "노란",
}

GROUP_KO = {
    "auklet": "바다오리",
    "avadavat": "아바다바트",
    "avocet": "장다리물떼새",
    "bittern": "해오라기",
    "blackbird": "검은새",
    "bluebird": "파랑새",
    "booby": "부비",
    "brambling": "되새",
    "bulbul": "직박구리",
    "bunting": "멧새",
    "cardinal": "홍관조",
    "chat": "챗",
    "chickadee": "박새",
    "condor": "콘도르",
    "coot": "물닭",
    "cormorant": "가마우지",
    "cowbird": "찌르레기",
    "crane": "두루미",
    "crow": "까마귀",
    "cuckoo": "뻐꾸기",
    "dipper": "물까마귀",
    "dove": "비둘기",
    "drongo": "바람까마귀",
    "duck": "오리",
    "eagle": "수리",
    "egret": "백로",
    "falcon": "매",
    "finch": "되새",
    "flicker": "딱따구리",
    "flycatcher": "딱새",
    "frogmouth": "개구리입쏙독새",
    "gallinule": "물닭",
    "gnatcatcher": "모기잡이새",
    "goldeneye": "흰죽지오리",
    "goose": "기러기",
    "grackle": "검정새",
    "grebe": "논병아리",
    "grosbeak": "콩새",
    "grouse": "들꿩",
    "gull": "갈매기",
    "harrier": "개구리매",
    "hawk": "매",
    "heron": "왜가리",
    "hornbill": "코뿔새",
    "hummingbird": "벌새",
    "iora": "아이오라",
    "ibis": "따오기",
    "jay": "어치",
    "junglefowl": "야계",
    "kestrel": "황조롱이",
    "kingbird": "킹버드",
    "kingfisher": "물총새",
    "kite": "솔개",
    "koel": "코엘",
    "lapwing": "댕기물떼새",
    "lark": "종다리",
    "longspur": "긴발톱멧새",
    "loon": "아비",
    "magpie": "까치",
    "martin": "제비",
    "meadowlark": "종다리",
    "merganser": "비오리",
    "minivet": "할미새사촌",
    "mockingbird": "흉내지빠귀",
    "myna": "구관조",
    "nighthawk": "쏙독새",
    "nutcracker": "잣까마귀",
    "nuthatch": "동고비",
    "oriole": "꾀꼬리",
    "osprey": "물수리",
    "owlet": "올빼미",
    "owl": "올빼미",
    "oystercatcher": "검은머리물떼새",
    "parakeet": "앵무",
    "parrot": "앵무",
    "pelican": "펠리컨",
    "pheasant": "꿩",
    "phoebe": "피비새",
    "pigeon": "비둘기",
    "pipit": "밭종다리",
    "plover": "물떼새",
    "puffin": "퍼핀",
    "quail": "메추라기",
    "rail": "뜸부기",
    "raven": "큰까마귀",
    "redling": "레들링",
    "redstart": "딱새",
    "roadrunner": "로드러너",
    "robin": "로빈",
    "sanderling": "세가락도요",
    "sandpiper": "도요새",
    "sapsucker": "딱따구리",
    "scaup": "검은머리흰죽지",
    "serin": "방울새",
    "shelduck": "혹부리오리",
    "shoveler": "넓적부리",
    "shrike": "때까치",
    "skimmer": "가위부리",
    "snipe": "꺅도요",
    "sparrow": "참새",
    "spoonbill": "저어새",
    "starling": "찌르레기",
    "stilt": "장다리물떼새",
    "stork": "황새",
    "swallow": "제비",
    "swan": "고니",
    "swift": "칼새",
    "tanager": "풍금조",
    "tailorbird": "재봉새",
    "teal": "쇠오리",
    "tern": "제비갈매기",
    "thrasher": "흉내지빠귀",
    "thrush": "지빠귀",
    "titmouse": "박새",
    "towhee": "토히",
    "tragopan": "비단꿩",
    "turnstone": "꼬까도요",
    "turkey": "칠면조",
    "vireo": "비레오",
    "vulture": "독수리",
    "warbler": "워블러",
    "waxwing": "여새",
    "whistling": "휘파람",
    "willet": "윌렛",
    "woodcock": "멧도요",
    "woodpecker": "딱따구리",
    "wren": "굴뚝새",
    "yellowlegs": "노랑발도요",
    "yellowthroat": "노란목솔새",
}

PHONETIC_WORDS = {
    "albedo": "알베도",
    "amber": "앰버",
    "anhinga": "아닝가",
    "barbara": "바바라",
    "bobolink": "보보링크",
    "brant": "브란트",
    "bushtit": "부시팃",
    "canvasback": "캔버스백",
    "chuck": "척",
    "cuckoo": "쿠쿠",
    "dickcissel": "딕시슬",
    "dowitcher": "도위처",
    "godwit": "갓윗",
    "grackle": "그래클",
    "junco": "정코",
    "kildeer": "킬디어",
    "kittiwake": "키티웨이크",
    "petrel": "페트럴",
    "phalarope": "팔라로프",
    "ptarmigan": "타미건",
    "turnstone": "턴스톤",
    "twite": "트와이트",
}


def korean_bird_name(english_name: str) -> str:
    english_name = NAME_FIXES.get(english_name, english_name)
    if english_name in KOREAN_NAME_OVERRIDES:
        return KOREAN_NAME_OVERRIDES[english_name]

    lower_name = english_name.casefold()
    if "scissor tailed" in lower_name:
        lower_name = lower_name.replace("scissor tailed", "scissor_tailed")
    tokens = re.findall(r"[a-z0-9_]+", lower_name)

    group_index = -1
    group_word = ""
    for index in range(len(tokens) - 1, -1, -1):
        token = tokens[index].replace("_", " ")
        if token in GROUP_KO:
            group_index = index
            group_word = token
            break

    if group_index >= 0:
        modifiers = tokens[:group_index]
        group = GROUP_KO[group_word]
    else:
        modifiers = tokens
        group = "새"

    parts: list[str] = []
    for raw_token in modifiers:
        token = raw_token.replace("_", " ")
        if token in WORD_KO:
            parts.append(WORD_KO[token])
        elif token in GROUP_KO:
            parts.append(GROUP_KO[token])
        elif token in PHONETIC_WORDS:
            parts.append(PHONETIC_WORDS[token])
        else:
            parts.append(token)

    if parts:
        return "".join(parts) + group
    return group


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def sentence_repetition_penalty(text: str) -> int:
    sentences = [part.strip().casefold() for part in re.split(r"[.!?]+", text) if part.strip()]
    if len(sentences) < 2:
        return 0
    unique_ratio = len(set(sentences)) / len(sentences)
    if unique_ratio <= 0.4:
        return 45
    if unique_ratio <= 0.65:
        return 25
    return 0


def transcript_score(row: dict[str, str]) -> int:
    text = normalize_space(row.get("transcript", ""))
    if not text or row.get("error"):
        return -10_000

    score = 0
    vo_id = str(row.get("vo_id", ""))
    file_name = str(row.get("file_name", ""))
    bird_name = normalize_space(row.get("bird_name", ""))
    detected_language = str(row.get("detected_language", "")).casefold()

    if "_PL" in vo_id or "_PL" in file_name:
        score -= 70
    if "#" in vo_id or "#" in file_name:
        score -= 20
    if detected_language == "en":
        score += 20
    try:
        probability = float(row.get("language_probability", "0") or "0")
    except ValueError:
        probability = 0
    if probability >= 0.8:
        score += 10

    length = len(text)
    if 45 <= length <= 190:
        score += 30
    elif 25 <= length < 45 or 190 < length <= 260:
        score += 10
    else:
        score -= 20

    if bird_name and bird_name.casefold() in text.casefold():
        score += 15
    if any(pattern.search(text) for pattern in SPAM_PATTERNS):
        score -= 80
    score -= sentence_repetition_penalty(text)

    ascii_ratio = sum(1 for ch in text if ord(ch) < 128) / max(1, len(text))
    if ascii_ratio < 0.75:
        score -= 20

    return score


def select_representative(rows: list[dict[str, str]]) -> tuple[dict[str, str], int]:
    ranked = sorted(
        ((transcript_score(row), row) for row in rows),
        key=lambda item: (
            item[0],
            -len(normalize_space(item[1].get("transcript", ""))),
            str(item[1].get("file_name", "")),
        ),
        reverse=True,
    )
    return ranked[0][1], ranked[0][0]


def category_sentence(bird_name: str) -> str:
    tokens = set(re.findall(r"[a-z0-9]+", bird_name.casefold()))
    for keywords, sentence in CATEGORY_RULES:
        if any(keyword in tokens for keyword in keywords):
            return sentence
    return "서식지에 맞게 독특한 먹이 활동과 행동을 보여 주는 새입니다."


def tts_text_for_bird(bird_name: str, bird_name_ko: str) -> str:
    bird_name = NAME_FIXES.get(bird_name, bird_name)
    sentence = category_sentence(bird_name)
    return f"{bird_name_ko}입니다. {sentence}"


def build_rows(input_path: Path, voice_tag: str) -> list[dict[str, str]]:
    source_rows = read_csv(input_path)
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in source_rows:
        card_no = normalize_space(row.get("card_no", ""))
        if card_no:
            grouped[card_no].append(row)

    output_rows: list[dict[str, str]] = []
    for card_no in sorted(grouped, key=lambda value: int(value) if value.isdigit() else value):
        source, score = select_representative(grouped[card_no])
        bird_name = normalize_space(source.get("bird_audio_bird_name") or source.get("bird_name", ""))
        bird_name = NAME_FIXES.get(bird_name, bird_name)
        bird_name_ko = korean_bird_name(bird_name)
        output_rows.append(
            {
                "card_no": card_no,
                "bird_name": bird_name,
                "bird_name_ko": bird_name_ko,
                "tts_text": tts_text_for_bird(bird_name, bird_name_ko),
                "voice_tag": voice_tag,
                "review_status": "draft",
                "source_file_name": source.get("file_name", ""),
                "source_vo_id": source.get("vo_id", ""),
                "source_transcript": normalize_space(source.get("transcript", "")),
                "source_score": str(score),
            }
        )
    return output_rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Build one Korean draft TTS intro row per Wingspan card.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--voice-tag", default=DEFAULT_VOICE_TAG)
    parser.add_argument("--dry-run", action="store_true", help="Print counts and sample rows without writing.")
    args = parser.parse_args()

    rows = build_rows(args.input, args.voice_tag)
    if args.dry_run:
        print(f"Input: {args.input}")
        print(f"Cards: {len(rows)}")
        for row in rows[:5]:
            print(f"{row['card_no']}: {row['bird_name']} / {row['bird_name_ko']} -> {row['tts_text']}")
        return 0

    write_csv(args.output, rows)
    print(f"Wrote {len(rows)} card TTS rows: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
