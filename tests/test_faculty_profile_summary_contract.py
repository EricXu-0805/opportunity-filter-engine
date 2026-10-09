"""The faculty description the server writes is re-said in the UI language.

The server sends the parts of the description as structured fields beside the
English sentence (``faculty_profile_summary``), and
frontend/src/lib/faculty-profile-copy.ts says those parts with its own
dictionary keys. The shared fixture pins both halves: what the server sends
for each record, and the sentence it writes from those fields. Matching the
English sentence is left only for payloads from a backend older than the
fields.
"""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from backend.lib.public_opportunity_detail import project_public_detail
from backend.routes.opportunities import _list_card
from src.evidence import (
    FACULTY_PROFILE_CLOSINGS,
    _faculty_profile_summary,
    faculty_profile_summary_fields,
    render_faculty_profile_summary,
)

_FIXTURE = Path(__file__).resolve().parents[1] / 'frontend/src/lib/__fixtures__/faculty-profile-summary.json'
_CASES = json.loads(_FIXTURE.read_text(encoding='utf-8'))['cases']
_IDS = [case['name'] for case in _CASES]


@pytest.mark.parametrize('case', _CASES, ids=_IDS)
def test_shared_fixture_is_what_the_server_writes(case):
    assert _faculty_profile_summary(case['record']) == case['server_text']
    areas = case['research_areas']
    assert (f'Research areas: {areas} ' in case['server_text']) if areas else ('Research areas:' not in case['server_text'])


@pytest.mark.parametrize('case', _CASES, ids=_IDS)
def test_the_fields_are_what_the_server_sends(case):
    assert faculty_profile_summary_fields(case['record']) == case['fields']


@pytest.mark.parametrize('case', _CASES, ids=_IDS)
def test_the_sentence_is_written_from_the_fields_alone(case):
    """One source: a client holding the fields holds everything the sentence says."""
    assert render_faculty_profile_summary(case['fields']) == case['server_text']


def test_fixture_covers_every_availability_sentence_and_affiliation_shape():
    texts = [case['server_text'] for case in _CASES]
    for sentence in FACULTY_PROFILE_CLOSINGS.values():
        assert any(text.endswith(sentence) for text in texts)
    records = [case['record'] for case in _CASES]
    assert {(bool(r.get('department')), bool(r.get('organization'))) for r in records} == {
        (True, True), (True, False), (False, True), (False, False),
    }


def test_the_fields_cover_every_template():
    """Every closing the server can write has an availability code the
    fixture carries, and every head shape and optional part appears both ways,
    so the frontend test renders each template from fields at least once."""
    fields = [case['fields'] for case in _CASES]
    assert {f['availability'] for f in fields} == set(FACULTY_PROFILE_CLOSINGS)
    assert {(f['department'] is not None, f['organization'] is not None) for f in fields} == {
        (True, True), (True, False), (False, True), (False, False),
    }
    assert {f['name'] is None for f in fields} == {True, False}
    assert {f['research_areas'] is None for f in fields} == {True, False}
    for f in fields:
        assert set(f) == {'version', 'name', 'department', 'organization', 'research_areas', 'availability'}
        assert f['version'] == 1
        for key in ('name', 'department', 'organization', 'research_areas'):
            # Absent is null, never "": the client picks the head sentence by
            # which of these exist.
            assert f[key] is None or (isinstance(f[key], str) and f[key].strip())


def _served_record(case: dict) -> dict:
    record = deepcopy(case['record'])
    record.update(id='faculty-summary-contract', source='uiuc_faculty_directory')
    return record


@pytest.mark.parametrize('case', _CASES, ids=_IDS)
def test_every_public_faculty_payload_carries_the_fields_beside_the_sentence(case):
    """Detail, batch and similar project through project_public_detail; the
    browse list through _list_card. Both reach the saved and detail pages."""
    for payload in (project_public_detail(_served_record(case)), _list_card(_served_record(case))):
        assert payload['faculty_profile_summary'] == case['fields']
        assert payload['description_clean'] == case['server_text']


def test_a_listing_carries_no_faculty_fields():
    listing = {
        'id': 'listing-1', 'source': 'uiuc_sro', 'source_type': 'campus_program',
        'title': 'Summer research', 'description_clean': 'A program.', 'metadata': {'is_active': True},
    }
    assert 'faculty_profile_summary' not in project_public_detail(listing)
    assert 'faculty_profile_summary' not in _list_card(listing)
