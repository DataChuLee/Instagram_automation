# 숙소 세로 영상 · Stay Studio

사진을 넣어 대본·음성·움직임·자막을 만드는 로컬 Windows 프로그램은 `studio/`에 있습니다.
사진 첨부와 함께 여기어때 국내 숙소 링크에서 사진을 수집하고 골라 추가할 수 있습니다.
완성본 MP4, 자막·음성 없는 MP4, 대본 TXT/자막 SRT, 내레이션 MP3를 각각 저장합니다.
친구에게 전달할 폴더는 `dist/StayStudio`, 압축 파일은 `dist/StayStudio-Windows.zip`입니다.
실행 및 로그인 방법은 [친구 PC 사용법](docs/친구-PC-사용법.md)을 보세요.

개발 실행 및 검증:

```powershell
python -m pip install --target .tools/studio-python -r requirements-studio.txt
python scripts/install_browser.py
python launch.py
python scripts/test_studio.py
python scripts/build_windows.py
```

새 프로그램은 기존 결과물을 덮어쓰지 않습니다. 개발 중 작업은 `.local/jobs`에 저장합니다.
링크 수집 결과는 `.local/collections`에 보관합니다. 같은 링크를 다시 수집하면 정상 저장된 사진을 재사용합니다.
사진 구성은 분석 전에만 변경하며, 기존 작업의 새 다운로드 파일은 저장된 미디어로 다시 합성해 만듭니다.
최종 출력은 1080×1920 / 30fps, 자막은 페이퍼로지 Bold와 Y=13 기본값입니다.
움직임과 Drama3 음성은 같은 Fish MCP 연결과 패키지 크레딧으로 생성합니다.
음성은 Drama3 (`drama-3-preview`)와 일반여성2로 고정하며 별도 음성 로그인은 없습니다.
Story Studio의 무료 견적을 확인하고 승인한 뒤 생성합니다. 모델·목소리·가격이
변경되면 생성을 중단합니다. 실제 계정 생성 검증 상태는
[진행 기록](docs/superpowers/plans/2026-10-08-local-video-studio-progress.md)에 남깁니다.

## 기존 17장 영상

이번 결과물: `output/stay_reel.mp4`. Fish Audio의 일반여성2 목소리와 `Data/Test_Data` 사진 17장을 사용한다. 내레이션·흰색 중앙 자막·사진 확대 효과를 포함한다.

- `output/storyboard.json`: 장면별 대본, 사진 인덱스, 목소리 ID, 생성 기록과 타임라인.
- `output/stay_reel.srt`: 자막 파일.
- `output/preview.jpg`: 실제 출력 영상에서 추출한 장면 미리보기.
- `output/verification.json`: 전체 디코딩 및 형식 검증 결과.

Python 3.11, Pillow와 프로젝트 `.tools/python`의 imageio-ffmpeg를 사용한다. FFmpeg 배포 방식은 https://github.com/imageio/imageio-ffmpeg 를 따른다.

저장된 대본과 음성으로 다시 합성하려면 프로젝트 폴더에서 실행한다:

```powershell
& 'C:/Users/qasd1/.pyenv/pyenv-win/versions/3.11.9/python.exe' scripts/render_video.py
& 'C:/Users/qasd1/.pyenv/pyenv-win/versions/3.11.9/python.exe' scripts/verify_video.py
```

재합성은 Fish 생성 호출을 하지 않으며 기존 출력 파일을 갱신한다. 새 대본은 별도 음성 생성이 필요하다. 새로운 사진 세트는 장면 목록과 사진 인덱스를 함께 수정해야 한다. 렌더러는 현재 Test_Data 입력에 맞춰져 있으며 무인 대본 생성·예약 실행 기능은 포함하지 않는다.
