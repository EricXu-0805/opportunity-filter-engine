"""Anonymous official-source authority, privacy and shared historical contract."""
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from backend.lib import public_opportunity_detail as detail
from backend.lib import public_projection as projection
from backend.routes.opportunities import _list_card
from src.lab_context import lab_context_for, lab_snapshot_version, validate_public_lab_context

NOW = datetime(2026, 9, 26, 11, tzinfo=UTC)
GOLDEN = Path(__file__).parent / 'fixtures/lab-context-v1-golden.json'


def context():
    return json.loads(GOLDEN.read_text())


def record():
    snapshot = context()['snapshot']; snapshot.pop('snapshot_version')
    return {
        'id': snapshot['record_id'], 'school': snapshot['school'], 'department': snapshot['department'],
        'pi_name': snapshot['identity_name'], 'source': 'ucb_stat_faculty', 'source_type': 'faculty_research',
        'source_url': snapshot['record_source_url'], 'url': snapshot['record_source_url'],
        'title': 'Jane Doe', 'organization': 'University of California, Berkeley', 'opportunity_type': 'research',
        'description_clean': 'A generated legacy introduction.', 'eligibility': {}, 'application': {},
        'metadata': {'lab_snapshot': snapshot, 'lab_refresh': {'checked_at': '2026-09-26T10:00:00Z', 'reason': 'ok'}},
    }


@pytest.fixture(autouse=True)
def fixed_time(monkeypatch):
    monkeypatch.setattr(detail, 'lab_context_for', lambda opp: lab_context_for(opp, now=NOW))
    monkeypatch.setattr(projection, 'lab_context_for', lambda opp: lab_context_for(opp, now=NOW))


def test_shared_ts_python_golden_is_exact_and_detached():
    value = context(); assert validate_public_lab_context(value)
    item = record(); original = deepcopy(item)
    result = detail.project_public_detail(item)
    assert result['lab_context'] == value and item == original
    assert 'lab_snapshot' not in result['metadata'] and 'lab_refresh' not in result['metadata']
    assert result['research_context']['status'] == 'unavailable'  # independent sources
    result['lab_context']['snapshot']['pages'][0]['sections'][0]['text'] = 'Changed by consumer'
    assert item == original


def test_historical_hash_and_status_have_separate_jobs():
    value = context(); value['status'] = 'stale'; assert validate_public_lab_context(value)
    value['snapshot']['pages'][0]['sections'][0]['text'] += 'invented'
    assert not validate_public_lab_context(value)


@pytest.mark.parametrize('field,replacement', [('id','another'), ('school','uiuc'), ('department','Other'),
    ('pi_name','Jane Other'), ('source','url_import'), ('source_type','listing'),
    ('source_url','https://statistics.berkeley.edu/people/other')])
def test_current_identity_revocation_invalidates_source_and_writing_version(field, replacement):
    item = record(); old = detail.project_public_detail(item)
    item[field] = replacement
    new = detail.project_public_detail(item)
    assert new['lab_context'] == {'version':1, 'status':'unavailable', 'snapshot':None}
    assert detail.writing_target_version(old) != detail.writing_target_version(new)


@pytest.mark.parametrize('location', ['section', 'heading', 'title', 'identity'])
def test_contact_redaction_never_resigns_edited_website_evidence(location):
    item = record(); snap = item['metadata']['lab_snapshot']; page = snap['pages'][0]
    if location == 'section': page['sections'][0]['text'] += ' Contact private@example.edu'
    elif location == 'heading': page['sections'][0]['heading'] += ' private@example.edu'
    elif location == 'title': page['page_title'] += ' private@example.edu'
    else:
        snap['identity_name'] = page['identity_text'] = item['pi_name'] = 'private@example.edu'
    before = deepcopy(item)
    out = detail.project_public_detail(item)
    assert out['lab_context']['status'] == 'unavailable'
    assert 'private@example.edu' not in json.dumps(out)
    assert item == before


def test_source_content_time_and_status_all_change_writing_version():
    original = record(); before = detail.writing_target_version(detail.project_public_detail(original))
    for change in ('text','heading','checked_at','stale'):
        item = deepcopy(original); snap = item['metadata']['lab_snapshot']
        if change in ('text','heading'): snap['pages'][0]['sections'][0][change] += ' Changed'
        else: snap['checked_at'] = (NOW - timedelta(days=31 if change == 'stale' else 1)).isoformat().replace('+00:00','Z')
        after = detail.project_public_detail(item)
        assert detail.writing_target_version(after) != before
        if change == 'stale': assert after['lab_context']['status'] == 'stale'


def test_caller_cannot_mint_lab_authority_and_cards_do_not_leak_raw_snapshots():
    item = record(); forged = context(); forged['snapshot']['pages'][0]['sections'][0]['text'] = 'Forged public text'
    payload = {**deepcopy(item), 'lab_context': forged}
    out = projection.project_public_opportunity_payload(payload, item)
    assert out['lab_context'] == context()
    card = _list_card(item)
    encoded = json.dumps(card)
    assert 'lab_snapshot' not in encoded and 'lab_refresh' not in encoded
    assert 'Our group studies' not in encoded
    item['metadata'].pop('lab_snapshot')
    out = projection.project_public_opportunity_payload(payload, item)
    assert out['lab_context']['status'] == 'unavailable'
    assert 'Forged public text' not in json.dumps(out)


def test_unsupported_lab_site_remains_readable_history_but_has_no_current_authority():
    value = context(); snap = value['snapshot']; page = deepcopy(snap['pages'][0])
    page.update(kind='lab_website', requested_url='https://research.berkeley.edu/lab/', source_url='https://research.berkeley.edu/lab/',
        linked_from={'profile_url':snap['record_source_url'], 'href':'https://research.berkeley.edu/lab/', 'anchor_text':'Lab research'})
    snap['pages'].append(page); private = {k:v for k,v in snap.items() if k != 'snapshot_version'}
    snap['snapshot_version'] = lab_snapshot_version(private)
    assert validate_public_lab_context(value)
    item = record(); item['metadata']['lab_snapshot'] = private
    assert detail.project_public_detail(item)['lab_context']['status'] == 'unavailable'
