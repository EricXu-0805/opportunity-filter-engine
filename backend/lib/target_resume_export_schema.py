"""Bounded render-only projection. Signatures bind bytes, not source truth."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TEMPLATE = 'standard-v1'
MAX_PROJECTION_BYTES = 2 * 1024 * 1024
MAX_BODY_BYTES = MAX_PROJECTION_BYTES + 64 * 1024
MAX_FILE_BYTES = 64 * 1024 * 1024
FINGERPRINT = re.compile(r'^v1:sha256:[a-f0-9]{64}$')
ROLES = frozenset(('name', 'email', 'phone', 'location', 'url', 'school', 'degree', 'field', 'start', 'end',
                   'title', 'organization', 'authors', 'venue', 'date', 'publication_status', 'doi', 'experience', 'skill', 'other'))
JS_WHITESPACE = '\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'
MIME = {'pdf': 'application/pdf', 'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}


class ExportError(ValueError):
    """Only stable public codes, never private text or underlying errors."""


def xml_text(value: str) -> str:
    for char in value:
        point = ord(char)
        if not (point in (9, 10, 13) or 0x20 <= point <= 0xD7FF or 0xE000 <= point <= 0xFFFD or 0x10000 <= point <= 0x10FFFF):
            raise ExportError('invalid_export_text')
    return value


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def export_signature(value) -> str:
    return 'v1:sha256:' + hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class ExportLine(StrictModel):
    role: str
    label: str = Field(max_length=120)
    text: str

    @field_validator('role')
    @classmethod
    def valid_role(cls, value):
        if value not in ROLES:
            raise ValueError('invalid_role')
        return value

    @field_validator('label', 'text')
    @classmethod
    def valid_text(cls, value):
        return xml_text(value)


class ExportBlock(StrictModel):
    lines: list[ExportLine] = Field(min_length=1, max_length=600)


class ExportSection(StrictModel):
    kind: Literal['basics', 'education', 'activities', 'publications', 'skills', 'other']
    heading: str = Field(max_length=120)
    blocks: list[ExportBlock] = Field(min_length=1, max_length=600)

    @field_validator('heading')
    @classmethod
    def valid_heading(cls, value):
        return xml_text(value)


class ExportProjection(StrictModel):
    version: Literal[1]
    template: Literal['standard-v1']
    locale: Literal['en', 'zh']
    page_size: Literal['letter', 'a4']
    sections: list[ExportSection] = Field(min_length=1, max_length=305)

    @field_validator('version', mode='before')
    @classmethod
    def strict_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError('invalid_version')
        return value

    @model_validator(mode='after')
    def valid_document(self):
        blocks = [block for section in self.sections for block in section.blocks]
        lines = [line for block in blocks for line in block.lines]
        if len(blocks) > 600 or len(lines) > 600:
            raise ValueError('projection_limit')
        if not any(line.text.strip(JS_WHITESPACE) for line in lines):
            raise ExportError('empty_document')
        if len(canonical(self.model_dump()).encode('utf-8')) > MAX_PROJECTION_BYTES:
            raise ExportError('export_too_large')
        return self


class ExportRequest(StrictModel):
    version: Literal[1]
    request_id: str = Field(pattern=r'^[A-Za-z0-9._:-]{1,80}$')
    format: Literal['pdf', 'docx']
    document_signature: str = Field(pattern=r'^v1:sha256:[a-f0-9]{64}$')
    export_signature: str = Field(pattern=r'^v1:sha256:[a-f0-9]{64}$')
    projection: ExportProjection

    @field_validator('version', mode='before')
    @classmethod
    def strict_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError('invalid_version')
        return value

    def verify_signature(self):
        if export_signature(self.projection.model_dump()) != self.export_signature:
            raise ExportError('invalid_export_signature')
