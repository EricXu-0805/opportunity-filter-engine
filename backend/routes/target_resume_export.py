"""Private, ephemeral file rendering. No model, persistence, or target lookup."""
from __future__ import annotations

from time import monotonic

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.responses import JSONResponse, Response

from backend.lib.blocking import LOCAL_WORK_TIMEOUT_SECONDS, BlockingWorkOverloaded, BlockingWorkTimeout, run_blocking
from backend.lib.target_resume_export import render_export
from backend.lib.target_resume_export_schema import MAX_FILE_BYTES, MIME, TEMPLATE, ExportError, ExportRequest

PRIVATE = {'Cache-Control': 'private, no-store, max-age=0', 'Pragma': 'no-cache'}
ERROR_STATUS = {'invalid_export_signature': 422, 'invalid_export_text': 422, 'empty_document': 422,
                'unsupported_glyph': 422, 'fonts_unavailable': 503, 'export_too_large': 413, 'export_timeout': 504}


class ExportRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                return await original(request)
            except RequestValidationError as exc:
                # Pydantic's default response includes input values, including
                # private text and unpaired surrogates that cannot be encoded.
                code = 'invalid_export_request'
                for error in exc.errors():
                    cause = error.get('ctx', {}).get('error')
                    if isinstance(cause, ExportError) and str(cause) in ERROR_STATUS:
                        code = str(cause)
                        break
                return JSONResponse({'detail': {'code': code}}, status_code=ERROR_STATUS.get(code, 422), headers=PRIVATE)
            except HTTPException as exc:
                return JSONResponse({'detail': exc.detail}, status_code=exc.status_code, headers=PRIVATE)
        return handler


router = APIRouter(route_class=ExportRoute)


@router.post('/resume/full-target/export')
async def full_target_export(request: ExportRequest):
    try:
        request.verify_signature()
        # The worker checks its own deadline, including queue wait, before the
        # outer bridge timeout. Cancelling a Future cannot kill a running thread.
        deadline = monotonic() + LOCAL_WORK_TIMEOUT_SECONDS - min(1.0, LOCAL_WORK_TIMEOUT_SECONDS / 10)
        data = await run_blocking(render_export, request.projection.model_dump(), request.format,
                                  deadline=deadline, timeout_seconds=LOCAL_WORK_TIMEOUT_SECONDS)
        if not data or len(data) > MAX_FILE_BYTES:
            raise ExportError('export_too_large')
    except ExportError as exc:
        code = str(exc) if str(exc) in ERROR_STATUS else 'export_failed'
        raise HTTPException(ERROR_STATUS.get(code, 500), detail={'code': code}) from None
    except BlockingWorkOverloaded:
        raise HTTPException(503, detail={'code': 'export_overloaded'}) from None
    except BlockingWorkTimeout:
        raise HTTPException(504, detail={'code': 'export_timeout'}) from None
    except Exception:
        # Renderer exceptions can contain document text. Never return/log them.
        raise HTTPException(500, detail={'code': 'export_failed'}) from None
    return Response(data, media_type=MIME[request.format], headers={
        **PRIVATE, 'Content-Disposition': f'attachment; filename="resume.{request.format}"',
        'x-ofe-export-request': request.request_id, 'x-ofe-document-signature': request.document_signature,
        'x-ofe-export-signature': request.export_signature, 'x-ofe-export-template': TEMPLATE,
    })
