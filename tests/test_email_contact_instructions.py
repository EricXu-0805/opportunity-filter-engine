"""Source policy applies to all email entry points, without changing history."""
from copy import deepcopy

import pytest

from backend.lib.email_contact_instructions import contact_instruction_brief, required_email_subject
from backend.lib.public_opportunity_detail import project_public_detail, writing_target_version
from backend.routes import cold_email as ce
from tests.test_cold_email_writing_quality import OPP
from tests.test_email_contact_context import FIRST, post, result
from tests.test_email_contact_context import client as shared_client_fixture

SUBJECT = "Undergraduate Research Application"
POLICY = {"version": 1, "status": "known", "email_policy": "allowed", "rules": [{
    "kind": "subject", "quote": f'Use the subject "{SUBJECT}".', "subject": SUBJECT,
    "source_url": "https://example.edu/join", "checked_at": "2026-09-25T10:00:00Z",
}]}


@pytest.fixture
def client(monkeypatch):
    return shared_client_fixture.__wrapped__(monkeypatch)


@pytest.fixture
def source_policy(monkeypatch):
    policy = deepcopy(POLICY)
    monkeypatch.setattr('backend.lib.public_opportunity_detail.contact_instructions_for', lambda _record: deepcopy(policy))
    return policy


@pytest.mark.parametrize('path', ['', 'variants', 'stream', 'refine'])
@pytest.mark.parametrize('policy', ['not_accepted', 'form_only', 'conflicting'])
def test_restricted_contact_stops_before_any_generator(client, monkeypatch, source_policy, path, policy):
    source_policy['email_policy'] = policy
    if policy == 'conflicting':
        source_policy['status'] = 'conflicting'
    monkeypatch.setattr(ce, '_run_engine', lambda *_a, **_k: pytest.fail('restricted source reached generator'))
    response = post(client, path, FIRST, engine='ai')
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'EMAIL_CONTACT_INSTRUCTIONS'
    assert response.json()['detail']['reason'] == policy


@pytest.mark.parametrize('path', ['', 'variants', 'stream'])
def test_required_subject_survives_template_and_variants(client, source_policy, path):
    output = result(post(client, path, FIRST), path)
    for variant in output.get('variants', [output]):
        assert variant['subject'] == SUBJECT
        assert 'attached' not in variant['body'].lower()


def test_source_requirement_is_shared_with_refine_brief_and_not_student_evidence(source_policy):
    opp = project_public_detail(OPP)
    parts = ce._common_parts({}, opp)
    assert SUBJECT in ce._render_professor_brief(parts, opp)
    assert SUBJECT.lower() in ce._build_email_corpus(parts, opp)
    assert SUBJECT.lower() not in ce._student_email_corpus(parts)
    assert 'not prove that any file' in contact_instruction_brief(opp)


def test_requirement_change_invalidates_old_writing_version(client, source_policy):
    old = writing_target_version(project_public_detail(OPP))
    source_policy['rules'][0]['subject'] = 'New official subject'
    response = post(client, '', FIRST, expected_target_version=old)
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'WRITING_TARGET_CHANGED'
    source_policy.update(version=1, status='unknown', email_policy='unknown', rules=[])
    assert required_email_subject(project_public_detail(OPP)) is None


def test_source_snapshots_do_not_leak_in_public_detail():
    record = deepcopy(OPP)
    record.setdefault('metadata', {})['contact_instruction_sources'] = [{'private_marker': 'do not expose'}]
    record['contact_instructions'] = deepcopy(POLICY)
    before = deepcopy(record)
    public = project_public_detail(record)
    assert 'contact_instruction_sources' not in public['metadata']
    assert public['contact_instructions']['status'] == 'unknown'
    assert record == before


@pytest.mark.parametrize('path', ['', 'stream', 'variants', 'refine'])
def test_source_overflow_is_refused_before_generation(client, source_policy, monkeypatch, path):
    source_policy.update(review_required=True, reason='too_many_requirements')
    monkeypatch.setattr(ce, '_run_engine', lambda *_a, **_k: pytest.fail('incomplete source reached generator'))
    response = post(client, path, FIRST)
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'EMAIL_CONTACT_INSTRUCTIONS'
    assert response.json()['detail']['reason'] == 'too_many_requirements'
