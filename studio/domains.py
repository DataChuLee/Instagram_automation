"""Domain schemas: the object types, UI wording and features of each short-form kind (stay, shopping).

Each `studio/skills/<domain>-shortform/domain.json` describes one domain; its skill files hold the prompts.
Jobs keep the domain they were created with, and everything domain-specific is read from here.
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field

from .paths import RESOURCES

DOMAINS = ('stay', 'shopping')
SKILLS = RESOURCES / 'studio/skills'


class Property(BaseModel):
    name: str
    label: str
    type: str = 'text'
    source: Literal['photo', 'user'] = 'photo'  # 'user' properties are typed in by the user as job facts.


class Link(BaseModel):
    name: str
    target: str


class ObjectType(BaseModel):
    name: str
    label: str
    description: str = ''
    properties: list[Property] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)


class Features(BaseModel):
    link_collection: bool = False
    enhance: bool = True
    ai_composition: bool = True


class Domain(BaseModel):
    id: str
    label: str
    object_types: list[ObjectType] = Field(min_length=1)
    features: Features = Field(default_factory=Features)
    ui: dict[str, str] = Field(default_factory=dict)
    disclosure: str = ''  # Shown small on the final reel, e.g. an affiliate notice.
    media: Literal['photo', 'video'] = 'photo'  # photo: stills animated by AI clips; video: uploaded clips edited.
    min_media: int = Field(10, ge=1)
    max_media: int = Field(60, ge=1)

    @property
    def folder(self):
        return SKILLS / f'{self.id}-shortform'

    def skill(self, name: str) -> str:
        return (self.folder / name).read_text(encoding='utf-8')

    def facts(self):
        """Properties the user fills in, as (object type, property) pairs."""
        return [(kind, prop) for kind in self.object_types for prop in kind.properties if prop.source == 'user']

    def text(self, key: str, default: str = '') -> str:
        return self.ui.get(key, default)


@lru_cache(maxsize=None)
def load(domain_id: str = 'stay') -> Domain:
    if domain_id not in DOMAINS:
        raise ValueError('지원하지 않는 영상 종류입니다.')
    folder = SKILLS / f'{domain_id}-shortform'
    domain = Domain.model_validate(json.loads((folder / 'domain.json').read_text(encoding='utf-8')))
    if domain.id != domain_id:
        raise ValueError(f'{folder.name}/domain.json의 id가 {domain_id}가 아닙니다.')
    return domain


def all() -> list[Domain]:
    return [load(domain_id) for domain_id in DOMAINS]


def schema_block(domain: Domain) -> str:
    """The domain's object model as a prompt preamble, so the model reads types instead of guessing them."""
    lines = [f'<ontology-schema domain="{domain.id}">', f'영상 종류: {domain.label}']
    for kind in domain.object_types:
        lines.append(f'- {kind.name} ({kind.label}): {kind.description}'.rstrip(': '))
        if kind.properties:
            props = ', '.join(f'{p.name}({p.label}{", 사용자 입력" if p.source == "user" else ""})' for p in kind.properties)
            lines.append(f'  속성: {props}')
        if kind.links:
            lines.append('  링크: ' + ', '.join(f'{link.name} → {link.target}' for link in kind.links))
    lines.append('</ontology-schema>')
    return '\n'.join(lines)


def public(domain: Domain) -> dict:
    """What the UI needs: wording, features and the fields the user can fill in."""
    return {'id': domain.id, 'label': domain.label, 'ui': domain.ui, 'features': domain.features.model_dump(),
            'disclosure': domain.disclosure, 'media': domain.media, 'min_media': domain.min_media,
            'max_media': domain.max_media,
            'facts': [{'key': prop.name, 'label': prop.label, 'object': kind.label} for kind, prop in domain.facts()]}
