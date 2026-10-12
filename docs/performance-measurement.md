# 영상 생성 시간 측정

서버를 새 코드로 다시 시작한 뒤 실행한 작업부터 `.local/jobs/<작업 ID>/performance.jsonl`에 시간을 기록합니다.
배포 프로그램은 앱 데이터 폴더의 같은 위치에 저장합니다. 기존 작업의 세부 시간은 소급해서 측정할 수 없습니다.

`GET /api/jobs/<작업 ID>/performance` 또는 아래 명령으로 실행별 전체 경과 시간과 세부 구간을 확인합니다.

```powershell
python scripts/profile_generation.py <작업 ID>
```

기록하는 구간:

| 구간 | 의미 |
| --- | --- |
| enhance / photo.enhance | 사진 고화질 변환 전체 / 개별 사진 |
| prepare | 사진 변환과 대본 분석 동시 실행 전체 |
| analyze / script.analyze | 대본 분석 전체 / Codex 분석 호출 |
| quote / motion.upload / motion.quote / voice.quote | 견적 전체 / 사진 업로드 / 영상 견적 / 음성 견적 |
| generate | 승인 후 미디어 생성부터 합성 완료까지의 전체 경과 시간 |
| motion.submit / motion.total | 영상 생성 요청 / 영상 조회·대기·다운로드 분기 |
| motion.status / motion.poll_wait / motion.result / motion.download | 상태 조회 / 다음 조회까지 대기 / 결과 조회 / 다운로드 |
| voice.total / voice.generate | 음성 전체 분기 / 장면별 검증·요청·대기·다운로드 |
| voice.submit / voice.status / voice.poll_wait / voice.download | 음성 제출 / 상태 조회 / 조회 간격 대기 / 다운로드 |
| voice.recover | 이전에 제출한 음성 복구 |
| preview / render.total | 미리보기 처리 / 로컬 합성 전체 |
| render.shot_detection / render.probe | 움직임 컷 검출 / 영상 정보 확인 |
| render.audio_process / render.audio_pad | 음성 속도·무음·볼륨 가공 / 장면 길이 맞춤 |
| render.clip_encode | 사진별 자막 포함·미포함 클립 인코딩 |
| render.package / render.decode_verify / render.poster | 결과 묶기 / 전체 디코딩 검사 / 대표 이미지 |
| render / export.copy | 내보내기 전체 / 확인된 미리보기 파일 복사 |

구간은 중첩되며 음성과 움직임 분기는 병렬입니다. **모든 단계 시간을 더한 값은 전체 경과 시간이 아닙니다.**
`intervals`의 `offset_seconds`, `seconds`, `parent_id`로 실제 실행 순서와 겹치는 구간을 확인할 수 있습니다.
`details.photo`와 `details.scene`은 0부터 시작하는 번호입니다. `status`는 성공·오류·취소를 구분합니다.
캐시로 재사용한 자산은 생성 시간을 새로 기록하지 않습니다. 강제 종료된 진행 구간은 끝 시간이 없어서 기록되지 않을 수 있습니다.

`poll_wait`는 외부 서버의 생성 대기와 완료 확인 지연을 함께 포함합니다. 이 숫자 전체가 폴링 개선으로 줄어드는 시간은 아닙니다.
또한 `voice.generate`는 내부 `voice.submit`, `voice.status`, `voice.poll_wait`, `voice.download` 구간을 포함합니다.
로그에는 대본·인증 정보·다운로드 URL을 넣지 않습니다. 로그 저장 실패는 생성 작업을 중단하지 않습니다.

## 저장된 미디어로 로컬 합성만 측정

```powershell
python scripts/profile_generation.py --list-ready
python scripts/profile_generation.py <작업 ID> --benchmark-render
python scripts/profile_generation.py <작업 ID> --benchmark-render --workers 1
```

활성 입력 파일을 `output/performance/<시각>-<작업 ID>/`에 복사해 합성하므로 기존 작업 결과를 덮어쓰지 않습니다.
Fish/Codex 요청이나 유료 생성 없이 실제 합성·검사를 수행하며, 결과 영상과 `performance-report.json`, `benchmark.json`을 저장합니다.
CPU를 많이 쓰는 다른 작업이 없는 상태에서 측정해야 비교하기 좋습니다. 기본값은 클립 인코딩 2개 동시 처리이며 `--workers 1`, `2`, `3`으로 비교할 수 있습니다.

## 개선 우선순위 판단

- 움직임 분기가 음성 분기보다 오래 걸리면 먼저 요청부터 완료 확인까지의 구간을 확인합니다. 여러 클립의 상태 조회 병렬화는 앞 클립 대기로 뒤 클립 확인이 지연되는 경우에 도움이 됩니다. 외부 서버 생성 시간 자체를 없애지는 못합니다.
- 음성 분기가 오래 걸리면 장면별 `voice.generate`와 내부 구간을 비교합니다. 음성은 작업당 최대 3개 동시 처리하며, Drama 공유 잠금은 생성 제출까지만 유지하고 결과 대기는 병렬로 진행합니다. 같은 음성 자산은 한 번만 생성합니다.
- `render.clip_encode`가 합성 대부분을 차지하면 장면 캐시와 제한된 병렬 인코딩, 하드웨어 인코더를 검토합니다. 하드웨어 인코더는 지원 여부와 화질을 별도로 확인해야 합니다.
- `render.shot_detection`이 크면 컷 검출 결과 재사용 또는 분석용 해상도 축소를 검토합니다.
- 전체 디코딩 검사가 크면 검사 비용을 확인하되 출력 검증을 제거하는 방식으로 처리하지 않습니다.
