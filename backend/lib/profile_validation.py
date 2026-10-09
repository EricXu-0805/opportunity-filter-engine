"""Safe ProfileRequest rejection metadata shared by HTTP route boundaries."""

from fastapi.exceptions import RequestValidationError

from backend.schemas import ProfileRequest


def safe_profile_validation_detail(exc: RequestValidationError, *, profile_root: bool = False) -> dict | None:
    """Never expose Pydantic input, free-form messages, or arbitrary dict keys.

    profile_root identifies routes where the whole body is ProfileRequest.
    Nested profile errors are recognizable without route-specific metadata.
    """
    for error in exc.errors():
        kind = error.get("type")
        context = error.get("ctx") or {}
        if kind in {"profile_input_limit_exceeded", "profile_input_invalid"}:
            field = context.get("field", "profile")
            allowed = {"profile", *(f"profile.{key}" for key in ProfileRequest.model_fields),
                       "profile.hard_skills.name", "profile.hard_skills.level", "profile.hard_skills.source"}
            detail = {"code": kind.upper(), "field": field if field in allowed else "profile",
                      "message": "Profile input exceeds the supported limit." if kind == "profile_input_limit_exceeded" else "Profile input is invalid.",
                      "retryable": False}
            if kind == "profile_input_limit_exceeded":
                detail.update({key: context[key] for key in ("actual", "limit", "unit")})
            return detail
        if kind == "student_name_required":
            continue
        loc = list(error.get("loc") or ())
        if not loc or loc[0] != "body":
            continue
        path = loc[1:]
        if path and path[0] == "profile":
            path = path[1:]
        elif not profile_root:
            continue
        first = path[0] if path else None
        field = f"profile.{first}" if isinstance(first, str) and first in ProfileRequest.model_fields else "profile"
        return {"code": "PROFILE_INPUT_INVALID", "field": field,
                "message": "Profile input is invalid.", "retryable": False}
    return None


# A 422 names its first errors; a longer list says no more.
MAX_VALIDATION_ERRORS = 20


def safe_validation_errors(exc: RequestValidationError) -> list[dict]:
    """Keep standard error categories without reflecting values or unknown keys."""
    return [{"type": error.get("type", "value_error"),
             "loc": [part for part in error.get("loc", ())[:1]
                     if part in {"body", "query", "path", "header", "cookie"}],
             "msg": "Request input is invalid."} for error in exc.errors()[:MAX_VALIDATION_ERRORS]]
