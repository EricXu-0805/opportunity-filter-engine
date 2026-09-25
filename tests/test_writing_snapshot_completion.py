"""Remaining legacy writers bind to one anonymous detached target snapshot."""
import json
from copy import deepcopy
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.routes import cold_email, opportunities, tailor

client = TestClient(app)
PATHS = ["/cold-email", "/cold-email/stream", "/cold-email/variants", "/cold-email/refine",
         "/tailor/renovate", "/tailor/bullet"]
TEXT = "Built a thermal sensor and wrote a lab report"


@pytest.fixture(autouse=True)
def corpus(monkeypatch):
    record = {"id": "snapshot-target", "title": "Sensor research", "organization": "Example University",
              "source_type": "manual", "opportunity_type": "research", "description_clean": "Build sensors",
              "eligibility": {"skills_required": ["Python"], "preferred_year": ["Junior", "Senior"]},
              "application": {"contact_method": "email"}, "metadata": {"listing_status": "open"},
              "contact_email": "private@example.edu", "pi_email": "hidden@example.edu"}
    rows = {record["id"]: record}
    for module in (opportunities, cold_email, tailor):
        monkeypatch.setattr(module, "load_opportunities_by_id", lambda: rows)
    for module in (cold_email, tailor):
        monkeypatch.setattr(module, "is_configured", lambda: False)
        monkeypatch.setattr(module, "chat_completion", Mock(side_effect=AssertionError("provider forbidden")))
    async def anonymous(_value): return None
    monkeypatch.setattr(opportunities, "authenticated_uid", anonymous)
    monkeypatch.setattr(cold_email, "authenticated_uid", anonymous)
    monkeypatch.setattr(tailor, "_schedule_usage", Mock())
    return rows, record


def target_version():
    response = client.get("/api/opportunities/snapshot-target",
                          params={"_release_scope": opportunities.CURRENT_TRUTH_AWARE_SCOPE})
    assert response.status_code == 200
    return response.json()["writing_target_version"]


def payload(path, version=None):
    body = {"profile": {"name": "Test Student"}, "opportunity_id": "snapshot-target"}
    if version is not None: body["expected_target_version"] = version
    if path == "/cold-email/refine": body.update(current_body="Hello, I am interested in your lab.", instruction="shorter")
    elif path == "/tailor/renovate": body["sections"] = [{"id": "s", "bullets": [{"id": "b", "text": TEXT}]}]
    elif path == "/tailor/bullet": body.update(current_text=TEXT, base_text=TEXT)
    return body


def receipt(response, path):
    assert response.status_code == 200, response.text
    if path.endswith("/stream"):
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        return next(event for event in events if event["stage"] == "done")
    return response.json()


@pytest.mark.parametrize("path", PATHS)
def test_every_accepted_receipt_binds_detail_snapshot_and_pipeline(path):
    version = target_version()
    result = receipt(client.post("/api" + path, json=payload(path, version)), path)
    assert result["opportunity_id"] == "snapshot-target"
    assert result["target_version"] == version
    assert result["pipeline_version"] == ("w12.6" if path.startswith("/cold") else "w13.4")


@pytest.mark.parametrize("path", PATHS)
def test_public_change_refuses_before_auth_provider_or_work(path, corpus, monkeypatch):
    old = target_version()
    corpus[1]["eligibility"]["preferred_year"].reverse()
    auth = Mock(side_effect=AssertionError("auth must not begin"))
    monkeypatch.setattr(cold_email, "authenticated_uid", auth)
    for module in (cold_email, tailor):
        monkeypatch.setattr(module, "is_configured", Mock(side_effect=AssertionError("work must not begin")))
    response = client.post("/api" + path, json=payload(path, old))
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "WRITING_TARGET_CHANGED",
        "message": "This opportunity changed. Check it again before continuing.", "retryable": False}
    assert old not in response.text and "private@example.edu" not in response.text
    auth.assert_not_called()
    tailor._schedule_usage.assert_not_called()


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("bad", ["wt1:" + "A" * 64, "wt1:" + "a" * 64 + "\n", 3])
def test_malformed_token_rejected_without_lookup(path, bad, monkeypatch):
    for module in (cold_email, tailor):
        monkeypatch.setattr(module, "load_opportunities_by_id", Mock(side_effect=AssertionError("lookup forbidden")))
    assert client.post("/api" + path, json=payload(path, bad)).status_code == 422


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("legacy", ["omitted", "null"])
def test_older_client_compatibility_does_not_omit_receipt(path, legacy):
    body = payload(path)
    if legacy == "null": body["expected_target_version"] = None
    result = receipt(client.post("/api" + path, json=body), path)
    assert result["target_version"] == target_version()
    assert result["opportunity_id"] == "snapshot-target"


@pytest.mark.parametrize("path", PATHS)
def test_deleted_or_historical_target_still_refused(path, corpus):
    version = target_version()
    rows, record = corpus
    rows.clear()
    assert client.post("/api" + path, json=payload(path, version)).status_code == 404
    record["metadata"]["listing_status"] = "closed"
    rows[record["id"]] = record
    response = client.post("/api" + path, json=payload(path, version))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] != "WRITING_TARGET_CHANGED"


@pytest.mark.parametrize("path", PATHS)
def test_source_cache_and_rules_mutating_during_await_cannot_rebind_accepted_work(path, corpus, monkeypatch):
    from backend.lib.public_opportunity_detail import project_public_detail
    rows, record = corpus
    expected_public = project_public_detail(deepcopy(record))
    version = target_version()
    expected_pipeline = cold_email.COLD_EMAIL_PIPELINE_VERSION if path.startswith('/cold') else tailor.TAILOR_PIPELINE_VERSION
    seen = []
    def mutate():
        record['eligibility']['skills_required'].append('Rust')
        record['description_clean'] = 'Changed during accepted work'
        record['contact_email'] = 'changed-private@example.edu'
        rows.clear()
        monkeypatch.setattr(cold_email, 'COLD_EMAIL_PIPELINE_VERSION', 'future-email')
        monkeypatch.setattr(tailor, 'TAILOR_PIPELINE_VERSION', 'future-tailor')
    original_parts = cold_email._experience_parts
    def parts(request, profile, opp):
        seen.append(deepcopy(opp))
        return original_parts(request, profile, opp)
    monkeypatch.setattr(cold_email, '_experience_parts', parts)
    if path in PATHS[:3]:
        async def changing_auth(_value):
            mutate()
            return 'signed-in-owner'
        monkeypatch.setattr(cold_email, 'authenticated_uid', changing_auth)
        # Trusted resolution is still isolated from the public writing input.
        def contact(source, *, authenticated):
            return ('revealed', source['contact_email']) if authenticated and 'contact_email' in source else ('unavailable', '')
        monkeypatch.setattr(cold_email, 'contact_email_status', contact)
    else:
        module = cold_email if path.startswith('/cold') else tailor
        monkeypatch.setattr(module, 'is_configured', lambda: True)
        async def changing_worker(fn, *args, **kwargs):
            if module is tailor:
                seen.append(deepcopy(args[1]))
            mutate()
            return None
        monkeypatch.setattr(module, 'run_blocking', changing_worker)
    result = receipt(client.post('/api' + path, json=payload(path, version)), path)
    assert result['target_version'] == version
    assert result['pipeline_version'] == expected_pipeline
    assert seen and all(value == expected_public for value in seen)
    assert 'private@example.edu' not in json.dumps(seen)
    if path in PATHS[:3]:
        variants = result.get('variants', [result])
        assert all(item['recipient_email'] == 'private@example.edu' for item in variants)
        assert all('private@example.edu' not in item['body'] for item in variants)


@pytest.mark.parametrize('path', PATHS)
def test_new_public_field_changes_bind_but_private_and_key_order_do_not(path, corpus):
    rows, record = corpus
    version = target_version()
    record.update(contact_email='new-private@example.edu', professor_id='private-id', contact_email_status='revealed')
    rows[record['id']] = {key: record[key] for key in reversed(record)}
    result = receipt(client.post('/api' + path, json=payload(path, version)), path)
    assert result['target_version'] == version
    rows[record['id']]['new_public_criteria'] = {'完整': [None, '🧪']}
    response = client.post('/api' + path, json=payload(path, version))
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'WRITING_TARGET_CHANGED'


@pytest.mark.parametrize('path', PATHS)
def test_version_refusal_refunds_global_but_not_arrival_budget(path, monkeypatch):
    from collections import defaultdict

    from backend import main
    monkeypatch.setattr(main, 'RATE_LIMIT_DISABLED', False)
    monkeypatch.setattr(main, '_rate_buckets', defaultdict(list))
    monkeypatch.setattr(main, '_global_buckets', defaultdict(list))
    monkeypatch.setattr(main, '_last_purge', 0.0)
    monkeypatch.setattr(main, 'GLOBAL_LLM_PER_MIN', 1)
    monkeypatch.setattr(main.llm_budget, 'exhausted', lambda: False)
    for _ in range(2):
        response = client.post('/api' + path, json=payload(path, 'wt1:' + '0' * 64))
        assert response.status_code == 409
        assert response.json()['detail']['code'] == 'WRITING_TARGET_CHANGED'
        assert main._global_buckets['llm'] == []
    assert sum(len(value) for value in main._rate_buckets.values()) == 2


@pytest.mark.parametrize('path', ['/tailor/renovate', '/tailor/bullet'])
@pytest.mark.parametrize('mode', ['empty', 'no-provider', 'worker-timeout', 'invalid-output', 'rejected', 'accepted'])
def test_every_legacy_resume_fallback_and_success_is_stamped(path, mode, monkeypatch):
    version = target_version()
    body = payload(path, version)
    if mode == 'empty':
        if path.endswith('/renovate'): body['sections'] = []
        else: body['current_text'] = ''
    monkeypatch.setattr(tailor, 'is_configured', lambda: mode != 'no-provider')
    async def work(fn, *args, **kwargs):
        if mode == 'worker-timeout': raise tailor.BlockingWorkTimeout()
        if mode == 'invalid-output': return None
        text = 'Deployed Kubernetes services' if mode == 'rejected' else TEXT
        if fn is tailor._ai_renovation_plan:
            return {'order': ['s'], 'sections': {'s': [('b', 'foreground')]}}
        if fn is tailor._ai_tailor_bullets: return [{'text': text, 'source_evidence': TEXT}]
        return {'text': text, 'source_evidence': TEXT}
    monkeypatch.setattr(tailor, 'run_blocking', work)
    result = receipt(client.post('/api' + path, json=body), path)
    assert result['target_version'] == version
    assert result['opportunity_id'] == 'snapshot-target'
    assert result['pipeline_version'] == 'w13.4'
    assert result['generated_at']
    assert 'Kubernetes' not in json.dumps(result.get('sections', result.get('text', '')))


@pytest.mark.parametrize('path', ['/cold-email', '/cold-email/stream'])
@pytest.mark.parametrize('mode', ['not-configured', 'timeout', 'invalid', 'fabricated', 'accepted'])
def test_cold_email_fallbacks_and_ai_receipts_stamped(path, mode, monkeypatch):
    version = target_version()
    body = payload(path, version)
    body['engine'] = 'ai'
    monkeypatch.setattr(cold_email, 'is_configured', lambda: mode != 'not-configured')
    monkeypatch.setattr(cold_email, '_pipeline_generate', lambda *args, **kwargs:
        'not a structured email' if mode == 'invalid' else
        ('Subject: Inquiry\nDear team,\nI am an expert in Kubernetes.' if mode == 'fabricated' else
         'Subject: Research inquiry\nDear team,\nI would like to learn about your research.\nBest,\nTest Student'))
    if mode == 'timeout':
        async def timeout(*args, **kwargs): raise cold_email.BlockingWorkTimeout()
        monkeypatch.setattr(cold_email, 'run_blocking', timeout)
    result = receipt(client.post('/api' + path, json=body), path)
    assert result['target_version'] == version
    assert result['opportunity_id'] == 'snapshot-target'
    assert result['pipeline_version'] == 'w12.6'
    assert 'Kubernetes' not in result['body']
    assert result['method'] == ('ai' if mode == 'accepted' else 'template')


@pytest.mark.parametrize('mode', ['local', 'timeout', 'none', 'fabricated', 'accepted'])
def test_refine_fallbacks_and_ai_receipts_stamped(mode, monkeypatch):
    path = '/cold-email/refine'
    version = target_version()
    body = payload(path, version)
    monkeypatch.setattr(cold_email, 'is_configured', lambda: mode != 'local')
    async def work(*args, **kwargs):
        if mode == 'timeout': raise cold_email.BlockingWorkTimeout()
        if mode == 'none': return None
        if mode == 'fabricated': return 'I am an expert in Kubernetes.'
        return 'Hello, I would like to learn about your research.'
    monkeypatch.setattr(cold_email, 'run_blocking', work)
    result = receipt(client.post('/api' + path, json=body), path)
    assert result['target_version'] == version
    assert result['opportunity_id'] == 'snapshot-target'
    assert result['pipeline_version'] == 'w12.6'
    assert 'Kubernetes' not in result['body']
    assert result['method'] == ('llm' if mode == 'accepted' else 'local')
