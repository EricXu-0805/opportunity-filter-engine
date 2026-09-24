"""Exercise the installed SDK entirely through an in-memory HTTP transport."""
from __future__ import annotations

import logging

import httpx
import openai
import pytest

from backend.lib import llm


@pytest.mark.parametrize("private", [True, False])
def test_private_error_logging_suppresses_prompt_and_provider_echo_only_for_opt_in(monkeypatch, caplog, private):
    secret = "PRIVATE_RESUME_TEXT_AND_PROVIDER_ECHO"
    seen = []
    spends = []

    def respond(request):
        seen.append(request)
        return httpx.Response(400, json={"error": {"message": secret, "type": "invalid_request_error"}})

    original_client = openai.OpenAI
    transport = httpx.MockTransport(respond)
    clients = []

    def local_client(**kwargs):
        client = original_client(**kwargs, http_client=httpx.Client(transport=transport))
        clients.append(client)
        return client

    monkeypatch.setattr(openai, "OpenAI", local_client)
    monkeypatch.setattr(llm, "_resolve", lambda _: llm._ResolvedProvider("test", "fake", "https://provider.invalid", "test"))
    monkeypatch.setattr(llm.time, "sleep", lambda _: None)
    monkeypatch.setattr(llm.llm_budget, "spend", lambda: spends.append(1))
    caplog.set_level(logging.DEBUG)
    try:
        assert llm.chat_completion([{"role": "user", "content": secret}], safe_error_logging=private) is None
        assert len(seen) == len(spends) == 2
        assert all(secret.encode() in request.content for request in seen)
        if private:
            assert secret not in caplog.text
            assert "BadRequestError" in caplog.text and "status=400" in caplog.text
        else:
            assert secret in caplog.text
    finally:
        for client in clients:
            client.close()
    # Per-call suppression must not leak into another worker/call afterwards.
    assert llm._PRIVATE_PROVIDER_LOGGING.get() is False
