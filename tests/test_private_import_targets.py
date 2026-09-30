"""Offline actual-route tests; every auth and storage request uses MockTransport."""

from copy import deepcopy

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.routes import private_import_targets as route

OWNER = "a1000000-0000-4000-8000-000000000001"
OTHER = "a1000000-0000-4000-8000-000000000002"
ID = "private-import:a2000000-0000-4000-8000-000000000001"
STAMP = "2026-09-28T12:00:00+00:00"
AUTH_LOOKUP = ("GET", "/auth/v1/user", "Bearer fixture-token")
OPPORTUNITY = {
    "source": "text_parser",
    "title": "Private research note",
    "description_raw": "GPA < 3.0 needs review; scores > 80 preferred. END 私人正文",
    "source_url": "",
    "url": "",
    "extra_fields": {
        "description_source": "pasted_text",
        "ai_input_scope": "source_excerpt",
        "llm_enriched": True,
        "suggested_skills": ["ImaginarySkill"],
        "target_truth": {"actionable": True},
    },
}


def test_route_registered_and_private(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://supabase.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fixture-only")
    response = TestClient(app).get(f"/api/private-import-targets/{ID}", params={"expected_owner_id": OWNER})
    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "private_target_auth_required"}}
    assert "no-store" in response.headers["cache-control"]


def raw_record(payload=None, revision=1, *, deleted=False, uid=OWNER):
    return {
        "id": ID,
        "owner_id": uid,
        "revision": revision,
        "opportunity": None if deleted else deepcopy(payload or OPPORTUNITY),
        "created_at": STAMP,
        "updated_at": STAMP,
        "deleted_at": STAMP if deleted else None,
    }


@pytest.fixture
def storage(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://supabase.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fixture-only")
    state = {
        "row": None,
        "calls": [],
        "user": {"id": OWNER, "is_anonymous": False, "app_metadata": {"provider": "google"}},
        "failure": None,
    }

    def handle(request):
        import json

        state["calls"].append((request.method, request.url.path, request.headers.get("authorization")))
        if request.url.path == "/auth/v1/user":
            if request.headers.get("authorization") != "Bearer fixture-token":
                return httpx.Response(401, json={"message": "invalid JWT"})
            return httpx.Response(200, json=state["user"])
        data = json.loads(request.content)
        assert request.headers["authorization"] == "Bearer fixture-token"
        if state["failure"]:
            return httpx.Response(400, json={"code": state["failure"], "message": "PRIVATE_SECRET_SOURCE"})
        if state.get("rpc_result") is not None:
            return httpx.Response(200, json=state["rpc_result"])
        name = request.url.path.rsplit("/", 1)[-1]
        row = state["row"]
        if name == "save_private_import_target":
            if row and row["deleted_at"] is not None:
                return httpx.Response(400, json={"code": "55000"})
            if (
                row
                and row["revision"] == data["p_expected_revision"] + 1
                and row["opportunity"] == data["p_opportunity"]
            ):
                return httpx.Response(200, json={"target": row, "replayed": True})
            if (row is None and data["p_expected_revision"] != 0) or (
                row and row["revision"] != data["p_expected_revision"]
            ):
                return httpx.Response(400, json={"code": "23505"})
            row = raw_record(data["p_opportunity"], data["p_expected_revision"] + 1)
            state["row"] = row
            return httpx.Response(200, json={"target": row, "replayed": False})
        if name == "read_private_import_target":
            return httpx.Response(200, json={"target": row})
        if name == "delete_private_import_target":
            replay = bool(row and row["deleted_at"] and row["revision"] == data["p_expected_revision"] + 1)
            if not replay and (not row or row["revision"] != data["p_expected_revision"]):
                return httpx.Response(400, json={"code": "23505"})
            if not replay:
                state["row"] = raw_record(revision=data["p_expected_revision"] + 1, deleted=True)
            return httpx.Response(200, json={"target": state["row"], "replayed": replay})
        if name == "list_private_import_targets":
            items = []
            if row and not row["deleted_at"]:
                item = {k: v for k, v in row.items() if k != "opportunity"}
                item.update(
                    {
                        k: row["opportunity"].get(k, None if k == "organization" else "")
                        for k in ("title", "organization", "source_url", "url", "source")
                    }
                )
                items.append(item)
            return httpx.Response(200, json={"items": items, "next_cursor": None})
        raise AssertionError(name)

    monkeypatch.setattr(route, "new_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    return state


def request(client, method, payload=None, *, params=None, target=ID):
    return client.request(
        method,
        "/api/private-import-targets" + (f"/{target}" if target else ""),
        json=payload,
        params=params,
        headers={"Authorization": "Bearer fixture-token"},
    )


def save_body(revision=0, payload=None):
    return {"expected_owner_id": OWNER, "expected_revision": revision, "opportunity": deepcopy(payload or OPPORTUNITY)}


def test_actual_route_crud_scope_labels_tombstone_and_replay(storage):
    client = TestClient(app)
    first = request(client, "PUT", save_body())
    assert first.status_code == 200, first.text
    target = first.json()["target"]
    assert target["opportunity"] == OPPORTUNITY
    assert target["import_source"] == {
        "version": 1,
        "description_source": "pasted_text",
        "ai_input_scope": "source_excerpt",
        "llm_enriched": True,
    }
    assert target["verification"] == "unverified" and target["target_scope"] == "private_import"
    assert "target_truth" not in target and "public" not in target
    assert request(client, "PUT", save_body()).json()["replayed"] is True
    read = request(client, "GET", params={"expected_owner_id": OWNER}).json()["target"]
    assert read == target
    listing = request(client, "GET", params={"expected_owner_id": OWNER}, target=None).json()
    assert len(listing["items"]) == 1 and "opportunity" not in listing["items"][0]
    assert listing["items"][0]["target_version"] == target["target_version"]
    changed = deepcopy(OPPORTUNITY)
    changed["description_raw"] += "\nNEW END"
    updated = request(client, "PUT", save_body(1, changed)).json()["target"]
    assert updated["target_version"] != target["target_version"] and updated["revision"] == 2
    assert request(client, "PUT", save_body(0, changed)).status_code == 409
    deleted = request(client, "DELETE", {"expected_owner_id": OWNER, "expected_revision": 2})
    assert deleted.status_code == 200 and deleted.json()["target"]["opportunity"] is None
    assert deleted.json()["target"]["import_source"] is None
    assert request(client, "DELETE", {"expected_owner_id": OWNER, "expected_revision": 2}).json()["replayed"] is True
    assert request(client, "GET", params={"expected_owner_id": OWNER}).json()["target"]["deleted_at"] == STAMP
    assert request(client, "PUT", save_body(3)).json()["detail"]["code"] == "private_target_deleted"
    assert request(client, "GET", params={"expected_owner_id": OWNER}, target=None).json()["items"] == []


@pytest.mark.parametrize(
    "labels,expected",
    [
        ({}, None),
        ({"description_source": "page_text", "llm_enriched": True, "ai_input_scope": "source_excerpt"}, "unknown"),
        ({"description_source": "pasted_text", "llm_enriched": True, "ai_input_scope": "full_source"}, "unknown"),
        ({"description_source": "pasted_text", "llm_enriched": "true", "ai_input_scope": "source_excerpt"}, "unknown"),
    ],
)
def test_labels_never_imply_full_model_or_public_verification(storage, labels, expected):
    value = deepcopy(OPPORTUNITY)
    value["extra_fields"] = labels
    response = request(TestClient(app), "PUT", save_body(payload=value))
    assert response.status_code == 200
    target = response.json()["target"]
    assert target["verification"] == "unverified"
    assert (
        target["import_source"] is None if expected is None else target["import_source"]["ai_input_scope"] == expected
    )
    assert target["opportunity"]["extra_fields"] == labels


@pytest.mark.parametrize(
    "change,status,code",
    [
        ({"id": OTHER}, 409, "owner_changed"),
        ({"is_anonymous": True}, 401, "auth_required"),
        ({"is_anonymous": None}, 401, "auth_required"),
        ({"id": "invalid"}, 401, "auth_required"),
    ],
)
def test_auth_before_storage(storage, change, status, code):
    storage["user"].update(change)
    response = request(TestClient(app), "PUT", save_body())
    assert response.status_code == status and response.json()["detail"]["code"] == f"private_target_{code}"
    assert len(storage["calls"]) == 1 and storage["calls"][0][1] == "/auth/v1/user"


@pytest.mark.parametrize(
    "sqlstate,status,code",
    [
        ("42501", 401, "auth_required"),
        ("P0002", 404, "not_found"),
        ("23505", 409, "conflict"),
        ("55000", 409, "deleted"),
        ("22023", 422, "invalid_request"),
        ("54000", 413, "too_large"),
        ("XX000", 503, "unavailable"),
    ],
)
def test_safe_storage_errors(storage, sqlstate, status, code):
    storage["failure"] = sqlstate
    response = request(TestClient(app), "PUT", save_body())
    assert response.status_code == status
    assert response.json() == {"detail": {"code": f"private_target_{code}"}}
    assert "PRIVATE_SECRET" not in response.text and "no-store" in response.headers["cache-control"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(expected_revision=True),
        lambda p: p.update(extra="PRIVATE_SECRET_SOURCE"),
        lambda p: p["opportunity"].update(source="faculty_research"),
        lambda p: p["opportunity"].update(description_raw=""),
        lambda p: p["opportunity"].update(description_raw="PRIVATE_SECRET\x00"),
        lambda p: p["opportunity"].update(title="PRIVATE_SECRET\ud800"),
        lambda p: p["opportunity"]["extra_fields"].update({"PRIVATE_SECRET\x00": "bad"}),
        lambda p: p["opportunity"]["extra_fields"].update(value="PRIVATE_SECRET\x00"),
    ],
)
def test_invalid_body_privacy_and_no_storage_call(storage, mutate):
    import json

    body = save_body()
    mutate(body)
    response = TestClient(app).put(
        f"/api/private-import-targets/{ID}",
        content=json.dumps(body),
        headers={"content-type": "application/json", "Authorization": "Bearer fixture-token"},
    )
    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "private_target_invalid_request"}}
    # The token is verified before the body is parsed; nothing reaches storage.
    assert storage["calls"] == [AUTH_LOOKUP] and "no-store" in response.headers["cache-control"]


@pytest.mark.parametrize(
    "body",
    [
        '{"expected_owner_id":"'
        + OWNER
        + '","expected_revision":0,"opportunity":{"source":"text_parser","title":"T","description_raw":"ok","extra_fields":{"secret":NaN}}}',
        '{"expected_owner_id":"'
        + OWNER
        + '","expected_revision":0,"opportunity":{"source":"text_parser","title":"T","description_raw":"ok","extra_fields":{"secret":Infinity}}}',
    ],
)
def test_nonfinite_private_json_rejected(storage, body):
    response = TestClient(app).put(
        f"/api/private-import-targets/{ID}",
        content=body,
        headers={"content-type": "application/json", "Authorization": "Bearer fixture-token"},
    )
    assert response.status_code == 422 and storage["calls"] == [AUTH_LOOKUP]


def test_deep_and_metadata_budget(storage):
    value = {}
    node = value
    for _ in range(34):
        node["next"] = {}
        node = node["next"]
    body = save_body()
    body["opportunity"]["extra_fields"] = value
    response = request(TestClient(app), "PUT", body)
    assert response.status_code == 422
    body["opportunity"]["extra_fields"] = {"secret": "x" * (256 * 1024)}
    response = request(TestClient(app), "PUT", body)
    assert response.status_code == 413 and response.json()["detail"]["code"] == "private_target_too_large"
    assert storage["calls"] == [AUTH_LOOKUP, AUTH_LOOKUP]


def test_complete_over_default_middleware_limit_and_explicit_storage_budget(storage):
    body = save_body()
    body["opportunity"]["description_raw"] = "保留🙂" * 150000 + "END_MARKER"
    response = request(TestClient(app), "PUT", body)
    assert (
        response.status_code == 200
        and response.json()["target"]["opportunity"]["description_raw"] == body["opportunity"]["description_raw"]
    )
    body["opportunity"]["description_raw"] = "🙂" * (2 * 1024 * 1024)
    response = request(TestClient(app), "PUT", body)
    assert response.status_code == 413 and response.json()["detail"]["code"] == "private_target_too_large"


def test_middleware_early_reject_safe_and_private(storage):
    response = TestClient(app).put(
        f"/api/private-import-targets/{ID}",
        content=b"PRIVATE_SECRET",
        headers={"content-length": str(10 * 1024 * 1024), "Authorization": "Bearer fixture-token"},
    )
    assert response.status_code == 413 and response.json() == {"detail": {"code": "private_target_too_large"}}
    assert storage["calls"] == [] and "no-store" in response.headers["cache-control"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(owner_id=OTHER),
        lambda r: r.update(id=ID[:-1] + "2"),
        lambda r: r.update(revision=True),
        lambda r: r.update(opportunity=None),
        lambda r: r.update(extra="private"),
        lambda r: r.update(deleted_at=STAMP),
    ],
)
def test_poisoned_receipts_are_not_returned(storage, mutate):
    row = raw_record()
    mutate(row)
    storage["rpc_result"] = {"target": row, "replayed": False}
    response = request(TestClient(app), "PUT", save_body())
    assert response.status_code == 502
    assert response.json() == {"detail": {"code": "private_target_invalid_receipt"}}


def test_missing_and_queries_are_safe(storage):
    client = TestClient(app)
    assert request(client, "GET", params={"expected_owner_id": OWNER}).status_code == 404
    for params in [
        {"expected_owner_id": OWNER, "bad": "PRIVATE"},
        {"expected_owner_id": OWNER, "before_id": ID},
        {"expected_owner_id": OWNER, "limit": "51"},
    ]:
        response = request(client, "GET", params=params, target=None)
        assert response.status_code == 422 and "PRIVATE" not in response.text


def test_receipt_boolean_is_not_interchangeable_with_number(storage):
    row = raw_record()
    row["opportunity"]["extra_fields"]["llm_enriched"] = 1
    storage["rpc_result"] = {"target": row, "replayed": False}
    response = request(TestClient(app), "PUT", save_body())
    assert response.status_code == 502


def test_chunked_request_limit_is_safe_and_private(storage, monkeypatch):
    from fastapi import FastAPI

    import backend.main as main

    local = FastAPI()
    local.include_router(route.router, prefix="/api")
    local.add_middleware(main.RequestBodyLimitMiddleware, max_bytes=1024, private_target_max_bytes=1024)
    local.add_middleware(main.SecurityHeadersMiddleware)
    body = b'{"private_marker":"' + b"x" * 1500 + b'"}'
    response = TestClient(local).put(
        f"/api/private-import-targets/{ID}",
        content=iter([body[:800], body[800:]]),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json() == {"detail": {"code": "private_target_too_large"}}
    assert "no-store" in response.headers["cache-control"] and storage["calls"] == []


def test_actual_version_fixture_stable_and_owner_bound():
    import hashlib
    import json

    from backend.lib.private_import_targets import target_receipt

    base = raw_record()
    receipt = target_receipt(base, OWNER)
    material = '{"id":"' + ID + '","owner_id":"' + OWNER + '","revision":1}'
    assert receipt["target_version"] == "pit1:" + hashlib.sha256(material.encode()).hexdigest()
    reordered = dict(reversed(list(base.items())))
    assert target_receipt(reordered, OWNER)["target_version"] == receipt["target_version"]
    moved = {**base, "owner_id": OTHER}
    assert target_receipt(moved, OTHER)["target_version"] != receipt["target_version"]
    # Content may only change through SQL revision increments; the token is not
    # an authenticity proof for arbitrary user-crafted receipts.
    assert json.loads(material) == {"id": ID, "owner_id": OWNER, "revision": 1}


@pytest.mark.parametrize("mode", ["read_backwards", "save_backwards", "tombstone_mismatch"])
def test_receipt_chronology_is_checked(storage, mode):
    row = raw_record(deleted=mode == "tombstone_mismatch")
    if mode == "tombstone_mismatch":
        row["deleted_at"] = "2026-09-29T12:00:00+00:00"
    else:
        row["updated_at"] = "2026-09-27T12:00:00+00:00"
    result = {"target": row}
    if mode == "save_backwards":
        result["replayed"] = False
    storage["rpc_result"] = result
    if mode == "save_backwards":
        response = request(TestClient(app), "PUT", save_body())
    else:
        response = request(TestClient(app), "GET", params={"expected_owner_id": OWNER})
    assert response.status_code == 502
    assert response.json() == {"detail": {"code": "private_target_invalid_receipt"}}


def test_cors_preflight_allows_the_save_method():
    response = TestClient(app).options(f"/api/private-import-targets/{ID}", headers={
        "Origin": "https://joinalab.com", "Access-Control-Request-Method": "PUT",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    assert response.status_code == 200
    assert "PUT" in response.headers["access-control-allow-methods"]


@pytest.mark.parametrize(
    "authorization",
    [None, "", "Bearer ", "Basic fixture-token", "Bearer " + "x" * 16384],
    ids=["absent", "empty", "blank-bearer", "not-bearer", "oversized"],
)
@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_missing_credentials_refused_before_the_body_is_parsed(storage, method, authorization):
    import json

    # Invalid on purpose: were the body parsed first, this would be a 422.
    headers = {"content-type": "application/json"}
    if authorization is not None:
        headers["Authorization"] = authorization
    response = TestClient(app).request(
        method, f"/api/private-import-targets/{ID}",
        content=json.dumps({"expected_owner_id": "PRIVATE_SECRET", "expected_revision": True}), headers=headers,
    )
    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "private_target_auth_required"}}
    assert storage["calls"] == [] and "no-store" in response.headers["cache-control"]


@pytest.mark.parametrize("streamed", [False, True])
@pytest.mark.parametrize("path", [ID, "resolved"])
def test_small_bodies_are_bounded_before_parsing(storage, path, streamed):
    import json

    method = "DELETE" if path == ID else "POST"
    body = json.dumps({"expected_owner_id": OWNER, "expected_revision": 1, "ids": [ID],
                       "padding": "PRIVATE_SECRET" * 5000}).encode()
    response = TestClient(app).request(
        method, f"/api/private-import-targets/{path}",
        content=iter([body[:1000], body[1000:]]) if streamed else body,
        headers={"content-type": "application/json", "Authorization": "Bearer fixture-token"},
    )
    assert response.status_code == 413
    assert response.json() == {"detail": {"code": "private_target_too_large"}}
    assert storage["calls"] == [] and "PRIVATE_SECRET" not in response.text



def test_invalid_bearer_refused_over_the_network_before_the_save_is_parsed(storage):
    # Not JSON at all: were it parsed before the token check, this would be 422.
    body = b'{"opportunity": "' + b"x" * (4 * 1024 * 1024)
    response = TestClient(app).put(
        f"/api/private-import-targets/{ID}", content=body,
        headers={"content-type": "application/json", "Authorization": "Bearer forged-token"},
    )
    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "private_target_auth_required"}}
    assert storage["calls"] == [("GET", "/auth/v1/user", "Bearer forged-token")]
    assert "no-store" in response.headers["cache-control"]


def test_verified_save_asks_supabase_for_the_user_once(storage):
    response = request(TestClient(app), "PUT", save_body())
    assert response.status_code == 200, response.text
    assert storage["calls"] == [AUTH_LOOKUP, ("POST", "/rest/v1/rpc/save_private_import_target", "Bearer fixture-token")]


def test_pre_parse_verification_vouches_only_for_its_own_header_and_request(storage):
    import asyncio

    from backend.lib import private_import_targets as lib

    def service(authorization):
        return lib.PrivateTargetService(route.new_client(), "https://supabase.invalid", "fixture-only", authorization)

    async def scenario():
        async with lib.caller_verified_before_parsing("Bearer fixture-token", route.new_client):
            assert await service("Bearer fixture-token").authenticate(lib.Scope(expected_owner_id=OWNER)) == OWNER
            with pytest.raises(lib.PrivateTargetError) as other_owner:
                await service("Bearer fixture-token").authenticate(lib.Scope(expected_owner_id=OTHER))
            assert other_owner.value.code == "private_target_owner_changed"
            with pytest.raises(lib.PrivateTargetError) as other_token:
                await service("Bearer forged-token").verify_user()
            assert other_token.value.code == "private_target_auth_required"
        assert await service("Bearer fixture-token").verify_user() == OWNER

    asyncio.run(scenario())
    assert storage["calls"] == [AUTH_LOOKUP, ("GET", "/auth/v1/user", "Bearer forged-token"), AUTH_LOOKUP]
