"""Application PDF trust boundaries and interrupted storage operations."""
from __future__ import annotations

import asyncio
import hashlib
import io
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from backend.lib import material_archive as lib
from backend.lib.material_archive_schema import MAX_BODY_BYTES, MaterialError
from backend.main import RequestBodyLimitMiddleware, _material_body_limit_from_env, app
from backend.routes import application_materials as route

OWNER = "11111111-1111-4111-8111-111111111111"
EVENT = "22222222-2222-4222-8222-222222222222"
MATERIAL = "33333333-3333-4333-8333-333333333333"
RECORD = "44444444-4444-4444-8444-444444444444"
TOKEN = "55555555-5555-4555-8555-555555555555"
SESSION = "66666666-6666-4666-8666-666666666666"
STAMP = "2026-09-25T12:00:00+00:00"
SCOPE = {"expected_owner_id": OWNER, "application_event_id": EVENT, "opportunity_id": "test-opportunity"}
HEADERS = {"Authorization": "Bearer user-token"}
BASE = "/api/application-materials"


def pdf_bytes():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


PDF = pdf_bytes()


def metadata(**changes):
    return {"version": 1, **SCOPE, "material_id": MATERIAL, "record_id": RECORD, "filename": "简历.pdf",
            "mime_type": "application/pdf", "byte_length": len(PDF),
            "bytes_sha256": hashlib.sha256(PDF).hexdigest(), "attested": True, **changes}


def artifact(status="ready", *, kind="application", **changes):
    ready = status == "ready"
    deleted = status == "deleted"
    return {"material_id": MATERIAL, "record_id": RECORD, f"{kind}_event_id": EVENT,
            "opportunity_id": SCOPE["opportunity_id"], "owner_id": OWNER, "status": status,
            "filename": None if deleted else "简历.pdf", "mime_type": None if deleted else "application/pdf",
            "byte_length": None if deleted else len(PDF), "sha256": hashlib.sha256(PDF).hexdigest() if ready else None,
            "created_at": STAMP, "expires_at": "2026-09-26T12:00:00+00:00",
            "archived_at": STAMP if status != "staged" else None,
            "recorded_at": STAMP if status != "staged" else None,
            "deleted_at": STAMP if deleted else None, "confirmation_source": "user_reported", **changes}


class Provider:
    def __init__(self, kind="application"):
        self.kind = kind
        self.calls = []
        self.row = None
        self.object = None
        self.anon = False
        self.owner = OWNER
        self.auth_status = 200
        self.upload_unknown = False
        self.finalize_unknown = False
        self.revoke_on_authorize = False
        self.authorizations = 0
        self.finalize_deleted = False
        self.rpc_overrides = {}

    def handle(self, request):
        path = request.url.path
        body = json.loads(request.content) if "/rest/" in path else None
        self.calls.append((request.method, path, body, request.headers.get("authorization")))
        if path == "/auth/v1/user":
            return httpx.Response(self.auth_status, json={"id": self.owner, "is_anonymous": self.anon})
        if "/rpc/" in path:
            name = path.rsplit("/", 1)[-1]
            if name in self.rpc_overrides:
                return httpx.Response(200, json=self.rpc_overrides[name])
            if name != f"finalize_{self.kind}_material":
                assert body[f"p_{self.kind}_event_id"] == EVENT
                assert body["p_expected_owner"] == OWNER
                assert body["p_opportunity_id"] == SCOPE["opportunity_id"]
                assert f"p_{'contact' if self.kind == 'application' else 'application'}_event_id" not in body
            if name == f"stage_{self.kind}_material":
                if self.row is None:
                    self.row = artifact("staged", kind=self.kind)
                return httpx.Response(200, json={"artifact": self.row, "replayed": self.row["status"] != "staged",
                    "upload": {"bucket": "application-materials", "object_key": f"pdf/{MATERIAL}.pdf",
                               "stage_token": TOKEN, "session_id": SESSION, "authorized_until": "2026-09-25T13:00:00Z"}
                    if self.row["status"] == "staged" else None})
            if name == f"finalize_{self.kind}_material":
                assert request.headers["authorization"] == "Bearer service-secret"
                assert body["p_verified_owner"] == OWNER and body["p_verified_session_id"] == SESSION
                assert body["p_stage_token"] == TOKEN
                assert body["p_verified_sha256"] == hashlib.sha256(self.object).hexdigest()
                self.row = artifact("deleted" if self.finalize_deleted else "ready", kind=self.kind)
                if self.finalize_unknown:
                    self.finalize_unknown = False
                    raise httpx.ReadTimeout("PRIVATE-provider-message")
                return httpx.Response(200, json={"artifact": self.row, "replayed": False})
            assert request.headers["authorization"] == "Bearer user-token"
            if name == f"get_{self.kind}_material":
                assert body["p_record_id"] == RECORD
                return httpx.Response(200, json={"artifact": self.row})
            if name == f"list_{self.kind}_materials":
                return httpx.Response(200, json={"items": [] if self.row is None else [self.row], "next_cursor": None})
            if name == f"authorize_{self.kind}_material_download":
                self.authorizations += 1
                if self.revoke_on_authorize and self.authorizations == 2:
                    return httpx.Response(403, json={"code": "42501", "message": "PRIVATE-revoked"})
                return httpx.Response(200, json={"artifact": self.row, "bucket": "application-materials",
                                                "object_key": f"pdf/{MATERIAL}.pdf"})
            if name == f"delete_{self.kind}_material":
                self.row = artifact("deleted", kind=self.kind)
                return httpx.Response(200, json={"artifact": self.row, "replayed": False})
            raise AssertionError(name)
        assert path == f"/storage/v1/object/application-materials/pdf/{MATERIAL}.pdf"
        assert request.headers["authorization"] == "Bearer service-secret"
        if request.method == "POST":
            assert request.headers["x-upsert"] == "false"
            if self.object is not None:
                return httpx.Response(409, json={"statusCode": "409", "error": "Duplicate"})
            self.object = request.content
            if self.upload_unknown:
                self.upload_unknown = False
                raise httpx.ReadTimeout("PRIVATE-upload-timeout")
            return httpx.Response(200, json={"Key": f"application-materials/pdf/{MATERIAL}.pdf"})
        return httpx.Response(200, content=self.object, headers={"Content-Type": "application/pdf"})


@pytest.fixture
def endpoint(monkeypatch):
    state = Provider()
    monkeypatch.setenv("SUPABASE_URL", "https://storage.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-secret")
    monkeypatch.setenv("OFE_MATERIAL_ARCHIVE_ENABLED", "1")
    monkeypatch.setenv("OFE_DISABLE_RATE_LIMIT", "1")
    monkeypatch.setattr(route, "new_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(state.handle)))
    return TestClient(app), state


def upload(client, meta=None, data=PDF, headers=None):
    return client.post(BASE, files={"metadata": (None, json.dumps(meta or metadata(), ensure_ascii=False)),
                                   "file": ("selected.pdf", data, "application/pdf")},
                       headers=HEADERS if headers is None else headers)


def test_real_pdf_structure_validator_preserves_input():
    before = bytes(PDF)
    asyncio.run(lib.validate_pdf(PDF))
    assert PDF == before


@pytest.mark.parametrize("bad", [b"not a PDF", b"%PDF-1.7\nfake body\n%%EOF", PDF[:-80]])
def test_invalid_pdf_is_rejected_in_actual_subprocess(bad):
    with pytest.raises(MaterialError):
        asyncio.run(lib.validate_pdf(bad))


def test_encrypted_pdf_rejected():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("password")
    out = io.BytesIO()
    writer.write(out)
    with pytest.raises(MaterialError):
        asyncio.run(lib.validate_pdf(out.getvalue()))


def test_archive_download_and_delete_keep_original_bytes(endpoint):
    client, state = endpoint
    response = upload(client)
    assert response.status_code == 200, response.text
    row = response.json()["record"]
    assert row["status"] == "ready" and row["linked_at"] == STAMP and row["staged_at"] == STAMP
    assert row["bytes_sha256"] == hashlib.sha256(PDF).hexdigest()
    assert "stage_token" not in response.text and "session_id" not in response.text
    assert state.object == PDF
    paths = [p for _, p, _, _ in state.calls]
    assert paths.index("/rest/v1/rpc/stage_application_material") < paths.index(f"/storage/v1/object/application-materials/pdf/{MATERIAL}.pdf")
    assert [p for _, p, _, _ in state.calls][-1] == "/rest/v1/rpc/finalize_application_material"
    downloaded = client.get(f"{BASE}/{RECORD}/file", params=SCOPE, headers=HEADERS)
    assert downloaded.status_code == 200 and downloaded.content == PDF
    assert downloaded.headers["x-ofe-material-sha256"] == hashlib.sha256(PDF).hexdigest()
    assert "attachment" in downloaded.headers["content-disposition"]
    assert "no-store" in downloaded.headers["cache-control"] and state.authorizations == 2
    deleted = client.request("DELETE", f"{BASE}/{RECORD}", json={**SCOPE, "material_id": MATERIAL}, headers=HEADERS)
    assert deleted.status_code == 200
    tombstone = deleted.json()["record"]
    assert tombstone["status"] == "deleted"
    assert all(tombstone[k] is None for k in ["filename", "bytes_sha256", "byte_length", "mime_type"])
    assert not any("interaction" in p or "confirm_application" in p for _, p, _, _ in state.calls)
    # HTTP deletion truth is the revoked metadata; the physical object remains
    # for the separately verified cleanup worker, never falsely marked erased.
    assert state.object == PDF


def test_exact_ready_retry_has_no_storage_write(endpoint):
    client, state = endpoint
    assert upload(client).status_code == 200
    count = sum(method == "POST" and "/storage/" in path for method, path, _, _ in state.calls)
    retry = upload(client)
    assert retry.status_code == 200 and retry.json()["replayed"] is True
    assert sum(method == "POST" and "/storage/" in path for method, path, _, _ in state.calls) == count


@pytest.mark.parametrize("where", ["upload_unknown", "finalize_unknown"])
def test_lost_response_can_be_looked_up_and_retried_without_overwrite(endpoint, where):
    client, state = endpoint
    setattr(state, where, True)
    first = upload(client)
    assert first.status_code == 503 and "PRIVATE" not in first.text
    lookup = client.get(f"{BASE}/{RECORD}", params=SCOPE, headers=HEADERS)
    assert lookup.status_code == 200
    assert lookup.json()["record"]["status"] == ("staged" if where == "upload_unknown" else "ready")
    retry = upload(client)
    assert retry.status_code == 200 and state.object == PDF
    assert retry.json()["record"]["material_id"] == MATERIAL


def test_mismatched_existing_object_never_finalizes(endpoint):
    client, state = endpoint
    state.object = b"wrong object"
    response = upload(client)
    assert response.status_code == 502
    assert not any(path.endswith("finalize_application_material") for _, path, _, _ in state.calls)
    assert state.object == b"wrong object"


def test_revoked_during_storage_upload_never_reports_success(endpoint):
    client, state = endpoint
    state.finalize_deleted = True
    response = upload(client)
    assert response.status_code == 410 and response.json()["detail"]["code"] == "material_deleted"
    assert state.row["status"] == "deleted"


def test_deleted_stage_is_not_uploaded_again(endpoint):
    client, state = endpoint
    state.row = artifact("deleted")
    response = upload(client)
    assert response.status_code == 410
    assert not any("/storage/" in path for _, path, _, _ in state.calls)


def test_download_rechecks_authority_after_fetching_object(endpoint):
    client, state = endpoint
    state.row, state.object = artifact(), PDF
    state.revoke_on_authorize = True
    response = client.get(f"{BASE}/{RECORD}/file", params=SCOPE, headers=HEADERS)
    assert response.status_code == 401 and response.content != PDF
    assert "PRIVATE" not in response.text


@pytest.mark.parametrize("change", [
    {"attested": False}, {"attested": "true"}, {"version": True}, {"byte_length": True},
    {"bytes_sha256": "a" * 64}, {"filename": "resume.docx"}, {"filename": "../resume.pdf"},
    {"filename": "a\\resume.pdf"}, {"filename": "a\x80.pdf"}, {"byte_length": len(PDF) + 1},
    {"additional_private_field": "do not echo"}, {"filename": "x" * 200 + ".pdf"},
])
def test_invalid_metadata_is_rejected_without_database_write(endpoint, change):
    client, state = endpoint
    response = upload(client, metadata(**change))
    assert response.status_code == 422
    assert all("/rest/" not in path for _, path, _, _ in state.calls)
    assert "do not echo" not in response.text


@pytest.mark.parametrize("auth", ["guest", "missing", "different", "revoked"])
def test_authentication_before_archive(endpoint, auth):
    client, state = endpoint
    headers = HEADERS
    if auth == "guest":
        state.anon = True
    elif auth == "missing":
        headers = {}
    elif auth == "different":
        state.owner = RECORD
    else:
        state.auth_status = 401
    response = upload(client, headers=headers)
    assert response.status_code in (401, 409)
    assert state.object is None and not any("/rest/" in path for _, path, _, _ in state.calls)


def test_missing_configuration_fails_closed(endpoint, monkeypatch):
    client, state = endpoint
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY")
    response = upload(client)
    assert response.status_code == 503 and state.calls == []


@pytest.mark.parametrize("row_change", [
    {"owner_id": RECORD}, {"application_event_id": RECORD}, {"opportunity_id": "other"},
    {"record_id": EVENT}, {"sha256": "broken"}, {"recorded_at": None}, {"untrusted": "private"},
])
def test_wrong_or_malformed_receipts_are_not_accepted(endpoint, row_change):
    client, state = endpoint
    state.row = artifact(**row_change)
    response = client.get(f"{BASE}/{RECORD}", params=SCOPE, headers=HEADERS)
    assert response.status_code == 502 and "private" not in response.text
    assert "no-store" in response.headers["cache-control"]


def test_lookup_missing_is_not_an_empty_record_and_list_failure_not_empty(endpoint):
    client, state = endpoint
    assert client.get(f"{BASE}/{RECORD}", params=SCOPE, headers=HEADERS).status_code == 404
    state.rpc_overrides["list_application_materials"] = {"items": [], "next_cursor": {"wrong": "data"}}
    response = client.get(BASE, params=SCOPE, headers=HEADERS)
    assert response.status_code == 502


def test_list_includes_only_scoped_finalized_rows(endpoint):
    client, state = endpoint
    state.row = artifact()
    response = client.get(BASE, params=SCOPE, headers=HEADERS)
    assert response.status_code == 200 and len(response.json()["items"]) == 1
    state.row = artifact("staged")
    assert client.get(BASE, params=SCOPE, headers=HEADERS).status_code == 502


@pytest.mark.parametrize("params", [
    {**SCOPE, "cursor_record_id": RECORD}, {**SCOPE, "cursor_linked_at": "invalid", "cursor_record_id": RECORD},
    {**SCOPE, "unknown": "private"},
])
def test_invalid_list_queries_are_rejected(endpoint, params):
    client, state = endpoint
    response = client.get(BASE, params=params, headers=HEADERS)
    assert response.status_code == 422 and state.calls == []


def test_io_saturation_does_not_queue_or_accept_body(endpoint):
    client, state = endpoint
    route._IO_CAPACITY.acquire()
    route._IO_CAPACITY.acquire()
    try:
        response = upload(client)
        assert response.status_code == 503 and response.json()["detail"]["code"] == "material_busy"
        assert state.calls == []
    finally:
        route._IO_CAPACITY.release()
        route._IO_CAPACITY.release()


def test_oversized_envelope_rejected_before_authentication(endpoint):
    client, state = endpoint
    response = client.post(BASE, content=b"x", headers={**HEADERS, "Content-Length": str(MAX_BODY_BYTES + 1)})
    assert response.status_code == 413 and state.calls == []


def test_material_body_limit_honors_lower_operator_limit(monkeypatch):
    monkeypatch.delenv("OFE_MAX_REQUEST_BODY_BYTES", raising=False)
    assert _material_body_limit_from_env() == MAX_BODY_BYTES
    monkeypatch.setenv("OFE_MAX_REQUEST_BODY_BYTES", "1048576")
    assert _material_body_limit_from_env() == 1048576


@pytest.mark.parametrize("base", [BASE, "/api/contact-materials"])
def test_chunked_upload_uses_material_limit_only_on_upload_path(base):
    async def run(path, limit, method="POST"):
        sent, done = [], []
        messages = iter([{"type": "http.request", "body": b"x" * 9, "more_body": False}])

        async def receive():
            return next(messages)

        async def send(value):
            sent.append(value)

        async def target(scope, receive, send):
            await receive()
            done.append(True)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        await RequestBodyLimitMiddleware(target, max_bytes=8, material_max_bytes=limit)(
            {"type": "http", "path": path, "method": method, "headers": []}, receive, send)
        return sent[0]["status"], bool(done)

    assert asyncio.run(run(base, 10)) == (200, True)
    assert asyncio.run(run(base, 8)) == (413, False)
    assert asyncio.run(run("/api/unrelated", 10)) == (413, False)
    assert asyncio.run(run(base, 10, "DELETE")) == (413, False)


def test_cors_delete_and_download_integrity_headers(endpoint):
    client, state = endpoint
    preflight = client.options(f"{BASE}/{RECORD}", headers={
        "Origin": "https://joinalab.com", "Access-Control-Request-Method": "DELETE",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    assert preflight.status_code == 200
    state.row, state.object = artifact(), PDF
    response = client.get(f"{BASE}/{RECORD}/file", params=SCOPE, headers={**HEADERS, "Origin": "https://joinalab.com"})
    assert "x-ofe-material-sha256" in response.headers["access-control-expose-headers"]


def test_database_timezone_does_not_leak_into_utc_http_contract(endpoint):
    client, state = endpoint
    state.row = artifact(created_at="2026-09-25T07:00:00-05:00",
                         archived_at="2026-09-25T07:00:00.123456-05:00",
                         recorded_at="2026-09-25T07:00:00.123456-05:00")
    response = client.get(f"{BASE}/{RECORD}", params=SCOPE, headers=HEADERS)
    assert response.status_code == 200
    record = response.json()["record"]
    assert record["staged_at"] == STAMP
    assert record["archived_at"] == "2026-09-25T12:00:00.123456+00:00"
    assert record["linked_at"] == "2026-09-25T12:00:00.123456+00:00"


@pytest.mark.parametrize("base", [BASE, "/api/contact-materials"])
@pytest.mark.parametrize("disconnect", [False, True])
def test_stalled_or_disconnected_multipart_releases_file_capacity(endpoint, monkeypatch, disconnect, base):
    _, state = endpoint
    monkeypatch.setattr(route, "_REQUEST_TIMEOUT_SECONDS", 0.02)
    async def run():
        sent = []
        first = True
        async def receive():
            nonlocal first
            if first:
                first = False
                return {"type": "http.request", "body": b"--boundary\r\n", "more_body": True}
            if disconnect:
                return {"type": "http.disconnect"}
            await asyncio.Event().wait()
        async def send(message):
            sent.append(message)
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                 "method": "POST", "scheme": "http", "path": base, "raw_path": base.encode(),
                 "root_path": "", "query_string": b"", "server": ("testserver", 80),
                 "client": ("127.0.0.1", 10000), "headers": [
                     (b"authorization", b"Bearer user-token"),
                     (b"content-type", b"multipart/form-data; boundary=boundary")]}
        await asyncio.wait_for(app(scope, receive, send), 1)
        assert sent[0]["status"] == 503
        assert b"material_unavailable" in b"".join(item.get("body", b"") for item in sent)
    asyncio.run(run())
    assert state.calls[0][1] == "/auth/v1/user"
    assert not any("/rest/" in path for _, path, _, _ in state.calls)
    assert route._IO_CAPACITY.acquire(blocking=False)
    assert route._IO_CAPACITY.acquire(blocking=False)
    route._IO_CAPACITY.release()
    route._IO_CAPACITY.release()
