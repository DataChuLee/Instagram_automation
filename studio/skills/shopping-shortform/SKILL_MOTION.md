---
name: shopping-shortform-motion
description: Write English multi-shot reference-to-video prompts that turn 3-4 product photos into one hard-cut clip with small, product-faithful motion.
---

# 상품 사진 움직임

모든 사진은 영상이 된다. 앱이 연속된 사진 3~4장을 하나의 클립으로 묶고 클립 길이를 정한다. 각 사진은 클립 안에서 하나의 Shot이 되어 하드 컷으로 이어진다. 클립마다 영어 프롬프트 하나를 쓴다.

## 움직임 공식

1. Shot당 포인트 하나: 한 Shot에는 눈에 띄는 움직임을 하나만 준다. 사진에 실제로 있는 요소만 움직인다. 없으면 카메라 이동만 쓴다.
   - 상품 단독 컷: 아주 느린 푸시인, 또는 상품을 중심으로 한 미세한 궤도 이동(slow orbit, 10도 이내).
   - 손이 보이는 사용 컷: 이미 보이는 손이 문지르기·뿌리기·짜기 같은 사용 동작을 한 번 자연스럽게 이어 간다.
   - 액체·가루·거품: 이미 보이는 액체가 흐르거나 거품이 살짝 일고, 가루가 조금 흩날린다.
   - 결과 컷: 반짝이는 표면에 빛이 한 번 지나간다(soft light sweep).
2. 느린 카메라: 흔들림·빠른 줌·급회전은 쓰지 않는다. 이어지는 Shot은 서로 다른 카메라 이동을 쓴다.
3. 작게, 깔끔하게: 움직임 강도는 subtle~moderate로 제한한다.
4. 상품 보존(가장 중요): 상품의 모양, 크기 비율, 색, 로고, 라벨, 글자, 포장 디자인을 절대 바꾸지 않는다. 글자를 새로 쓰거나 지우지 않는다. 상품을 다른 상품으로 바꾸거나 개수를 늘리지 않는다. 사용 전 사진을 사용 후처럼 바꾸지 않는다. 사진끼리 섞지 않는다.

## 프롬프트 형식

```
A {N}-second vertical product reel made of {K} hard-cut shots, one per reference image, in order, about {초} seconds each.
Shot 1 (0-{t1}s): image 1 exactly, {카메라 이동}, {포인트 움직임}. Hard cut.
Shot 2 ({t1}-{t2}s): image 2 exactly, ... Hard cut.
...
Each shot must reproduce its reference photo faithfully: the same product shape, colors, logo, label text, packaging, hands, background and composition.
Do not blend images together, do not invent new products, objects, people or text, and do not change any printed text. No camera shake, no transitions other than hard cuts.
```

- Shot 설명에는 그 사진의 핵심 대상을 짧게 넣는다 (예: "image 2 exactly, a hand spraying the bottle onto a stained sleeve, very slow push-in").
