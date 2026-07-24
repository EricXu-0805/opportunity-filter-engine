"""ASGI-level request body limits run before FastAPI/Pydantic parsing."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from backend.main import (
    DEFAULT_MAX_REQUEST_BODY_BYTES,
    MAX_CONFIGURABLE_REQUEST_BODY_BYTES,
    RequestBodyLimitMiddleware,
    _request_body_limit_from_env,
    app,
)


def _invoke(
    *,
    limit: int,
    chunks: list[tuple[bytes, bool]],
    content_length: bytes | None = None,
    duplicate_content_lengths: list[bytes] | None = None,
    method: str = "POST",
) -> tuple[list[dict], dict]:
    """Run the middleware with deterministic ASGI request chunks."""
    sent: list[dict] = []
    state = {"receive_calls": 0, "downstream_completed": False}
    messages = [
        {"type": "http.request", "body": body, "more_body": more}
        for body, more in chunks
    ]
    if not messages:
        messages = [{"type": "http.request", "body": b"", "more_body": False}]

    async def receive():
        state["receive_calls"] += 1
        if messages:
            return messages.pop(0)
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    async def downstream(_scope, limited_receive, limited_send):
        # Mirrors how FastAPI consumes a body: read chunks until the last one.
        while True:
            message = await limited_receive()
            if message["type"] != "http.request" or not message.get("more_body", False):
                break
        state["downstream_completed"] = True
        await limited_send(
            {"type": "http.response.start", "status": 200, "headers": []}
        )
        await limited_send(
            {"type": "http.response.body", "body": b"ok", "more_body": False}
        )

    headers = []
    if content_length is not None:
        headers.append((b"content-length", content_length))
    if duplicate_content_lengths:
        headers.extend(
            (b"content-length", value) for value in duplicate_content_lengths
        )
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": "/test",
        "raw_path": b"/test",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 443),
    }

    asyncio.run(
        RequestBodyLimitMiddleware(downstream, max_bytes=limit)(scope, receive, send)
    )
    return sent, state


def _status(messages: list[dict]) -> int:
    return next(message["status"] for message in messages if message["type"] == "http.response.start")


def _response_headers(messages: list[dict]) -> dict[bytes, bytes]:
    start = next(
        message for message in messages if message["type"] == "http.response.start"
    )
    return dict(start["headers"])


class TestRequestBodyLimitMiddleware:
    def test_rejects_oversized_content_length_without_reading_body(self):
        messages, state = _invoke(
            limit=8,
            chunks=[(b"not-read", False)],
            content_length=b"9",
        )

        assert _status(messages) == 413
        assert _response_headers(messages)[b"connection"] == b"close"
        assert state["receive_calls"] == 0
        assert state["downstream_completed"] is False

    def test_counts_chunked_body_cumulatively(self):
        messages, state = _invoke(
            limit=6,
            chunks=[(b"abc", True), (b"defg", False)],
        )

        assert _status(messages) == 413
        assert _response_headers(messages)[b"connection"] == b"close"
        assert state["receive_calls"] == 2
        assert state["downstream_completed"] is False

    def test_allows_body_exactly_at_limit(self):
        messages, state = _invoke(
            limit=6,
            chunks=[(b"abc", True), (b"def", False)],
        )

        assert _status(messages) == 200
        assert state["downstream_completed"] is True

    def test_get_without_body_is_unchanged(self):
        messages, state = _invoke(limit=6, chunks=[], method="GET")

        assert _status(messages) == 200
        assert state["downstream_completed"] is True

    def test_invalid_content_length_is_rejected_before_downstream(self):
        messages, state = _invoke(
            limit=8,
            chunks=[(b"ignored", False)],
            content_length=b"not-a-number",
        )

        assert _status(messages) == 400
        assert _response_headers(messages)[b"connection"] == b"close"
        assert state["receive_calls"] == 0
        assert state["downstream_completed"] is False

    def test_duplicate_content_length_is_rejected_even_when_values_match(self):
        messages, state = _invoke(
            limit=8,
            chunks=[(b"ignored", False)],
            duplicate_content_lengths=[b"7", b"7"],
        )

        assert _status(messages) == 400
        assert _response_headers(messages)[b"connection"] == b"close"
        assert state["receive_calls"] == 0
        assert state["downstream_completed"] is False

    def test_dishonest_declared_length_is_caught_by_the_counter(self):
        # Declared 4 bytes (under the limit) but streams 10: the counting
        # receive wrapper — not the header check — must trip the 413.
        messages, state = _invoke(
            limit=8,
            chunks=[(b"abcde", True), (b"fghij", False)],
            content_length=b"4",
        )

        assert _status(messages) == 413
        assert state["downstream_completed"] is False


class TestRequestBodyLimitConfiguration:
    def test_valid_env_override(self, monkeypatch):
        monkeypatch.setenv("OFE_MAX_REQUEST_BODY_BYTES", "2048")
        assert _request_body_limit_from_env() == 2048

    def test_unset_env_uses_default(self, monkeypatch):
        monkeypatch.delenv("OFE_MAX_REQUEST_BODY_BYTES", raising=False)
        assert _request_body_limit_from_env() == DEFAULT_MAX_REQUEST_BODY_BYTES

    def test_invalid_nonpositive_or_excessive_values_fail_safe(self, monkeypatch):
        for value in (
            "not-an-int",
            "0",
            "-1",
            str(MAX_CONFIGURABLE_REQUEST_BODY_BYTES + 1),
        ):
            monkeypatch.setenv("OFE_MAX_REQUEST_BODY_BYTES", value)
            assert _request_body_limit_from_env() == DEFAULT_MAX_REQUEST_BODY_BYTES


def test_real_app_rejects_oversized_declared_body():
    body = b"{" + b"x" * DEFAULT_MAX_REQUEST_BODY_BYTES + b"}"
    response = TestClient(app).post(
        "/api/import-text",
        content=body,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "Request body too large"


def test_real_app_rejects_oversized_chunked_body():
    # No Content-Length: an iterable body goes out chunked, so only the
    # counting receive wrapper can stop it.
    def chunks():
        for _ in range(18):
            yield b"x" * 65536

    response = TestClient(app).post(
        "/api/import-text",
        content=chunks(),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "Request body too large"


def test_real_app_get_probe_still_works():
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200


def test_real_app_small_body_reaches_pydantic_validation():
    response = TestClient(app).post("/api/import-text", json={"text": "short"})
    assert response.status_code == 422
