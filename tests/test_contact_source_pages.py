"""Independently retained application pages: local fixtures, no network."""
import json
import socket
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from backend.data_loader import _canonicalize_corpus
from backend.lib.public_opportunity_detail import project_public_detail, writing_target_version
from src.collectors import faculty_graph, ucb_common
from src.collectors.uiuc_faculty import carry_forward_contact_instruction_sources as carry
from src.contact_instructions import (
    CAPTURE_KEY,
    PAGES_KEY,
    SOURCE_KEY,
    capture_failure,
    capture_from_html,
    capture_metadata,
    contact_instruction_pages,
    contact_instructions_for,
)

PROFILE = 'https://example.edu/people/alice'
LAB = 'https://example.edu/lab/apply'
OTHER = 'https://example.edu/project/other'


def stamp(age=0):
    return (datetime.now(UTC) - timedelta(days=age)).isoformat()


def record():
    return {'id':'alice', 'source':'sample_faculty', 'source_type':'faculty_research',
            'title':'Alice Example', 'pi_name':'Alice Example', 'organization':'Example University',
            'url':PROFILE, 'source_url':PROFILE, 'metadata':{}}


def observation(url, text='Please email us.', *, checked=None, requested=None):
    return capture_metadata(capture_from_html(
        f'<main><h1>Alice Example</h1><h2>Undergraduate applicants</h2><p>{text}</p></main>',
        source_url=url, record_source_url=PROFILE, identity_name='Alice Example',
        checked_at=checked or stamp(1), requested_source_url=requested))


def incoming(metadata):
    value = record()
    value['metadata'] = metadata
    return value


def two_pages():
    prior = record()
    prior['metadata'][SOURCE_KEY] = (
        observation(PROFILE, 'Please email us. Minimum GPA: 3.0.', checked=stamp(5))[SOURCE_KEY]
        + observation(LAB, 'Do not email us. Minimum GPA: 3.5.', checked=stamp(4))[SOURCE_KEY])
    return prior


def urls(value):
    return [s['source_url'] for s in value['metadata'].get(SOURCE_KEY, [])]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *_a, **_k: pytest.fail('No external network'))


@pytest.mark.parametrize('text', ['Please email us. Minimum GPA: 3.7.', 'We study parsers.'])
def test_profile_capture_or_empty_preserves_independent_lab_source(text):
    prior = two_pages()
    new = incoming(observation(PROFILE, text))
    carry(prior, new)
    assert LAB in urls(new)
    lab = next(s for s in new['metadata'][SOURCE_KEY] if s['source_url'] == LAB)
    assert lab == prior['metadata'][SOURCE_KEY][1]
    assert contact_instructions_for(new)['email_policy'] != 'allowed'


def test_legacy_single_receipt_only_migrates_its_own_page():
    prior = two_pages()
    empty = observation(PROFILE, 'We study parsers.', checked=stamp(3))
    prior['metadata'][CAPTURE_KEY] = empty[CAPTURE_KEY]
    new = record()
    carry(prior, new)
    assert urls(new) == [LAB]
    pages = contact_instruction_pages(new)
    assert len(pages) == 2
    profile = next(p for p in pages if p['requested_source_url'] == PROFILE)
    assert profile['receipt']['status'] == 'empty' and profile['sources'] == []
    assert profile['last_success_at'] == empty[CAPTURE_KEY]['attempted_at']


@pytest.mark.parametrize('reason', ['fetch_failed', 'http_429'])
def test_failure_retains_each_page_observation_and_retry_schedule(reason):
    prior = two_pages()
    failed = capture_failure(source_url=PROFILE, requested_source_url=PROFILE,
                             record_source_url=PROFILE, identity_name='Alice Example',
                             checked_at=stamp(2), reason=reason, next_retry_at=stamp(-2))
    new = incoming(capture_metadata(failed))
    carry(prior, new)
    assert new['metadata'][SOURCE_KEY] == prior['metadata'][SOURCE_KEY]
    page = next(p for p in contact_instruction_pages(new) if p['requested_source_url'] == PROFILE)
    assert page['receipt']['next_retry_at'] == failed['next_retry_at']
    assert page['last_success_at'] == prior['metadata'][SOURCE_KEY][0]['checked_at']
    copied = record()
    carry(new, copied)
    assert contact_instruction_pages(copied) == contact_instruction_pages(new)


def test_failed_attempt_after_empty_keeps_last_successful_empty_date():
    new = incoming(observation(PROFILE, 'We study parsers.', checked=stamp(3)))
    carry(two_pages(), new)
    empty_stamp = new['metadata'][CAPTURE_KEY]['attempted_at']
    failed = incoming(capture_metadata(capture_failure(source_url=PROFILE, record_source_url=PROFILE,
                    identity_name='Alice Example', checked_at=stamp(1))))
    carry(new, failed)
    page = next(p for p in contact_instruction_pages(failed) if p['requested_source_url'] == PROFILE)
    assert page['receipt']['status'] == 'failed'
    assert page['last_success_at'] == empty_stamp
    assert page['sources'] == [] and urls(failed) == [LAB]


@pytest.mark.parametrize('kind', ['captured', 'legacy'])
@pytest.mark.parametrize('equal', [False, True])
def test_deleted_page_does_not_revive_from_old_or_equal_snapshot(kind, equal):
    cleared = incoming(observation(PROFILE, 'We study parsers.', checked=stamp(3)))
    carry(two_pages(), cleared)
    cleared_at = cleared['metadata'][CAPTURE_KEY]['attempted_at']
    old = observation(PROFILE, checked=cleared_at if equal else stamp(4))
    if kind == 'legacy':
        old.pop(CAPTURE_KEY)
    new = incoming(old)
    carry(cleared, new)
    assert urls(new) == [LAB]
    assert len(contact_instruction_pages(new)) == 2


@pytest.mark.parametrize('kind', ['captured', 'legacy'])
def test_newer_success_can_restore_only_its_page_and_survives_next_refresh(kind):
    cleared = incoming(observation(PROFILE, 'We study parsers.', checked=stamp(3)))
    carry(two_pages(), cleared)
    fresh = observation(PROFILE, 'Please email us.', checked=stamp(1))
    if kind == 'legacy':
        fresh.pop(CAPTURE_KEY)
    new = incoming(fresh)
    carry(cleared, new)
    again = record()
    carry(new, again)
    assert set(urls(again)) == {PROFILE, LAB}


def test_requested_page_identity_prevents_redirect_from_clearing_wrong_destination():
    prior = two_pages()
    failed = incoming(capture_metadata(capture_failure(source_url=LAB, requested_source_url=PROFILE,
                       record_source_url=PROFILE, identity_name='Alice Example', checked_at=stamp(1), reason='redirect_mismatch')))
    carry(prior, failed)
    assert urls(failed) == [LAB]
    page = next(p for p in contact_instruction_pages(failed) if p['requested_source_url'] == PROFILE)
    assert page['receipt']['source_url'] == LAB and page['sources'] == []


def test_legacy_redirect_cannot_guess_which_of_multiple_pages_was_requested():
    prior = two_pages()
    failed = incoming(capture_metadata(capture_failure(source_url=OTHER, record_source_url=PROFILE,
                       identity_name='Alice Example', checked_at=stamp(1), reason='redirect_mismatch')))
    carry(prior, failed)
    assert failed['metadata'][SOURCE_KEY] == prior['metadata'][SOURCE_KEY]
    assert failed['metadata'][PAGES_KEY]['merge_issue'] == 'invalid_input'


def test_legacy_redirect_can_revoke_the_only_existing_profile_page():
    prior = incoming(observation(PROFILE, checked=stamp(5)))
    failed = incoming(capture_metadata(capture_failure(source_url=OTHER, record_source_url=PROFILE,
                       identity_name='Alice Example', checked_at=stamp(1), reason='redirect_mismatch')))
    carry(prior, failed)
    assert urls(failed) == []
    pages = contact_instruction_pages(failed)
    assert len(pages) == 1 and pages[0]['requested_source_url'] == PROFILE


@pytest.mark.parametrize('field,value', [('id','other-id'), ('pi_name','Other Example'), ('organization','Other University'), ('url',OTHER)])
def test_target_identity_change_inherits_no_previous_page(field, value):
    new = record()
    new[field] = value
    carry(two_pages(), new)
    assert urls(new) == [] and contact_instruction_pages(new) == []


def test_eight_source_limit_rejects_addition_without_dropping_any_old_source():
    prior = record()
    prior['metadata'][SOURCE_KEY] = [observation(f'https://example.edu/pages/{i}', checked=stamp(5))[SOURCE_KEY][0] for i in range(8)]
    new = incoming(observation(OTHER))
    carry(prior, new)
    assert new['metadata'][SOURCE_KEY] == prior['metadata'][SOURCE_KEY]
    assert new['metadata'][PAGES_KEY]['merge_issue'] == 'source_limit'
    assert new['metadata'][CAPTURE_KEY]['status'] == 'unsupported'
    assert new['metadata'][CAPTURE_KEY]['reason'] == 'source_limit'
    assert len(contact_instruction_pages(new)) == 9


def test_thirty_two_page_limit_preserves_all_tombstones():
    current = record()
    for index in range(32):
        new = incoming(observation(f'https://example.edu/pages/{index}', 'We study parsers.'))
        carry(current, new)
        current = new
    before = deepcopy(current['metadata'][PAGES_KEY]['pages'])
    extra = incoming(observation(OTHER))
    carry(current, extra)
    assert extra['metadata'][PAGES_KEY]['pages'] == before
    assert extra['metadata'][PAGES_KEY]['merge_issue'] == 'page_limit'
    assert extra['metadata'].get(SOURCE_KEY) == []


@pytest.mark.parametrize('bad', [None, [], {'version':1, 'pages':[]}, {'version':1, 'pages':[{}]}])
def test_explicit_bad_ledger_cannot_fall_back_to_raw_sources(bad):
    prior = two_pages()
    prior['metadata'][PAGES_KEY] = bad
    assert contact_instruction_pages(prior) == []


def test_source_conflicts_survive_actual_merge_loader_and_public_projection(tmp_path, monkeypatch):
    prior = two_pages()
    prior['metadata'].update({'is_active':True, 'last_verified':stamp(1), 'verification_scope':'profile'})
    path = tmp_path/'opportunities.json'
    path.write_text(json.dumps([prior]))
    monkeypatch.setattr(ucb_common, 'PROCESSED_FILE', path)
    before = project_public_detail(_canonicalize_corpus([deepcopy(prior)])[0])
    new = incoming(observation(PROFILE, 'Please email us. Minimum GPA: 3.8.'))
    new['metadata']['first_seen_at'] = stamp(1)
    faculty_graph.merge_into_processed([new])
    stored = json.loads(path.read_text())[0]
    public = project_public_detail(_canonicalize_corpus([stored])[0])
    assert set(urls(stored)) == {PROFILE, LAB}
    assert public['contact_instructions']['email_policy'] != 'allowed'
    gpa = next(c for c in public['target_conditions']['conditions'] if c['field'] == 'eligibility.min_gpa')
    assert gpa['status'] == 'conflicting'
    assert PAGES_KEY not in public.get('metadata', {})
    assert writing_target_version(public) != writing_target_version(before)


def test_tombstone_overrides_inconsistent_materialized_array_in_both_consumers():
    from backend.lib.email_target_conditions import build_target_conditions
    cleared = incoming(observation(PROFILE, 'We study parsers.', checked=stamp(3)))
    carry(two_pages(), cleared)
    # A stale cached materialization must not bypass the page-specific ledger.
    cleared['metadata'][SOURCE_KEY].extend(observation(PROFILE, 'Please email us. Applicants must submit a resume.', checked=stamp(4))[SOURCE_KEY])
    assert contact_instructions_for(cleared)['email_policy'] != 'allowed'
    conditions = build_target_conditions(cleared)
    assert not any(c['field'] == 'application.requires_resume' and c['status'] == 'stated' for c in conditions['conditions'])
    assert all(PROFILE != source['source_url'] for c in conditions['conditions'] for source in c['sources'])


def test_page_only_withdrawal_updates_deduplicated_canonical_entity():
    from src.normalizers.ucb_dedup import dedupe_against_existing
    prior = two_pages()
    withdrawn = incoming(observation(PROFILE, 'We study parsers.', checked=stamp(1)))
    carry(prior, withdrawn)
    withdrawn['id'] = 'other-feed'
    withdrawn['metadata'].pop(CAPTURE_KEY)
    kept, dropped = dedupe_against_existing([withdrawn], [prior])
    assert dropped == 1 and len(kept) == 1
    assert kept[0]['id'] == prior['id']
    assert urls(kept[0]) == [LAB]
    assert len(contact_instruction_pages(kept[0])) == 2


def test_generic_normalizer_overflow_is_explicit_and_does_not_wash_old_state():
    from src.normalizers.normalizer import normalize
    prior = two_pages()
    raw = deepcopy(prior)
    raw['extra_fields'] = {SOURCE_KEY:[observation(f'https://example.edu/pages/{i}')[SOURCE_KEY][0] for i in range(9)]}
    new = normalize(raw)
    assert new['metadata'][PAGES_KEY]['merge_issue'] == 'source_limit'
    carry(prior, new)
    assert new['metadata'][SOURCE_KEY] == prior['metadata'][SOURCE_KEY]
    assert new['metadata'][PAGES_KEY]['merge_issue'] == 'source_limit'


@pytest.mark.parametrize('bad', [['source_limit'], {'invalid':True}, 42])
def test_malformed_ledger_issue_is_not_a_crash_or_legacy_bypass(bad):
    prior = two_pages()
    prior['metadata'][PAGES_KEY] = {'version':1, 'pages':[], 'merge_issue':bad}
    assert contact_instruction_pages(prior) == []
    new = record()
    carry(prior, new)
    assert urls(new) == []


@pytest.mark.parametrize('bad', ['2026-01-01T00:00:00', 'not-a-date', '2000-01-01T00:00:00+00:00'])
def test_invalid_retry_schedule_cannot_be_accepted(bad):
    prior = two_pages()
    attempt = capture_failure(source_url=PROFILE, record_source_url=PROFILE, identity_name='Alice Example',
                              checked_at=stamp(1), next_retry_at=bad)
    new = incoming(capture_metadata(attempt))
    carry(prior, new)
    assert new['metadata'][SOURCE_KEY] == prior['metadata'][SOURCE_KEY]
    assert new['metadata'][PAGES_KEY]['merge_issue'] == 'invalid_input'


def test_success_clears_prior_failed_retry_schedule():
    prior = two_pages()
    failed = incoming(capture_metadata(capture_failure(source_url=PROFILE, record_source_url=PROFILE,
                      identity_name='Alice Example', checked_at=stamp(2), next_retry_at=stamp(-2))))
    carry(prior, failed)
    success = incoming(observation(PROFILE, checked=stamp(1)))
    carry(failed, success)
    page = next(p for p in contact_instruction_pages(success) if p['requested_source_url'] == PROFILE)
    assert 'next_retry_at' not in page['receipt']
    assert page['last_success_at'] == success['metadata'][CAPTURE_KEY]['attempted_at']


def test_real_http_detail_and_stale_writing_version_use_all_retained_pages(monkeypatch):
    from unittest.mock import Mock

    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.routes import opportunities, tailor

    prior = two_pages()
    prior['opportunity_type'] = 'research'
    prior['metadata']['listing_status'] = 'open'
    rows = {prior['id']:prior}
    monkeypatch.setattr(opportunities, 'load_opportunities_by_id', lambda:rows)
    monkeypatch.setattr(tailor, 'load_opportunities_by_id', lambda:rows)
    provider = Mock(side_effect=AssertionError('No provider allowed'))
    monkeypatch.setattr(tailor, 'chat_completion', provider)
    monkeypatch.setattr(tailor, 'is_configured', lambda:False)
    async def no_auth(_value):
        return None
    monkeypatch.setattr(opportunities, 'authenticated_uid', no_auth)
    client = TestClient(app)
    path = '/api/opportunities/alice'
    params = {'_release_scope':opportunities.CURRENT_TRUTH_AWARE_SCOPE}
    before = client.get(path, params=params)
    assert before.status_code == 200
    old_version = before.json()['writing_target_version']
    new = incoming(observation(PROFILE, 'Please email us. Minimum GPA: 3.8.'))
    carry(prior, new)
    new['opportunity_type'] = 'research'
    rows['alice'] = new
    response = client.get(path, params=params)
    assert response.status_code == 200
    public = response.json()
    assert PAGES_KEY not in public.get('metadata', {})
    assert public['contact_instructions']['email_policy'] != 'allowed'
    assert public['writing_target_version'] != old_version
    gpa = next(c for c in public['target_conditions']['conditions'] if c['field'] == 'eligibility.min_gpa')
    assert gpa['status'] == 'conflicting'
    stale = client.post('/api/tailor', json={'profile':{}, 'opportunity_id':'alice',
                         'expected_target_version':old_version, 'original_bullets':['Built a parser.']})
    assert stale.status_code == 409 and stale.json()['detail']['code'] == 'WRITING_TARGET_CHANGED'
    provider.assert_not_called()


@pytest.mark.parametrize('has_existing', [False, True])
def test_full_multisource_snapshot_replay_preserves_all_pages(has_existing):
    base = two_pages()
    snapshot = incoming(observation(PROFILE, 'Please email us.', checked=stamp(2)))
    carry(base, snapshot)
    old = base if has_existing else {}
    restored = deepcopy(snapshot)
    carry(old, restored)
    assert restored['metadata'][SOURCE_KEY] == snapshot['metadata'][SOURCE_KEY]
    assert len(contact_instruction_pages(restored)) == 2


def test_revocation_then_failure_keeps_delete_barrier_and_has_no_effective_success():
    revoked = incoming(capture_metadata(capture_failure(source_url=PROFILE, record_source_url=PROFILE,
                       identity_name='Alice Example', checked_at=stamp(3), reason='source_revoked')))
    carry(two_pages(), revoked)
    failed = incoming(capture_metadata(capture_failure(source_url=PROFILE, record_source_url=PROFILE,
                      identity_name='Alice Example', checked_at=stamp(2))))
    carry(revoked, failed)
    copied = deepcopy(failed)
    carry({}, copied)
    page = next(p for p in contact_instruction_pages(copied) if p['requested_source_url'] == PROFILE)
    assert page['last_success_at'] is None and page['sources'] == []
    assert urls(copied) == [LAB]
    replay = incoming(observation(PROFILE, checked=stamp(4)))
    carry(copied, replay)
    assert urls(replay) == [LAB]


def test_capacity_rejection_remains_a_bounded_scheduler_observation():
    prior = record()
    prior['metadata'][SOURCE_KEY] = [observation(f'https://example.edu/pages/{i}', checked=stamp(5))[SOURCE_KEY][0] for i in range(8)]
    attempted = stamp(1)
    new = incoming(observation(PROFILE, checked=attempted))
    carry(prior, new)
    assert len(new['metadata'][PAGES_KEY]['pages']) == 9
    rejected = next(p for p in contact_instruction_pages(new) if p['requested_source_url'] == PROFILE)
    assert rejected['receipt']['attempted_at'] == attempted
    assert rejected['receipt']['reason'] == 'source_limit'
    assert rejected['sources'] == [] and rejected['last_success_at'] is None
    copied = record()
    carry(new, copied)
    rejected_again = next(p for p in contact_instruction_pages(copied) if p['requested_source_url'] == PROFILE)
    assert rejected_again == rejected


def capacity_snapshot():
    prior = record()
    prior['metadata'][SOURCE_KEY] = [observation(f'https://example.edu/pages/{i}', checked=stamp(5))[SOURCE_KEY][0] for i in range(8)]
    blocked = incoming(observation(PROFILE, checked=stamp(3)))
    carry(prior, blocked)
    return blocked


def test_complete_ledger_with_historical_capacity_issue_can_restore_to_empty_record():
    blocked = capacity_snapshot()
    serialized = json.loads(json.dumps(blocked))
    carry({}, serialized)
    assert serialized['metadata'][SOURCE_KEY] == blocked['metadata'][SOURCE_KEY]
    assert len(contact_instruction_pages(serialized)) == 9


def test_capacity_then_empty_repair_can_restore_complete_snapshot():
    blocked = capacity_snapshot()
    repaired = incoming(observation('https://example.edu/pages/0', 'We study parsers.', checked=stamp(1)))
    carry(blocked, repaired)
    assert len(repaired['metadata'][SOURCE_KEY]) == 7
    serialized = json.loads(json.dumps(repaired))
    carry({}, serialized)
    assert serialized['metadata'][SOURCE_KEY] == repaired['metadata'][SOURCE_KEY]
    assert len(contact_instruction_pages(serialized)) == 9


def test_different_id_full_ledger_with_capacity_history_keeps_valid_pages():
    from src.normalizers.ucb_dedup import dedupe_against_existing
    blocked = capacity_snapshot()
    blocked['id'] = 'other-feed'
    canonical = record()
    kept, dropped = dedupe_against_existing([blocked], [canonical])
    assert dropped == 1 and len(kept) == 1
    assert len(kept[0]['metadata'][SOURCE_KEY]) == 8
    assert len(contact_instruction_pages(kept[0])) == 9


@pytest.mark.parametrize('field,value', [('id','other-id'), ('organization','Other University')])
def test_changed_target_cannot_reimport_its_copied_old_complete_ledger(field, value):
    prior = record()
    carry(two_pages(), prior)
    changed = deepcopy(prior)
    changed[field] = value
    carry(prior, changed)
    assert urls(changed) == []
    assert contact_instruction_pages(changed) == []


def test_changed_target_accepts_only_new_single_page_observation():
    prior = two_pages()
    changed = incoming(observation(PROFILE, checked=stamp(1)))
    changed['organization'] = 'Other University'
    carry(prior, changed)
    assert urls(changed) == [PROFILE]
    assert len(contact_instruction_pages(changed)) == 1


@pytest.mark.parametrize('keep_all_sources', [False, True])
def test_changed_target_cannot_reuse_old_single_capture_after_removing_ledger(keep_all_sources):
    prior = incoming(observation(PROFILE, checked=stamp(1)))
    carry(two_pages(), prior)
    copied = deepcopy(prior)
    copied['organization'] = 'Other University'
    copied['metadata'].pop(PAGES_KEY)
    if not keep_all_sources:
        copied['metadata'][SOURCE_KEY] = [s for s in copied['metadata'][SOURCE_KEY] if s['source_url'] == PROFILE]
    carry(prior, copied)
    assert urls(copied) == []
    assert contact_instruction_pages(copied) == []
