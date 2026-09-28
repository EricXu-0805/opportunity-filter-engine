"""Explicit user-reviewed supporting-source selection, bound by document digest."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ResumeSupportGroup(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    unit_id: str = Field(min_length=1, max_length=80)
    support_unit_ids: list[str] = Field(min_length=1, max_length=24)
    confirmed: Literal[True]

    @field_validator('confirmed', mode='before')
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError('support_confirmation_required')
        return value
