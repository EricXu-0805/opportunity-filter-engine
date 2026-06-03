"""Shared LLM provider chain for backend routes.

Two route handlers (``backend/routes/matches.py::_llm_explanation`` and
``backend/routes/opportunities.py::_llm_chat_call``) used to maintain
near-identical copies of the provider-selection + chat-completion logic.
This module consolidates them so adding a fourth provider, changing the
default model, or wiring up retry/observability happens in one place.

Provider chain (same as the historical inline copies):
  1. ``OPENAI_API_KEY``     → ``gpt-4o-mini`` against api.openai.com
  2. ``GEMINI_API_KEY``     → ``gemini-2.5-flash`` via Google's
                              OpenAI-compatible v1beta endpoint
  3. ``OPENROUTER_API_KEY`` → ``google/gemini-2.0-flash-lite-001``
                              via openrouter.ai

Gemini models need ``reasoning_effort: none`` in ``extra_body`` or they
default to extended thinking and blow past ``max_tokens`` with reasoning
tokens that never reach the user. We attach it automatically.

All public functions return ``None`` on any failure (no provider configured,
SDK missing, network error, model refusal). Callers should fall back to a
local template — never raise from a chat-completion attempt.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("ofe.llm")

_MAX_ATTEMPTS = 2
_RETRY_BASE_DELAY_SECONDS = 0.5
_REQUEST_TIMEOUT_SECONDS = 20.0

_PROVIDERS: tuple[tuple[str, str, str], ...] = (
    ("OPENAI_API_KEY", "", "gpt-4o-mini"),
    (
        "GEMINI_API_KEY",
        "https://generativelanguage.googleapis.com/v1beta/openai/",
        "gemini-2.5-flash",
    ),
    (
        "OPENROUTER_API_KEY",
        "https://openrouter.ai/api/v1",
        "google/gemini-2.0-flash-lite-001",
    ),
)


@dataclass(frozen=True)
class _ResolvedProvider:
    api_key: str
    base_url: str
    model: str


def _resolve() -> Optional[_ResolvedProvider]:
    for env_var, base_url, model in _PROVIDERS:
        api_key = os.environ.get(env_var)
        if api_key:
            return _ResolvedProvider(api_key=api_key, base_url=base_url, model=model)
    return None


def chat_completion(
    messages: list[dict],
    *,
    max_tokens: int = 400,
    temperature: float = 0.4,
    reasoning_effort: str = "none",
) -> Optional[str]:
    """Single-turn chat completion against the first configured provider.

    Returns the assistant text, or ``None`` when:
      * no provider env var is set,
      * the ``openai`` SDK isn't importable,
      * the upstream call raises for any reason.

    Callers should treat ``None`` as "fall back to local template" — never
    surface as a 5xx to the user. The provider chain is order-dependent;
    see ``_PROVIDERS`` for the canonical priority.
    """
    provider = _resolve()
    if provider is None:
        return None

    try:
        import openai
    except ImportError:
        return None

    client_kwargs: dict = {"api_key": provider.api_key, "timeout": _REQUEST_TIMEOUT_SECONDS}
    if provider.base_url:
        client_kwargs["base_url"] = provider.base_url

    call_kwargs: dict = {
        "model": provider.model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if provider.model.startswith("gemini-"):
        call_kwargs["extra_body"] = {"reasoning_effort": reasoning_effort}

    last_error: Optional[Exception] = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            client = openai.OpenAI(**client_kwargs)
            resp = client.chat.completions.create(**call_kwargs)
            text = (resp.choices[0].message.content or "").strip()
            return text or None
        except Exception as exc:
            last_error = exc
            if attempt < _MAX_ATTEMPTS:
                time.sleep(_RETRY_BASE_DELAY_SECONDS * attempt)

    logger.warning(
        "LLM chat_completion failed after %d attempt(s) (model=%s): %s",
        _MAX_ATTEMPTS,
        provider.model,
        last_error,
    )
    return None


def is_configured() -> bool:
    """True iff at least one supported LLM provider env var is set.

    Cheap synchronous check — does not contact the network. Useful for
    health endpoints and feature-flag UI that wants to hide an "Ask AI"
    button when nothing is wired.
    """
    return _resolve() is not None
