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
