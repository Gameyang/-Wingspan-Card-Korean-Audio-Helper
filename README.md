# Wingspan Korean Audio Card Helper

핸드폰 카메라로 **윙스팬(Wingspan) 카드**를 스캔하고, 식별된 카드의 한국어 정보를 보여준 뒤, 미리 준비된 한국어 오디오 파일을 재생해주는 보드게임 헬퍼 웹앱입니다.

이 프로젝트는 GitHub Pages에서 정적 웹사이트로 배포할 수 있도록 HTML, CSS, JavaScript 기반으로 동작합니다.

## 프로젝트 한 줄 설명

스마트폰 카메라로 윙스팬 카드를 인식하고, 해당 카드의 한국어 안내 오디오를 재생하는 GitHub Pages 기반 정적 웹앱입니다.

## 주요 기능

- 모바일 브라우저에서 후면 카메라 실행
- 윙스팬 카드 촬영 또는 스캔
- 카드명 OCR 또는 이미지 매칭을 통한 카드 후보 검색
- 카드 후보를 사용자에게 표시
- 사용자가 카드를 확인 후 선택
- 선택된 카드의 한국어 정보 표시
- 미리 생성된 한국어 오디오 파일 재생
- GitHub Pages를 통한 정적 배포

## 사용 목적

윙스팬을 플레이할 때 카드 설명을 빠르게 확인하고, 한국어 안내를 음성으로 듣기 위한 보조 도구입니다.

다음과 같은 상황에 유용합니다.

- 카드 효과를 빠르게 확인하고 싶을 때
- 카드 설명을 매번 직접 읽기 번거로울 때
- 게임 흐름을 끊지 않고 카드 정보를 듣고 싶을 때
- 한국어 안내 오디오로 카드 정보를 확인하고 싶을 때

## 기술 스택

- HTML
- CSS
- JavaScript
- Web Camera API
- HTML5 Audio
- JSON 카드 데이터
- GitHub Pages

선택적으로 다음 기능을 확장할 수 있습니다.

- OCR 기반 카드명 인식
- 이미지 매칭 기반 카드 식별
- 카드 후보 유사도 검색
- PWA 오프라인 캐시
- 확장판 카드 데이터 분리
- 최근 스캔 기록

## 프로젝트 구조 예시

```txt
.
├── index.html
├── style.css
├── script.js
├── cards.json
├── audio/
│   ├── american_robin.mp3
│   ├── bald_eagle.mp3
│   └── common_raven.mp3
├── assets/
│   └── images/
└── README.md
````

## 전체 동작 흐름

```txt
모바일 브라우저에서 웹앱 접속
→ 카메라 권한 허용
→ 카드명 영역 또는 카드 전체 촬영
→ OCR 또는 이미지 매칭으로 카드 후보 검색
→ 사용자에게 후보 카드 표시
→ 사용자가 최종 카드 선택
→ 카드 정보 표시
→ 해당 카드의 한국어 오디오 파일 재생
```

초기 버전에서는 완전 자동 인식보다는 **카드 후보 표시 후 사용자가 확인하는 방식**을 권장합니다.

## 실행 방법

### 1. 저장소 클론

```bash
git clone https://github.com/your-username/your-repository.git
cd your-repository
```

### 2. 로컬에서 실행

정적 파일이므로 간단한 로컬 서버로 실행할 수 있습니다.

```bash
python -m http.server 8000
```

브라우저에서 아래 주소로 접속합니다.

```txt
http://localhost:8000
```

카메라 기능은 브라우저 보안 정책상 `localhost` 또는 `https` 환경에서 정상 동작합니다.

## GitHub Pages 배포 방법

### 1. GitHub 저장소에 파일 업로드

다음 파일들이 저장소 루트에 있어야 합니다.

```txt
index.html
style.css
script.js
cards.json
audio/
README.md
```

### 2. GitHub Pages 활성화

GitHub 저장소에서 다음 순서로 설정합니다.

1. `Settings`로 이동
2. `Pages` 메뉴 선택
3. `Build and deployment` 항목에서 `Deploy from a branch` 선택
4. Branch를 `main`으로 선택
5. Folder를 `/root`로 선택
6. `Save` 클릭

잠시 후 아래와 같은 주소로 접속할 수 있습니다.

```txt
https://your-username.github.io/your-repository/
```

## 모바일 사용 방법

1. 스마트폰에서 GitHub Pages 주소 접속
2. 카메라 권한 허용
3. 윙스팬 카드를 화면 가이드에 맞춤
4. 촬영 또는 스캔 버튼 클릭
5. 인식된 카드 후보 확인
6. 올바른 카드 선택
7. 카드 정보 확인
8. `음성 듣기` 버튼을 눌러 한국어 오디오 재생

## 카메라 권한 안내

카메라 기능은 브라우저 보안 정책상 HTTPS 환경에서 사용하는 것을 권장합니다.

GitHub Pages는 HTTPS를 제공하므로 실제 배포 환경에서는 카메라 사용에 적합합니다.

단, 사용자가 브라우저의 카메라 권한 요청을 허용해야 합니다. 권한을 거부한 경우 브라우저 또는 OS 설정에서 카메라 권한을 다시 허용해야 합니다.

로컬 개발 시에는 `localhost`에서는 동작할 수 있지만, 같은 네트워크의 IP 주소로 접속하는 경우 모바일 브라우저에서 카메라 권한이 차단될 수 있습니다.

### 카메라 실행 예시

```html
<video id="camera" autoplay playsinline muted></video>
```

```js
async function startCamera() {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: {
      facingMode: { ideal: "environment" }
    },
    audio: false
  });

  const video = document.querySelector("#camera");
  video.srcObject = stream;
}
```

## 카드 인식 정확도 안내

카드 식별 정확도는 촬영 환경과 구현 방식에 따라 달라질 수 있습니다.

정확도에 영향을 주는 요소는 다음과 같습니다.

* 조명 밝기
* 카드 기울어짐
* 카메라 흔들림
* 카드와 카메라 사이 거리
* 슬리브 반사
* 카드명 영역의 초점
* 카드 이미지 해상도
* 확장판 카드 여부
* `cards.json`에 등록된 카드 데이터 범위
* OCR 또는 이미지 매칭 알고리즘의 성능

초기 버전에서는 **완전 자동 카드 식별**보다는 다음 방식을 권장합니다.

```txt
카드명 영역 캡처
→ OCR 수행
→ cards.json에서 유사한 카드명 검색
→ 후보 카드 1~3개 표시
→ 사용자가 올바른 카드 선택
```

이 방식은 완전 자동 인식보다 안정적이며, 실제 보드게임 플레이 중에도 오인식 문제를 줄일 수 있습니다.

## 카드 식별 방식

### 1. OCR 기반 카드명 인식

카드 상단의 이름 영역을 캡처한 뒤 OCR로 카드명을 읽고, `cards.json`에 등록된 카드명과 비교합니다.

장점:

* 구현 난이도가 비교적 낮음
* 카드 이미지 전체 데이터가 없어도 가능
* 정적 웹앱으로 구현 가능

단점:

* 조명, 흔들림, 초점에 민감함
* OCR 결과가 부정확할 수 있음
* 한글/영문 카드명 처리 방식이 필요함

### 2. 이미지 매칭 기반 식별

카드 이미지 또는 특징점을 기준으로 입력 이미지와 등록된 카드 데이터를 비교합니다.

장점:

* OCR이 어려운 경우에도 사용할 수 있음
* 카드명 텍스트가 흐려도 식별 가능성이 있음

단점:

* 기준 이미지 데이터 준비가 필요함
* 카드 수가 많아질수록 처리량 증가
* 모바일 성능 최적화가 필요함

### 3. 사용자 확인 기반 흐름

가장 권장하는 MVP 방식입니다.

자동 식별 결과를 바로 확정하지 않고, 후보 카드를 사용자에게 보여준 뒤 선택하게 합니다.

```txt
인식 결과: American Robin
후보:
1. American Robin
2. European Robin
3. Red-winged Blackbird
```

사용자가 최종 선택하면 해당 카드의 한국어 정보와 오디오를 재생합니다.

## 오디오 파일 방식

이 프로젝트는 실시간 TTS를 생성하지 않습니다.

각 카드별 한국어 안내 음성 파일을 미리 생성하여 `audio/` 폴더에 저장하고, 카드 식별 후 해당 오디오 파일을 재생합니다.

이 방식은 브라우저 내장 TTS보다 안정적이며, 기기나 브라우저에 따라 음성 품질이 달라지는 문제를 줄일 수 있습니다.

## 카드 데이터 예시

`cards.json` 예시:

```json
[
  {
    "id": "american_robin",
    "name_en": "American Robin",
    "name_ko": "아메리카울새",
    "habitat": ["forest", "grassland", "wetland"],
    "food": ["worm", "berry"],
    "points": 1,
    "nest": "bowl",
    "eggs": 4,
    "wingspan_cm": 31,
    "power_type": "when_activated",
    "description_ko": "활성화할 때, 공급처에서 무척추동물 먹이 1개를 가져옵니다.",
    "audio": "audio/american_robin.mp3"
  }
]
```

## 오디오 파일 관리 규칙

카드 ID와 오디오 파일명을 동일하게 관리하는 것을 권장합니다.

예시:

```txt
cards.json의 id: american_robin
오디오 파일: audio/american_robin.mp3
```

권장 구조:

```txt
audio/
├── american_robin.mp3
├── bald_eagle.mp3
├── common_raven.mp3
└── ...
```

카드 데이터에는 해당 오디오 파일 경로를 명시합니다.

```json
{
  "id": "bald_eagle",
  "name_ko": "흰머리수리",
  "audio": "audio/bald_eagle.mp3"
}
```

## 오디오 재생 예시

```html
<audio id="card-audio" controls preload="none"></audio>
```

```js
function setCardAudio(card) {
  const audio = document.querySelector("#card-audio");

  if (!card.audio) {
    alert("이 카드의 오디오 파일이 없습니다.");
    return;
  }

  audio.src = card.audio;
  audio.load();
}
```

```js
function playCardAudio(card) {
  if (!card.audio) {
    alert("이 카드의 오디오 파일이 없습니다.");
    return;
  }

  const audio = new Audio(card.audio);

  audio.play().catch((error) => {
    console.error(error);
    alert("오디오 재생에 실패했습니다. 화면을 한 번 터치한 뒤 다시 시도해 주세요.");
  });
}
```

## 모바일 오디오 재생 주의사항

모바일 브라우저에서는 사용자 동작 없이 자동으로 오디오가 재생되지 않을 수 있습니다.

따라서 카드가 인식되자마자 자동 재생하기보다는, 사용자가 `음성 듣기` 버튼을 누른 뒤 오디오를 재생하는 방식을 권장합니다.

권장 흐름:

```txt
카드 인식
→ 카드 정보 표시
→ 음성 듣기 버튼 표시
→ 사용자가 버튼 터치
→ 오디오 재생
```

## 오디오 파일 용량 관리

카드별 MP3 파일을 포함하면 저장소 용량과 초기 로딩 비용이 증가할 수 있습니다.

권장 사항:

* MP3 파일 사용
* 필요할 때만 오디오 로딩
* `preload="none"` 사용
* 카드별 짧은 요약 음성 사용
* PWA 캐시 적용 시 용량 관리
* 확장판별 오디오 폴더 분리

예시:

```txt
audio/
├── base/
│   ├── american_robin.mp3
│   └── bald_eagle.mp3
├── european/
└── oceania/
```

## 브라우저 지원

권장 브라우저:

* Chrome Android
* Safari iOS
* Samsung Internet
* Microsoft Edge

카메라 기능은 HTTPS 환경에서 사용하는 것을 권장합니다.

GitHub Pages는 HTTPS를 제공하므로 모바일 카메라 사용에 적합합니다.

## 구현 시 권장 MVP 범위

초기 버전에서는 다음 범위로 시작하는 것을 권장합니다.

* 기본판 카드 일부만 지원
* 카드명 OCR 기반 인식
* 후보 카드 표시
* 사용자 선택 방식
* 선택된 카드 정보 표시
* 미리 준비된 MP3 파일 재생

초기 목표는 완전 자동 인식이 아니라, 실제 플레이 중 사용할 수 있는 안정적인 보조 도구를 만드는 것입니다.

## 향후 개선 아이디어

* 카드명 영역 자동 감지
* OCR 정확도 개선
* 이미지 매칭 추가
* 카드 후보 유사도 개선
* 확장판별 카드 DB 분리
* 한국어 오디오 일괄 생성 스크립트
* 오디오 파일 누락 검사
* 최근 인식 카드 기록
* 즐겨찾기 카드 저장
* PWA 오프라인 지원
* 오디오 캐시 최적화
* 카드별 짧은 설명 / 긴 설명 모드
* 다국어 오디오 지원

## 주의 사항

이 프로젝트는 팬메이드 보드게임 보조 도구입니다.

윙스팬 및 관련 카드명, 이미지, 텍스트, 로고 등의 권리는 원저작권자에게 있습니다.

카드 이미지나 공식 카드 텍스트를 프로젝트에 포함할 경우 저작권 및 이용 조건을 반드시 확인해야 합니다.

공개 GitHub 저장소에 공식 카드 이미지 전체 또는 공식 카드 텍스트 전체를 포함하는 것은 권장하지 않습니다.

가능하면 다음 방식으로 데이터를 관리하는 것을 권장합니다.

* 직접 작성한 요약 설명 사용
* 사용자가 직접 보유한 카드 데이터를 로컬에서 사용
* 공식 이미지 전체 대신 카드명 기반 인식 사용
* 공개 배포 시 저작권 검토

또한 TTS 서비스나 음성 생성 서비스를 사용해 오디오 파일을 만든 경우, 해당 서비스의 라이선스와 공개 배포 가능 여부를 확인해야 합니다.

## 라이선스

이 프로젝트의 소스코드는 MIT License로 배포할 수 있습니다.

단, 윙스팬 카드 이미지, 카드 텍스트, 게임명, 로고, 생성된 음성 파일 등은 별도의 권리자가 있을 수 있으므로 프로젝트에 포함하기 전에 반드시 사용 가능 여부를 확인하세요.

## 기여

버그 제보, 카드 데이터 개선, 인식 기능 개선, 오디오 파일 정리 PR을 환영합니다.

1. 저장소 Fork
2. 새 브랜치 생성
3. 기능 추가 또는 수정
4. Pull Request 생성

## 개발 우선순위

1. 모바일 카메라 실행
2. 카드명 영역 캡처
3. 카드 데이터 JSON 구조 정의
4. 카드 후보 검색
5. 사용자 카드 선택 UI
6. 카드 정보 표시
7. MP3 오디오 재생
8. OCR 또는 이미지 매칭 정확도 개선
9. PWA 및 오프라인 지원
