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
tokens that never reach the user. We attach it automatically (keyed on the
effective model, so an overridden strong model still gets it).

Quality-sensitive features (resume tailoring, cold email) can opt into a
stronger model than the cheap default via the ``OFE_STRONG_MODEL`` env var —
see ``strong_model()``. It must name a model the *active* provider serves (a
Gemini id when GEMINI_API_KEY is resolved, a GPT id when OPENAI_API_KEY, etc.);
when unset, those features use the provider's default model unchanged.

The Ask-AI chat, by contrast, can let the user pick among a few OpenRouter
models (``chat_model_options`` / ``chat_model_slug`` + ``OFE_CHAT_MODELS``);
``chat_completion(provider_id="openrouter", model=slug)`` routes one call to a
specific provider instead of the chain's first.

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

# (id, env_var, base_url, default_model). The id lets a caller target a
# specific provider (e.g. the Ask-AI chat picker routes through "openrouter").
_PROVIDERS: tuple[tuple[str, str, str, str], ...] = (
    ("openai", "OPENAI_API_KEY", "", "gpt-4o-mini"),
    (
        "gemini",
        "GEMINI_API_KEY",
        "https://generativelanguage.googleapis.com/v1beta/openai/",
        "gemini-2.5-flash",
    ),
    (
        "openrouter",
        "OPENROUTER_API_KEY",
        "https://openrouter.ai/api/v1",
        "google/gemini-2.0-flash-lite-001",
    ),
)

# Ask-AI chat lets the user pick among a few OpenRouter models (the formal
# flows — résumé tailoring, cold email — stay pinned to strong_model()). The
# default set is deliberately restricted to vetted, US-operated providers
# (OpenAI, Google) that the privacy policy names as subprocessors — the chat
# prompt embeds profile PII incl. the international-student flag, so we do NOT
# default-route F-1 users' data to undisclosed / non-US operators (e.g. DeepSeek
# was dropped for this reason). Still env-overridable via OFE_CHAT_MODELS
# ("id|label|slug,...") so a stale slug is fixable without a deploy; if you add a
# model from a new provider here or via env, disclose it in the privacy policy.
# Surfaced ONLY when OPENROUTER_API_KEY is set; otherwise the picker stays hidden
# and chat uses the default provider chain.
_DEFAULT_CHAT_MODELS: tuple[tuple[str, str, str], ...] = (
    ("gemini-flash", "Gemini Flash", "google/gemini-2.5-flash"),
    ("gpt-4o-mini", "GPT-4o mini", "openai/gpt-4o-mini"),
)


@dataclass(frozen=True)
class _ResolvedProvider:
    api_key: str
    base_url: str
    model: str


def _resolve(provider_id: Optional[str] = None) -> Optional[_ResolvedProvider]:
    """First configured provider, or — when ``provider_id`` is given — that
    specific provider only if its key is set (else ``None``)."""
    for pid, env_var, base_url, model in _PROVIDERS:
        if provider_id is not None and pid != provider_id:
            continue
        api_key = os.environ.get(env_var)
        if api_key:
            return _ResolvedProvider(api_key=api_key, base_url=base_url, model=model)
    return None


def _chat_models() -> tuple[tuple[str, str, str], ...]:
    """The (id, label, slug) chat-model table, from OFE_CHAT_MODELS or the
    built-in default. Malformed env entries are skipped; an all-malformed env
    falls back to the default rather than emptying the picker."""
    raw = os.environ.get("OFE_CHAT_MODELS", "").strip()
    if not raw:
        return _DEFAULT_CHAT_MODELS
    parsed: list[tuple[str, str, str]] = []
    for entry in raw.split(","):
        parts = [p.strip() for p in entry.split("|")]
        if len(parts) == 3 and all(parts):
            parsed.append((parts[0], parts[1], parts[2]))
    return tuple(parsed) or _DEFAULT_CHAT_MODELS


def chat_model_options() -> list[dict]:
    """Public chat-model list for the Ask-AI picker: ``[{"id","label"}]``.
    Empty when OPENROUTER_API_KEY is unset, so the UI hides the picker and
    chat stays on the default provider chain."""
    if not os.environ.get("OPENROUTER_API_KEY"):
        return []
    return [{"id": mid, "label": label} for mid, label, _slug in _chat_models()]


def chat_model_slug(model_id: str) -> Optional[str]:
    """Resolve a picker model id → its OpenRouter slug, or ``None`` when the id
    is unknown or OpenRouter isn't configured (caller falls back to default)."""
    if not os.environ.get("OPENROUTER_API_KEY"):
        return None
    for mid, _label, slug in _chat_models():
        if mid == model_id:
            return slug
    return None


def strong_model() -> Optional[str]:
    """The model id quality-sensitive features (resume tailor, cold email)
    should use, from ``OFE_STRONG_MODEL``. ``None`` -> use the active provider's
    default model. Must be a model that provider serves (e.g. a Gemini id when
    GEMINI_API_KEY is the resolved provider, a GPT id when OPENAI_API_KEY)."""
    return os.environ.get("OFE_STRONG_MODEL", "").strip() or None


def chat_completion(
    messages: list[dict],
    *,
    max_tokens: int = 400,
    temperature: float = 0.4,
    reasoning_effort: str = "none",
    model: Optional[str] = None,
    provider_id: Optional[str] = None,
) -> Optional[str]:
    """Single-turn chat completion against the first configured provider.

    ``model`` overrides the provider's default model (used by quality-sensitive
    callers via :func:`strong_model`); it must be a model the resolved provider
    serves. ``provider_id`` targets a specific provider (e.g. ``"openrouter"``
    for the chat model picker) instead of the chain's first — returns ``None``
    if that provider isn't configured. Returns the assistant text, or ``None``
    when:
      * no (matching) provider env var is set,
      * the ``openai`` SDK isn't importable,
      * the upstream call raises for any reason.

    Callers should treat ``None`` as "fall back to local template" — never
    surface as a 5xx to the user. The provider chain is order-dependent;
    see ``_PROVIDERS`` for the canonical priority.
    """
    provider = _resolve(provider_id)
    if provider is None:
        return None

    try:
        import openai
    except ImportError:
        return None

    effective_model = model or provider.model
    client_kwargs: dict = {"api_key": provider.api_key, "timeout": _REQUEST_TIMEOUT_SECONDS}
    if provider.base_url:
        client_kwargs["base_url"] = provider.base_url

    call_kwargs: dict = {
        "model": effective_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if effective_model.startswith("gemini-"):
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
        effective_model,
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
