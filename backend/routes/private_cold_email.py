"""Owner-bound private first-contact templates and exact manual draft checks.

This router intentionally has no provider import or AI fallback. It does not
send mail or register a contact event; user-reported historical events retain
the existing separate contact-ledger contract.
"""
import httpx
from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import ValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from backend.lib.private_email_context import resolve_private_email_context
from backend.lib.private_email_drafting import template_variants, validate_manual
from backend.lib.private_email_schema import (
    PrivateEmailRequest,
    PrivateEmailValidationRequest,
    PrivateEmailValidationResponse,
    PrivateEmailVariantsResponse,
)
from backend.lib.private_import_targets_schema import PRIVATE, PrivateTargetError
from backend.lib.profile_validation import safe_profile_validation_detail


class PrivateEmailRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                return await original(request)
            except PrivateTargetError as exc:
                return JSONResponse({'detail': {'code': exc.code}}, status_code=exc.status, headers=PRIVATE)
            except RequestValidationError as exc:
                # A fixed schema-owned error, never raw input, arbitrary keys,
                # dynamic validator messages or private exception context.
                detail = safe_profile_validation_detail(exc)
                if detail is None:
                    known = {'private_email_context_unsupported', 'student_name_required', 'private_email_draft_limit'}
                    code = next((error['type'] for error in exc.errors() if error.get('type') in known), 'private_email_invalid_request')
                    detail = {'code': code}
                return JSONResponse({'detail': detail}, status_code=422, headers=PRIVATE)
            except (ValidationError, ValueError, UnicodeError, RecursionError):
                return JSONResponse({'detail': {'code': 'private_email_invalid_request'}}, status_code=422, headers=PRIVATE)
            except HTTPException as exc:
                code = 'private_target_too_large' if exc.status_code == 413 else 'private_email_invalid_request'
                return JSONResponse({'detail': {'code': code}}, status_code=exc.status_code, headers=PRIVATE)
            except (httpx.HTTPError, TimeoutError, OSError):
                return JSONResponse({'detail': {'code': 'private_target_unavailable'}}, status_code=503, headers=PRIVATE)

        return handler


router = APIRouter(prefix='/private-import-targets', route_class=PrivateEmailRoute)


async def _context(target_id: str, data: PrivateEmailRequest, request: Request) -> dict:
    if request.query_params:
        raise PrivateTargetError('private_email_invalid_request', 422)
    context = await resolve_private_email_context(
        target_id, authorization=request.headers.get('authorization'),
        expected_owner_id=data.expected_owner_id, expected_writing_version=data.expected_target_version)
    if data.engine != 'template':
        raise PrivateTargetError('private_email_ai_unavailable', 409)
    return context


@router.post('/{target_id}/cold-email/variants')
async def variants(target_id: str, data: PrivateEmailRequest, request: Request):
    context = await _context(target_id, data, request)
    if context['contact_policy']['state'] == 'blocked':
        raise PrivateTargetError('private_email_contact_blocked', 409)
    response = PrivateEmailVariantsResponse.model_validate(template_variants(data, context))
    return JSONResponse(response.model_dump(mode='json'), headers=PRIVATE)


@router.post('/{target_id}/cold-email/validate')
async def validate(target_id: str, data: PrivateEmailValidationRequest, request: Request):
    context = await _context(target_id, data, request)
    response = PrivateEmailValidationResponse.model_validate(validate_manual(data, context))
    return JSONResponse(response.model_dump(mode='json'), headers=PRIVATE)
