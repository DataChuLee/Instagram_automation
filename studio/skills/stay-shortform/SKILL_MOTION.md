---
name: stay-shortform-motion
description: Write English multi-shot reference-to-video prompts that turn 3-4 accommodation photos into one hard-cut clip in the slow, single-accent motion style of the reference reels.
---

# 숙소 사진 움직임

모든 사진은 영상이 된다. 앱이 연속된 사진 3~4장을 하나의 클립으로 묶고 클립 길이를 정한다. 각 사진은 클립 안에서 하나의 Shot이 되어 하드 컷으로 이어진다. 클립마다 영어 프롬프트 하나를 쓴다.

## 움직임 공식

레퍼런스 쇼츠 두 편에서 공통으로 쓰는 규칙을 따른다.

1. Shot당 포인트 하나: 한 Shot에는 눈에 띄는 움직임을 하나만 준다. 물, 빛, 불, 사람 중 사진에 실제로 있는 요소를 고른다. 없으면 카메라 이동만 쓴다.
   - 물: 풀·욕조 수면이 잔잔히 일렁이고 빛이 반사된다. 분수·물줄기는 이미 보이는 흐름만 이어 간다.
   - 빛: 창으로 들어오는 햇빛이 살짝 번지거나 렌즈 플레어가 은은하게 지나간다. 이미 켜진 조명은 부드럽게 반짝인다.
   - 조명 켜짐: 사진에 보이는 조명 기구(간접등, 매립등, 스탠드, 외부 업라이트)가 어둡게 시작해 원래 밝기로 켜진다.
   - 불: 화로·숯·바비큐 불꽃이 살아 오르고 작은 불티가 튄다.
   - 사람: 이미 있는 사람이 고개를 돌리거나 손을 움직이는 정도로만 움직인다. 얼굴 클로즈업은 움직이지 않는다.
2. 느린 카메라: Shot마다 아주 느린 푸시인, 좌우 트래킹, 드론 샷의 미세한 하강·회전 중 하나만 쓴다. 흔들림·빠른 줌·급회전은 쓰지 않는다. 이어지는 Shot은 서로 다른 카메라 이동을 쓴다.
   - 항공·외관 전경: slow aerial drift 또는 gentle descending push-in
   - 객실·실내: slow dolly push-in 또는 gentle lateral slide
   - 평면적인 장면: slow lateral truck
3. 작게, 고급스럽게: 움직임 강도는 subtle~moderate로 제한해 사진 같은 질감을 유지한다.
4. 변화 없이 보존: 건물/객실 구조, 가구, 얼굴, 글자, 색을 유지한다. 새 물체·사람·시설·조명 기구를 추가하지 않는다. 사진에 없는 조명을 만들거나 맑은 낮 사진을 밤으로 바꾸지 않는다. 사진끼리 섞지 않는다.

## 프롬프트 형식

다음 형식을 그대로 따른다. 2026-10-09 테스트에서 네 사진이 순서대로, 원본에 가깝게 나온 형식이다.

```
A {N}-second vertical travel reel made of {K} hard-cut shots, one per reference image, in order, about {초} seconds each.
Shot 1 (0-{t1}s): image 1 exactly, {카메라 이동}, {포인트 움직임}. Hard cut.
Shot 2 ({t1}-{t2}s): image 2 exactly, ... Hard cut.
...
Each shot must reproduce its reference photo faithfully: same architecture, pools, trees, furniture, colors, lighting and composition.
Do not blend images together, do not invent new buildings, objects, people or text. No camera shake, no transitions other than hard cuts.
```

- Shot 설명에는 그 사진의 핵심 대상을 짧게 넣는다 (예: "image 2 exactly, the hotel facade with white parasols, very slow lateral slide").
- 조명 켜짐 Shot은 "only the existing light fixtures brighten from dim to their original brightness"로 쓰고, 보존 조건의 lighting은 그 Shot에 적용하지 않는다고 덧붙인다.

## Sources

Motion formula derived from the two reference reels in Data/영상_1.mp4 and Data/영상_2.mp4 (analyzed 2026-10-09).
