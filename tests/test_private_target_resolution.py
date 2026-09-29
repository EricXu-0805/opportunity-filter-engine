"""Private resolved detail tests use synthetic GoTrue/PostgREST responses only."""

import pytest
from fastapi.testclient import TestClient

from backend.lib import private_target_resolution as resolution
from backend.routes import private_import_targets as private_route
from tests.test_private_import_targets import ID, OWNER, app, raw_record
from tests.test_private_import_targets import storage as storage_fixture


@pytest.fixture
def storage(monkeypatch):
    return storage_fixture.__wrapped__(monkeypatch)


@pytest.fixture(autouse=True)
def offline_resolver(storage, monkeypatch):
    monkeypatch.setattr(resolution.storage, "new_client", private_route.new_client)


def test_resolved_route_registered(storage):
    storage["row"] = raw_record()
    response = TestClient(app).get(
        f"/api/private-import-targets/{ID}/resolved",
        params={"expected_owner_id": OWNER},
        headers={"Authorization": "Bearer fixture-token"},
    )
    assert response.status_code == 200
    assert response.json()["capabilities"] == {"read": True, "tracker_identity": True, "writes": False}


def get_resolved(client=None, *, target_id=ID, owner=OWNER, version=None, authorized=True, params=None):
    query = {"expected_owner_id": owner}
    if version is not None:
        query["expected_target_version"] = version
    if params:
        query.update(params)
    return (client or TestClient(app)).get(
        f"/api/private-import-targets/{target_id}/resolved",
        params=query,
        headers={"Authorization": "Bearer fixture-token"} if authorized else {},
    )


def test_full_private_source_only_no_public_authority(storage, monkeypatch):
    import json
    from copy import deepcopy

    from tests.test_private_import_targets import OPPORTUNITY

    raw = deepcopy(OPPORTUNITY)
    raw["description_raw"] = "Research source paragraph.\n" * 400 + "LATE_END_MARKER GPA < 3.0. 中文🙂"
    raw["source_url"] = "https://school.example/program#application"
    raw["url"] = "https://school.example/program?application=1"
    raw["deadline"] = "Imported date without a year"
    raw["organization"] = "Imported organization"
    raw["extra_fields"].update(
        {
            "source_type": "faculty_research",
            "record_kind": "listing",
            "target_truth": {"actionable": True, "accepting_state": "verified"},
            "eligibility": {"skills_required": ["FAKE_AUTHORITY"]},
            "application": {"contact_email": "FAKE_AUTHORITY@private.example"},
            "contact_email": "FAKE_AUTHORITY@private.example",
            "contact_instruction_sources": [{"text": "FAKE_AUTHORITY", "verified": True}],
            "research_context": {"status": "available", "snapshot": {"title": "FAKE_AUTHORITY"}},
            "lab_context": {"status": "available"},
            "target_version": "wt1:FAKE_AUTHORITY",
            "description_raw": "FAKE_AUTHORITY",
            "verification": "verified",
            "capabilities": {"writes": True},
        }
    )
    storage["row"] = raw_record(raw)

    def forbidden(*args, **kwargs):
        raise AssertionError("Public/model path must not be used")

    import backend.data_loader as loader
    import backend.lib.llm as llm
    import backend.lib.public_opportunity_detail as public_detail

    monkeypatch.setattr(public_detail, "project_public_detail", forbidden)
    monkeypatch.setattr(loader, "load_opportunities_by_id", forbidden)
    monkeypatch.setattr(llm, "chat_completion", forbidden)
    response = get_resolved()
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["detail"]["description_raw"] == raw["description_raw"]
    assert value["detail"]["deadline"] == raw["deadline"]
    assert value["detail"]["source_url"] == raw["source_url"]
    assert value["detail"]["url"] == raw["url"]
    assert value["tracker"]["target_version"] == value["target_version"]
    assert "description_raw" not in value["tracker"]
    assert "FAKE_AUTHORITY" not in json.dumps(value)
    assert "eligibility" not in value["detail"] and "contact_email" not in value["detail"]
    assert value["capabilities"] == {"read": True, "tracker_identity": True, "writes": False}
    assert value["verification"] == value["tracker"]["verification"] == "unverified"
    assert storage["row"]["opportunity"] == raw
    assert [call[1] for call in storage["calls"]] == ["/auth/v1/user", "/rest/v1/rpc/read_private_import_target"]
    assert "no-store" in response.headers["cache-control"]


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,private",
        "file:///private/file",
        "https://user:password@school.example/program",
        "http://127.0.0.1/secret",
        "http://localhost/private",
        "https://site.internal/source",
        "https://school.example/private path",
        "https://school.example:bad/path",
        "https://school.example/?email=private@example.com",
        "",
    ],
)
def test_unsafe_source_link_is_not_a_contact_or_browser_link(storage, url):
    row = raw_record()
    row["opportunity"]["source_url"] = row["opportunity"]["url"] = url
    storage["row"] = row
    response = get_resolved()
    assert response.status_code == 200
    value = response.json()
    assert value["detail"]["source_url"] is value["detail"]["url"] is None
    assert value["tracker"]["source_url"] is value["tracker"]["url"] is None
    assert "recipient_email" not in value and storage["row"]["opportunity"]["source_url"] == url


def test_version_is_current_and_stale_is_refused_before_projection(storage, monkeypatch):
    storage["row"] = raw_record()
    current = get_resolved().json()["target_version"]
    assert get_resolved(version=current).status_code == 200
    storage["row"] = raw_record(revision=2)

    def forbidden(*args, **kwargs):
        raise AssertionError("Stale target must not be projected")

    monkeypatch.setattr(resolution, "project_private_target", forbidden)
    response = get_resolved(version=current)
    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "private_target_changed"}}
    assert "description_raw" not in response.text


def test_deleted_target_is_refused_even_without_expected_version(storage):
    storage["row"] = raw_record(revision=2, deleted=True)
    response = get_resolved()
    assert response.status_code == 409 and response.json() == {"detail": {"code": "private_target_deleted"}}


def test_missing_and_other_owners_target_are_both_not_found(storage):
    missing = get_resolved()
    storage["failure"] = "P0002"
    other = get_resolved()
    assert missing.status_code == other.status_code == 404
    assert missing.json() == other.json() == {"detail": {"code": "private_target_not_found"}}


def test_wrong_expected_owner_stops_before_record_read(storage):
    from tests.test_private_import_targets import OTHER

    response = get_resolved(owner=OTHER)
    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "private_target_owner_changed"}}
    assert len(storage["calls"]) == 1


@pytest.mark.parametrize("case", ["no_bearer", "anonymous", "retired_or_expired", "poisoned_owner"])
def test_private_auth_cannot_be_bypassed(storage, case):
    from tests.test_private_import_targets import OTHER

    storage["row"] = raw_record()
    status, code = 401, "private_target_auth_required"
    if case == "anonymous":
        storage["user"]["is_anonymous"] = True
    if case == "retired_or_expired":
        storage["failure"] = "42501"
    if case == "poisoned_owner":
        storage["row"]["owner_id"] = OTHER
        status, code = 502, "private_target_invalid_receipt"
    response = get_resolved(authorized=case != "no_bearer")
    assert response.status_code == status
    assert response.json() == {"detail": {"code": code}}
    if case == "no_bearer":
        assert storage["calls"] == []


@pytest.mark.parametrize(
    "arguments",
    [
        {"target_id": "canonical-public-id"},
        {"target_id": "private-import:bad"},
        {"owner": "not-an-owner"},
        {"version": "wt1:private"},
        {"version": "pit1:" + "F" * 64},
        {"params": {"opportunity": "PRIVATE_SOURCE"}},
    ],
)
def test_invalid_identifier_or_contract_never_falls_back(storage, arguments):
    response = get_resolved(**arguments)
    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "private_target_invalid_request"}}
    assert storage["calls"] == []


def test_duplicate_query_is_rejected_before_storage(storage):
    response = TestClient(app).get(
        f"/api/private-import-targets/{ID}/resolved",
        params=[("expected_owner_id", OWNER), ("expected_owner_id", OWNER)],
    )
    assert response.status_code == 422 and storage["calls"] == []


def test_namespace_recognition_never_certifies_validity():
    assert resolution.private_target_namespace(ID)
    assert resolution.private_target_namespace("private-import:malformed")
    assert not resolution.private_target_namespace("ordinary-public-id")
    assert not resolution.private_target_namespace(None)


def test_projection_recomputes_decorations_and_is_detached():
    from backend.lib.private_import_targets import target_receipt

    receipt = target_receipt(raw_record(), OWNER, ID)
    receipt.update(
        verification="verified",
        target_version="wt1:FORGED",
        import_source={"ai_input_scope": "full_source"},
        capabilities={"writes": True},
    )
    resolved = resolution.project_private_target(receipt, expected_owner_id=OWNER, target_id=ID)
    value = resolved.as_dict()
    assert value["verification"] == "unverified"
    assert value["target_version"].startswith("pit1:")
    assert value["detail"]["import_source"]["ai_input_scope"] == "source_excerpt"
    value["detail"]["import_source"]["ai_input_scope"] = "full_source"
    assert resolved.as_dict()["detail"]["import_source"]["ai_input_scope"] == "source_excerpt"
    assert receipt["import_source"]["ai_input_scope"] == "full_source"


@pytest.mark.parametrize(
    "url",
    [
        "https://school.example/program\\application",
        "https://school.example/program\x01application",
        "https://school.example/program\x7fapplication",
        "https://exa%mple.test/path",
        "https://[v1.example]/path",
        "https://school%2fexample.test/path",
        "https://%ED%A0%80.example/path",
    ],
)
def test_projected_links_match_client_rejection_boundary(storage, url):
    row = raw_record()
    row["opportunity"]["source_url"] = url
    storage["row"] = row
    response = get_resolved()
    assert response.status_code == 200
    assert response.json()["detail"]["source_url"] is None
    assert response.json()["tracker"]["source_url"] is None
    assert storage["row"]["opportunity"]["source_url"] == url


@pytest.mark.parametrize(
    "url",
    [
        "https://school.example/program%5Capplication",
        "https://school.example/[part]",
        "https://school.example/{}",
        "https://school.example/path|part",
        "https://💡.example/path",
        "https://school.example./path",
        "https://%65xample.com/path",
    ],
)
def test_valid_browser_links_are_not_blanket_removed(storage, url):
    storage["row"] = raw_record()
    storage["row"]["opportunity"]["source_url"] = url
    response = get_resolved()
    assert response.status_code == 200
    assert response.json()["detail"]["source_url"] == url
