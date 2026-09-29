"""Bound complete serialized LLM inputs without replacing them with excerpts."""

import json

from fastapi import HTTPException


class PromptInputTooLarge(HTTPException):
    """An input refusal that provider-failure fallbacks must not hide."""


def check_prompt_size(
    messages: list[dict], *, limit: int, code: str, message: str,
) -> None:
    """Count JSON escaping and all roles; never echo source material on failure.

    This is a character limit, not a tokenizer or a model-context guarantee.
    Call before streaming starts or a provider-recovery exception handler.
    """
    serialized = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) > limit:
        raise PromptInputTooLarge(status_code=413, detail={
            "code": code, "message": message, "max_characters": limit, "retryable": False,
        })
