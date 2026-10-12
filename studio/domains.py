"""Domain schemas: the object types, UI wording and features of each short-form kind.

A domain is a folder `<id>-shortform/` holding `domain.json` and the skill (prompt) files its media engine needs.
Built-in domains ship in `studio/skills/`; extra or overriding ones live in the data folder's `domains/`
(e.g. %LOCALAPPDATA%\\StayStudio\\domains on the packaged app), so a new kind needs no rebuild.
A data folder may hold only some files of a built-in domain; the rest come from the built-in folder.

Engine-owned "system types" (Photo, Scene, Segment, ...) are defined here once per media engine and added to every
schema; domains describe only their own business types (Accommodation, Product, ...).
Jobs keep the domain they were created with, and everything domain-specific is read from here.
"""
from __future__ import annotations

import hashlib
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from . import paths
from .paths import RESOURCES

DEFAULT = 'stay'  # Jobs saved before domains existed are stays.
SKILLS = RESOURCES / 'studio/skills'
PROPERTY_SOURCES = ('photo', 'user')
UI_KEYS = {'intro', 'upload_title', 'upload_hint', 'caption_default', 'preview_title', 'preview_text', 'ai_help',
           'recommend_progress', 'enhance_label', 'photo_name',
           'noun', 'unit', 'select', 'analyze', 'nav_hint', 'heading', 'facts_title', 'facts_help'}
log = logging.getLogger(__name__)


class Property(BaseModel):
    name: str
    label: str
    type: str = 'text'
    source: str = 'photo'  # 'user' properties are typed in by the user as job facts.


class Link(BaseModel):
    name: str
    target: str  # A type name, or several joined with ' | '.

    def targets(self):
        return [part.strip() for part in self.target.split('|') if part.strip()]


class ObjectType(BaseModel):
    name: str
    label: str
    description: str = ''
    properties: list[Property] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)


class SystemLink(BaseModel):
    """A link from an engine-owned type to a domain type, e.g. Photo.shows -> Room."""
    type: str
    name: str
    target: str


class Features(BaseModel):
    link_collection: bool = False  # Yeogi accommodation links only.
    enhance: bool = True
    ai_composition: bool = True
    narration: bool = True


# Engine-owned types: what the photo and video pipelines actually store. Domains link to them, never redefine them.
SYSTEM_TYPES = {
    'photo': [
        ObjectType(name='Photo', label='사진', description='영상에 쓰는 사진 한 장',
                   properties=[Property(name='labels', label='출처 라벨')]),
        ObjectType(name='Scene', label='장면', description='내레이션 한두 문장과 그동안 보이는 연속된 사진 1~3장',
                   properties=[Property(name='text', label='내레이션·자막')], links=[Link(name='photos', target='Photo')]),
        ObjectType(name='MotionClip', label='움직임 클립', description='연속된 사진 3~4장을 하드 컷으로 잇는 AI 영상 클립',
                   properties=[Property(name='prompt', label='영어 움직임 프롬프트')], links=[Link(name='photos', target='Photo')]),
    ],
    'video': [
        ObjectType(name='SourceVideo', label='소스 영상', description='사용자가 올린 영상 하나. 화면에 박힌 자막·워터마크는 확대로 가린다',
                   properties=[Property(name='duration', label='길이(초)'), Property(name='crop', label='자막 가림 확대·위치')]),
        ObjectType(name='Segment', label='구간', description='장면에 쓰는 소스 영상의 시작~끝 구간',
                   properties=[Property(name='start', label='시작(초)'), Property(name='end', label='끝(초)')],
                   links=[Link(name='source', target='SourceVideo')]),
        ObjectType(name='Scene', label='장면', description='내레이션 한두 문장과 그동안 보이는 연속된 구간 1~3개',
                   properties=[Property(name='text', label='내레이션·자막')], links=[Link(name='segments', target='Segment')]),
    ],
}
# Words that follow the media engine, not the domain; a domain's `ui` may override any of them.
MEDIA_WORDS = {
    'photo': {'noun': '사진', 'unit': '장', 'select': '선택한 사진', 'analyze': '사진 분석 & 대본 만들기 ↗',
              'nav_hint': '←/→ 키로 사진 이동', 'heading': '사진 & 이야기'},
    'video': {'noun': '영상', 'unit': '개', 'select': '선택한 장면', 'analyze': '영상 분석 & 대본 만들기 ↗',
              'nav_hint': '구간 "보기"로 장면 이동', 'heading': '영상 & 이야기'},
}


class Domain(BaseModel):
    id: str
    label: str
    version: str = Field(min_length=1)
    order: int = 100  # Tab order; lower first.
    object_types: list[ObjectType] = Field(min_length=1)
    links_from_system: list[SystemLink] = Field(default_factory=list)
    features: Features = Field(default_factory=Features)
    ui: dict[str, str] = Field(default_factory=dict)
    disclosure: str = ''  # Shown small on the final reel, e.g. an affiliate notice.
    media: Literal['photo', 'video'] = 'photo'  # photo: stills animated by AI clips; video: uploaded clips edited.
    min_media: int = Field(10, ge=1)
    max_media: int = Field(60, ge=1)
    folders: list[str] = Field(default_factory=list, exclude=True)  # Lookup order for skill files, override first.
    overridden: bool = Field(False, exclude=True)

    def skill(self, name: str) -> str:
        for folder in self.folders:
            path = Path(folder) / name
            if path.is_file():
                return path.read_text(encoding='utf-8')
        raise FileNotFoundError(f'{self.id}-shortform에 {name}이 없습니다.')

    def has_skill(self, name: str) -> bool:
        return any((Path(folder) / name).is_file() for folder in self.folders)

    def skill_overridden(self, name: str) -> bool:
        return self.overridden and (Path(self.folders[0]) / name).is_file()

    def facts(self):
        """Properties the user fills in, as (object type, property) pairs."""
        return [(kind, prop) for kind in self.object_types for prop in kind.properties if prop.source == 'user']

    def text(self, key: str, default: str = '') -> str:
        return self.words().get(key, default)

    def words(self) -> dict:
        return {**MEDIA_WORDS[self.media], **self.ui}

    def system_types(self):
        return SYSTEM_TYPES[self.media]

    def required_skills(self):
        if self.media == 'video':
            return ['SKILL_TEXT.md', 'SKILL_EDIT.md']
        names = ['SKILL_TEXT.md', 'SKILL_MOTION.md']
        if self.features.enhance:
            names.append('SKILL_ENHANCE.md')
        if self.features.ai_composition:
            names += ['SKILL_ASSESS.md', 'SKILL_SELECT.md']
        return names

    def check(self) -> tuple[list[str], list[str]]:
        """(errors, warnings) about the schema's structure and skill files; errors make the domain unusable."""
        errors, warnings = [], []
        system = {kind.name for kind in self.system_types()}
        own = [kind.name for kind in self.object_types]
        for name in sorted(system & set(own)):
            errors.append(f'{name}은 엔진이 정의하는 타입이라 domain.json에 다시 쓸 수 없습니다.')
        if len(set(own)) != len(own):
            errors.append('객체 타입 이름이 중복되었습니다.')
        known = system | set(own)
        for kind in self.object_types:
            for link in kind.links:
                for target in link.targets():
                    if target not in known:
                        errors.append(f'{kind.name}.{link.name}의 대상 {target}이 없는 타입입니다.')
            for prop in kind.properties:
                if prop.source not in PROPERTY_SOURCES:
                    warnings.append(f'{kind.name}.{prop.name}의 source "{prop.source}"는 알 수 없는 값입니다.')
        for link in self.links_from_system:
            if link.type not in system:
                errors.append(f'links_from_system의 {link.type}은 이 재료 방식의 시스템 타입이 아닙니다.')
            for target in Link(name=link.name, target=link.target).targets():
                if target not in known:
                    errors.append(f'{link.type}.{link.name}의 대상 {target}이 없는 타입입니다.')
        for key in sorted(set(self.ui) - UI_KEYS):
            warnings.append(f'ui의 "{key}"는 앱이 쓰지 않는 키입니다.')
        if self.min_media > self.max_media:
            errors.append('min_media가 max_media보다 큽니다.')
        if self.media == 'photo' and self.min_media < 2:
            errors.append('사진 방식은 min_media가 2 이상이어야 합니다. 사진 1장으로는 클립 길이 한도(15초)를 넘습니다.')
        for name in self.required_skills():
            if not self.has_skill(name):
                errors.append(f'{self.id}-shortform에 {name}이 없습니다.')
        return errors, warnings


def roots():
    """Built-in skills first, then the data folder's domains (later roots override earlier ones)."""
    return [SKILLS, paths.DATA / 'domains']


def _read(folder: Path, domain_id: str) -> dict:
    value = json.loads((folder / 'domain.json').read_text(encoding='utf-8'))
    if value.get('id') != domain_id:
        raise ValueError(f'{folder.name}/domain.json의 id가 {domain_id}가 아닙니다.')
    return value


def _build(domain_id: str, layers: list[Path]) -> Domain:
    """Merges domain.json top-level keys from built-in to override, then validates the result."""
    value, folders = {}, []
    for folder in layers:
        if (folder / 'domain.json').is_file():
            value.update(_read(folder, domain_id))
        folders.insert(0, str(folder))
    domain = Domain.model_validate(value)
    domain.folders = folders
    domain.overridden = len(layers) > 1
    errors, warnings = domain.check()
    for message in warnings:
        log.warning('%s: %s', domain_id, message)
    if errors:
        raise ValueError(' '.join(errors))
    return domain


@lru_cache(maxsize=None)
def _catalog():
    """id -> Domain for every usable folder, plus the problems found while loading."""
    layers: dict[str, list[Path]] = {}
    for root in roots():
        if not root.is_dir():
            continue
        for folder in sorted(root.glob('*-shortform')):
            if folder.is_dir():
                layers.setdefault(folder.name[:-len('-shortform')], []).append(folder)
    found, problems = {}, {}
    for domain_id, stack in layers.items():
        try:
            found[domain_id] = _build(domain_id, stack)
        except (OSError, ValueError, ValidationError) as error:
            if len(stack) > 1:  # A broken override falls back to the built-in domain.
                try:
                    found[domain_id] = _build(domain_id, stack[:1])
                    problems[domain_id] = f'{domain_id} 덮어쓰기가 맞지 않아 기본값을 사용해요: {error}'
                    continue
                except (OSError, ValueError, ValidationError):
                    pass
            problems[domain_id] = f'{domain_id}-shortform을 쓸 수 없어요: {error}'
    for message in problems.values():
        log.warning(message)
    if 'stay' in found:
        # Both stay categories share schemas, prompts and user overrides.
        stay = found['stay']
        stay.label = '숙소(음성O)'
        silent = stay.model_copy(deep=True)
        silent.id, silent.label, silent.order = 'stay-silent', '숙소(음성X)', stay.order + 1
        silent.features.narration = False
        silent.min_media = 8
        silent.ui['intro'] = '숙소 사진을 넣고, 음성 없이 자막으로 이야기를 전하세요.'
        silent.ui['upload_title'] = '숙소 사진을 넣고 8~10장을 골라 주세요'
        silent.ui['upload_hint'] = '사진 8~10장 · 장당 2초 · 총 16~20초 · JPG, PNG, WebP'
        silent.ui['caption_default'] = '감성 숙소 찾는다면\n댓글 남겨주세요'
        found['stay-silent'] = silent
    return found, problems


def reload():
    _catalog.cache_clear()
    return problems()


def problems() -> dict[str, str]:
    return dict(_catalog()[1])


def ids() -> list[str]:
    found = _catalog()[0]
    return sorted(found, key=lambda domain_id: (found[domain_id].order, domain_id))


def load(domain_id: str = DEFAULT) -> Domain:
    found, broken = _catalog()
    if domain_id not in found:
        raise ValueError(broken.get(domain_id) or f'이 영상 종류({domain_id})가 없어 사용할 수 없어요.')
    return found[domain_id]


def all() -> list[Domain]:
    return [load(domain_id) for domain_id in ids()]


def schema_block(domain: Domain) -> str:
    """The domain's object model (its own types, then the engine's) as a prompt preamble."""
    links = {}
    for link in domain.links_from_system:
        links.setdefault(link.type, []).append(Link(name=link.name, target=link.target))
    lines = [f'<ontology-schema domain="{domain.id}" version="{domain.version}">', f'영상 종류: {domain.label}']
    for kind in domain.object_types + domain.system_types():
        lines.append(f'- {kind.name} ({kind.label}): {kind.description}'.rstrip(': '))
        if kind.properties:
            props = ', '.join(f'{p.name}({p.label}{", 사용자 입력" if p.source == "user" else ""})' for p in kind.properties)
            lines.append(f'  속성: {props}')
        every = kind.links + links.get(kind.name, [])
        if every:
            lines.append('  링크: ' + ', '.join(f'{link.name} → {link.target}' for link in every))
    lines.append('</ontology-schema>')
    return '\n'.join(lines)


def record(domain: Domain, prompt_parts: list[str], skills: list[str]) -> dict:
    """What a storyboard keeps about the schema and prompt that produced it."""
    digest = hashlib.sha256('\n'.join(prompt_parts).encode('utf-8')).hexdigest()[:16]
    return {'domain': domain.id, 'version': domain.version, 'skill_hash': digest,
            'overridden': any(domain.skill_overridden(name) for name in skills + ['domain.json'])}


def public(domain: Domain) -> dict:
    """What the UI needs: wording, features and the fields the user can fill in."""
    return {'id': domain.id, 'label': domain.label, 'version': domain.version, 'order': domain.order,
            'ui': domain.words(), 'features': domain.features.model_dump(),
            'disclosure': domain.disclosure, 'media': domain.media, 'min_media': domain.min_media,
            'max_media': domain.max_media, 'overridden': domain.overridden,
            'facts': [{'key': prop.name, 'label': prop.label, 'object': kind.label} for kind, prop in domain.facts()]}
