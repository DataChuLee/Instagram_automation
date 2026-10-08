# 숙소 세로 영상

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
