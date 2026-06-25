"""Tests for the shared LLM provider chain — focused on the OFE_STRONG_MODEL
knob and the per-call model override added so quality-sensitive features
(resume tailor, cold email) can run on a stronger model than chat."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import backend.lib.llm as llm

_CAPTURED: dict = {}


class _Msg:
    def __init__(self, content: str):
        self.content = content


class _Choice:
    def __init__(self, content: str):
        self.message = _Msg(content)


class _FakeResp:
    def __init__(self, content: str):
        self.choices = [_Choice(content)]


class _FakeCompletions:
    @staticmethod
    def create(**kwargs):
        _CAPTURED.clear()
        _CAPTURED.update(kwargs)
        return _FakeResp("ok")


class _FakeChat:
    completions = _FakeCompletions()


class _FakeOpenAI:
    def __init__(self, **kwargs):
        self.chat = _FakeChat()


def _use_provider(monkeypatch, env_var: str, value: str = "test-key"):
    for v in ("OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv(env_var, value)
    import openai
    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    _CAPTURED.clear()


class TestStrongModel:
    def test_none_when_unset(self, monkeypatch):
        monkeypatch.delenv("OFE_STRONG_MODEL", raising=False)
        assert llm.strong_model() is None

    def test_returns_value(self, monkeypatch):
        monkeypatch.setenv("OFE_STRONG_MODEL", "gemini-3.1-pro")
        assert llm.strong_model() == "gemini-3.1-pro"

    def test_blank_is_none(self, monkeypatch):
        monkeypatch.setenv("OFE_STRONG_MODEL", "   ")
        assert llm.strong_model() is None


class TestModelOverride:
    def test_override_is_passed_to_the_provider(self, monkeypatch):
        _use_provider(monkeypatch, "GEMINI_API_KEY")
        out = llm.chat_completion([{"role": "user", "content": "hi"}], model="gemini-3.1-pro")
        assert out == "ok"
        assert _CAPTURED["model"] == "gemini-3.1-pro"

    def test_default_model_when_no_override(self, monkeypatch):
        _use_provider(monkeypatch, "GEMINI_API_KEY")
        llm.chat_completion([{"role": "user", "content": "hi"}])
        assert _CAPTURED["model"] == "gemini-2.5-flash"

    def test_none_override_falls_back_to_default(self, monkeypatch):
        # strong_model() returns None when unset; that must mean "default", not
        # a literal model named None.
        _use_provider(monkeypatch, "GEMINI_API_KEY")
        llm.chat_completion([{"role": "user", "content": "hi"}], model=None)
        assert _CAPTURED["model"] == "gemini-2.5-flash"

    def test_gemini_reasoning_effort_keys_off_effective_model(self, monkeypatch):
        # a strong GEMINI override still needs reasoning_effort:none or it burns
        # max_tokens on hidden extended thinking.
        _use_provider(monkeypatch, "GEMINI_API_KEY")
        llm.chat_completion([{"role": "user", "content": "hi"}], model="gemini-3.1-pro")
        assert _CAPTURED.get("extra_body", {}).get("reasoning_effort") == "none"

    def test_non_gemini_override_sends_no_extra_body(self, monkeypatch):
        _use_provider(monkeypatch, "OPENAI_API_KEY")
        llm.chat_completion([{"role": "user", "content": "hi"}], model="gpt-5.5")
        assert _CAPTURED["model"] == "gpt-5.5"
        assert "extra_body" not in _CAPTURED


class TestProviderTargeting:
    def test_provider_id_targets_openrouter(self, monkeypatch):
        # GEMINI is first in the chain, but provider_id="openrouter" must route
        # to OpenRouter (its key is also set here).
        for v in ("OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
            monkeypatch.setenv(v, "test-key")
        import openai
        monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
        _CAPTURED.clear()
        out = llm.chat_completion(
            [{"role": "user", "content": "hi"}],
            model="meta-llama/llama-3.3-70b-instruct",
            provider_id="openrouter",
        )
        assert out == "ok"
        assert _CAPTURED["model"] == "meta-llama/llama-3.3-70b-instruct"

    def test_provider_id_unconfigured_returns_none(self, monkeypatch):
        # Only GEMINI set; asking for openrouter must not silently use gemini.
        for v in ("OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
            monkeypatch.delenv(v, raising=False)
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        out = llm.chat_completion(
            [{"role": "user", "content": "hi"}],
            model="google/gemini-2.0-flash-001", provider_id="openrouter",
        )
        assert out is None


class TestChatModelOptions:
    def test_empty_without_openrouter(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        assert llm.chat_model_options() == []
        assert llm.chat_model_slug("gemini-flash") is None

    def test_default_list_when_openrouter_set(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        monkeypatch.delenv("OFE_CHAT_MODELS", raising=False)
        opts = llm.chat_model_options()
        ids = {o["id"] for o in opts}
        assert "gemini-flash" in ids
        assert all("label" in o and "id" in o for o in opts)
        # slug is resolvable server-side but never leaked in the public list.
        assert all("slug" not in o for o in opts)
        assert llm.chat_model_slug("gemini-flash") == "google/gemini-2.5-flash"

    def test_unknown_id_has_no_slug(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        assert llm.chat_model_slug("not-a-real-id") is None

    def test_env_override_parses_pipe_format(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        monkeypatch.setenv("OFE_CHAT_MODELS", "x|X Model|vendor/x-1, bad-entry, y|Y|vendor/y-2")
        opts = llm.chat_model_options()
        assert [o["id"] for o in opts] == ["x", "y"]
        assert llm.chat_model_slug("x") == "vendor/x-1"

    def test_all_malformed_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        monkeypatch.setenv("OFE_CHAT_MODELS", "garbage,more-garbage")
        ids = {o["id"] for o in llm.chat_model_options()}
        assert "gemini-flash" in ids  # default table

    def test_default_models_are_only_disclosed_us_providers(self, monkeypatch):
        # Privacy invariant: the default Ask-AI picker must route only to the
        # vetted, US-operated providers named in the privacy policy (OpenAI,
        # Google, Anthropic). The chat prompt carries profile PII incl. the F-1
        # flag, so a China-based / undisclosed provider must never slip into the
        # default set.
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        monkeypatch.delenv("OFE_CHAT_MODELS", raising=False)
        slugs = [llm.chat_model_slug(o["id"]) for o in llm.chat_model_options()]
        assert slugs and all(
            s.startswith(("openai/", "google/", "anthropic/")) for s in slugs
        ), slugs


class TestModelFor:
    def _clear(self, monkeypatch):
        for v in ("OPENROUTER_API_KEY", "OFE_STRONG_MODEL",
                  "OFE_MODEL_COLD_EMAIL", "OFE_MODEL_TAILOR"):
            monkeypatch.delenv(v, raising=False)

    def test_routes_to_openrouter_best_fit_when_configured(self, monkeypatch):
        self._clear(monkeypatch)
        monkeypatch.setenv("OPENROUTER_API_KEY", "k")
        assert llm.model_for("cold_email") == {
            "provider_id": "openrouter",
            "model": "anthropic/claude-sonnet-4.6",
        }

    def test_per_task_env_override(self, monkeypatch):
        self._clear(monkeypatch)
        monkeypatch.setenv("OPENROUTER_API_KEY", "k")
        monkeypatch.setenv("OFE_MODEL_COLD_EMAIL", "anthropic/claude-opus-4.8")
        out = llm.model_for("cold_email")
        assert out["provider_id"] == "openrouter"
        assert out["model"] == "anthropic/claude-opus-4.8"

    def test_falls_back_to_strong_model_without_openrouter(self, monkeypatch):
        self._clear(monkeypatch)
        monkeypatch.setenv("OFE_STRONG_MODEL", "gemini-2.5-pro")
        out = llm.model_for("cold_email")
        assert out == {"model": "gemini-2.5-pro"}
        assert "provider_id" not in out

    def test_unknown_task_without_openrouter_uses_strong_model(self, monkeypatch):
        self._clear(monkeypatch)
        assert llm.model_for("nonsense") == {"model": None}
