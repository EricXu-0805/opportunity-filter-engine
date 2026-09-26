"""Confirmed-contact originals share PDF handling, but never application scope."""
from __future__ import annotations

import hashlib
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.lib.material_archive_schema import ContactMaterialInput, ContactScope, MaterialInput, Scope
from backend.main import app
from backend.routes import application_materials as route
from tests.test_application_materials import (
    EVENT,
    HEADERS,
    MATERIAL,
    OWNER,
    PDF,
    RECORD,
    STAMP,
    Provider,
    artifact,
    metadata,
)

BASE = "/api/contact-materials"
SCOPE = {"expected_owner_id": OWNER, "contact_event_id": EVENT, "opportunity_id": "test-opportunity"}


def contact_metadata(**changes):
    value = metadata()
    del value["application_event_id"]
    return {**value, **SCOPE, **changes}


def contact_artifact(status="ready", **changes):
    return artifact(status, kind="contact", **changes)


@pytest.fixture
def endpoint(monkeypatch):
    state = Provider("contact")
    monkeypatch.setenv("SUPABASE_URL", "https://storage.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-secret")
    monkeypatch.setenv("OFE_MATERIAL_ARCHIVE_ENABLED", "1")
    monkeypatch.setenv("OFE_DISABLE_RATE_LIMIT", "1")
    monkeypatch.setattr(route, "new_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(state.handle)))
    return TestClient(app), state


def upload(client, meta=None, data=PDF, headers=None):
    return client.post(BASE, files={"metadata": (None, json.dumps(meta or contact_metadata(), ensure_ascii=False)),
                                   "file": ("selected.pdf", data, "application/pdf")},
                       headers=HEADERS if headers is None else headers)


def test_contact_original_roundtrip_and_delete_do_not_change_the_contact_event(endpoint):
    client, state = endpoint
    result = upload(client)
    assert result.status_code == 200, result.text
    record = result.json()["record"]
    assert record["contact_event_id"] == EVENT and "application_event_id" not in record
    assert record["linked_at"] == STAMP and record["confirmation_source"] == "user_reported"
    assert record["bytes_sha256"] == hashlib.sha256(PDF).hexdigest()
    assert not any(key in result.text for key in ("stage_token", "session_id", "service-secret"))
    listing = client.get(BASE, params=SCOPE, headers=HEADERS)
    assert listing.status_code == 200 and listing.json()["items"] == [record]
    download = client.get(f"{BASE}/{RECORD}/file", params=SCOPE, headers=HEADERS)
    assert download.status_code == 200 and download.content == PDF
    assert download.headers["x-ofe-material-record"] == RECORD
    assert download.headers["x-ofe-material-sha256"] == hashlib.sha256(PDF).hexdigest()
    assert "no-store" in download.headers["cache-control"] and state.authorizations == 2
    deletion = client.request("DELETE", f"{BASE}/{RECORD}", json={**SCOPE, "material_id": MATERIAL}, headers=HEADERS)
    assert deletion.status_code == 200 and deletion.json()["record"]["status"] == "deleted"
    assert all(deletion.json()["record"][key] is None for key in ("filename", "byte_length", "mime_type", "bytes_sha256"))
    rpc_names = [path.rsplit("/", 1)[-1] for _, path, _, _ in state.calls if "/rpc/" in path]
    assert set(rpc_names) == {"stage_contact_material", "finalize_contact_material", "list_contact_materials",
                              "authorize_contact_material_download", "delete_contact_material"}
    assert state.object == PDF  # Revocation is immediate; physical deletion is a separate cleanup operation.


@pytest.mark.parametrize("boundary", ["upload_unknown", "finalize_unknown"])
def test_contact_retry_after_unknown_outcome_keeps_ids_and_original_bytes(endpoint, boundary):
    client, state = endpoint
    setattr(state, boundary, True)
    first = upload(client)
    assert first.status_code == 503 and "PRIVATE" not in first.text
    lookup = client.get(f"{BASE}/{RECORD}", params=SCOPE, headers=HEADERS)
    assert lookup.status_code == 200
    assert lookup.json()["record"]["status"] == ("staged" if boundary == "upload_unknown" else "ready")
    retried = upload(client)
    assert retried.status_code == 200 and retried.json()["record"]["material_id"] == MATERIAL
    assert state.object == PDF
    writes = len([1 for method, path, _, _ in state.calls if method == "POST" and "/storage/" in path])
    assert upload(client).json()["replayed"] is True
    assert len([1 for method, path, _, _ in state.calls if method == "POST" and "/storage/" in path]) == writes


@pytest.mark.parametrize("where", ["stage", "finalize"])
def test_cancelled_contact_upload_never_reports_saved(endpoint, where):
    client, state = endpoint
    if where == "stage":
        state.row = contact_artifact("deleted")
    else:
        state.finalize_deleted = True
    result = upload(client)
    assert result.status_code == 410 and result.json()["detail"]["code"] == "material_deleted"
    if where == "stage":
        assert not any("/storage/" in path for _, path, _, _ in state.calls)


@pytest.mark.parametrize("change", [
    {"attested": False}, {"version": True}, {"byte_length": True}, {"filename": "../resume.pdf"},
    {"bytes_sha256": "a" * 64}, {"contact_event_id": "broken"}, {"application_event_id": EVENT},
    {"artifact_kind": "application"}, {"material_kind": "application"}, {"event_field": "application_event_id"},
])
def test_contact_metadata_is_strict_and_cannot_choose_another_kind(endpoint, change):
    client, state = endpoint
    result = upload(client, contact_metadata(**change))
    assert result.status_code == 422
    assert not any("/rest/" in path for _, path, _, _ in state.calls)


@pytest.mark.parametrize("auth", ["guest", "missing", "different", "revoked"])
def test_contact_authentication_precedes_any_database_or_storage_write(endpoint, auth):
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
    assert not any("/rest/" in path or "/storage/" in path for _, path, _, _ in state.calls)


@pytest.mark.parametrize("where", ["lookup", "list", "stage", "finalize", "download", "delete"])
def test_application_receipt_is_rejected_at_every_contact_boundary(endpoint, where):
    client, state = endpoint
    state.row, state.object = artifact("deleted" if where == "delete" else "ready"), PDF
    if where == "finalize":
        state.rpc_overrides["finalize_contact_material"] = {"artifact": state.row, "replayed": False}
        state.row, state.object = None, None
        result = upload(client)
    elif where == "stage":
        result = upload(client)
    elif where == "delete":
        state.rpc_overrides["delete_contact_material"] = {"artifact": state.row, "replayed": False}
        result = client.request("DELETE", f"{BASE}/{RECORD}", json={**SCOPE, "material_id": MATERIAL}, headers=HEADERS)
    else:
        suffix = "" if where == "list" else f"/{RECORD}" + ("/file" if where == "download" else "")
        result = client.get(BASE + suffix, params=SCOPE, headers=HEADERS)
    assert result.status_code == 502 and result.content != PDF
    if where != "finalize":
        assert not any("/storage/" in path for _, path, _, _ in state.calls)


@pytest.mark.parametrize("change", [
    {"owner_id": RECORD}, {"contact_event_id": RECORD}, {"opportunity_id": "other"},
    {"record_id": EVENT}, {"application_event_id": EVENT}, {"artifact_kind": "contact"},
])
def test_contact_receipt_rejects_wrong_owner_event_target_and_extra_fields(endpoint, change):
    client, state = endpoint
    state.row = contact_artifact(**change)
    assert client.get(f"{BASE}/{RECORD}", params=SCOPE, headers=HEADERS).status_code == 502


def test_contact_download_rechecks_authority_after_reading_storage(endpoint):
    client, state = endpoint
    state.row, state.object, state.revoke_on_authorize = contact_artifact(), PDF, True
    response = client.get(f"{BASE}/{RECORD}/file", params=SCOPE, headers=HEADERS)
    assert response.status_code == 401 and response.content != PDF and state.authorizations == 2


@pytest.mark.parametrize("params", [
    {"expected_owner_id": OWNER, "application_event_id": EVENT, "opportunity_id": "test-opportunity"},
    {**SCOPE, "application_event_id": EVENT}, {**SCOPE, "cursor_record_id": RECORD},
    list(SCOPE.items()) + [("contact_event_id", EVENT)],
])
def test_contact_query_rejects_mixed_or_duplicate_scope_before_authentication(endpoint, params):
    client, state = endpoint
    assert client.get(BASE, params=params, headers=HEADERS).status_code == 422
    assert state.calls == []


def test_scope_models_remain_disjoint_and_serialization_has_no_internal_kind():
    assert set(ContactScope.model_validate(SCOPE).model_dump()) == set(SCOPE)
    assert set(ContactMaterialInput.model_validate(contact_metadata()).model_dump()) == set(contact_metadata())
    with pytest.raises(ValueError):
        Scope.model_validate(SCOPE)
    with pytest.raises(ValueError):
        MaterialInput.model_validate(contact_metadata())
