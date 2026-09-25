"""Trust boundaries for durable, opaque PDF cleanup jobs. No real providers."""
from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest

from backend.lib import material_cleanup as worker
from backend.lib.material_archive import MaterialService
from backend.lib.material_archive_schema import MaterialError

MATERIAL = "11111111-1111-4111-8111-111111111111"
CLAIM = "22222222-2222-4222-8222-222222222222"
KEY = f"pdf/{MATERIAL}.pdf"
SERVICE_KEY = "test-service-secret"
URL = "https://storage.invalid"


def job(**changes):
    return {"material_id": MATERIAL, "bucket": "application-materials", "object_key": KEY,
            "claim_token": CLAIM, "claimed_until": "2026-09-25T16:00:00+00:00", **changes}


class CleanupProvider:
    def __init__(self, *, jobs=None, delete_status=200, head_status=404, network_failure=None, accepted=True,
                 fallback_status=400, fallback_body=None, fallback_stream=None):
        self.jobs = [job()] if jobs is None else jobs
        self.delete_status, self.head_status = delete_status, head_status
        self.network_failure, self.accepted = network_failure, accepted
        self.fallback_status = fallback_status
        self.fallback_body = {"statusCode": "404", "error": "not_found", "message": "Object not found"} if fallback_body is None else fallback_body
        self.fallback_stream = fallback_stream
        self.calls = []
        self.acks = []

    def handle(self, request):
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, request.url.path, body))
        # Even if a user Authorization was supplied to MaterialService, cleanup
        # must exclusively use the service role, never a user/anonymous token.
        assert request.headers["authorization"] == f"Bearer {SERVICE_KEY}"
        assert request.headers["apikey"] == SERVICE_KEY
        assert not request.url.query
        if request.url.path == "/rest/v1/rpc/claim_material_cleanup":
            assert body == {"p_limit": 20}
            return httpx.Response(200, json={"jobs": self.jobs})
        if request.url.path == "/rest/v1/rpc/ack_material_cleanup":
            self.acks.append(body)
            return httpx.Response(200, json={"accepted": self.accepted})
        if request.method == "DELETE":
            assert request.url.path == "/storage/v1/object/application-materials"
            assert body == {"prefixes": [KEY]}
            if self.network_failure == "delete":
                raise httpx.ReadTimeout("PRIVATE provider filename=resume.pdf key=test-service-secret")
            return httpx.Response(self.delete_status, json=[] if self.delete_status == 200 else {"error": "PRIVATE"})
        if request.method == "HEAD":
            assert request.url.path == f"/storage/v1/object/application-materials/{KEY}"
            assert body is None
            if self.network_failure == "head":
                raise httpx.ConnectError("PRIVATE provider response")
            return httpx.Response(self.head_status)
        if request.method == "GET":
            assert request.url.path == f"/storage/v1/object/application-materials/{KEY}"
            assert body is None
            if self.network_failure == "get":
                raise httpx.ReadTimeout("PRIVATE error while checking removal")
            if self.fallback_stream is not None:
                return httpx.Response(self.fallback_status, stream=self.fallback_stream)
            if isinstance(self.fallback_body, bytes):
                return httpx.Response(self.fallback_status, content=self.fallback_body)
            return httpx.Response(self.fallback_status, json=self.fallback_body)
        raise AssertionError(f"unexpected cleanup operation: {request.method} {request.url.path}")


def cleanup(provider):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider.handle), follow_redirects=False) as client:
            return await MaterialService(client, URL, SERVICE_KEY, "Bearer should-never-be-used").cleanup()
    return asyncio.run(run())


def test_cleanup_uses_exact_opaque_key_and_claim_before_counting_confirmed_absence():
    provider = CleanupProvider()
    assert cleanup(provider) == {"claimed": 1, "succeeded": 1, "failed": 0}
    assert provider.calls == [
        ("POST", "/rest/v1/rpc/claim_material_cleanup", {"p_limit": 20}),
        ("DELETE", "/storage/v1/object/application-materials", {"prefixes": [KEY]}),
        ("HEAD", f"/storage/v1/object/application-materials/{KEY}", None),
        ("POST", "/rest/v1/rpc/ack_material_cleanup", {
            "p_material_id": MATERIAL, "p_claim_token": CLAIM, "p_success": True,
        }),
    ]
    # Success is acknowledged, not a command to delete the durable SQL job.
    assert all("delete_material_cleanup" not in path for _, path, _ in provider.calls)


@pytest.mark.parametrize("changes", [
    {"delete_status": 500}, {"delete_status": 403}, {"network_failure": "delete"},
    {"network_failure": "head"}, {"head_status": 200}, {"head_status": 403}, {"head_status": 500},
])
def test_uncertain_or_denied_removal_is_acknowledged_false_and_remains_retryable(changes):
    provider = CleanupProvider(**changes)
    assert cleanup(provider) == {"claimed": 1, "succeeded": 0, "failed": 1}
    assert provider.acks == [{"p_material_id": MATERIAL, "p_claim_token": CLAIM, "p_success": False}]
    if changes.get("delete_status") or changes.get("network_failure") == "delete":
        assert not any(method == "HEAD" for method, _, _ in provider.calls)


def test_stale_ack_cannot_count_a_successful_storage_response_as_completed_job():
    provider = CleanupProvider(accepted=False)
    assert cleanup(provider) == {"claimed": 1, "succeeded": 0, "failed": 1}
    assert provider.acks[0]["p_success"] is True


@pytest.mark.parametrize("bad_job", [
    job(object_key="../other-owner/private-resume.pdf"),
    job(object_key=f"pdf/{MATERIAL}.pdf?token=private"),
    job(bucket="tracker-attachments"), job(material_id="../private"),
    job(claim_token="not-a-uuid"), job(claimed_until="no-timezone"),
    job(filename="PRIVATE resume.pdf"), None,
])
def test_malformed_or_private_paths_never_reach_storage_or_ack(bad_job):
    provider = CleanupProvider(jobs=[bad_job])
    with pytest.raises(MaterialError, match="material_invalid_receipt"):
        cleanup(provider)
    assert len(provider.calls) == 1
    assert provider.acks == []


def test_empty_queue_has_no_storage_request():
    provider = CleanupProvider(jobs=[])
    assert cleanup(provider) == {"claimed": 0, "succeeded": 0, "failed": 0}
    assert len(provider.calls) == 1


@pytest.mark.parametrize("failure", [TimeoutError("PRIVATE service-key=secret filename=resume.pdf"), RuntimeError("PRIVATE provider error")])
def test_background_timeout_or_provider_failure_only_logs_a_safe_marker(monkeypatch, caplog, failure):
    async def run():
        stop = asyncio.Event()
        async def once():
            stop.set()
            raise failure
        async def wait_for(awaitable, *, timeout):
            if timeout == 60:
                # Advance the periodic timer without real waiting, ensuring its
                # never-awaited Event coroutine does not leak a warning.
                awaitable.close()
                raise TimeoutError
            assert timeout == 45
            return await awaitable
        monkeypatch.setattr(worker, "cleanup_once", once)
        monkeypatch.setattr(worker.asyncio, "wait_for", wait_for)
        await worker.run_forever(stop)
    with caplog.at_level(logging.INFO, logger="ofe.material_cleanup"):
        asyncio.run(run())
    assert [record.getMessage() for record in caplog.records] == ["material_cleanup_unavailable"]
    assert "PRIVATE" not in caplog.text and "secret" not in caplog.text and "resume.pdf" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_worker_cancellation_propagates_without_turning_into_failure_logging(monkeypatch, caplog):
    async def run():
        async def once():
            raise asyncio.CancelledError
        async def wait_for(awaitable, *, timeout):
            if timeout == 60:
                awaitable.close()
                raise TimeoutError
            return await awaitable
        monkeypatch.setattr(worker, "cleanup_once", once)
        monkeypatch.setattr(worker.asyncio, "wait_for", wait_for)
        await worker.run_forever(asyncio.Event())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run())
    assert not caplog.records


class TrackedBody(httpx.AsyncByteStream):
    """Prove an existing PDF is closed unread and oversized errors stop early."""
    def __init__(self, chunks, failure=None):
        self.chunks, self.failure = chunks, failure
        self.reads = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.reads += 1
            yield chunk
        if self.failure:
            raise self.failure

    async def aclose(self):
        self.closed = True


@pytest.mark.parametrize("status_code", ["404", 404])
def test_real_storage_head_400_then_explicit_get_not_found_confirms_absence(status_code):
    # Shape observed from local Storage; HTTP 400 alone is never proof.
    provider = CleanupProvider(head_status=400, fallback_body={"statusCode": status_code, "error": "not_found", "message": "Object not found"})
    assert cleanup(provider) == {"claimed": 1, "succeeded": 1, "failed": 0}
    assert [method for method, path, _ in provider.calls if "/storage/" in path] == ["DELETE", "HEAD", "GET"]
    assert provider.acks[0]["p_success"] is True


@pytest.mark.parametrize("body", [
    {"statusCode": "403", "error": "not_found"},
    {"statusCode": "404", "error": "access_denied"},
    {"statusCode": "404"}, ["not_found"], b"not json", b"\xff",
])
def test_head_400_with_unproven_get_error_stays_retryable(body):
    provider = CleanupProvider(head_status=400, fallback_body=body)
    assert cleanup(provider) == {"claimed": 1, "succeeded": 0, "failed": 1}
    assert provider.acks[0]["p_success"] is False


@pytest.mark.parametrize("status", [200, 403, 500])
def test_fallback_never_reads_existing_pdf_or_unexpected_status_body(status):
    body = TrackedBody([b"%PDF-SECRET remaining original document"])
    provider = CleanupProvider(head_status=400, fallback_status=status, fallback_stream=body)
    assert cleanup(provider) == {"claimed": 1, "succeeded": 0, "failed": 1}
    assert body.reads == 0 and body.closed
    assert provider.acks[0]["p_success"] is False


def test_error_body_limit_is_inclusive_and_rejects_extra_bytes_without_reading_the_rest():
    missing = json.dumps({"statusCode": "404", "error": "not_found"}).encode()
    exact = TrackedBody([missing + b" " * (4096 - len(missing))])
    provider = CleanupProvider(head_status=400, fallback_stream=exact)
    assert cleanup(provider)["succeeded"] == 1 and exact.closed
    oversized = TrackedBody([missing + b" " * (1024 - len(missing))] + [b" " * 1024] * 4 + [b"PRIVATE unread tail"])
    provider = CleanupProvider(head_status=400, fallback_stream=oversized)
    assert cleanup(provider) == {"claimed": 1, "succeeded": 0, "failed": 1}
    assert oversized.reads == 5 and oversized.closed
    assert provider.acks[0]["p_success"] is False


def test_fallback_network_and_interrupted_error_stream_never_ack_success():
    provider = CleanupProvider(head_status=400, network_failure="get")
    assert cleanup(provider)["failed"] == 1 and provider.acks[0]["p_success"] is False
    stream = TrackedBody([b'{"statusCode":"404",'], failure=httpx.ReadError("PRIVATE broken stream"))
    provider = CleanupProvider(head_status=400, fallback_stream=stream)
    assert cleanup(provider)["failed"] == 1
    assert stream.closed and provider.acks[0]["p_success"] is False
