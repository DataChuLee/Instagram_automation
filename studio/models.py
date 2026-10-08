from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field, field_validator

VIDEO_MODEL = 'seedance-2.0'
VOICE_ID = '4a81bbbb5cd44f22922bf934cb93b369'
DRAMA_MODEL = 'drama-3-preview'
MOTION_PARAMETERS = {'aspect_ratio': '9:16', 'resolution': '1080p', 'duration': '4s'}


class CaptionStyle(BaseModel):
    font_size: int = Field(64, ge=28, le=120)
    x: float = Field(0, ge=-35, le=35)
    y: float = Field(13, ge=-35, le=35)
    color: str = Field('#CCCACC', pattern=r'^#[0-9a-fA-F]{6}$')
    outline: int = Field(8, ge=0, le=16)
    background_opacity: float = Field(0.2, ge=0, le=1)
    shadow: int = Field(3, ge=0, le=12)

    def center(self, width=1080, height=1920):
        # VLLO screenshot calibration: positive Y moves upward from center.
        return round(width * (0.5 + self.x / 100)), round(height * (0.5 - self.y / 100))


class Scene(BaseModel):
    photos: list[int] = Field(min_length=1)
    text: str = Field(min_length=1, max_length=160)


class Motion(BaseModel):
    photo: int = Field(ge=0)
    prompt: str = Field(min_length=1, max_length=2000)

    @field_validator('prompt', mode='before')
    @classmethod
    def trim_prompt(cls, value):
        return value.strip() if isinstance(value, str) else value


class CropFocus(BaseModel):
    photo: int = Field(ge=0)
    x: float = Field(0.5, ge=0, le=1)
    y: float = Field(0.5, ge=0, le=1)


class Storyboard(BaseModel):
    scenes: list[Scene] = Field(min_length=1)
    motion: list[Motion] = Field(default_factory=list)
    crop_focus: list[CropFocus] = Field(default_factory=list)

    @classmethod
    def validate_plan(cls, value, photo_count: int, max_motion: int):
        plan = cls.model_validate(value)
        used = [index for scene in plan.scenes for index in scene.photos]
        if sorted(used) != list(range(photo_count)):
            raise ValueError('모든 사진은 장면에 정확히 한 번씩 포함되어야 합니다.')
        indices = [item.photo for item in plan.motion]
        if len(indices) > max_motion or len(set(indices)) != len(indices):
            raise ValueError('움직임 장면 수가 설정 범위를 벗어났습니다.')
        if any(index >= photo_count for index in indices):
            raise ValueError('움직임 장면의 사진 번호가 올바르지 않습니다.')
        if any(focus.photo >= photo_count for focus in plan.crop_focus):
            raise ValueError('크롭 기준의 사진 번호가 올바르지 않습니다.')
        return plan


class CreateOptions(BaseModel):
    max_motion: int = Field(3, ge=0)
    caption: CaptionStyle = Field(default_factory=CaptionStyle)
    speed: float = Field(1.0, ge=0.75, le=1.25)


class ApproveRequest(BaseModel):
    quote_id: str
    expected_credits: int = Field(ge=0)


class Job(BaseModel):
    id: str
    state: Literal['uploaded', 'analyzing', 'quoting', 'awaiting_approval', 'generating',
                   'rendering', 'complete', 'error', 'interrupted'] = 'uploaded'
    message: str = '사진을 준비했습니다.'
    photos: list[dict] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)
    options: CreateOptions = Field(default_factory=CreateOptions)
    storyboard: Storyboard | None = None
    quote: dict | None = None
    approval: dict | None = None
    generated: dict = Field(default_factory=dict)
    narration: dict = Field(default_factory=dict)
    result: dict | None = None
    error: str | None = None


def stable_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def motion_fingerprint(photo_hash: str, prompt: str) -> str:
    return stable_hash({'image': photo_hash, 'prompt': prompt,
                        'model': VIDEO_MODEL, 'parameters': MOTION_PARAMETERS})
