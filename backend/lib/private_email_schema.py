"""Provider-free private first-contact input and receipt shapes."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

from backend.lib.private_import_targets_schema import Scope
from backend.schemas import (
    EmailContactContext,
    EmailContactReceipt,
    ExperienceEvidence,
    ExperienceUsage,
    ProfileRequest,
)


class PrivateEmailRequest(Scope):
    expected_target_version: str = Field(pattern=r"^pwt1:[0-9a-f]{64}$", min_length=69, max_length=69)
    profile: ProfileRequest
    experience_evidence: ExperienceEvidence | None = None
    contact_context: EmailContactContext | None = None
    engine: Literal['template', 'ai'] = 'template'

    @field_validator('contact_context', mode='before')
    @classmethod
    def first_contact_only(cls, value):
        if isinstance(value, dict) and (value.get('purpose') not in (None, 'first_contact')
                                      or any(value.get(key) is not None for key in ('paper_reading', 'referral', 'follow_up'))):
            raise PydanticCustomError('private_email_context_unsupported', 'private_email_context_unsupported')
        return value

    @field_validator('profile')
    @classmethod
    def student_name(cls, value):
        if not value.name.strip():
            raise PydanticCustomError('student_name_required', 'student_name_required')
        return value.model_copy(update={'name': value.name.strip()})


class PrivateEmailValidationRequest(PrivateEmailRequest):
    subject: str
    body: str
    recipient: str = Field(default='', max_length=320)
    contact_requirements_reviewed: bool = False

    @field_validator('subject', 'body')
    @classmethod
    def draft_limits(cls, value, info):
        try:
            size = len(value.encode('utf-16-le')) // 2
        except UnicodeError:
            raise ValueError('Invalid draft Unicode') from None
        limit = 2000 if info.field_name == 'subject' else 5000
        if '\0' in value or size > limit:
            raise PydanticCustomError('private_email_draft_limit', 'private_email_draft_limit')
        return value

    @field_validator('recipient')
    @classmethod
    def valid_unicode(cls, value):
        value.encode('utf-8')
        return value


class PrivateEmailBinding(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: Literal[1] = 1
    target_scope: Literal['private_import'] = 'private_import'
    verification: Literal['unverified'] = 'unverified'
    owner_id: str
    opportunity_id: str
    target_version: str
    source_version: str
    private_context: dict
    pipeline_version: Literal['private-cold-email-v1'] = 'private-cold-email-v1'
    contact_context_receipt: EmailContactReceipt
    target_conditions: dict


class PrivateEmailVariant(BaseModel):
    id: Literal['private-first-contact'] = 'private-first-contact'
    label: Literal['First contact'] = 'First contact'
    subject: str
    body: str
    recipient_email: Literal[''] = ''
    mailto_link: Literal[''] = ''
    experience_usage: ExperienceUsage
    contact_context_receipt: EmailContactReceipt
    target_conditions: dict


class PrivateEmailVariantsResponse(PrivateEmailBinding):
    method: Literal['template'] = 'template'
    grounding: Literal['no_target_data'] = 'no_target_data'
    source_freshness: Literal['unknown'] = 'unknown'
    recipient_status: Literal['unavailable'] = 'unavailable'
    recipient_email: Literal[''] = ''
    lab_type: None = None
    recommended_style: Literal['professional'] = 'professional'
    generated_at: str
    experience_usage: ExperienceUsage
    variants: list[PrivateEmailVariant] = Field(min_length=1, max_length=1)


PrivateEmailIssue = Literal[
    'empty_draft', 'invalid_recipient', 'contact_review_required', 'contact_blocked',
    'unsupported_eligibility_claim', 'unsupported_deadline_claim',
    'unsupported_material_claim', 'unsupported_attachment_claim',
]


class PrivateEmailValidationResponse(PrivateEmailBinding):
    outcome: Literal['ready', 'review_required']
    issues: list[PrivateEmailIssue]
