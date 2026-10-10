# Codex 고화질 변환 설계 — 2026-10-10

## 목적

수집·업로드한 숙소 사진은 압축 손상이 있고, 가로 사진을 9:16으로 자르면 약 608×1080만 남아
영상이 흐려진다. Codex CLI 내장 `image_generation`으로 사진을 다시 생성해 고화질·인물 제거·
세로 9:16·화사한 보정 이미지를 만들고, 그 이미지로 분석·움직임·렌더링을 진행한다.

### 확인된 사실 (2026-10-10 테스트, `output/codex_enhance_test_20261010/`)

- Codex CLI 0.161.0의 `image_generation` 기능은 기본 활성화되어 있고 ChatGPT 구독 로그인만으로
  동작한다. 별도 MCP/API 키가 필요 없다.
- 생성 이미지는 `CODEX_HOME/generated_images/<session id>/*.png`에 저장된다. `codex exec`의
  샌드박스가 read-only로 동작해 작업 폴더에 직접 저장하게 할 수 없다. 세션 ID는 stderr의
  `session id: <id>` 줄에서 얻는다.
- 결과는 941×1672(9:16). 5장 병렬 약 74초, 1장 40~90초.
- "글자 금지"만 쓰면 숙소 간판까지 지워진다. 사용자는 원본 색 유지보다 화사한 보정을 선호한다.
- 넓은 가로 사진은 9:16 확장 영역(위·아래)을 모델이 새로 그린다 → 사진별 원본 되돌리기가 필요.

## 사용자 결정

- 변환은 **버튼으로 실행**한다(업로드 직후 자동 실행 아님).
- 변환 성공 시 **변환본이 기본**이고, 사진별로 **원본으로 되돌릴 수 있다**.
- 구현 방식 A: 사진 dict에 원본·변환본을 함께 두고 `file`만 바꿔 끼운다.

## 구조

### `studio/enhance.py` (새 모듈)

- `prompt()` — `studio/skills/stay-shortform/SKILL_ENHANCE.md` 내용을 반환한다.
- `async enhance_photo(source: Path, target: Path) -> None`
  1. `codex.login_status()`가 거짓이면 `RuntimeError('설정에서 ChatGPT 구독 계정으로 Codex에 로그인해 주세요.')`.
  2. `codex exec --sandbox read-only --skip-git-repo-check --ephemeral --ignore-user-config
     --ignore-rules -C <target 폴더> -i <source> -` 에 프롬프트를 stdin으로 전달한다.
     실행 파일·환경은 `codex.executable()`, `codex.environment()`를 쓴다.
  3. 제한 시간 300초. 초과 시 프로세스를 종료하고 `EnhanceError('변환 시간이 초과되었습니다.')`.
  4. stderr에 `usage limit`이 있으면 `UsageLimit` 예외(일괄 변환 중단 신호).
  5. stderr의 `session id: <id>`로 `DATA/auth/codex/generated_images/<id>/` 안의 가장 최근 PNG를
     찾는다. 없으면 `EnhanceError('생성된 이미지가 없습니다.')`.
  6. 이미지를 9:16 중앙 크롭 후 1080×1920 LANCZOS로 키워 `target`에 JPEG(quality 96)로 저장한다.
     임시 파일에 쓰고 교체해 반쯤 쓰인 파일이 남지 않게 한다.
  7. 생성 세션 폴더를 삭제한다(Codex 폴더에 쌓이지 않도록).
- 예외: `EnhanceError(RuntimeError)`, `UsageLimit(EnhanceError)`.

### 프롬프트 `SKILL_ENHANCE.md`

테스트에서 확정한 3차 프롬프트:

- 세로 9:16, 최대한 높은 해상도
- 9:16에 맞출 때 새로 그리는 영역 최소화, 원본 부분을 최대한 살린 구도
- 사람·모자이크·블러 제거, 그 자리는 원래 뒤 배경으로 자연스럽게 채움
- 건물 구조·가구·배치·조경·표지물 유지, 없는 물체 추가 금지
- 원본 간판·로고·글자 유지, 새 글자·워터마크만 금지
- 호텔 광고 사진처럼 밝기·대비·채도를 올려 화사하게, 선명도·디테일·노이즈 개선
- 파일 저장이나 다른 도구 사용 없이 이미지 생성만

### 사진 데이터 (`job.photos[i]`)

```
file:          영상에 실제로 쓰는 파일 (분석·크롭·움직임·렌더링은 이것만 읽는다)
original_file: 원본 파일 이름 — 변환을 한 번이라도 시도한 사진에만 생긴다
enhanced:      {"file": "photo-003-enhanced.jpg", "state": "done"}
               또는 {"state": "failed", "error": "..."}
```

- `sha256`은 원본 기준으로 유지한다(중복 업로드 검사용).
- 토글은 `file`을 `original_file` 또는 `enhanced.file`로 바꾸는 것뿐이다. 선택 상태는
  `enhanced.active`에도 기록한다.
- 움직임 캐시는 크롭 이미지 해시 기준이라 파일이 바뀌면 자동으로 무효화된다.

### 후보 목록 동기화 (workflow v2)

- v2 작업은 구성을 바꿀 때 `composition.select`가 `job.candidates`에서 사진 목록을 다시 만든다.
  변환·토글 시 같은 `sha256`의 후보에 `enhanced` dict를 복사해 둔다(후보의 `file`은 원본 유지).
- `composition.select`는 후보의 `enhanced`가 `done`이고 변환 파일이 있으면 그대로 이어받고,
  `original_file`은 새로 복사한 원본 파일, `file`은 `active`에 따라 정한다.
- `recommendation.candidates`가 사진에서 후보를 만들 때 `file`은 `original_file`을 우선한다.
- 앱 재시작 시 `enhancing` 상태는 `uploaded`로 돌리고 "다시 누르면 남은 사진만 변환" 안내를 표시한다.

### 작업 상태

- `Job.state`에 `'enhancing'`을 추가한다.

### 파이프라인 `Pipeline.enhance(job_id, indices=None)`

1. 사진 편집 가능 조건(분석 전)을 다시 확인한다.
2. 대상: `indices`가 없으면 `enhanced.state != 'done'`인 모든 사진, 있으면 해당 사진(다시 변환).
3. 상태 `enhancing`, 메시지 `고화질 변환 중 · 0/N장`.
4. 최대 4장 동시 실행(`asyncio.Semaphore(4)`). 1장 끝날 때마다 작업을 다시 읽어 해당 사진만
   갱신·저장하고 진행 메시지를 바꾼다.
   - 성공: `original_file` 설정(없을 때), `enhanced={file, state: done, active: true}`, `file=enhanced.file`.
   - 실패(`EnhanceError`): `enhanced={'state':'failed','error'}`, `file`은 원본 유지.
   - `UsageLimit`: 남은 대기 작업을 취소하고, 이미 성공한 사진은 유지한 채 오류 상태로 끝낸다
     (`Codex 구독 사용 한도에 도달했습니다. 한도가 초기화된 뒤 다시 눌러 주세요.`).
5. 끝나면 상태 `uploaded`, 메시지 `고화질 변환 완료 · 성공 S장 · 실패 F장`.
6. 다시 변환 시 기존 변환 파일은 성공했을 때만 새 파일로 교체한다(실패하면 이전 변환본 유지).

### API

- `POST /api/jobs/{id}/enhance` body `{"photos": [int] | null}` → 202, 백그라운드 실행.
  분석 후·진행 중·사진 없음·잘못된 번호는 400.
- `POST /api/jobs/{id}/photos/{index}/source` body `{"source": "original" | "enhanced"}` →
  `file` 교체 후 작업 반환. 분석 후·진행 중·변환본 없음은 400.
- 파일 제공 허용 목록에 각 사진의 `original_file`, `enhanced.file`을 추가한다.

### UI

- 사진 목록 아래, 분석 버튼 옆에 `[고화질 변환 · 인물 제거 ↗]` 버튼과 안내
  ("ChatGPT 구독 사용량을 씁니다. 사진 10장 기준 약 3~4분").
  사진 없음·분석 후·진행 중이면 비활성.
- `busyStates`에 `enhancing` 추가 → 변환 중 분석·사진 추가·순서 변경 잠김. 상태 표시줄에 진행 메시지.
- 사진 카드: 변환본 사용 중이면 `HD` 배지. 변환을 시도한 사진에는 `[원본|변환본]` 토글과
  `[다시 변환]`. 실패한 사진은 `변환 실패` 표시. 토글 시 미리보기가 갱신된다.

## 오류 처리

| 상황 | 동작 |
|---|---|
| Codex 로그인 안 됨 | 시작 전 400, 계정 연결 안내 |
| 구독 사용 한도 | 남은 사진 중단, 성공분 유지, 오류 상태와 안내 |
| 사진 1장 실패/시간 초과 | 그 사진만 실패 표시, 나머지 계속 |
| 앱 종료/중단 | 1장씩 저장되어 있으므로 다시 누르면 남은 사진만 진행 |
| 9:16이 아닌 결과 | 중앙 9:16 크롭 후 저장 |

## 테스트

- `tests/test_enhance.py`: 가짜 Codex 프로세스로 저장·크기(1080×1920)·세션 폴더 삭제, 비 9:16 크롭,
  생성 이미지 없음, 한도 오류, 프롬프트 포함.
- `tests/test_pipeline.py`: 부분 실패, 한도 중단, 이미 변환된 사진 건너뛰기, 다시 변환 실패 시 이전 변환본 유지.
- `tests/test_app.py`: 토글·분석 후 차단, 다시 변환 대상, 파일 허용 목록, 변환 중 편집 차단.
- 브라우저: 가짜 Codex로 버튼→진행→HD 배지→토글→미리보기→실패 표시, 모바일 폭.
- 실제: Test_Data 10장으로 변환→분석→크롭 미리보기(유료 Fish 생성 제외), 배포 EXE 경로 확인.

## 범위 밖

- 업로드 직후 자동 변환, 변환 결과 여러 개 중 고르기, 사진별 프롬프트 편집.
